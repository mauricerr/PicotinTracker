from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from .cache import DedupeCache
from .config import MonitorConfig
from .models import CandidateProduct, InventoryHit
from .notifiers import Notifier
from .rules import contains_anti_bot_text, contains_unavailable_text, identify_product, normalize_color


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class PicotinMonitor:
    def __init__(self, config: MonitorConfig, cache: DedupeCache, notifier: Notifier | None) -> None:
        self.config = config
        self.cache = cache
        self.notifier = notifier
        self.logger = logging.getLogger("picotin_monitor")

    async def run_once(self) -> int:
        self.logger.info("polling start")
        notified = 0
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.config.headless,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            context = await self._new_context(browser)
            try:
                candidates = await self._discover_candidates(context)
                self.logger.info("products detected count=%s", len(candidates))
                for candidate in candidates[: self.config.max_products]:
                    hit = await self._verify_candidate(context, candidate)
                    if hit is None:
                        continue
                    self.logger.info(
                        "qualifying inventory product=%s color=%s size=%s url=%s",
                        hit.product_name,
                        hit.color,
                        hit.size,
                        hit.url,
                    )
                    if not self.cache.should_notify(hit.dedupe_key):
                        self.logger.info("dedupe suppressed key=%s", hit.dedupe_key)
                        continue
                    if self.notifier is None:
                        self.logger.warning("qualifying inventory found but no notifier configured")
                        continue
                    self.notifier.send(hit)
                    self.cache.mark_notified(hit.dedupe_key)
                    self.logger.info("notification sent key=%s", hit.dedupe_key)
                    notified += 1
            finally:
                await context.close()
                await browser.close()
        self.logger.info("polling end notified=%s", notified)
        return notified

    async def _new_context(self, browser: Browser) -> BrowserContext:
        return await browser.new_context(
            user_agent=USER_AGENT,
            locale="en-US",
            timezone_id="America/Chicago",
            viewport={"width": 1440, "height": 1200},
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "DNT": "1",
            },
        )

    async def _discover_candidates(self, context: BrowserContext) -> list[CandidateProduct]:
        page = await context.new_page()
        try:
            await self._goto_with_retries(page, self.config.category_url)
            await self._settle(page)
            body_text = await page.locator("body").inner_text(timeout=5000)
            if contains_anti_bot_text(body_text):
                self.logger.warning("anti-bot event detected on category page")
                return []
            candidates = await self._extract_candidates_from_page(page)
            if candidates:
                return candidates
            self.logger.info("category yielded no candidates; trying homepage fallback")
            await self._goto_with_retries(page, self.config.home_url)
            await self._settle(page)
            return await self._extract_candidates_from_page(page)
        except Exception as exc:
            self.logger.warning("candidate discovery failed: %s", exc)
            return []
        finally:
            await page.close()

    async def _extract_candidates_from_page(self, page: Page) -> list[CandidateProduct]:
        raw_items = await page.evaluate(
            """() => {
                const anchors = Array.from(document.querySelectorAll('a[href]'));
                return anchors.map((a) => {
                    const nodeText = (a.innerText || a.textContent || '').trim();
                    const labelled = [
                        a.getAttribute('aria-label') || '',
                        a.getAttribute('title') || '',
                        a.querySelector('img')?.getAttribute('alt') || ''
                    ].filter(Boolean).join(' ');
                    const container = a.closest('li, article, [data-testid], .product-item, .product-card');
                    const containerText = container ? (container.innerText || container.textContent || '') : '';
                    return {
                        href: a.href,
                        text: [nodeText, labelled, containerText].filter(Boolean).join('\\n')
                    };
                });
            }"""
        )
        seen: set[str] = set()
        candidates: list[CandidateProduct] = []
        for item in raw_items:
            url = str(item.get("href") or "")
            text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
            if not url or url in seen:
                continue
            identity = identify_product(text)
            if identity is None:
                continue
            seen.add(url)
            candidates.append(CandidateProduct(name=identity.canonical_name, url=urljoin(page.url, url)))
        return candidates

    async def _verify_candidate(self, context: BrowserContext, candidate: CandidateProduct) -> InventoryHit | None:
        page = await context.new_page()
        try:
            await self._goto_with_retries(page, candidate.url)
            await self._settle(page)
            await self._wait_for_purchase_section(page)
            body_text = await page.locator("body").inner_text(timeout=5000)
            if contains_anti_bot_text(body_text):
                self.logger.warning("anti-bot event detected url=%s", candidate.url)
                return None
            if contains_unavailable_text(body_text):
                self.logger.info("rejected unavailable text url=%s", candidate.url)
                return None
            details = await self._extract_product_details(page)
            identity = identify_product(details["name"] or candidate.name)
            if identity is None:
                self.logger.info("rejected product name=%s url=%s", details["name"], candidate.url)
                return None
            color = normalize_color(details["color"], self.config.include_secondary_colors)
            if color is None:
                self.logger.info("rejected color raw=%s url=%s", details["color"], candidate.url)
                return None
            if not details["variant_selectable"]:
                self.logger.info("rejected missing selectable variant url=%s", candidate.url)
                return None
            if not details["add_to_cart_exists"] or not details["add_to_cart_enabled"]:
                self.logger.info("rejected add-to-cart unavailable url=%s", candidate.url)
                return None
            screenshot_path = await self._capture_screenshot(page, identity.canonical_name, color, identity.size)
            sku = details["sku"] or page.url
            return InventoryHit(
                product_name=identity.canonical_name,
                color=color,
                size=identity.size,
                price=details["price"] or "Unknown",
                url=page.url,
                sku=sku,
                timestamp=datetime.now(timezone.utc).isoformat(),
                screenshot_path=screenshot_path,
            )
        except Exception as exc:
            self.logger.warning("candidate verification failed url=%s error=%s", candidate.url, exc)
            return None
        finally:
            await page.close()

    async def _extract_product_details(self, page: Page) -> dict[str, object]:
        return await page.evaluate(
            """() => {
                const text = (document.body.innerText || '').replace(/\\s+/g, ' ').trim();
                const jsonLd = Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
                  .map((script) => {
                    try { return JSON.parse(script.textContent || '{}'); } catch { return null; }
                  }).filter(Boolean);
                const products = [];
                const visit = (node) => {
                  if (!node || typeof node !== 'object') return;
                  if (node['@type'] === 'Product') products.push(node);
                  for (const value of Object.values(node)) {
                    if (Array.isArray(value)) value.forEach(visit);
                    else visit(value);
                  }
                };
                jsonLd.forEach(visit);
                const product = products[0] || {};
                const meta = (name) => document.querySelector(`meta[property="${name}"], meta[name="${name}"]`)?.content || '';
                const name = product.name || meta('og:title') || document.querySelector('h1')?.innerText || '';
                const description = product.description || meta('description') || text;
                const colorSources = [
                  product.color || '',
                  document.querySelector('[data-testid*="color" i], [class*="color" i]')?.innerText || '',
                  description
                ];
                const price = (
                  product.offers?.price ||
                  product.offers?.lowPrice ||
                  document.querySelector('[data-testid*="price" i], [class*="price" i]')?.innerText ||
                  (text.match(/\\$[0-9][0-9,.]*/) || [''])[0]
                );
                const sku = product.sku || product.productID || meta('product:retailer_item_id') || '';
                const controls = Array.from(document.querySelectorAll('button, [role="button"], input[type="submit"]'));
                const addButtons = controls.filter((el) => /add\\s*to\\s*(cart|bag)|add item/i.test(el.innerText || el.value || el.getAttribute('aria-label') || ''));
                const enabledAddButtons = addButtons.filter((el) => {
                  const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true' || el.className.toString().toLowerCase().includes('disabled');
                  const style = window.getComputedStyle(el);
                  return !disabled && style.visibility !== 'hidden' && style.display !== 'none';
                });
                const variantControls = Array.from(document.querySelectorAll('select, button, [role="radio"], [role="option"], [data-testid*="size" i], [data-testid*="variant" i]'));
                const selectableVariants = variantControls.filter((el) => {
                  const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true';
                  const label = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim();
                  return !disabled && label.length > 0;
                });
                return {
                  name: String(name || ''),
                  color: colorSources.filter(Boolean).join(' '),
                  price: String(price || ''),
                  sku: String(sku || ''),
                  add_to_cart_exists: addButtons.length > 0,
                  add_to_cart_enabled: enabledAddButtons.length > 0,
                  variant_selectable: selectableVariants.length > 0,
                  body_length: text.length
                };
            }"""
        )

    async def _wait_for_purchase_section(self, page: Page) -> None:
        await page.wait_for_load_state("domcontentloaded", timeout=self.config.navigation_timeout_ms)
        try:
            await page.wait_for_load_state("networkidle", timeout=self.config.render_timeout_ms)
        except PlaywrightTimeoutError:
            self.logger.info("network idle timed out; continuing to strict control checks")
        await page.wait_for_function(
            """() => document.body && document.body.innerText && document.body.innerText.length > 500""",
            timeout=self.config.render_timeout_ms,
        )

    async def _settle(self, page: Page) -> None:
        await page.wait_for_load_state("domcontentloaded", timeout=self.config.navigation_timeout_ms)
        try:
            await page.wait_for_load_state("networkidle", timeout=self.config.render_timeout_ms)
        except PlaywrightTimeoutError:
            self.logger.info("network idle timeout url=%s", page.url)
        await asyncio.sleep(random.uniform(1.2, 3.5))

    async def _goto_with_retries(self, page: Page, url: str) -> None:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                await asyncio.sleep(random.uniform(0.5, 2.0) * attempt)
                await page.goto(url, wait_until="domcontentloaded", timeout=self.config.navigation_timeout_ms)
                return
            except Exception as exc:
                last_error = exc
                self.logger.info("retry navigation attempt=%s url=%s error=%s", attempt, url, exc)
                await asyncio.sleep((2**attempt) + random.uniform(0, 2))
        raise RuntimeError(f"navigation failed after retries: {last_error}")

    async def _capture_screenshot(self, page: Page, product_name: str, color: str, size: str) -> Path:
        self.config.screenshot_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe = re.sub(r"[^a-zA-Z0-9]+", "-", f"{product_name}-{color}-{size}").strip("-").lower()
        path = self.config.screenshot_dir / f"{stamp}-{safe}.png"
        await page.screenshot(path=str(path), full_page=True)
        return path


def setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path, encoding="utf-8")],
    )

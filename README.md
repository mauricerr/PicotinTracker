# Hermès Picotin Stock Monitor

Conservative Playwright monitor for real purchasable Hermès US Picotin Lock 18 and Picotin Lock 22 inventory.

The monitor is intentionally quiet. It sends no notification for no stock, uncertain inventory, timeouts, partial rendering, anti-bot challenges, missing purchase controls, disabled add-to-cart controls, or sold-out language.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
python -m playwright install chromium
cp .env.example .env
```

Use Python 3.9 or newer. This machine has been prepared with Homebrew Python 3.14.5 in `.venv314`.

Fill in at least one notification channel in `.env`. Telegram is preferred, then Discord, Pushover, then email.

## Run One Poll

```bash
PYTHONPATH=src .venv314/bin/python -m picotin_monitor.cli --env .env
```

This performs a single polling pass and exits. That is the intended shape for Codex Automations and other scheduled runners.

## Conservative Rules

The monitor notifies only when all of these are true:

- Product name resolves to `Picotin Lock 18` or `Picotin Lock 22`
- Color normalizes to an allowed color
- Product page is fully loaded
- Variant/purchase section is present and not unavailable
- Add-to-cart control exists and is enabled
- No sold-out, unavailable, notify-me, or anti-bot language appears
- The same product/color/size has not notified in the last 6 hours

Primary colors are `Black`, `Gold`, and `Etoupe`. Secondary colors can be enabled with `PICOTIN_SECONDARY_COLORS=true`.

## Codex Automation

Schedule the command every 5 minutes when possible:

```bash
PYTHONPATH=src .venv314/bin/python -m picotin_monitor.cli --env .env
```

If the runner supports only coarser schedules, use 15 minutes. The script remains silent unless it confirms purchasable inventory.

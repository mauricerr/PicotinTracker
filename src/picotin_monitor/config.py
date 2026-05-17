from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


CATEGORY_URL = (
    "https://www.hermes.com/us/en/category/leather-goods/bags-and-clutches/"
    "womens-bags-and-clutches/?facet_line=picotin_lock"
)
HOME_URL = "https://www.hermes.com/us/en/"


def load_env_file(path: Path | None) -> None:
    if not path or not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class MonitorConfig:
    category_url: str
    home_url: str
    cache_path: Path
    screenshot_dir: Path
    log_path: Path
    dedupe_hours: float
    headless: bool
    include_secondary_colors: bool
    max_products: int
    navigation_timeout_ms: int
    render_timeout_ms: int

    @classmethod
    def from_env(cls) -> "MonitorConfig":
        return cls(
            category_url=os.getenv("PICOTIN_CATEGORY_URL", CATEGORY_URL),
            home_url=os.getenv("PICOTIN_HOME_URL", HOME_URL),
            cache_path=Path(os.getenv("PICOTIN_CACHE_PATH", ".state/picotin_seen.json")),
            screenshot_dir=Path(os.getenv("PICOTIN_SCREENSHOT_DIR", "artifacts/screenshots")),
            log_path=Path(os.getenv("PICOTIN_LOG_PATH", "logs/picotin-monitor.log")),
            dedupe_hours=float(os.getenv("PICOTIN_DEDUPE_HOURS", "6")),
            headless=env_bool("PICOTIN_HEADLESS", True),
            include_secondary_colors=env_bool("PICOTIN_SECONDARY_COLORS", False),
            max_products=int(os.getenv("PICOTIN_MAX_PRODUCTS", "60")),
            navigation_timeout_ms=int(os.getenv("PICOTIN_NAVIGATION_TIMEOUT_MS", "45000")),
            render_timeout_ms=int(os.getenv("PICOTIN_RENDER_TIMEOUT_MS", "25000")),
        )

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CandidateProduct:
    name: str
    url: str
    color_hint: str | None = None
    price_hint: str | None = None


@dataclass(frozen=True)
class InventoryHit:
    product_name: str
    color: str
    size: str
    price: str
    url: str
    sku: str
    timestamp: str
    screenshot_path: Path | None = None

    @property
    def dedupe_key(self) -> str:
        return "|".join((self.sku, self.product_name, self.color, self.size)).lower()

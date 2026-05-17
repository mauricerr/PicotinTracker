from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


PRIMARY_COLORS = {"Black", "Gold", "Etoupe"}
SECONDARY_COLORS = {"Gris Meyer", "Etain", "Nata", "Craie"}

FORBIDDEN_PRODUCT_TERMS = (
    "pocket",
    "cargo",
    "casaque",
    "micro",
)

UNAVAILABLE_PATTERNS = (
    "unfortunately this product is no longer available",
    "sold out",
    "out of stock",
    "notify me",
    "not available",
    "temporarily unavailable",
)

ANTI_BOT_PATTERNS = (
    "access denied",
    "captcha",
    "verify you are human",
    "unusual traffic",
    "akamai",
)


@dataclass(frozen=True)
class ProductIdentity:
    canonical_name: str
    size: str


def plain_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_text).strip()


def normalize_for_match(value: str) -> str:
    return plain_text(value).lower()


def identify_product(name: str) -> ProductIdentity | None:
    text = normalize_for_match(name)
    if "picotin" not in text or "lock" not in text:
        return None
    if any(term in text for term in FORBIDDEN_PRODUCT_TERMS):
        return None
    if re.search(r"\b18\b", text):
        return ProductIdentity("Picotin Lock 18", "18")
    if re.search(r"\b22\b", text):
        return ProductIdentity("Picotin Lock 22", "22")
    return None


def normalize_color(raw_color: str, include_secondary: bool = False) -> str | None:
    text = normalize_for_match(raw_color)
    aliases = (
        ("gris meyer", "Gris Meyer"),
        ("etoupe", "Etoupe"),
        ("etain", "Etain"),
        ("noir", "Black"),
        ("black", "Black"),
        ("gold", "Gold"),
        ("nata", "Nata"),
        ("craie", "Craie"),
    )
    allowed = set(PRIMARY_COLORS)
    if include_secondary:
        allowed.update(SECONDARY_COLORS)
    for needle, canonical in aliases:
        if re.search(rf"\b{re.escape(needle)}\b", text) and canonical in allowed:
            return canonical
    return None


def contains_unavailable_text(text: str) -> bool:
    haystack = normalize_for_match(text)
    return any(pattern in haystack for pattern in UNAVAILABLE_PATTERNS)


def contains_anti_bot_text(text: str) -> bool:
    haystack = normalize_for_match(text)
    return any(pattern in haystack for pattern in ANTI_BOT_PATTERNS)

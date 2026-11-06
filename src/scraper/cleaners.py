"""Turn raw page text into clean values."""
from __future__ import annotations

import re
from urllib.parse import urljoin

_NUMBER = re.compile(r"-?\d[\d.,\s]*")


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", " ", value).strip() or None


def to_number(value: str | None) -> float | int | None:
    """Parse '1,299.50', '1.299,50', '1 299' and '£51.77'. Returns None if there is no number."""
    if not value:
        return None
    match = _NUMBER.search(value)
    if not match:
        return None
    raw = re.sub(r"\s", "", match.group()).rstrip(".,")
    has_comma, has_dot = "," in raw, "." in raw
    if has_comma and has_dot:
        # Whichever separator comes last is the decimal point.
        decimal, thousands = (",", ".") if raw.rfind(",") > raw.rfind(".") else (".", ",")
        raw = raw.replace(thousands, "").replace(decimal, ".")
    elif has_comma or has_dot:
        sep = "," if has_comma else "."
        parts = raw.split(sep)
        # 1,299 and 1,299,000 are thousands. 12,5 and 19.99 are decimals.
        if len(parts) > 2 or (len(parts[-1]) == 3 and parts[0] not in {"0", "-0"}):
            raw = raw.replace(sep, "")
        else:
            raw = raw.replace(sep, ".")
    try:
        number = float(raw)
    except ValueError:
        return None
    return int(number) if number.is_integer() else number


def apply_cleaner(kind: str, value: str | None, base_url: str) -> str | float | int | None:
    if kind in {"number", "price"}:
        return to_number(value)
    if kind == "url":
        return urljoin(base_url, value.strip()) if value else None
    return clean_text(value)

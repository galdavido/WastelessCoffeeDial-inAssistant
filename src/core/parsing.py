"""Pure parsers and label normalisers for free-text bag, roast and grind values."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
from typing import Any


def as_non_empty_text(value: Any, default: str = "Unknown") -> str:
    if value is None:
        return default
    text_value = str(value).strip()
    if not text_value or text_value.lower() == "none":
        return default
    return text_value


_LEADING_NUMBER = re.compile(r"\s*(-?\d+(?:[.,]\d+)?)")


# 1 light .. 5 dark. Prod contains "Medium-light", "Medium Light" and
# "Medium-Light" for the same roast, so match on normalised labels. The trade
# names are the ones roasters print instead of a plain level.
_ROAST_ORDINALS: dict[str, int] = {
    "light": 1,
    "blonde": 1,
    "blond": 1,
    "cinnamon": 1,
    "nordic": 1,
    "scandinavian": 1,
    "medium light": 2,
    "light medium": 2,
    "medium": 3,
    "medium dark": 4,
    "dark medium": 4,
    "dark": 5,
    "french": 5,
    "italian": 5,
    "vienna": 5,
}


def parse_grind_clicks(value: str | float | None) -> float | None:
    """Numeric grind value from a free-text setting, or None if there isn't one.

    Historic rows hold strings like "38", "33 clicks" or "Unknown". Returning
    None for the unparseable case is deliberate -- a missing grind value must
    not become a number.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = _LEADING_NUMBER.match(str(value))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def parse_roast_date(value: Any) -> date | None:
    """Parse the roast date vision extracts, tolerating the usual formats.

    Returns None rather than guessing: days-since-roast widens the acceptance
    bands, so a wrong date silently changes the advice. That includes a date
    that parses but cannot be right for a bag being brewed now -- in the
    future, or more than a year old -- which is what a misread digit in the
    year (2023 for 2026) produces.
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() in ("none", "unknown", "n/a"):
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%Y.%m.%d", "%m/%d/%Y"):
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        return parsed if plausible_roast_date(parsed) else None
    return None


# Older than this, a scanned roast date is far more likely a misread year than
# a bag still being dialled in.
MAX_ROAST_AGE_DAYS = 365


def plausible_roast_date(value: date, today: date | None = None) -> bool:
    """Whether a roast date read off a bag could belong to a coffee in use."""
    # A day of slack for a roaster in a timezone ahead of the server.
    age = ((today or date.today()) - value).days
    return -1 <= age <= MAX_ROAST_AGE_DAYS


def roast_level_ordinal(label: str | None) -> int | None:
    """Map a roast-level label onto the 1 (light) .. 5 (dark) ordinal scale."""
    if not label:
        return None
    key = normalize_label(label).removesuffix(" roast")
    return _ROAST_ORDINALS.get(key)


def normalize_label(value: str) -> str:
    lowered = value.strip().lower()
    deaccented = (
        unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode()
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", deaccented).split())

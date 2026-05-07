import re
from decimal import Decimal
from typing import Optional


def parse_price_range(text: str) -> tuple[Optional[Decimal], Optional[Decimal]]:
    """
    Parses user input like "50000-80000", "до 100000", "100000 gacha",
    "от 50000", "50000 dan", "200000+", "200000".
    Returns (min, max) in USD. None means no bound.
    """
    text = text.strip().lower().replace(",", "").replace(" ", "")

    # "50000-80000" or "50000–80000"
    m = re.match(r"^(\d+)[-–](\d+)$", text)
    if m:
        return Decimal(m.group(1)), Decimal(m.group(2))

    # "до100000" / "100000gacha" / "100000tagacha"
    m = re.match(r"^(?:до|до|)(\d+)(?:gacha|tagacha)?$", text)
    if m:
        return None, Decimal(m.group(1))
    m = re.match(r"^(\d+)(?:gacha|tagacha)$", text)
    if m:
        return None, Decimal(m.group(1))

    # "от50000" / "50000dan"
    m = re.match(r"^(?:от|от|)(\d+)(?:dan|ortiq|oshiq)?$", text)
    if m:
        return Decimal(m.group(1)), None
    m = re.match(r"^(\d+)(?:dan|ortiq|oshiq|\+)$", text)
    if m:
        return Decimal(m.group(1)), None

    # single number — treat as max
    m = re.match(r"^(\d+)$", text)
    if m:
        return None, Decimal(m.group(1))

    return None, None


def parse_int(text: str) -> Optional[int]:
    try:
        return int(text.strip())
    except (ValueError, AttributeError):
        return None


def parse_decimal(text: str) -> Optional[Decimal]:
    try:
        cleaned = text.strip().replace(",", ".").replace(" ", "")
        return Decimal(cleaned)
    except Exception:
        return None

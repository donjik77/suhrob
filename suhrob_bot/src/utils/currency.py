from decimal import Decimal


def usd_to_uzs(usd: Decimal | float | int, rate: float) -> int:
    return int(Decimal(str(usd)) * Decimal(str(rate)))


def format_price_uzs(uzs: int) -> str:
    return f"{uzs:,}".replace(",", " ")


def format_price_usd(usd: Decimal | float | int) -> str:
    val = float(usd)
    if val == int(val):
        return f"{int(val):,}"
    return f"{val:,.2f}"

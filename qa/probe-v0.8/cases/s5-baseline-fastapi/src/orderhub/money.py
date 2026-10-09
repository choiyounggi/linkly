from decimal import ROUND_HALF_UP, Decimal


def pct(cents: int, bp: int) -> int:
    """Compute cents * bp/10000, rounded half-up to the nearest cent.

    e.g. pct(5997, 1000) = round(599.7) = 600 (ROUND_HALF_UP).
    """
    value = Decimal(cents) * Decimal(bp) / Decimal(10000)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

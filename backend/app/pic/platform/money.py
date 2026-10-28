"""Money and quantity arithmetic. Amounts are integer minor units (paise)."""
from decimal import ROUND_HALF_UP, Decimal
from typing import Union

Number = Union[int, float, str, Decimal]


def D(value: Number) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def to_minor(rupees: Number) -> int:
    return int((D(rupees) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_minor(minor: int) -> Decimal:
    return (Decimal(minor) / 100).quantize(Decimal("0.01"))


def line_amount(qty: Number, unit_price_minor: int) -> int:
    return int((D(qty) * Decimal(unit_price_minor)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tax_amount(net_minor: int, rate_pct: Number) -> int:
    return int((Decimal(net_minor) * D(rate_pct) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of(minor: int, pct: Number) -> int:
    return int((Decimal(minor) * D(pct) / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fmt_inr(minor: int) -> str:
    """Indian digit grouping, e.g. 2149200_00 -> '₹21,49,200.00'."""
    value = from_minor(minor)
    sign = "-" if value < 0 else ""
    whole, frac = f"{abs(value):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}₹{whole}.{frac}"


def crore(minor: int) -> Decimal:
    return (Decimal(minor) / 100 / Decimal(10_000_000)).quantize(Decimal("0.01"))

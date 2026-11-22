"""Amount comparison and statutory rounding."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from typing import Optional

from app.case_study_2.rules import AMOUNT_TOLERANCE_RUPEES


def round_nearest(value: float) -> float:
    """PF style: nearest rupee, halves go up (Python's round() would use banker's rounding)."""
    return float(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_up(value: float) -> float:
    """ESIC style: any fraction goes to the next higher rupee."""
    return float(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_CEILING))


def amounts_match(wagesheet_amount: Optional[float], ecr_amount: Optional[float]) -> bool:
    if wagesheet_amount is None or ecr_amount is None:
        return False
    return abs(wagesheet_amount - ecr_amount) <= AMOUNT_TOLERANCE_RUPEES


def format_rupees(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"₹{value:,.0f}" if float(value).is_integer() else f"₹{value:,.2f}"

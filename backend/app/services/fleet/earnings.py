"""What one trip pays the rider. Pure, so the admin page, the app and payouts agree."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.services.fleet.config import RiderPay


def earning_for(km: float, pay: RiderPay) -> tuple[Decimal, dict[str, Any]]:
    """`max(minimum, base + per_km x km)`, and the parts it was made from.

    Km is rounded to one decimal: the distance is a road estimate, and paying
    to the metre would claim a precision nobody measured. The breakdown is
    stored on the trip so a rider who asks "why Rs 49?" gets the sum, even
    after the admin changes the rates.
    """

    rounded = round(max(float(km), 0.0), 1)
    amount = pay.base + pay.per_km * Decimal(str(rounded))
    amount = max(amount, pay.minimum).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return amount, {"base": str(pay.base), "per_km": str(pay.per_km), "km": rounded, "minimum": str(pay.minimum)}


__all__ = ["earning_for"]

"""What one trip pays the rider. Pure, so the admin page, the app and payouts agree."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.services.fleet.config import RiderPay

_CENT = Decimal("0.01")


def earning_for(km: float, pay: RiderPay, *, delivered: bool = True) -> tuple[Decimal | None, dict[str, Any]]:
    """The slab this distance falls in plus the incentive, and the parts.

    Km is rounded to one decimal: the distance is a road estimate, and paying
    to the metre would claim a precision nobody measured. The top of a slab
    belongs to it (3.0 km is the "up to 3 km" slab), as on the customer's
    side (`delivery/slabs.fee_for_distance`).

    Past the last slab the amount is None: the owner prices those by hand
    (`trips.set_manual_pay`). The breakdown is stored on the trip so a rider
    who asks "why Rs 35?" gets the sum, even after the admin changes rates.

    The incentive is for a successful delivery: `delivered=False` (cancelled
    after pickup, nobody at the door) pays the slab alone. Offers and the
    board estimate a delivery, so they leave it True.
    """

    rounded = round(max(float(km), 0.0), 1)
    incentive = pay.incentive if delivered else Decimal("0")
    for slab in pay.slabs:
        if rounded <= slab.up_to_km:
            amount = (slab.amount + incentive).quantize(_CENT, rounding=ROUND_HALF_UP)
            return amount, {
                "km": rounded,
                "slab_km": slab.up_to_km,
                "slab": str(slab.amount),
                "incentive": str(incentive),
            }
    return None, {"km": rounded, "manual": True, "over_km": pay.slabs[-1].up_to_km, "incentive": str(incentive)}


__all__ = ["earning_for"]

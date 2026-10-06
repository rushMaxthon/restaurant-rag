"""How one order's money divides between the restaurant and the platform.

The only place this arithmetic lives. The ledger, the transfer and both
screens read the result; none of them adds the columns up again.

    restaurant_share = subtotal - commission - discount + packaging + food GST
    platform_keeps   = commission + delivery fee + delivery GST + platform fee

`subtotal` already carries the commission (the menu price is the restaurant's
price with the platform's percentage folded in), which is why it comes back
out of the restaurant's half. Discounts are the restaurant's: an owner runs
offers for their own kitchen. Delivery and its GST are the platform's, because
the platform pays the rider. Razorpay's own fee is not in either figure: the
platform absorbs it, so a restaurant's share never shrinks with the gateway's.

A split that does not add back up to what the customer paid is BLOCKED rather
than rounded or guessed. That happens to orders from before food and delivery
GST were stored apart, and to anything a later price change adds without
teaching this function; in both cases the right number is unknown, and
transferring a wrong one is real money in the wrong bank.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

_PAISA = Decimal("0.01")


@dataclass(frozen=True)
class Split:
    restaurant_share: Decimal
    platform_keeps: Decimal
    #: Empty when the split can be paid; otherwise the sentence an admin reads.
    blocked_reason: str


def _money(order: Any, name: str) -> Decimal:
    value = getattr(order, name, None)
    return Decimal(value or 0).quantize(_PAISA)


def split_order(order: Any) -> Split:
    share = (
        _money(order, "subtotal")
        - _money(order, "commission_amount")
        - _money(order, "discount_amount")
        + _money(order, "packaging_fee")
        + _money(order, "food_tax_amount")
    )
    keeps = (
        _money(order, "commission_amount")
        + _money(order, "delivery_fee")
        + _money(order, "delivery_tax_amount")
        + _money(order, "platform_fee")
    )
    total = _money(order, "total_amount")

    reason = ""
    if share + keeps != total:
        reason = (
            f"The shares add up to {share + keeps} but the customer paid {total}; "
            "this order's figures do not reconcile, so nothing is transferred."
        )
    elif share < 0:
        reason = "The discount is larger than the food, so the restaurant's share is below zero."
    return Split(restaurant_share=share, platform_keeps=keeps, blocked_reason=reason)

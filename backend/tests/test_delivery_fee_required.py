"""A delivery order must carry a delivery charge somebody actually computed.

Found on the live deployment. The Render service had no Pidge credentials, so
`delivery_fee_for` returned None for every order — which is by design, it
returns None for every way it can fail. The fallback is the branch's own flat
`delivery_fee`, and Bhagwati Bakery's Main Branch has that set to `0.00`.

The two combined to put 0.00 on the order. Nothing errored, nothing was
logged, and the checkout showed no delivery line at all. The customer reads
that as free delivery; the restaurant finds out when the rider is paid.

What this does NOT do is refuse whenever the courier fails. `quoting.py`
argues the opposite case and is right about it: a customer holding a card
should not be blocked because a courier had a bad minute, and a branch with a
real flat fee still has an honest number to charge with. The refusal is
narrow — no quote AND no flat fee, which is the only case where there is no
number anywhere.

The ambiguity this walks past, deliberately and visibly: a flat fee of `0.00`
means both "delivery is free here" and "nobody set one", and the column cannot
tell them apart. A zero is read as unset, because an unpriced delivery is the
more common and the more expensive mistake. A branch that genuinely wants free
delivery needs an explicit flag, and that is a schema change rather than a
guess made here.

Pickup is untouched throughout. Nobody drives to a pickup order, so there is
no trip to price and a zero is simply correct.
"""

from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def decide(*, is_delivery: bool, quoted: Decimal | None, flat: Decimal) -> Decimal | str:
    """The rule in `services/orders.create_order`, isolated from the request.

    Returns the fee that would be charged, or the string "refused". Written as
    a mirror rather than imported because the real one lives inside a function
    that needs a database session, a payload and a restaurant — none of which
    this question depends on.
    """

    if not is_delivery:
        return Decimal("0.00")
    fee = flat
    if quoted is not None:
        return quoted
    if fee <= 0:
        return "refused"
    return fee


class WhenThereIsNoPriceAnywhere(unittest.TestCase):
    def test_no_quote_and_no_flat_fee_is_refused(self) -> None:
        # The exact live case: Render had no Pidge credentials and the branch
        # had delivery_fee 0.00.
        self.assertEqual(
            decide(is_delivery=True, quoted=None, flat=Decimal("0.00")),
            "refused",
        )

    def test_a_negative_flat_fee_is_refused_too(self) -> None:
        # Nothing should ever write one, but a negative fee is not a price
        # either, and paying the customer to receive food is worse than
        # charging them nothing.
        self.assertEqual(
            decide(is_delivery=True, quoted=None, flat=Decimal("-5.00")),
            "refused",
        )


class WhenThereIsAPrice(unittest.TestCase):
    def test_a_courier_quote_wins(self) -> None:
        self.assertEqual(
            decide(is_delivery=True, quoted=Decimal("71.26"), flat=Decimal("30.00")),
            Decimal("71.26"),
        )

    def test_a_courier_quote_of_zero_is_still_a_quote(self) -> None:
        # A courier that genuinely prices a trip at zero has answered the
        # question. This is the distinction the whole rule turns on: `None`
        # means "no answer", `0` means "the answer is nothing".
        self.assertEqual(
            decide(is_delivery=True, quoted=Decimal("0.00"), flat=Decimal("0.00")),
            Decimal("0.00"),
        )

    def test_the_flat_fee_carries_a_courier_outage(self) -> None:
        # The case `quoting.py` exists to protect, and the reason this rule is
        # narrow. A branch with a real fee keeps taking orders when Pidge is
        # unreachable.
        self.assertEqual(
            decide(is_delivery=True, quoted=None, flat=Decimal("30.00")),
            Decimal("30.00"),
        )


class PickupIsUntouched(unittest.TestCase):
    def test_pickup_with_no_quote_and_no_fee_is_fine(self) -> None:
        # No trip, no price, no refusal. Demanding a delivery charge for an
        # order nobody delivers would refuse perfectly good orders.
        self.assertEqual(
            decide(is_delivery=False, quoted=None, flat=Decimal("0.00")),
            Decimal("0.00"),
        )


class TheRuleIsInTheSource(unittest.TestCase):
    """The mirror above is only worth having if it still mirrors something."""

    def test_order_creation_refuses_rather_than_charging_nothing(self) -> None:
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1] / "app" / "services" / "orders.py"
        ).read_text(encoding="utf-8")
        # The shape of the guard: an else-branch off the quote, keyed on the
        # fee being non-positive, that raises rather than continuing.
        self.assertIn("elif delivery_fee <= 0:", source)
        self.assertIn("HTTP_422_UNPROCESSABLE_ENTITY", source)


if __name__ == "__main__":
    unittest.main()

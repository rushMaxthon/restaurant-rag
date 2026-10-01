"""A delivery order needs a number a rider can ring.

Found by dispatching a real order at Pidge's sandbox. The order was placed,
accepted by the kitchen, and the courier refused the whole thing:

    "trips[0].receiver_detail.mobile" is not allowed to be empty

The shape of that failure is what matters. It happens at DISPATCH, which is
triggered by the kitchen accepting — so the order is taken, the food is made,
and no rider is ever booked. The customer is gone by then, and the only sign
is a warning in a worker log.

The web checkout already collects a number and the WhatsApp agent asks for one
outright. Neither is a guarantee: this is the backend, the courier's
requirement is a business rule, and `CLAUDE.md` is explicit that the backend
enforces while the UI only hides. So it is settled at creation, where the
customer is still present to fix it.

Pickup orders are deliberately exempt. Nobody drives to them and no courier is
ever asked, so demanding a phone for one would refuse an order for no reason.
"""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.orders import _contact_phone_for  # noqa: E402


def customer(phone: str | None):
    return SimpleNamespace(phone_number=phone, full_name="Test Customer")


def payload(phone: str | None):
    return SimpleNamespace(contact_phone=phone)


class TheNumberARiderRings(unittest.TestCase):
    def test_what_the_customer_typed_at_checkout_wins(self) -> None:
        # They may be ordering for somebody else, or from a different phone
        # than the one on the account. The number given FOR THIS ORDER is the
        # one the rider should call.
        self.assertEqual(
            _contact_phone_for(customer("+919000000001"), payload("+919000000002")),
            "+919000000002",
        )

    def test_the_account_number_is_the_fallback(self) -> None:
        # The case that produced the bug: a client that sends no contact phone
        # at all. Refusing when the number is already on the account would be
        # failing with the answer in hand.
        self.assertEqual(
            _contact_phone_for(customer("+919000000001"), payload(None)),
            "+919000000001",
        )

    def test_nothing_anywhere_gives_nothing(self) -> None:
        # Not a space, not a placeholder. The caller refuses on empty, and an
        # empty-looking string that is not empty would sail through to the
        # courier and be refused there instead — which is the failure being
        # prevented.
        self.assertEqual(_contact_phone_for(customer(None), payload(None)), "")

    def test_whitespace_is_not_a_phone_number(self) -> None:
        self.assertEqual(_contact_phone_for(customer(None), payload("   ")), "")
        self.assertEqual(_contact_phone_for(customer("  "), payload(None)), "")

    def test_a_blank_payload_still_falls_back(self) -> None:
        # A form that submits "" rather than omitting the field must behave the
        # same as one that omits it.
        self.assertEqual(
            _contact_phone_for(customer("+919000000001"), payload("")),
            "+919000000001",
        )


if __name__ == "__main__":
    unittest.main()

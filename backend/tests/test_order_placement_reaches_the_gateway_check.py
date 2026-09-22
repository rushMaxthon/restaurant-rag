"""Placing an order runs the payment-availability check without crashing.

Live, to a real customer on WhatsApp:

    >>> Yes place it
    I could not place that order just now. Let me get someone to help.

Behind it, in the worker log:

    File "app/services/orders.py", line 368, in _prepare_order_draft
        restaurant_id=draft.restaurant.id,
    NameError: name 'draft' is not defined

`draft` is what `_prepare_order_draft` is on its way to BUILDING; the rows it
already holds are `restaurant` and `restaurant_location`, used two lines
further down. Every card order raised here, so nothing could be placed at all
— on any channel, by any customer.

**No test caught it because every test mocks this function.** `create_order`
is exercised with `patch.object(orders, "_prepare_order_draft", ...)`, which
is reasonable for testing what surrounds it and means the line itself never
ran. This test drives the real function far enough to reach that check, with
only the two loaders and the gateway lookup stubbed.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.enums import (
    OrderFulfillmentType,
    OrderScheduleType,
    PaymentMethod,
    UserRole,
)
from app.services import orders


def a_customer():
    return SimpleNamespace(id=uuid.uuid4(), role=UserRole.CUSTOMER, full_name="Vishal")


def a_payload(**over):
    base = {
        "restaurant_id": uuid.uuid4(),
        "restaurant_location_id": uuid.uuid4(),
        "fulfillment_type": OrderFulfillmentType.DELIVERY,
        "schedule_type": OrderScheduleType.ASAP,
        "scheduled_at": None,
        "payment_method": PaymentMethod.CARD,
        "items": [],
        "delivery_address": "42 Example Road",
        "contact_name": "Vishal",
        "contact_phone": "+919876500099",
        "contact_email": "vishal@example.com",
        "special_instructions": None,
        "offer_id": None,
    }
    base.update(over)
    return SimpleNamespace(**base)


class ThePaymentCheckRunsTests(unittest.TestCase):
    """It reads the rows this function loaded, not one it has not built."""

    def setUp(self) -> None:
        self.restaurant = SimpleNamespace(id=uuid.uuid4(), name="Bangkok Bowl",
                                          currency="CAD")
        self.location = SimpleNamespace(
            id=uuid.uuid4(), branch_name="Bodakdev",
            minimum_order_amount=Decimal("0.00"),
        )
        self.seen: dict = {}

    def _run(self, available):
        def fake_available(db, *, restaurant_id, location):
            # What the check is asked, which is the half that was broken.
            self.seen["restaurant_id"] = restaurant_id
            self.seen["location"] = location
            return available

        with (
            patch.object(orders, "_load_restaurant_for_order", return_value=self.restaurant),
            patch.object(orders, "_load_location_for_order", return_value=self.location),
            patch.object(orders, "_resolve_scheduled_at", return_value=None),
            patch.object(
                orders, "get_enabled_payment_methods", return_value=[PaymentMethod.CARD]
            ),
            patch.object(orders, "available_payment_methods", fake_available),
            # Past the check is another function's business; stopping here
            # keeps this test about the line that crashed.
            patch.object(
                orders,
                "fetch_menu_items_for_customized_order",
                side_effect=RuntimeError("reached the menu step"),
            ),
        ):
            with self.assertRaises(Exception) as caught:  # noqa: B017
                orders._prepare_order_draft(
                    None, a_customer(), a_payload(), require_payment_validation=True
                )
            return caught.exception

    def test_it_does_not_raise_a_name_error(self) -> None:
        error = self._run([PaymentMethod.CARD])
        self.assertNotIsInstance(error, NameError)
        self.assertEqual(str(error), "reached the menu step", "it got past the check")

    def test_it_asks_about_this_restaurant_and_this_branch(self) -> None:
        # The bug was not only the crash: whatever it meant to read, it had
        # to be the rows for THIS order. A restaurant settles through its own
        # gateway account, so asking about another's is a wrong answer even
        # when it does not raise.
        self._run([PaymentMethod.CARD])
        self.assertEqual(self.seen["restaurant_id"], self.restaurant.id)
        self.assertIs(self.seen["location"], self.location)

    def test_a_method_the_branch_cannot_settle_is_refused(self) -> None:
        # The check still does its job: this is the guard that stopped a card
        # button charging the wrong account.
        error = self._run([])
        self.assertEqual(getattr(error, "status_code", None), 503)
        self.assertIn("Card payments are not available", str(getattr(error, "detail", "")))

    def test_validation_can_be_skipped(self) -> None:
        # Some callers place on behalf of a channel that has already checked.
        with (
            patch.object(orders, "_load_restaurant_for_order", return_value=self.restaurant),
            patch.object(orders, "_load_location_for_order", return_value=self.location),
            patch.object(orders, "_resolve_scheduled_at", return_value=None),
            patch.object(
                orders, "get_enabled_payment_methods", return_value=[PaymentMethod.CARD]
            ),
            patch.object(
                orders,
                "available_payment_methods",
                side_effect=AssertionError("must not be consulted"),
            ),
            patch.object(
                orders,
                "fetch_menu_items_for_customized_order",
                side_effect=RuntimeError("reached the menu step"),
            ),
        ):
            with self.assertRaises(RuntimeError) as caught:
                orders._prepare_order_draft(
                    None, a_customer(), a_payload(), require_payment_validation=False
                )
        self.assertEqual(str(caught.exception), "reached the menu step")


if __name__ == "__main__":
    unittest.main()

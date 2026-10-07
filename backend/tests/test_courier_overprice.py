"""A rider assigned at a price far above what the customer paid for delivery.

Pidge's account auto-allocates, so Pidge - not us - picks the network, and
the price is only known once a rider is on the way. On 2026-10-06 the
checkout quoted about Rs 57 for a 3.7 km trip and wefast was assigned at
Rs 285.61, twice; porter took the same trip for Rs 76.69. Nobody saw it
until the wallet ran down.

Decided with the platform owner: FLAG, never cancel - the food still goes
out - and only past 1.5x what the customer paid (fee plus its GST line),
so an ordinary spread between the estimate and the network's price is not
noise. The courier's charge is the platform admin's to see and nobody
else's (`OrderDeliveryResponse.for_viewer`), and so is this flag.
"""

from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.models.enums import UserRole  # noqa: E402
from app.schemas.order import OrderDeliveryResponse  # noqa: E402
from app.services.delivery import service  # noqa: E402

# 2026-10-06, Bhagwati Bakery: fee 48.31 plus 8.69 GST = 57.00 paid.
PAID = dict(delivery_fee=Decimal("48.31"), delivery_tax_amount=Decimal("8.69"))


def order(**over):
    return SimpleNamespace(**{**PAID, **over})


def row(charge):
    return SimpleNamespace(courier_charge=None if charge is None else Decimal(charge))


class WhatCountsAsOverpricedTests(unittest.TestCase):
    def test_paid_for_delivery_is_the_fee_and_its_tax(self) -> None:
        self.assertEqual(service.paid_for_delivery(order()), Decimal("57.00"))

    def test_wefast_at_five_times_the_fee_is_flagged(self) -> None:
        self.assertTrue(service.courier_overpriced(order(), row("285.61")))

    def test_porter_a_little_over_is_not(self) -> None:
        # 76.69 against 57.00 is 1.35x: an ordinary spread, not a problem.
        self.assertFalse(service.courier_overpriced(order(), row("76.69")))

    def test_exactly_at_the_line_is_not(self) -> None:
        self.assertFalse(service.courier_overpriced(order(), row("85.50")))
        self.assertTrue(service.courier_overpriced(order(), row("85.51")))

    def test_no_charge_yet_is_not(self) -> None:
        self.assertFalse(service.courier_overpriced(order(), row(None)))

    def test_free_delivery_is_a_decision_not_an_overcharge(self) -> None:
        # The restaurant chose to charge nothing; any courier price is "over"
        # zero, and flagging every free-delivery order would bury the real ones.
        free = order(delivery_fee=Decimal("0"), delivery_tax_amount=Decimal("0"))
        self.assertFalse(service.courier_overpriced(free, row("50")))

    def test_the_line_is_a_setting(self) -> None:
        with mock.patch.object(service, "get_settings", return_value=SimpleNamespace(courier_overprice_ratio=1.25)):
            self.assertTrue(service.courier_overpriced(order(), row("76.69")))


class WhoSeesTheFlagTests(unittest.TestCase):
    def _response(self) -> OrderDeliveryResponse:
        now = datetime.now(UTC)
        return OrderDeliveryResponse(
            provider="pidge", provider_order_id="x", state="ASSIGNED", provider_status="OUT_FOR_PICKUP",
            rider_name="", rider_mobile="", tracking_url="", distance_metres=None, picked_up_at=None,
            delivered_at=None, last_error="", created_at=now, updated_at=now, courier_charge=Decimal("285.61"),
            paid_for_delivery=Decimal("57.00"), courier_overpriced=True,
        )

    def test_the_platform_admin_does(self) -> None:
        seen = self._response().for_viewer(SimpleNamespace(role=UserRole.ADMIN))
        self.assertTrue(seen.courier_overpriced)
        self.assertEqual(seen.paid_for_delivery, Decimal("57.00"))

    def test_nobody_else_does(self) -> None:
        for role in (UserRole.OWNER, UserRole.KITCHEN, UserRole.CUSTOMER):
            with self.subTest(role=role):
                seen = self._response().for_viewer(SimpleNamespace(role=role))
                self.assertFalse(seen.courier_overpriced)
                self.assertIsNone(seen.paid_for_delivery)


class TheOrderPageCarriesItTests(unittest.TestCase):
    def test_the_delivery_card_is_told(self) -> None:
        from app.api.orders import _delivery_response

        now = datetime.now(UTC)
        delivery = SimpleNamespace(
            order_id="o1", provider="pidge", provider_order_id="P", state="ASSIGNED", provider_status="OUT_FOR_PICKUP",
            rider_name="Mohit", rider_mobile="", tracking_url="", distance_metres=3700.9, picked_up_at=None,
            delivered_at=None, last_error="", created_at=now, updated_at=now, courier_charge=Decimal("285.61"),
            pickup_eta=None, drop_eta=None, rider_latitude=None, rider_longitude=None, rider_location_at=None,
            failure_reason="", timeline=[], attempt=1, network_name="wefast", network_order_id="95435557",
            allocated_at=None,
        )
        the_order = SimpleNamespace(status="PREPARING", **PAID)
        db = mock.Mock()
        db.get.return_value = the_order
        with mock.patch.object(service, "can_rebook", return_value=False), \
                mock.patch.object(service, "can_cancel", return_value=False), \
                mock.patch.object(service, "can_allocate", return_value=False), \
                mock.patch.object(service, "simulate_allowed", return_value=False):
            response = _delivery_response(db, delivery, SimpleNamespace(role=UserRole.ADMIN))
        self.assertTrue(response.courier_overpriced)
        self.assertEqual(response.paid_for_delivery, Decimal("57.00"))


class SayingSoWhenItHappensTests(unittest.TestCase):
    def test_a_warning_is_logged_once_when_the_price_arrives(self) -> None:
        from app.services.delivery.base import DeliveryResult, DeliveryState

        the_order = SimpleNamespace(id="o1", **PAID)
        the_row = SimpleNamespace(order_id="o1", courier_charge=None)
        result = DeliveryResult(provider_order_id="P", state=DeliveryState.ASSIGNED, courier_charge=Decimal("285.61"))
        with self.assertLogs("app.services.delivery.service", level="WARNING") as logged:
            service.note_courier_price(the_order, the_row, result)
        self.assertIn("285.61", logged.output[0])
        self.assertIn("57.00", logged.output[0])
        # Once the row already holds that price, the next poll says nothing.
        the_row.courier_charge = Decimal("285.61")
        with mock.patch.object(service.logger, "warning") as warned:
            service.note_courier_price(the_order, the_row, result)
        warned.assert_not_called()


if __name__ == "__main__":
    unittest.main()

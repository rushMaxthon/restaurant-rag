"""The own fleet is a courier, and Pidge takes over when our riders do not.

The flag-off test is the one that protects production: with
`enable_own_fleet` off, dispatch must pick exactly the courier it picked
before this existed. The fallback tests protect the food: a delivery our
riders pass on reaches Pidge on the SAME row (one live booking per order),
and when there is nobody at all, it says so where an admin will see it.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, postgres_available  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.enums import OfferOutcome  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.models.rider import RiderOffer  # noqa: E402
from app.services.delivery import registry, service  # noqa: E402
from app.services.delivery.base import DeliveryResult, DeliveryState  # noqa: E402

LOCAL_DISPATCH = {"ENABLE_DELIVERY_DISPATCH": "true", "PIDGE_BASE_URL": "https://store.dev.pidge.in"}


class _FakeCourier:
    name = "pidge"

    def __init__(self) -> None:
        self.created = []

    def create(self, request):
        self.created.append(request)
        return DeliveryResult(provider_order_id="P-123", state=DeliveryState.PENDING, provider_status="created")


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class FleetCourierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_courier_test")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fdb.drop()

    def setUp(self) -> None:
        self.addCleanup(get_settings.cache_clear)
        self.addCleanup(registry.reset_delivery_provider)
        get_settings.cache_clear()
        registry.reset_delivery_provider()

    def _env(self, **extra):
        patcher = mock.patch.dict(os.environ, {**LOCAL_DISPATCH, **extra})
        patcher.start()
        self.addCleanup(patcher.stop)
        get_settings.cache_clear()
        registry.reset_delivery_provider()

    def test_flag_off_dispatch_picks_the_same_courier_as_before(self) -> None:
        self._env()
        sentinel = object()
        with mock.patch.object(registry, "delivery_provider", return_value=sentinel):
            self.assertIs(registry.dispatch_provider(), sentinel)

    def test_flag_on_dispatch_creates_a_pending_fleet_row_and_starts_offering(self) -> None:
        self._env(ENABLE_OWN_FLEET="true")
        with self.fdb.session() as db:
            order = self.fdb.make_order(db)
            db.commit()
            with mock.patch("app.services.fleet.offers.queue_advance") as advance:
                row = service.dispatch(db, order)
                db.commit()
            self.assertEqual(row.provider, "own_fleet")
            self.assertEqual(row.state, "PENDING")
            self.assertTrue(row.provider_order_id.startswith("fleet-"))
            self.assertEqual(len(row.delivery_otp_hash), 64)
            advance.assert_called_once_with(row.id)

    def test_fallback_repoints_the_same_row_to_the_courier(self) -> None:
        self._env()
        courier = _FakeCourier()
        with self.fdb.session() as db:
            order = self.fdb.make_order(db)
            row = self.fdb.make_fleet_delivery(db, order)
            row_id = row.id
            with mock.patch.object(service, "delivery_provider", return_value=courier):
                service.fallback_to_pidge(db, row, "no rider accepted")
            db.commit()
        with self.fdb.session() as db:
            again = db.get(OrderDelivery, row_id)
            self.assertEqual((again.provider, again.attempt, again.provider_order_id), ("pidge", 2, "P-123"))
        self.assertEqual(courier.created[0].reference, f"{order.id}-2")

    def test_no_rider_and_no_courier_is_visible(self) -> None:
        self._env()
        with self.fdb.session() as db:
            order = self.fdb.make_order(db)
            row = self.fdb.make_fleet_delivery(db, order)
            with mock.patch.object(service, "delivery_provider", return_value=None):
                service.fallback_to_pidge(db, row, "no rider online nearby")
            db.commit()
            self.assertEqual(row.provider, service.UNASSIGNED)
            self.assertIn("no rider online nearby", row.last_error)
            from app.services import platform_watch

            check = platform_watch._check_fleet(db)
            self.assertEqual(check.status, platform_watch.DOWN)
            self.assertIn("1", check.detail)

    def test_cancelling_a_fleet_order_needs_no_courier_and_withdraws_the_offer(self) -> None:
        self._env()
        with self.fdb.session() as db:
            order = self.fdb.make_order(db)
            rider = self.fdb.make_rider(db)
            row = self.fdb.make_fleet_delivery(db, order)
            from datetime import UTC, datetime, timedelta

            now = datetime.now(UTC)
            db.add(RiderOffer(order_delivery_id=row.id, rider_user_id=rider.id, offered_at=now,
                              expires_at=now + timedelta(seconds=30)))
            db.commit()
            with mock.patch.object(service, "delivery_provider") as courier:
                service.cancel(db, order)
                db.commit()
            courier.assert_not_called()
            self.assertEqual(row.state, "CANCELLED")
            outcome = db.scalar(select(RiderOffer.outcome).where(RiderOffer.order_delivery_id == row.id))
            self.assertEqual(outcome, OfferOutcome.WITHDRAWN)


if __name__ == "__main__":
    unittest.main()

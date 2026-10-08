"""Findings from the independent review of the fleet backend (2026-10-08).

Each test reproduces one way the first version could put two riders on one
order, a rider on a cancelled order, or a stale "cancelled" on a live trip.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, postgres_available  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models.enums import OfferOutcome, OrderStatus, RiderStatus  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.models.rider import RiderOffer, RiderTrip  # noqa: E402
from app.services.delivery import service  # noqa: E402
from app.services.delivery.base import DeliveryResult, DeliveryState  # noqa: E402
from app.services.fleet import offers, trips  # noqa: E402

LOCAL_DISPATCH = {"ENABLE_DELIVERY_DISPATCH": "true", "PIDGE_BASE_URL": "https://store.dev.pidge.in"}


class _Courier:
    name = "pidge"

    def __init__(self) -> None:
        self.created = 0

    def create(self, request):
        self.created += 1
        return DeliveryResult(provider_order_id=f"P-{self.created}", state=DeliveryState.PENDING)

    def cancel(self, provider_order_id):
        return None


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class ReviewFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_review_test")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fdb.drop()

    def setUp(self) -> None:
        env = mock.patch.dict(os.environ, LOCAL_DISPATCH)
        env.start()
        self.addCleanup(env.stop)
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        self.notify = {}
        for target in ("offer_made", "offer_withdrawn", "trip_changed", "trip_cancelled", "order_moved"):
            p = mock.patch(f"app.services.fleet.notify.{target}")
            self.notify[target] = p.start()
            self.addCleanup(p.stop)
        for target in ("schedule_expiry", "queue_advance"):
            p = mock.patch(f"app.services.fleet.offers.{target}")
            p.start()
            self.addCleanup(p.stop)

    # 1 -------------------------------------------------------------------------
    def test_rebook_of_a_fleet_row_hands_it_to_the_courier_for_good(self) -> None:
        courier = _Courier()
        with self.fdb.session() as db:
            order = self.fdb.make_order(db)
            row = self.fdb.make_fleet_delivery(db, order, state="FAILED")
            db.commit()
            with mock.patch.object(service, "delivery_provider", return_value=courier):
                service.rebook(db, db.get(Order, order.id))
                db.commit()
                self.assertEqual(row.provider, "pidge")
                # The offer loop must leave a courier's row alone.
                self.assertEqual(offers.advance(db, row.id), "closed")
        self.assertEqual(courier.created, 1)

    # 3 -------------------------------------------------------------------------
    def test_rider_is_told_of_a_cancel_only_after_it_commits(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, status=RiderStatus.ON_TRIP)
            order = self.fdb.make_order(db)
            row = self.fdb.make_fleet_delivery(db, order, state="ASSIGNED")
            db.add(RiderTrip(order_delivery_id=row.id, rider_user_id=rider.id, accepted_at=datetime.now(UTC)))
            db.commit()
            service.cancel(db, db.get(Order, order.id))
            self.notify["trip_cancelled"].assert_not_called()
            db.commit()
            self.notify["trip_cancelled"].assert_called_once()

    # 4 -------------------------------------------------------------------------
    def test_cancel_reaches_a_fleet_row_with_no_booking_id(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db)
            order = self.fdb.make_order(db)
            row = self.fdb.make_fleet_delivery(db, order, provider="unassigned", provider_order_id="")
            now = datetime.now(UTC)
            db.add(RiderOffer(order_delivery_id=row.id, rider_user_id=rider.id, offered_at=now,
                              expires_at=now + timedelta(seconds=30)))
            db.commit()
            service.cancel(db, db.get(Order, order.id))
            db.commit()
            self.assertEqual(row.state, "CANCELLED")
            outcome = db.scalar(select(RiderOffer.outcome).where(RiderOffer.order_delivery_id == row.id))
            self.assertEqual(outcome, OfferOutcome.WITHDRAWN)

    def test_accept_is_refused_on_a_cancelled_order(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db)
            order = self.fdb.make_order(db, status=OrderStatus.CANCELLED)
            row = self.fdb.make_fleet_delivery(db, order)
            now = datetime.now(UTC)
            offer = RiderOffer(order_delivery_id=row.id, rider_user_id=rider.id, offered_at=now,
                               expires_at=now + timedelta(seconds=30))
            db.add(offer)
            db.commit()
            with self.assertRaises(HTTPException) as raised:
                offers.accept(db, rider, offer.id)
            self.assertEqual(raised.exception.status_code, 409)

    def test_watch_ignores_unassigned_rows_of_finished_orders(self) -> None:
        from app.services import platform_watch

        with self.fdb.session() as db:
            for row in db.scalars(select(OrderDelivery).where(OrderDelivery.provider == "unassigned")):
                row.state = "CANCELLED"
            order = self.fdb.make_order(db, status=OrderStatus.CANCELLED)
            self.fdb.make_fleet_delivery(db, order, provider="unassigned", provider_order_id="")
            db.commit()
            self.assertNotEqual(platform_watch._check_fleet(db).status, platform_watch.DOWN)

    # 5 -------------------------------------------------------------------------
    def test_reassign_refuses_a_delivery_the_courier_holds(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db)
            admin = self.fdb.make_admin(db)
            order = self.fdb.make_order(db)
            row = self.fdb.make_fleet_delivery(db, order, provider="pidge", provider_order_id="P-9", state="ASSIGNED")
            db.commit()
            with self.assertRaises(HTTPException) as raised:
                offers.reassign(db, admin, row, rider.id)
            self.assertEqual(raised.exception.detail, "courier_has_it")

    def test_reassign_refuses_a_rider_already_looking_at_an_offer(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db)
            admin = self.fdb.make_admin(db)
            first = self.fdb.make_fleet_delivery(db, self.fdb.make_order(db))
            second = self.fdb.make_fleet_delivery(db, self.fdb.make_order(db))
            now = datetime.now(UTC)
            db.add(RiderOffer(order_delivery_id=first.id, rider_user_id=rider.id, offered_at=now,
                              expires_at=now + timedelta(seconds=30)))
            db.commit()
            with self.assertRaises(HTTPException) as raised:
                offers.reassign(db, admin, second, rider.id)
            self.assertEqual(raised.exception.detail, "rider_busy")

    # 7 -------------------------------------------------------------------------
    def test_the_loop_stops_for_a_cancelled_order(self) -> None:
        with self.fdb.session() as db:
            self.fdb.make_rider(db, lat=21.181, lng=72.84)
            order = self.fdb.make_order(db, status=OrderStatus.CANCELLED)
            row = self.fdb.make_fleet_delivery(db, order)
            db.commit()
            with mock.patch.object(service, "fallback_to_pidge") as fallback:
                self.assertEqual(offers.advance(db, row.id), "closed")
            fallback.assert_not_called()

    def test_fallback_books_nobody_for_a_cancelled_order(self) -> None:
        courier = _Courier()
        with self.fdb.session() as db:
            order = self.fdb.make_order(db, status=OrderStatus.CANCELLED)
            row = self.fdb.make_fleet_delivery(db, order)
            with mock.patch.object(service, "delivery_provider", return_value=courier):
                service.fallback_to_pidge(db, row, "no rider accepted")
        self.assertEqual(courier.created, 0)


if __name__ == "__main__":
    unittest.main()

"""A rider's trip, step by step, and what each step does to the order.

Each step is written through `delivery.service.record`, the function Pidge's
webhook feeds, so "picked up" moves the order to OUT_FOR_DELIVERY and
"delivered" to DELIVERED by the same forward-only rule. Steps cannot be
skipped, a retried request (same action id) changes nothing twice, the
delivery code locks after five wrong tries, and "customer unavailable" is
only allowed after a real wait and two calls.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, client_for, postgres_available, reset_overrides  # noqa: E402

from sqlalchemy import func, select  # noqa: E402

from app.models.enums import OrderStatus, RiderStatus, TripEndReason  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.models.order_status_event import OrderStatusEvent  # noqa: E402
from app.models.rider import Rider, RiderTrip  # noqa: E402
from app.services.fleet import otp, trips  # noqa: E402


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class TripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_trips_test")

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def setUp(self) -> None:
        for target in ("trip_changed", "trip_cancelled", "order_moved", "offer_made", "offer_withdrawn"):
            p = mock.patch(f"app.services.fleet.notify.{target}")
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(reset_overrides)

    def _trip(self, **trip_kw):
        """An order on a live trip: rider ON_TRIP, delivery ASSIGNED, 4 km."""

        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, status=RiderStatus.ON_TRIP)
            order = self.fdb.make_order(db, status=OrderStatus.PREPARING)
            delivery = self.fdb.make_fleet_delivery(db, order, state="ASSIGNED", distance_metres=4000.0)
            trip = RiderTrip(order_delivery_id=delivery.id, rider_user_id=rider.id,
                             accepted_at=datetime.now(UTC), **trip_kw)
            db.add(trip)
            db.commit()
            return rider, order, delivery, trip

    def _act(self, rider, trip, action, **body):
        body.setdefault("action_id", uuid.uuid4().hex)
        return client_for(self.fdb, rider).post(f"/api/rider/trip/{trip.id}/{action}", json=body)

    def test_happy_path_moves_the_order(self) -> None:
        rider, order, delivery, trip = self._trip()
        self.assertEqual(self._act(rider, trip, "arrived-pickup").status_code, 200)
        r = self._act(rider, trip, "picked-up")
        self.assertEqual(r.status_code, 200, r.text)
        with self.fdb.session() as db:
            self.assertEqual(db.get(Order, order.id).status, OrderStatus.OUT_FOR_DELIVERY)
        self.assertEqual(self._act(rider, trip, "arrived-drop").status_code, 200)
        r = self._act(rider, trip, "delivered", otp=otp.code_for(order.id))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["step"], "done")
        with self.fdb.session() as db:
            self.assertEqual(db.get(Order, order.id).status, OrderStatus.DELIVERED)
            done = db.get(RiderTrip, trip.id)
            self.assertEqual(done.end_reason, TripEndReason.DELIVERED)
            self.assertEqual(done.earning_amount, Decimal("35.00"))  # 3.5-4 km slab Rs 30 + Rs 5 a delivery
            self.assertEqual(db.get(Rider, rider.id).status, RiderStatus.ONLINE)
            self.assertEqual(db.get(OrderDelivery, delivery.id).state, "DELIVERED")

    def test_steps_cannot_be_skipped(self) -> None:
        rider, _, _, trip = self._trip()
        r = self._act(rider, trip, "picked-up")
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "out_of_order"))

    def test_retry_is_idempotent(self) -> None:
        rider, order, _, trip = self._trip(arrived_pickup_at=datetime.now(UTC))
        action_id = uuid.uuid4().hex
        first = self._act(rider, trip, "picked-up", action_id=action_id)
        again = self._act(rider, trip, "picked-up", action_id=action_id)
        self.assertEqual((first.status_code, again.status_code), (200, 200))
        with self.fdb.session() as db:
            events = db.scalar(select(func.count(OrderStatusEvent.id)).where(
                OrderStatusEvent.order_id == order.id, OrderStatusEvent.to_status == OrderStatus.OUT_FOR_DELIVERY))
            self.assertEqual(events, 1)

    def test_wrong_otp_counts_down_then_locks(self) -> None:
        now = datetime.now(UTC)
        rider, order, _, trip = self._trip(arrived_pickup_at=now, picked_up_at=now, arrived_drop_at=now)
        right = otp.code_for(order.id)
        wrong = "0000" if right != "0000" else "1111"
        for left in (4, 3, 2, 1, 0):
            r = self._act(rider, trip, "delivered", otp=wrong)
            self.assertEqual(r.status_code, 422)
            self.assertEqual(r.json()["detail"], {"code": "otp_wrong", "attempts_left": left})
        r = self._act(rider, trip, "delivered", otp=right)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "otp_locked"))

    def test_admin_confirm_completes_a_locked_delivery(self) -> None:
        now = datetime.now(UTC)
        rider, order, delivery, trip = self._trip(arrived_pickup_at=now, picked_up_at=now, arrived_drop_at=now)
        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            row = db.get(OrderDelivery, delivery.id)
            row.otp_locked = True
            db.commit()
            trips.admin_confirm_delivered(db, admin, row, "Customer showed the code on a call")
        with self.fdb.session() as db:
            self.assertEqual(db.get(RiderTrip, trip.id).end_reason, TripEndReason.DELIVERED)
            self.assertEqual(db.get(Order, order.id).status, OrderStatus.DELIVERED)
            events = [e["event"] for e in db.get(OrderDelivery, delivery.id).timeline]
            self.assertIn("confirmed_by_admin", events)

    def test_unavailable_needs_a_wait_and_two_calls(self) -> None:
        now = datetime.now(UTC)
        rider, order, delivery, trip = self._trip(arrived_pickup_at=now, picked_up_at=now, arrived_drop_at=now)
        r = self._act(rider, trip, "unavailable")
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "too_early"))
        with self.fdb.session() as db:
            db.get(RiderTrip, trip.id).arrived_drop_at = now - timedelta(minutes=11)
            db.commit()
        self._act(rider, trip, "call-logged")
        self.assertEqual(self._act(rider, trip, "unavailable").json()["detail"], "too_early")
        self._act(rider, trip, "call-logged")
        r = self._act(rider, trip, "unavailable")
        self.assertEqual(r.status_code, 200, r.text)
        with self.fdb.session() as db:
            self.assertEqual(db.get(OrderDelivery, delivery.id).state, "FAILED")
            self.assertEqual(db.get(RiderTrip, trip.id).end_reason, TripEndReason.CUSTOMER_UNAVAILABLE)
            self.assertEqual(db.get(Rider, rider.id).status, RiderStatus.ONLINE)

    def test_cancel_during_trip_pays_after_arrival(self) -> None:
        cases = (
            ({}, Decimal("0.00"), TripEndReason.CANCELLED_BEFORE_PICKUP),
            ({"arrived_pickup_at": datetime.now(UTC)}, Decimal("25"), TripEndReason.CANCELLED_BEFORE_PICKUP),
            ({"arrived_pickup_at": datetime.now(UTC), "picked_up_at": datetime.now(UTC)},
             Decimal("30.00"), TripEndReason.CANCELLED_AFTER_PICKUP),  # the slab; Rs 5 is for a delivery
        )
        for trip_kw, pay, reason in cases:
            with self.subTest(trip=list(trip_kw)):
                rider, _, delivery, trip = self._trip(**trip_kw)
                with self.fdb.session() as db:
                    trips.on_order_cancelled(db, db.get(OrderDelivery, delivery.id))
                    db.commit()
                with self.fdb.session() as db:
                    ended = db.get(RiderTrip, trip.id)
                    self.assertEqual((ended.earning_amount, ended.end_reason), (pay, reason))
                    self.assertEqual(db.get(Rider, rider.id).status, RiderStatus.ONLINE)

    def test_another_riders_trip_is_404(self) -> None:
        _, _, _, trip = self._trip()
        with self.fdb.session() as db:
            stranger = self.fdb.make_rider(db)
            db.commit()
        self.assertEqual(self._act(stranger, trip, "arrived-pickup").status_code, 404)

    def test_active_trip_view_for_the_app(self) -> None:
        rider, order, _, trip = self._trip()
        r = client_for(self.fdb, rider).get("/api/rider/trip")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["id"], str(trip.id))
        self.assertEqual(body["step"], "to_pickup")
        self.assertEqual(body["pickup"]["name"], "Bhagwati Bakery")
        self.assertEqual(body["drop"]["name"], "Asha")
        self.assertNotIn(otp.code_for(order.id), r.text)

    def test_no_trip_is_204(self) -> None:
        with self.fdb.session() as db:
            idle = self.fdb.make_rider(db)
            db.commit()
        self.assertEqual(client_for(self.fdb, idle).get("/api/rider/trip").status_code, 204)

    def test_otp_is_four_digits_and_stable(self) -> None:
        ids = [uuid.uuid4() for _ in range(20)]
        codes = [otp.code_for(i) for i in ids]
        self.assertTrue(all(len(c) == 4 and c.isdigit() for c in codes))
        self.assertEqual(codes[0], otp.code_for(ids[0]))
        self.assertGreater(len(set(codes)), 1)


if __name__ == "__main__":
    unittest.main()

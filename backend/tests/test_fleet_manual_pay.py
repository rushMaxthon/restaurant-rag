"""Past the rate card, a person sets the pay (the owner's rule, 2026-10-10).

The rate card ends at 8 km: "above 8 km - manual pricing". Such a trip still
runs and still ends, but with no amount - never a number nobody chose - and
waits on the admin's Riders page until the admin types the pay. The Rs 5
delivery incentive is added on top, exactly as on a slab trip, and the trip
is then paid in the next payout like any other.

The incentive is for a successful delivery only: a rider who carried food to
a door nobody opened, or whose order was cancelled after pickup, is paid the
slab without it.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, client_for, postgres_available, reset_overrides  # noqa: E402

from app.models.enums import OrderStatus, RiderStatus, TripEndReason  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.models.rider import RiderTrip  # noqa: E402
from app.services.fleet import otp, trips  # noqa: E402


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class ManualPayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_manual_pay_test")
        with cls.fdb.session() as db:
            cls.admin = cls.fdb.make_admin(db)
            cls.owner = cls.fdb.make_owner(db)
            db.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def setUp(self) -> None:
        for target in ("trip_changed", "trip_cancelled", "order_moved", "offer_made", "offer_withdrawn",
                       "delivery_changed", "riders_changed"):
            p = mock.patch(f"app.services.fleet.notify.{target}")
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(reset_overrides)

    def _trip(self, metres: float, **trip_kw):
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, status=RiderStatus.ON_TRIP)
            order = self.fdb.make_order(db, status=OrderStatus.PREPARING)
            delivery = self.fdb.make_fleet_delivery(db, order, state="ASSIGNED", distance_metres=metres)
            trip = RiderTrip(order_delivery_id=delivery.id, rider_user_id=rider.id,
                             accepted_at=datetime.now(UTC), **trip_kw)
            db.add(trip)
            db.commit()
            return rider, order, delivery, trip

    def _deliver(self, rider, order, trip) -> None:
        import uuid

        client = client_for(self.fdb, rider)
        for step in ("arrived-pickup", "picked-up", "arrived-drop"):
            r = client.post(f"/api/rider/trip/{trip.id}/{step}", json={"action_id": uuid.uuid4().hex})
            self.assertEqual(r.status_code, 200, r.text)
        r = client.post(f"/api/rider/trip/{trip.id}/delivered",
                        json={"action_id": uuid.uuid4().hex, "otp": otp.code_for(order.id)})
        self.assertEqual(r.status_code, 200, r.text)

    def test_a_long_trip_ends_without_a_price_and_waits_for_the_admin(self) -> None:
        rider, order, _, trip = self._trip(9400.0)
        with self.fdb.session() as db:
            # The rider is told up front that this one is priced by hand.
            self.assertIsNone(trips.trip_view(db, db.get(RiderTrip, trip.id))["earning"])
        self._deliver(rider, order, trip)
        with self.fdb.session() as db:
            ended = db.get(RiderTrip, trip.id)
            self.assertEqual(ended.end_reason, TripEndReason.DELIVERED)
            self.assertIsNone(ended.earning_amount)
            self.assertTrue(ended.earning_breakdown["manual"])
        admin = client_for(self.fdb, self.admin)
        waiting = admin.get("/api/admin/riders/trips/to-price")
        self.assertEqual(waiting.status_code, 200, waiting.text)
        row = next(r for r in waiting.json() if r["trip_id"] == str(trip.id))
        self.assertEqual((row["distance_km"], Decimal(row["incentive"]), row["delivered"]), (9.4, Decimal("5"), True))

        r = admin.put(f"/api/admin/riders/trips/{trip.id}/pay", json={"amount": "70"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(Decimal(r.json()["earning_amount"]), Decimal("75.00"))  # 70 + Rs 5 incentive
        with self.fdb.session() as db:
            priced = db.get(RiderTrip, trip.id)
            self.assertEqual(priced.earning_amount, Decimal("75.00"))
            self.assertEqual(priced.earning_breakdown["manual_amount"], "70")
            self.assertEqual(priced.earning_breakdown["priced_by"], str(self.admin.id))
        ids = [r["trip_id"] for r in admin.get("/api/admin/riders/trips/to-price").json()]
        self.assertNotIn(str(trip.id), ids)

        # And it is paid like any other trip.
        later = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
        payout = admin.post(f"/api/admin/riders/{rider.id}/payouts", json={"period_to": later, "reference": "UTR9"})
        self.assertEqual(payout.status_code, 201, payout.text)
        self.assertEqual(Decimal(payout.json()["amount"]), Decimal("75.00"))
        again = admin.put(f"/api/admin/riders/trips/{trip.id}/pay", json={"amount": "90"})
        self.assertEqual((again.status_code, again.json()["detail"]), (409, "already_paid"))

    def test_only_a_long_trip_is_priced_by_hand(self) -> None:
        rider, order, _, trip = self._trip(4000.0)
        self._deliver(rider, order, trip)
        admin = client_for(self.fdb, self.admin)
        r = admin.put(f"/api/admin/riders/trips/{trip.id}/pay", json={"amount": "70"})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "not_manual"))
        with self.fdb.session() as db:
            self.assertEqual(db.get(RiderTrip, trip.id).earning_amount, Decimal("35.00"))

    def test_the_admin_only_and_a_sane_amount(self) -> None:
        rider, order, _, trip = self._trip(12000.0)
        self._deliver(rider, order, trip)
        self.assertEqual(client_for(self.fdb, self.owner).get("/api/admin/riders/trips/to-price").status_code, 403)
        owner = client_for(self.fdb, self.owner).put(f"/api/admin/riders/trips/{trip.id}/pay", json={"amount": "70"})
        self.assertEqual(owner.status_code, 403)
        admin = client_for(self.fdb, self.admin)
        for bad in ("-1", "abc", "5001"):
            with self.subTest(amount=bad):
                self.assertEqual(admin.put(f"/api/admin/riders/trips/{trip.id}/pay", json={"amount": bad}).status_code, 422)

    def test_the_incentive_is_for_a_delivery(self) -> None:
        # Cancelled after pickup, 4 km: the slab's Rs 30, not Rs 35.
        _, _, delivery, trip = self._trip(4000.0, arrived_pickup_at=datetime.now(UTC), picked_up_at=datetime.now(UTC))
        with self.fdb.session() as db:
            trips.on_order_cancelled(db, db.get(OrderDelivery, delivery.id))
            db.commit()
        with self.fdb.session() as db:
            ended = db.get(RiderTrip, trip.id)
            self.assertEqual(ended.earning_amount, Decimal("30.00"))
            self.assertEqual(ended.earning_breakdown["incentive"], "0")

    def test_a_long_cancelled_trip_is_priced_without_the_incentive(self) -> None:
        _, _, delivery, trip = self._trip(9000.0, arrived_pickup_at=datetime.now(UTC), picked_up_at=datetime.now(UTC))
        with self.fdb.session() as db:
            trips.on_order_cancelled(db, db.get(OrderDelivery, delivery.id))
            db.commit()
        admin = client_for(self.fdb, self.admin)
        row = next(r for r in admin.get("/api/admin/riders/trips/to-price").json() if r["trip_id"] == str(trip.id))
        self.assertEqual((Decimal(row["incentive"]), row["delivered"]), (Decimal("0"), False))
        r = admin.put(f"/api/admin/riders/trips/{trip.id}/pay", json={"amount": "60"})
        self.assertEqual(Decimal(r.json()["earning_amount"]), Decimal("60.00"))


if __name__ == "__main__":
    unittest.main()

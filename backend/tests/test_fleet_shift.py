"""A rider's shift: online and offline, where they are, and noticing when they go quiet.

The location rules are about trust in a phone: a batch that arrives late must
not move a rider backwards, a phone clock running ahead must not make a rider
look "seen just now" for ever, and a rider who stopped reporting is taken off
shift so nobody is offered an order they will never see.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, client_for, postgres_available, reset_overrides  # noqa: E402

from app.models.enums import RiderStatus  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.models.rider import Rider, RiderTrip  # noqa: E402
from app.services.fleet import riders  # noqa: E402


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class ShiftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_shift_test")

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def tearDown(self) -> None:
        reset_overrides()

    def _rider(self, **kw):
        with self.fdb.session() as db:
            user = self.fdb.make_rider(db, **kw)
            db.commit()
            return user

    def test_online_then_offline(self) -> None:
        user = self._rider(status=RiderStatus.OFFLINE)
        client = client_for(self.fdb, user)
        r = client.post("/api/rider/status", json={"online": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "ONLINE")
        self.assertEqual(client.post("/api/rider/status", json={"online": False}).json()["status"], "OFFLINE")

    def test_me_reports_today(self) -> None:
        user = self._rider()
        r = client_for(self.fdb, user).get("/api/rider/me")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["today_trips"], float(body["today_earnings"])), (0, 0.0))
        self.assertIn("fleet_enabled", body)
        # The rider sees what a delivery pays, from the admin's own setting.
        self.assertEqual(
            {k: float(v) for k, v in body["pay"].items()}, {"base": 25.0, "per_km": 6.0, "minimum": 30.0}
        )

    def test_cannot_go_offline_on_a_trip(self) -> None:
        user = self._rider(status=RiderStatus.ON_TRIP)
        r = client_for(self.fdb, user).post("/api/rider/status", json={"online": False})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["detail"], "on_trip")

    def test_location_batch_keeps_the_newest(self) -> None:
        user = self._rider(lat=None, lng=None)
        now = datetime.now(UTC)
        fixes = [
            {"lat": 21.10, "lng": 72.10, "at": _iso(now - timedelta(seconds=30))},
            {"lat": 21.30, "lng": 72.30, "at": _iso(now - timedelta(seconds=5))},
            {"lat": 21.20, "lng": 72.20, "at": _iso(now - timedelta(seconds=20))},
        ]
        r = client_for(self.fdb, user).post("/api/rider/location", json={"fixes": fixes})
        self.assertEqual(r.status_code, 204, r.text)
        with self.fdb.session() as db:
            row = db.get(Rider, user.id)
            self.assertEqual((row.last_latitude, row.last_longitude), (21.30, 72.30))

    def test_a_late_batch_never_moves_the_rider_backwards(self) -> None:
        user = self._rider(lat=21.5, lng=72.5, seen_at=datetime.now(UTC))
        old = datetime.now(UTC) - timedelta(minutes=2)
        client_for(self.fdb, user).post("/api/rider/location", json={"fixes": [{"lat": 1, "lng": 1, "at": _iso(old)}]})
        with self.fdb.session() as db:
            self.assertEqual(db.get(Rider, user.id).last_latitude, 21.5)

    def test_fix_from_the_future_is_clamped(self) -> None:
        user = self._rider(lat=None, lng=None)
        ahead = datetime.now(UTC) + timedelta(hours=2)
        client_for(self.fdb, user).post("/api/rider/location", json={"fixes": [{"lat": 21, "lng": 72, "at": _iso(ahead)}]})
        with self.fdb.session() as db:
            self.assertLessEqual(db.get(Rider, user.id).last_location_at, datetime.now(UTC) + timedelta(seconds=1))

    def test_bad_coordinates_are_422(self) -> None:
        user = self._rider()
        r = client_for(self.fdb, user).post(
            "/api/rider/location", json={"fixes": [{"lat": 95, "lng": 72, "at": _iso(datetime.now(UTC))}]}
        )
        self.assertEqual(r.status_code, 422)

    def test_only_riders_reach_rider_routes(self) -> None:
        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            owner = self.fdb.make_owner(db)
            db.commit()
        for user in (admin, owner):
            with self.subTest(role=user.role):
                self.assertEqual(client_for(self.fdb, user).get("/api/rider/me").status_code, 403)

    def test_device_token_is_stored(self) -> None:
        user = self._rider()
        r = client_for(self.fdb, user).post("/api/rider/device-token", json={"token": "x" * 40, "app_version": "1.0.0"})
        self.assertEqual(r.status_code, 204, r.text)
        with self.fdb.session() as db:
            self.assertEqual(db.get(Rider, user.id).app_version, "1.0.0")

    def test_sweep_takes_silent_rider_offline_but_not_one_on_a_trip(self) -> None:
        stale = datetime.now(UTC) - timedelta(minutes=10)
        idle = self._rider(seen_at=stale)
        busy = self._rider(seen_at=stale, status=RiderStatus.ON_TRIP)
        with self.fdb.session() as db, mock.patch("app.services.fleet.offers.queue_advance"):
            result = riders.sweep_silent(db)
        with self.fdb.session() as db:
            self.assertEqual(db.get(Rider, idle.id).status, RiderStatus.OFFLINE)
            self.assertEqual(db.get(Rider, busy.id).status, RiderStatus.ON_TRIP)
        self.assertIn(str(busy.id), result["alerts"])

    def test_location_on_a_trip_reaches_the_delivery_row(self) -> None:
        with self.fdb.session() as db:
            user = self.fdb.make_rider(db, status=RiderStatus.ON_TRIP, lat=None, lng=None)
            order = self.fdb.make_order(db)
            delivery = self.fdb.make_fleet_delivery(db, order, state="ASSIGNED")
            db.add(RiderTrip(order_delivery_id=delivery.id, rider_user_id=user.id, accepted_at=datetime.now(UTC)))
            db.commit()
        with mock.patch("app.services.fleet.notify.order_moved") as moved:
            client_for(self.fdb, user).post(
                "/api/rider/location", json={"fixes": [{"lat": 21.19, "lng": 72.81, "at": _iso(datetime.now(UTC))}]}
            )
        with self.fdb.session() as db:
            row = db.get(OrderDelivery, delivery.id)
            self.assertEqual((row.rider_latitude, row.rider_longitude), (21.19, 72.81))
        moved.assert_called_once()


if __name__ == "__main__":
    unittest.main()

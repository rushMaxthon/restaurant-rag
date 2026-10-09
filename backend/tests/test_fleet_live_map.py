"""The super admin's live map: who is where, and which orders still need a rider.

The waiting list is what the admin assigns FROM, so it must hold exactly the
orders our fleet is responsible for and nobody is carrying: a Pidge booking
has its own rider coming (reassign refuses it), an order with a live trip is
already moving, and a delivered or cancelled one is finished. Showing any of
those as "waiting" would invite a second rider onto the same food.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, client_for, postgres_available, reset_overrides  # noqa: E402

from app.models.enums import OfferOutcome, OrderStatus, RiderStatus  # noqa: E402
from app.models.rider import RiderOffer, RiderTrip  # noqa: E402


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class LiveMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_live_map_test")
        with cls.fdb.session() as db:
            cls.admin = cls.fdb.make_admin(db)
            cls.owner = cls.fdb.make_owner(db)
            db.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def setUp(self) -> None:
        self.addCleanup(reset_overrides)

    def _waiting_ids(self) -> set[str]:
        r = client_for(self.fdb, self.admin).get("/api/admin/riders/waiting")
        self.assertEqual(r.status_code, 200, r.text)
        return {row["order_id"] for row in r.json()}

    def test_lists_fleet_orders_nobody_is_carrying_with_both_pins(self) -> None:
        with self.fdb.session() as db:
            order = self.fdb.make_order(db, lat=21.18, lng=72.84)
            self.fdb.make_fleet_delivery(db, order)
            db.commit()
        r = client_for(self.fdb, self.admin).get("/api/admin/riders/waiting")
        row = next(x for x in r.json() if x["order_id"] == str(order.id))
        self.assertEqual(row["restaurant_name"], "Bhagwati Bakery")
        self.assertEqual((row["pickup_lat"], row["pickup_lng"]), (21.18, 72.84))
        self.assertEqual((row["drop_lat"], row["drop_lng"]), (21.20, 72.80))
        self.assertIsNone(row["offered_to"])
        self.assertTrue(row["order_code"])

    def test_shows_every_branch_with_a_pin_and_whether_riders_serve_it(self) -> None:
        # Restaurants on the map (2026-10-09): where riders are heading from,
        # and which branches the fleet serves (`location_ids`, empty = all).
        from app.models.platform_setting import PlatformSetting
        from app.models.restaurant_location import RestaurantLocation

        with self.fdb.session() as db:
            order = self.fdb.make_order(db, lat=21.19, lng=72.85)
            served = order.restaurant_location_id
            other = self.fdb.make_order(db)
            db.add(PlatformSetting(key="own_fleet", value={"location_ids": [str(served)]}))
            hidden = db.get(RestaurantLocation, self.fdb.make_order(db).restaurant_location_id)
            hidden.latitude = None
            db.commit()
            hidden_id = hidden.id
        try:
            r = client_for(self.fdb, self.admin).get("/api/admin/riders/branches")
            self.assertEqual(r.status_code, 200, r.text)
            rows = {row["id"]: row for row in r.json()}
            self.assertEqual((rows[str(served)]["lat"], rows[str(served)]["lng"]), (21.19, 72.85))
            self.assertEqual(rows[str(served)]["restaurant_name"], "Bhagwati Bakery")
            self.assertTrue(rows[str(served)]["on_fleet"])
            self.assertFalse(rows[str(other.restaurant_location_id)]["on_fleet"])
            self.assertNotIn(str(hidden_id), rows)  # no pin, nothing to draw
            self.assertEqual(client_for(self.fdb, self.owner).get("/api/admin/riders/branches").status_code, 403)
        finally:
            with self.fdb.session() as db:
                db.query(PlatformSetting).delete()
                db.commit()

    def test_unassigned_orders_wait_too(self) -> None:
        with self.fdb.session() as db:
            order = self.fdb.make_order(db)
            self.fdb.make_fleet_delivery(db, order, provider="unassigned")
            db.commit()
        self.assertIn(str(order.id), self._waiting_ids())

    def test_says_who_is_being_asked_right_now(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, name="Kiran Rider")
            order = self.fdb.make_order(db)
            delivery = self.fdb.make_fleet_delivery(db, order)
            db.add(RiderOffer(order_delivery_id=delivery.id, rider_user_id=rider.id,
                              outcome=OfferOutcome.PENDING, offered_at=datetime.now(UTC),
                              expires_at=datetime.now(UTC) + timedelta(seconds=40), distance_to_pickup_m=500.0))
            db.commit()
        rows = client_for(self.fdb, self.admin).get("/api/admin/riders/waiting").json()
        self.assertEqual(next(x for x in rows if x["order_id"] == str(order.id))["offered_to"], "Kiran Rider")

    def test_an_expired_offer_is_not_asking_anyone(self) -> None:
        # The expiry task may be late (or no worker running): a PENDING row
        # past its deadline must not read as "Asking Kiran..." on the map.
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, name="Late Rider")
            order = self.fdb.make_order(db)
            delivery = self.fdb.make_fleet_delivery(db, order)
            past = datetime.now(UTC) - timedelta(minutes=2)
            db.add(RiderOffer(order_delivery_id=delivery.id, rider_user_id=rider.id,
                              outcome=OfferOutcome.PENDING, offered_at=past - timedelta(seconds=45),
                              expires_at=past, distance_to_pickup_m=500.0))
            db.commit()
        rows = client_for(self.fdb, self.admin).get("/api/admin/riders/waiting").json()
        self.assertIsNone(next(x for x in rows if x["order_id"] == str(order.id))["offered_to"])

    def test_leaves_out_what_is_moving_finished_or_the_couriers(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db)
            moving = self.fdb.make_order(db)
            d = self.fdb.make_fleet_delivery(db, moving, state="ASSIGNED")
            db.add(RiderTrip(order_delivery_id=d.id, rider_user_id=rider.id, accepted_at=datetime.now(UTC)))
            done = self.fdb.make_order(db, status=OrderStatus.DELIVERED)
            self.fdb.make_fleet_delivery(db, done)
            pidge = self.fdb.make_order(db)
            self.fdb.make_fleet_delivery(db, pidge, provider="pidge")
            db.commit()
        waiting = self._waiting_ids()
        for order in (moving, done, pidge):
            self.assertNotIn(str(order.id), waiting)

    def test_owner_is_refused(self) -> None:
        r = client_for(self.fdb, self.owner).get("/api/admin/riders/waiting")
        self.assertEqual(r.status_code, 403)

    def test_live_riders_carry_their_position(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, lat=21.19, lng=72.81, status=RiderStatus.ONLINE)
            db.commit()
        rows = client_for(self.fdb, self.admin).get("/api/admin/riders/live").json()
        row = next(x for x in rows if x["user_id"] == str(rider.id))
        self.assertEqual((row["last_latitude"], row["last_longitude"]), (21.19, 72.81))


if __name__ == "__main__":
    unittest.main()

"""What the super admin does with the fleet, and the one thing the customer sees.

Settings, reassigning and confirming a delivery, and paying riders are ADMIN
only: an owner never manages the shared fleet. Paying is the money path:
it sums exactly the unpaid finished trips, and a second click for the same
period pays nothing twice.

The delivery code is shown to the order's own customer and nobody else - not
the rider who must ask for it, not the kitchen, not the platform.
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

from sqlalchemy import select  # noqa: E402

from app.models.enums import RiderStatus, TripEndReason  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.rider import RiderTrip  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.fleet import otp  # noqa: E402


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class AdminOpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_admin_ops_test")
        with cls.fdb.session() as db:
            cls.admin = cls.fdb.make_admin(db)
            cls.owner = cls.fdb.make_owner(db)
            db.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def setUp(self) -> None:
        for target in ("trip_changed", "trip_cancelled", "offer_made", "offer_withdrawn", "order_moved"):
            p = mock.patch(f"app.services.fleet.notify.{target}")
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch("app.services.fleet.offers.schedule_expiry")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(reset_overrides)

    def test_settings_round_trip_and_owner_is_refused(self) -> None:
        admin = client_for(self.fdb, self.admin)
        r = admin.put("/api/admin/riders/settings/pay", json={
            "slabs": [{"up_to_km": 3, "amount": "30"}, {"up_to_km": 6, "amount": "45"}],
            "incentive": "7", "minimum": "20"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(Decimal(r.json()["pay"]["incentive"]), Decimal("7"))
        self.assertEqual([float(s["up_to_km"]) for s in r.json()["pay"]["slabs"]], [3.0, 6.0])
        r = admin.put("/api/admin/riders/settings/fleet", json={"offer_seconds": 40, "radius_km": 5})
        self.assertEqual(r.json()["fleet"]["offer_seconds"], 40)
        self.assertEqual(client_for(self.fdb, self.owner).get("/api/admin/riders/settings").status_code, 403)
        from app.models.platform_setting import PlatformSetting

        with self.fdb.session() as db:
            db.query(PlatformSetting).filter(PlatformSetting.key == "rider_pay").delete()
            db.commit()
        admin.put("/api/admin/riders/settings/fleet", json={})

    def test_settings_list_the_branches_the_allowlist_can_name(self) -> None:
        """The admin picks branches by name, so the settings carry the list.

        A demo restaurant's branch is left out, like everywhere else the
        platform admin reads across restaurants.
        """
        from app.models.restaurant import Restaurant

        with self.fdb.session() as db:
            real = self.fdb.make_order(db)
            demo = self.fdb.make_order(db)
            db.get(Restaurant, demo.restaurant_id).is_demo = True
            db.commit()
        r = client_for(self.fdb, self.admin).get("/api/admin/riders/settings")
        self.assertEqual(r.status_code, 200, r.text)
        branches = {b["id"]: b for b in r.json()["branches"]}
        self.assertIn(str(real.restaurant_location_id), branches)
        self.assertNotIn(str(demo.restaurant_location_id), branches)
        row = branches[str(real.restaurant_location_id)]
        self.assertEqual((row["restaurant_name"], row["branch_name"], row["city"]), ("Bhagwati Bakery", "Main", "Surat"))

    def test_reassign_to_an_offline_rider_is_409(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, status=RiderStatus.OFFLINE)
            order = self.fdb.make_order(db)
            self.fdb.make_fleet_delivery(db, order)
            db.commit()
        r = client_for(self.fdb, self.admin).post(
            f"/api/admin/riders/deliveries/{order.id}/reassign", json={"rider_user_id": str(rider.id)}
        )
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "rider_offline"))

    def test_reassign_offers_the_named_rider_and_shows_it(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, status=RiderStatus.ONLINE)
            order = self.fdb.make_order(db)
            self.fdb.make_fleet_delivery(db, order)
            db.commit()
        r = client_for(self.fdb, self.admin).post(
            f"/api/admin/riders/deliveries/{order.id}/reassign", json={"rider_user_id": str(rider.id)}
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual([o["outcome"] for o in r.json()["offers"]], ["PENDING"])

    def test_owner_cannot_read_fleet_delivery_detail(self) -> None:
        with self.fdb.session() as db:
            order = self.fdb.make_order(db)
            self.fdb.make_fleet_delivery(db, order)
            db.commit()
        self.assertEqual(client_for(self.fdb, self.owner).get(f"/api/admin/riders/deliveries/{order.id}").status_code, 403)

    def _ended_trip(self, db, rider, amount, ended_at):
        order = self.fdb.make_order(db)
        delivery = self.fdb.make_fleet_delivery(db, order, state="DELIVERED")
        db.add(RiderTrip(order_delivery_id=delivery.id, rider_user_id=rider.id, accepted_at=ended_at,
                         ended_at=ended_at, end_reason=TripEndReason.DELIVERED, earning_amount=Decimal(amount)))

    def test_payout_sums_unpaid_trips_once(self) -> None:
        now = datetime.now(UTC)
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db)
            self._ended_trip(db, rider, "49.00", now - timedelta(days=2))
            self._ended_trip(db, rider, "37.00", now - timedelta(days=1))
            self._ended_trip(db, rider, "60.00", now + timedelta(days=1))  # after the period
            db.commit()
        admin = client_for(self.fdb, self.admin)
        unpaid = {row["rider_user_id"]: row for row in admin.get("/api/admin/riders/payouts/unpaid").json()}
        self.assertEqual(Decimal(unpaid[str(rider.id)]["amount"]), Decimal("146.00"))
        r = admin.post(f"/api/admin/riders/{rider.id}/payouts", json={"period_to": now.isoformat(), "reference": "UTR123"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((Decimal(r.json()["amount"]), r.json()["trips"]), (Decimal("86.00"), 2))
        again = admin.post(f"/api/admin/riders/{rider.id}/payouts", json={"period_to": now.isoformat()})
        self.assertEqual((again.status_code, again.json()["detail"]), (409, "nothing_to_pay"))
        earnings = client_for(self.fdb, rider).get("/api/rider/earnings").json()
        self.assertEqual(Decimal(earnings["unpaid"]), Decimal("60.00"))
        self.assertEqual(Decimal(earnings["paid_total"]), Decimal("86.00"))

    def test_a_rider_sees_their_own_payouts_newest_first(self) -> None:
        now = datetime.now(UTC)
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db)
            other = self.fdb.make_rider(db)
            self._ended_trip(db, rider, "40.00", now - timedelta(days=3))
            self._ended_trip(db, other, "55.00", now - timedelta(days=3))
            db.commit()
        admin = client_for(self.fdb, self.admin)
        first = admin.post(f"/api/admin/riders/{rider.id}/payouts", json={"period_to": now.isoformat(), "reference": "UTR-A"})
        self.assertEqual(first.status_code, 201, first.text)
        with self.fdb.session() as db:
            self._ended_trip(db, rider, "25.00", now - timedelta(hours=1))
            db.commit()
        second = admin.post(f"/api/admin/riders/{rider.id}/payouts", json={"period_to": now.isoformat(), "reference": "UTR-B"})
        self.assertEqual(second.status_code, 201, second.text)
        mine = client_for(self.fdb, rider).get("/api/rider/payouts")
        self.assertEqual(mine.status_code, 200, mine.text)
        self.assertEqual([p["reference"] for p in mine.json()], ["UTR-B", "UTR-A"])
        self.assertEqual([Decimal(p["amount"]) for p in mine.json()], [Decimal("25.00"), Decimal("40.00")])
        # The other rider's payment is theirs alone.
        theirs = client_for(self.fdb, other).get("/api/rider/payouts").json()
        self.assertEqual(theirs, [])

    def test_courier_only_buttons_are_not_offered_on_a_fleet_order(self) -> None:
        # "Find a rider" asks the COURIER's network, and simulate drives the
        # courier's sandbox: on our own riders' order either would call Pidge.
        from app.services.delivery import service

        with self.fdb.session() as db:
            order = self.fdb.make_order(db)
            row = self.fdb.make_fleet_delivery(db, order)
            db.commit()
            self.assertFalse(service.can_allocate(order, row))
            with mock.patch.object(service, "delivery_provider") as courier:
                with self.assertRaises(Exception):
                    service.allocate(db, order)
                courier.return_value.allocate.assert_not_called()
        body = client_for(self.fdb, self.admin).get(f"/api/orders/{order.id}/delivery").json()
        self.assertFalse(body["can_allocate"])
        self.assertFalse(body["can_simulate"])

    def test_confirm_delivered_completes_the_trip(self) -> None:
        now = datetime.now(UTC)
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, status=RiderStatus.ON_TRIP)
            order = self.fdb.make_order(db)
            delivery = self.fdb.make_fleet_delivery(db, order, state="IN_TRANSIT", otp_locked=True)
            db.add(RiderTrip(order_delivery_id=delivery.id, rider_user_id=rider.id, accepted_at=now,
                             arrived_pickup_at=now, picked_up_at=now, arrived_drop_at=now))
            db.commit()
        r = client_for(self.fdb, self.admin).post(
            f"/api/admin/riders/deliveries/{order.id}/confirm-delivered", json={"reason": "Customer confirmed by phone"}
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["trip"]["step"], "done")
        self.assertFalse(r.json()["otp_locked"])


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class CustomerSeesTheCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_customer_otp_test")

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def tearDown(self) -> None:
        reset_overrides()

    def _order(self, state="ASSIGNED", provider="own_fleet"):
        with self.fdb.session() as db:
            order = self.fdb.make_order(db)
            self.fdb.make_fleet_delivery(db, order, state=state, provider=provider)
            db.commit()
            customer = db.get(User, order.customer_id)
            return order, customer

    def _code(self, viewer, order):
        r = client_for(self.fdb, viewer).get(f"/api/orders/{order.id}/delivery")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["delivery_otp"]

    def test_customer_sees_four_digits_while_the_rider_is_coming(self) -> None:
        for state in ("ASSIGNED", "PICKED_UP", "IN_TRANSIT"):
            with self.subTest(state=state):
                order, customer = self._order(state)
                self.assertEqual(self._code(customer, order), otp.code_for(order.id))

    def test_not_before_a_rider_or_after_delivery(self) -> None:
        for state in ("PENDING", "DELIVERED"):
            with self.subTest(state=state):
                order, customer = self._order(state)
                self.assertIsNone(self._code(customer, order))

    def test_nobody_else_sees_it(self) -> None:
        order, _ = self._order()
        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            owner = db.get(User, db.get(Order, order.id).restaurant.owner_id)
            db.commit()
        for viewer in (admin, owner):
            with self.subTest(role=viewer.role):
                self.assertIsNone(self._code(viewer, order))

    def test_customer_sees_how_far_the_rider_is(self) -> None:
        # Restaurant (21.18, 72.84), customer (21.20, 72.80) in the harness.
        order, customer = self._order("PICKED_UP")
        with self.fdb.session() as db:
            row = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order.id))
            row.rider_latitude, row.rider_longitude = 21.19, 72.80  # ~1.1 km from the door
            db.commit()
        body = client_for(self.fdb, customer).get(f"/api/orders/{order.id}/delivery").json()
        self.assertGreater(body["rider_distance_m"], 1000)
        self.assertLess(body["rider_distance_m"], 1600)  # road estimate, x1.3
        self.assertGreaterEqual(body["rider_eta_minutes"], 4)

    def test_before_pickup_the_eta_includes_the_restaurant(self) -> None:
        order, customer = self._order("ASSIGNED")
        with self.fdb.session() as db:
            row = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order.id))
            row.rider_latitude, row.rider_longitude = 21.18, 72.84  # at the restaurant
            db.commit()
        body = client_for(self.fdb, customer).get(f"/api/orders/{order.id}/delivery").json()
        # restaurant -> door is ~4.7 km straight, ~6 km by road
        self.assertGreater(body["rider_distance_m"], 5000)

    def test_no_position_no_eta(self) -> None:
        order, customer = self._order("PICKED_UP")
        body = client_for(self.fdb, customer).get(f"/api/orders/{order.id}/delivery").json()
        self.assertIsNone(body["rider_eta_minutes"])

    def test_a_courier_order_has_no_code(self) -> None:
        order, customer = self._order(provider="pidge")
        self.assertIsNone(self._code(customer, order))


if __name__ == "__main__":
    unittest.main()

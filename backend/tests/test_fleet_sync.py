"""Every rider status change is announced, the moment it is committed.

A rider's status is read in five places: the rider's own app, the admin
Riders list and live map, the admin order page, the restaurant's boards and
the customer's order page. All of them refetch over REST when told; this
file pins WHO is told for each change, so a new path cannot quietly leave a
screen showing "Online" for a rider who is on a trip until its next poll.

Two hints, both ids only:
- `riders_changed(rider_id, force=True)` - the admin's rider list and map.
  Forced: a status change must never be swallowed by the 3 s throttle that
  exists for location pings.
- `delivery_changed(delivery, reason)` - `order:updated` to the order's rooms
  (branch, restaurant, admin, customer), for a delivery step that does not
  move the order status (assigned, at the restaurant, at the door) and so
  would otherwise announce nothing.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, client_for, postgres_available, reset_overrides  # noqa: E402

from app.models.enums import OrderStatus, RiderStatus  # noqa: E402
from app.models.rider import RiderTrip  # noqa: E402
from app.services.fleet import otp, riders  # noqa: E402


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class RiderStatusSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_sync_test")
        with cls.fdb.session() as db:
            cls.admin = cls.fdb.make_admin(db)
            db.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def setUp(self) -> None:
        self.hints: dict[str, mock.MagicMock] = {}
        for target in (
            "riders_changed", "delivery_changed", "trip_changed", "trip_cancelled",
            "order_moved", "offer_made", "offer_withdrawn",
        ):
            p = mock.patch(f"app.services.fleet.notify.{target}")
            self.hints[target] = p.start()
            self.addCleanup(p.stop)
        for target in ("schedule_expiry", "queue_advance"):
            p = mock.patch(f"app.services.fleet.offers.{target}")
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(reset_overrides)

    # --- helpers ---------------------------------------------------------------

    def _forced_for(self, rider_id) -> bool:
        return any(
            c.args and c.args[0] == rider_id and c.kwargs.get("force") is True
            for c in self.hints["riders_changed"].call_args_list
        )

    def _delivery_reasons(self) -> list[str]:
        return [c.args[2] if len(c.args) > 2 else c.kwargs.get("reason") for c in self.hints["delivery_changed"].call_args_list]

    def _reset(self) -> None:
        for hint in self.hints.values():
            hint.reset_mock()

    def _on_trip(self):
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, status=RiderStatus.ON_TRIP, seen_at=datetime.now(UTC))
            order = self.fdb.make_order(db, status=OrderStatus.PREPARING)
            delivery = self.fdb.make_fleet_delivery(db, order, state="ASSIGNED", distance_metres=3000.0)
            trip = RiderTrip(order_delivery_id=delivery.id, rider_user_id=rider.id, accepted_at=datetime.now(UTC))
            db.add(trip)
            db.commit()
            return rider, order, trip

    def _act(self, rider, trip, action, **body):
        body.setdefault("action_id", uuid.uuid4().hex)
        r = client_for(self.fdb, rider).post(f"/api/rider/trip/{trip.id}/{action}", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r

    # --- going on and off shift -------------------------------------------------

    def test_online_and_offline_are_never_throttled(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, status=RiderStatus.OFFLINE, seen_at=datetime.now(UTC))
            db.commit()
        client = client_for(self.fdb, rider)
        client.post("/api/rider/status", json={"online": True})
        self.assertTrue(self._forced_for(rider.id))
        self._reset()
        client.post("/api/rider/status", json={"online": False})
        self.assertTrue(self._forced_for(rider.id))

    # --- taking an order ----------------------------------------------------------

    def test_claiming_an_order_tells_the_admin_and_the_order_watchers(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, status=RiderStatus.ONLINE, seen_at=datetime.now(UTC))
            order = self.fdb.make_order(db)
            self.fdb.make_fleet_delivery(db, order)
            db.commit()
        r = client_for(self.fdb, rider).post(f"/api/rider/open-orders/{order.id}/claim")
        self.assertEqual(r.status_code, 200, r.text)
        # Online -> on a trip, on the admin's list and map at once.
        self.assertTrue(self._forced_for(rider.id))
        # The customer sees a rider's name, the kitchen sees who is coming.
        self.assertIn("rider_assigned", self._delivery_reasons())

    # --- each step of the trip ------------------------------------------------------

    def test_every_step_reaches_the_order_watchers(self) -> None:
        rider, order, trip = self._on_trip()
        self._act(rider, trip, "arrived-pickup")
        self._act(rider, trip, "picked-up")
        self._act(rider, trip, "arrived-drop")
        self.assertEqual(self._delivery_reasons(), ["rider_arrived_pickup", "rider_picked_up", "rider_arrived_drop"])

    def test_a_logged_call_is_not_announced(self) -> None:
        rider, order, trip = self._on_trip()
        self._act(rider, trip, "arrived-pickup")
        self._act(rider, trip, "picked-up")
        self._act(rider, trip, "arrived-drop")
        self._reset()
        self._act(rider, trip, "call-logged")
        self.assertEqual(self._delivery_reasons(), [])

    def test_a_retried_step_is_not_announced_twice(self) -> None:
        rider, order, trip = self._on_trip()
        action_id = uuid.uuid4().hex
        self._act(rider, trip, "arrived-pickup", action_id=action_id)
        self._reset()
        self._act(rider, trip, "arrived-pickup", action_id=action_id)
        self.assertEqual(self._delivery_reasons(), [])

    def test_delivering_frees_the_rider_on_the_admin_list(self) -> None:
        rider, order, trip = self._on_trip()
        self._act(rider, trip, "arrived-pickup")
        self._act(rider, trip, "picked-up")
        self._act(rider, trip, "arrived-drop")
        self._reset()
        self._act(rider, trip, "delivered", otp=otp.code_for(order.id))
        self.assertTrue(self._forced_for(rider.id))
        self.assertIn("rider_delivered", self._delivery_reasons())

    def test_admin_confirming_delivery_frees_the_rider(self) -> None:
        rider, order, trip = self._on_trip()
        r = client_for(self.fdb, self.admin).post(
            f"/api/admin/riders/deliveries/{order.id}/confirm-delivered", json={"reason": "code locked, handed over"}
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self._forced_for(rider.id))
        self.assertIn("confirmed_by_admin", self._delivery_reasons())

    # --- the admin and the platform changing a rider ------------------------------

    def test_deactivating_a_rider_tells_the_admin_list(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, status=RiderStatus.ONLINE, seen_at=datetime.now(UTC))
            db.commit()
        r = client_for(self.fdb, self.admin).patch(f"/api/admin/riders/{rider.id}", json={"is_active": False})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(self._forced_for(rider.id))

    def test_the_silent_sweep_tells_the_admin_list(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, status=RiderStatus.ONLINE, seen_at=datetime.now(UTC) - timedelta(hours=2))
            db.commit()
            riders.sweep_silent(db)
        self.assertTrue(self._forced_for(rider.id))

    def test_reassigning_asks_the_named_rider(self) -> None:
        with self.fdb.session() as db:
            rider = self.fdb.make_rider(db, status=RiderStatus.ONLINE, seen_at=datetime.now(UTC))
            order = self.fdb.make_order(db)
            self.fdb.make_fleet_delivery(db, order)
            db.commit()
        r = client_for(self.fdb, self.admin).post(
            f"/api/admin/riders/deliveries/{order.id}/reassign", json={"rider_user_id": str(rider.id)}
        )
        self.assertEqual(r.status_code, 200, r.text)
        # offer_made carries the map hint (HintShapeTests below).
        self.assertEqual(self.hints["offer_made"].call_count, 1)


class HintShapeTests(unittest.TestCase):
    """The hints themselves: ids only, and forced past the throttle."""

    def test_a_forced_rider_hint_ignores_the_throttle(self) -> None:
        from app.services.fleet import notify

        rider_id = uuid.uuid4()
        redis = mock.MagicMock()
        redis.set.return_value = None  # the throttle key already exists
        with (
            mock.patch("app.services.fleet.notify.get_settings") as settings,
            mock.patch("app.services.cache.get_redis_client", return_value=redis),
            mock.patch("app.services.fleet.notify._emit") as emit,
        ):
            settings.return_value.enable_realtime = True
            notify.riders_changed(rider_id)
            self.assertEqual(emit.call_count, 0)  # throttled, as a location ping should be
            notify.riders_changed(rider_id, force=True)
            self.assertEqual(emit.call_count, 1)
        self.assertEqual(emit.call_args.args[1], {"rider_id": str(rider_id)})

    def test_an_offer_made_or_withdrawn_refreshes_the_admin_map(self) -> None:
        # "Asking Ravi..." on the live map's waiting list changes with every
        # offer; the map hears it through the rider hint.
        from app.services.fleet import notify

        offer = mock.MagicMock(id=uuid.uuid4(), rider_user_id=uuid.uuid4(),
                               expires_at=datetime.now(UTC) + timedelta(seconds=30))
        with (
            mock.patch("app.services.fleet.notify._to_rider"),
            mock.patch("app.services.fleet.notify._push"),
            mock.patch("app.services.fleet.notify.riders_changed") as hint,
        ):
            notify.offer_made(None, offer)
            notify.offer_withdrawn(None, offer)
        self.assertEqual(hint.call_args_list, [mock.call(offer.rider_user_id, force=True)] * 2)

    def test_a_delivery_hint_is_an_order_update_with_no_contents(self) -> None:
        from app.services.fleet import notify

        order = mock.MagicMock(id=uuid.uuid4(), restaurant_id=uuid.uuid4(),
                               restaurant_location_id=uuid.uuid4(), customer_id=uuid.uuid4())
        order.status.value = "PREPARING"
        delivery = mock.MagicMock(id=uuid.uuid4(), order=order)
        with (
            mock.patch("app.services.fleet.notify.get_settings") as settings,
            mock.patch("app.services.fleet.notify._emit") as emit,
        ):
            settings.return_value.enable_realtime = True
            notify.delivery_changed(None, delivery, "rider_arrived_drop")
        event, payload = emit.call_args.args[:2]
        self.assertEqual(event, "order:updated")
        self.assertEqual(set(payload), {"order_id", "restaurant_id", "restaurant_location_id",
                                        "status", "from_status", "occurred_at", "reason"})
        self.assertEqual(payload["reason"], "rider_arrived_drop")
        self.assertEqual(payload["order_id"], str(order.id))


if __name__ == "__main__":
    unittest.main()

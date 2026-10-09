"""Waves: the nearest riders see an order first, then it widens ring by ring.

The owner's rule (2026-10-09): an order is shown to the riders nearest the
restaurant first, and only if none of them takes it in a couple of minutes
does it open to the next ring out. Every `wave_minutes` the reach grows by
`first_wave_km`, up to `radius_km`. Two things keep that from wasting time:
with no free rider inside the current ring it widens at once to the ring
holding the nearest one, and a rider who already said no (declined, or let
the offer run out) no longer holds the order back.

Seeing and taking follow the same reach - `claim` refuses `order_not_near`
from outside it, so a stale board cannot jump the queue.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, postgres_available, reset_overrides  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.models.enums import OfferOutcome, RiderStatus  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.models.platform_setting import PlatformSetting  # noqa: E402
from app.models.rider import Rider, RiderOffer, RiderTrip  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.fleet import offers  # noqa: E402
from app.services.fleet.config import FleetConfig, validate_fleet  # noqa: E402

# The branch is at (21.18, 72.84); one degree of latitude is ~111 km.
RING_1 = (21.19, 72.84)  # ~1.1 km
RING_2 = (21.21, 72.84)  # ~3.3 km
RING_3 = (21.225, 72.84)  # ~5.0 km


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class WaveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_waves_test")

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def setUp(self) -> None:
        with self.fdb.session() as db:
            db.execute(delete(RiderOffer))
            db.execute(delete(RiderTrip))
            db.execute(delete(OrderDelivery))
            db.query(Rider).update({Rider.status: RiderStatus.OFFLINE})
            db.execute(delete(PlatformSetting))
            db.commit()
        for target in ("offer_made", "offer_withdrawn", "trip_changed"):
            p = mock.patch(f"app.services.fleet.notify.{target}")
            p.start()
            self.addCleanup(p.stop)
        for target in ("schedule_expiry", "queue_advance"):
            p = mock.patch(f"app.services.fleet.offers.{target}")
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(reset_overrides)

    def _rider(self, where, **kw) -> User:
        with self.fdb.session() as db:
            user = self.fdb.make_rider(db, lat=where[0], lng=where[1], **kw)
            db.commit()
            return user

    def _order(self):
        with self.fdb.session() as db:
            order = self.fdb.make_order(db)
            delivery = self.fdb.make_fleet_delivery(db, order)
            db.commit()
            return order, delivery.created_at

    def _sees(self, rider: User, after: timedelta, start: datetime) -> list:
        with self.fdb.session() as db:
            return [r["order_id"] for r in offers.open_orders(db, db.get(User, rider.id), now=start + after)]

    def _offer(self, order, rider: User, outcome: OfferOutcome, start: datetime) -> None:
        with self.fdb.session() as db:
            d = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order.id))
            db.add(RiderOffer(order_delivery_id=d.id, rider_user_id=rider.id, outcome=outcome,
                              offered_at=start, expires_at=start + timedelta(seconds=30),
                              distance_to_pickup_m=1100.0))
            db.commit()

    def test_at_first_only_the_nearest_ring_sees_it(self) -> None:
        near, middle = self._rider(RING_1), self._rider(RING_2)
        order, start = self._order()
        self.assertEqual(self._sees(near, timedelta(seconds=10), start), [order.id])
        self.assertEqual(self._sees(middle, timedelta(seconds=10), start), [])

    def test_it_widens_one_ring_every_wave(self) -> None:
        self._rider(RING_1)
        middle, outer = self._rider(RING_2), self._rider(RING_3)
        order, start = self._order()
        self.assertEqual(self._sees(middle, timedelta(minutes=2, seconds=5), start), [order.id])
        self.assertEqual(self._sees(outer, timedelta(minutes=2, seconds=5), start), [])
        self.assertEqual(self._sees(outer, timedelta(minutes=4, seconds=5), start), [order.id])

    def test_with_nobody_free_close_by_it_reaches_the_nearest_free_rider_at_once(self) -> None:
        # Waiting two minutes for a ring with nobody in it helps no one.
        outer = self._rider(RING_3)
        self._rider(RING_1, status=RiderStatus.OFFLINE)
        order, start = self._order()
        self.assertEqual(self._sees(outer, timedelta(seconds=10), start), [order.id])

    def test_a_near_rider_who_said_no_no_longer_holds_it_back(self) -> None:
        near, middle = self._rider(RING_1), self._rider(RING_2)
        order, start = self._order()
        self._offer(order, near, OfferOutcome.DECLINED, start)
        self.assertEqual(self._sees(middle, timedelta(seconds=40), start), [order.id])

    def test_a_near_rider_still_being_asked_keeps_it_in_the_first_ring(self) -> None:
        near, middle = self._rider(RING_1), self._rider(RING_2)
        order, start = self._order()
        self._offer(order, near, OfferOutcome.PENDING, start)
        self.assertEqual(self._sees(middle, timedelta(seconds=10), start), [])

    def test_claiming_from_outside_the_current_ring_is_refused(self) -> None:
        self._rider(RING_1)
        middle = self._rider(RING_2)
        order, start = self._order()
        with self.fdb.session() as db, self.assertRaises(HTTPException) as caught:
            offers.claim(db, db.get(User, middle.id), order.id, now=start + timedelta(seconds=10))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail, "order_not_near")
        with self.fdb.session() as db:
            trip = offers.claim(db, db.get(User, middle.id), order.id, now=start + timedelta(minutes=2, seconds=5))
            self.assertEqual(trip.rider_user_id, middle.id)

    def test_the_admin_sees_how_far_each_order_reaches(self) -> None:
        self._rider(RING_1)
        order, _ = self._order()
        with self.fdb.session() as db:
            rows = {r["order_id"]: r for r in offers.waiting_orders(db)}
        self.assertAlmostEqual(rows[order.id]["reach_km"], 2.0)


class WaveConfigTests(unittest.TestCase):
    def test_defaults_are_two_minutes_and_two_km(self) -> None:
        fleet = FleetConfig()
        self.assertEqual((fleet.wave_minutes, fleet.first_wave_km), (2, 2.0))

    def test_an_old_saved_config_without_waves_still_loads(self) -> None:
        fleet = validate_fleet({"radius_km": 6, "window_minutes": 5})
        self.assertEqual((fleet.wave_minutes, fleet.first_wave_km), (2, 2.0))

    def test_refuses_waves_out_of_range(self) -> None:
        for bad in ({"wave_minutes": 0}, {"wave_minutes": 11}, {"first_wave_km": 0.1}, {"first_wave_km": 30}):
            with self.assertRaises(HTTPException):
                validate_fleet(bad)


if __name__ == "__main__":
    unittest.main()

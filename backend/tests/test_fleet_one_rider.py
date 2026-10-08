"""One order, one rider: once a rider has it, nobody else can be given it.

Every door an order can leave by is tried here against an order that a rider
already holds: another rider's accept, a claim from the Orders board, the
offer loop, and the admin's reassign. The rider paths were guarded from the
start (row lock + `uq_rider_trips_one_live`). Reassign was not: it took an
order from its rider with no question asked, even after the food was picked
up (found 2026-10-08). Now it refuses while the rider is active, and always
after pickup; before pickup it may still rescue an order whose rider has gone
silent - a dead phone must not strand the food.
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
from sqlalchemy import delete, func, select  # noqa: E402

from app.models.enums import OfferOutcome, RiderStatus  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.models.platform_setting import PlatformSetting  # noqa: E402
from app.models.rider import Rider, RiderOffer, RiderTrip  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.fleet import offers  # noqa: E402

NEAR = (21.185, 72.84)


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class OneRiderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_one_rider_test")
        with cls.fdb.session() as db:
            cls.admin = cls.fdb.make_admin(db)
            db.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fdb.drop()

    def setUp(self) -> None:
        with self.fdb.session() as db:
            db.execute(delete(RiderOffer))
            db.execute(delete(RiderTrip))
            db.execute(delete(OrderDelivery))
            db.query(Rider).update({Rider.status: RiderStatus.OFFLINE})
            db.execute(delete(PlatformSetting))
            db.commit()
        for target in ("offer_made", "offer_withdrawn", "trip_changed", "trip_cancelled"):
            p = mock.patch(f"app.services.fleet.notify.{target}")
            p.start()
            self.addCleanup(p.stop)
        for target in ("schedule_expiry", "queue_advance"):
            p = mock.patch(f"app.services.fleet.offers.{target}")
            p.start()
            self.addCleanup(p.stop)
        self.fallback = mock.patch("app.services.delivery.service.fallback_to_pidge").start()
        self.addCleanup(mock.patch.stopall)

    def _rider(self, **kw) -> User:
        with self.fdb.session() as db:
            user = self.fdb.make_rider(db, lat=NEAR[0], lng=NEAR[1], **kw)
            db.commit()
            return user

    def _held(self, *, holder_seen: datetime | None = None, picked_up: bool = False):
        """An order whose delivery a rider is carrying (a live trip)."""

        holder = self._rider(status=RiderStatus.ON_TRIP, seen_at=holder_seen)
        with self.fdb.session() as db:
            order = self.fdb.make_order(db)
            row = self.fdb.make_fleet_delivery(db, order, state="PICKED_UP" if picked_up else "ASSIGNED")
            now = datetime.now(UTC)
            db.add(RiderTrip(order_delivery_id=row.id, rider_user_id=holder.id, accepted_at=now,
                             picked_up_at=now if picked_up else None))
            db.commit()
            return order, row.id, holder

    def _live_trips(self, delivery_id) -> list:
        with self.fdb.session() as db:
            return list(db.scalars(select(RiderTrip.rider_user_id).where(
                RiderTrip.order_delivery_id == delivery_id, RiderTrip.ended_at.is_(None))))

    def _reassign(self, delivery_id, rider: User):
        with self.fdb.session() as db:
            admin = db.get(User, self.admin.id)
            return offers.reassign(db, admin, db.get(OrderDelivery, delivery_id), rider.id)

    def test_another_rider_cannot_claim_it_from_the_board(self) -> None:
        order, delivery_id, holder = self._held()
        other = self._rider()
        with self.fdb.session() as db, self.assertRaises(HTTPException) as caught:
            offers.claim(db, db.get(User, other.id), order.id)
        self.assertEqual(caught.exception.detail, "order_taken")
        self.assertEqual(self._live_trips(delivery_id), [holder.id])

    def test_a_stale_offer_cannot_be_accepted_once_someone_has_it(self) -> None:
        order, delivery_id, holder = self._held()
        other = self._rider()
        with self.fdb.session() as db:
            now = datetime.now(UTC)
            offer = RiderOffer(order_delivery_id=delivery_id, rider_user_id=other.id, outcome=OfferOutcome.PENDING,
                               offered_at=now, expires_at=now + timedelta(seconds=30), distance_to_pickup_m=300.0)
            db.add(offer)
            db.commit()
            offer_id = offer.id
        with self.fdb.session() as db, self.assertRaises(HTTPException) as caught:
            offers.accept(db, db.get(User, other.id), offer_id)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self._live_trips(delivery_id), [holder.id])

    def test_the_offer_loop_leaves_it_alone(self) -> None:
        _, delivery_id, holder = self._held()
        self._rider()
        with self.fdb.session() as db:
            self.assertEqual(offers.advance(db, delivery_id, now=datetime.now(UTC) + timedelta(minutes=10)), "assigned")
        self.fallback.assert_not_called()
        self.assertEqual(self._live_trips(delivery_id), [holder.id])

    def test_admin_cannot_reassign_while_the_rider_is_active(self) -> None:
        _, delivery_id, holder = self._held()
        other = self._rider()
        with self.assertRaises(HTTPException) as caught:
            self._reassign(delivery_id, other)
        self.assertEqual((caught.exception.status_code, caught.exception.detail), (409, "rider_has_it"))
        self.assertEqual(self._live_trips(delivery_id), [holder.id])

    def test_admin_can_never_reassign_after_pickup_even_if_the_rider_went_quiet(self) -> None:
        _, delivery_id, holder = self._held(picked_up=True, holder_seen=datetime.now(UTC) - timedelta(minutes=30))
        other = self._rider()
        with self.assertRaises(HTTPException) as caught:
            self._reassign(delivery_id, other)
        self.assertEqual(caught.exception.detail, "food_picked_up")
        self.assertEqual(self._live_trips(delivery_id), [holder.id])

    def test_admin_can_rescue_an_order_whose_rider_went_silent_before_pickup(self) -> None:
        _, delivery_id, holder = self._held(holder_seen=datetime.now(UTC) - timedelta(minutes=30))
        other = self._rider()
        offer = self._reassign(delivery_id, other)
        self.assertEqual(offer.rider_user_id, other.id)
        self.assertEqual(self._live_trips(delivery_id), [])  # the silent rider's trip ended
        with self.fdb.session() as db:
            pending = db.scalar(select(func.count(RiderOffer.id)).where(
                RiderOffer.order_delivery_id == delivery_id, RiderOffer.outcome == OfferOutcome.PENDING))
        self.assertEqual(pending, 1)


if __name__ == "__main__":
    unittest.main()

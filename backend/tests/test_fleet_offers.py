"""Offering a delivery to riders, one at a time, nearest first.

The money question is "two riders, one order". One PENDING offer per delivery
and one live trip per delivery are partial unique indexes, and `accept` locks
the delivery row, so a double tap or a race between two phones resolves to
exactly one trip. The rest is about never stranding food: nobody online,
nobody accepting, a cash order or a branch outside the fleet all hand the
order to Pidge with a reason somebody can read.
"""

from __future__ import annotations

import os
import sys
import threading
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, postgres_available  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from app.models.enums import OfferOutcome, PaymentMethod, RiderStatus  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.models.platform_setting import PlatformSetting  # noqa: E402
from app.models.rider import Rider, RiderOffer, RiderTrip  # noqa: E402
from app.services.fleet import offers  # noqa: E402

# Branch at (21.18, 72.84). 0.01 degrees of latitude is about 1.1 km.
NEAR = (21.185, 72.84)  # ~0.55 km
MID = (21.20, 72.84)  # ~2.2 km
FAR = (21.27, 72.84)  # ~10 km, outside the 6 km radius


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class OfferLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_offers_test")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fdb.drop()

    def setUp(self) -> None:
        # Riders are shared state between tests: start each with nobody online.
        with self.fdb.session() as db:
            db.execute(delete(RiderOffer))
            db.execute(delete(RiderTrip))
            db.query(Rider).update({Rider.status: RiderStatus.OFFLINE})
            db.execute(delete(PlatformSetting))
            db.commit()
        patches = [
            mock.patch("app.services.fleet.offers.schedule_expiry"),
            mock.patch("app.services.fleet.offers.queue_advance"),
            mock.patch("app.services.fleet.notify.offer_made"),
            mock.patch("app.services.fleet.notify.offer_withdrawn"),
            mock.patch("app.services.fleet.notify.trip_changed"),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.fallback = mock.patch("app.services.delivery.service.fallback_to_pidge").start()
        self.addCleanup(mock.patch.stopall)

    def _delivery(self, **order_kw):
        with self.fdb.session() as db:
            order = self.fdb.make_order(db, **order_kw)
            row = self.fdb.make_fleet_delivery(db, order)
            db.commit()
            return row.id

    def _rider(self, where, **kw):
        with self.fdb.session() as db:
            user = self.fdb.make_rider(db, lat=where[0], lng=where[1], **kw)
            db.commit()
            return user

    def _open_offer(self, delivery_id):
        with self.fdb.session() as db:
            return db.scalar(
                select(RiderOffer).where(
                    RiderOffer.order_delivery_id == delivery_id, RiderOffer.outcome == OfferOutcome.PENDING
                )
            )

    def _advance(self, delivery_id, now=None):
        with self.fdb.session() as db:
            return offers.advance(db, delivery_id, now=now)

    def test_nearest_online_rider_is_offered_first(self) -> None:
        mid = self._rider(MID)
        near = self._rider(NEAR)
        self._rider(FAR)
        self._rider((21.181, 72.84), status=RiderStatus.OFFLINE)
        delivery = self._delivery()
        self.assertEqual(self._advance(delivery), "offered")
        offer = self._open_offer(delivery)
        self.assertEqual(offer.rider_user_id, near.id)
        self.assertAlmostEqual((offer.expires_at - offer.offered_at).total_seconds(), 30, delta=1)
        self.assertNotEqual(offer.rider_user_id, mid.id)

    def test_stale_location_is_not_a_candidate(self) -> None:
        self._rider(NEAR, seen_at=datetime.now(UTC) - timedelta(minutes=10))
        delivery = self._delivery()
        self.assertEqual(self._advance(delivery), "fallback")
        self.assertEqual(self.fallback.call_args.args[2], "no rider online nearby")

    def test_expired_offer_moves_to_the_next_rider(self) -> None:
        a = self._rider(NEAR)
        b = self._rider(MID)
        delivery = self._delivery()
        now = datetime.now(UTC)
        self._advance(delivery, now)
        self.assertEqual(self._advance(delivery, now + timedelta(seconds=5)), "waiting")
        self.assertEqual(self._advance(delivery, now + timedelta(seconds=31)), "offered")
        with self.fdb.session() as db:
            outcomes = dict(
                db.execute(select(RiderOffer.rider_user_id, RiderOffer.outcome).where(
                    RiderOffer.order_delivery_id == delivery)).tuples().all()
            )
        self.assertEqual(outcomes, {a.id: OfferOutcome.EXPIRED, b.id: OfferOutcome.PENDING})

    def test_decline_moves_on_and_never_reoffers_the_same_rider(self) -> None:
        a = self._rider(NEAR)
        delivery = self._delivery()
        self._advance(delivery)
        offer = self._open_offer(delivery)
        with self.fdb.session() as db:
            offers.decline(db, a, offer.id)
        self.assertEqual(self._advance(delivery), "fallback")

    def test_max_offers_then_pidge(self) -> None:
        with self.fdb.session() as db:
            db.add(PlatformSetting(key="own_fleet", value={"max_offers": 2}))
            db.commit()
        for where in (NEAR, MID, (21.21, 72.84)):
            self._rider(where)
        delivery = self._delivery()
        now = datetime.now(UTC)
        self._advance(delivery, now)
        self._advance(delivery, now + timedelta(seconds=31))
        self.assertEqual(self._advance(delivery, now + timedelta(seconds=62)), "fallback")
        self.assertEqual(self.fallback.call_args.args[2], "no rider accepted")

    def test_nobody_online_goes_straight_to_pidge(self) -> None:
        delivery = self._delivery()
        self.assertEqual(self._advance(delivery), "fallback")
        self.assertEqual(self.fallback.call_count, 1)

    def test_window_elapsed_goes_to_pidge(self) -> None:
        self._rider(NEAR)
        delivery = self._delivery()
        later = datetime.now(UTC) + timedelta(minutes=5)
        self.assertEqual(self._advance(delivery, later), "fallback")
        self.assertEqual(self.fallback.call_args.args[2], "no rider within 4 minutes")

    def test_cash_order_is_never_offered(self) -> None:
        self._rider(NEAR)
        delivery = self._delivery(payment=PaymentMethod.COD)
        self.assertEqual(self._advance(delivery), "fallback")
        self.assertEqual(self.fallback.call_args.args[2], "cash order")

    def test_branch_not_on_the_fleet_goes_to_pidge(self) -> None:
        self._rider(NEAR)
        with self.fdb.session() as db:
            db.add(PlatformSetting(key="own_fleet", value={"location_ids": ["00000000-0000-0000-0000-000000000000"]}))
            db.commit()
        delivery = self._delivery()
        self.assertEqual(self._advance(delivery), "fallback")
        self.assertEqual(self.fallback.call_args.args[2], "branch not on the fleet")

    def test_accept_creates_trip_and_assigns(self) -> None:
        rider = self._rider(NEAR)
        delivery = self._delivery()
        self._advance(delivery)
        offer = self._open_offer(delivery)
        with self.fdb.session() as db:
            trip = offers.accept(db, rider, offer.id)
        with self.fdb.session() as db:
            row = db.get(OrderDelivery, delivery)
            self.assertEqual(row.state, "ASSIGNED")
            self.assertEqual(row.rider_name, "Ravi Rider")
            self.assertEqual(db.get(Rider, rider.id).status, RiderStatus.ON_TRIP)
            self.assertIsNotNone(db.get(RiderTrip, trip.id))
            self.assertIn("assigned", [e["event"] for e in row.timeline])
        self.assertEqual(self._advance(delivery), "assigned")

    def test_two_accepts_one_wins(self) -> None:
        rider = self._rider(NEAR)
        delivery = self._delivery()
        self._advance(delivery)
        offer = self._open_offer(delivery)
        barrier = threading.Barrier(2)
        results: list[object] = []

        def tap() -> None:
            with self.fdb.session() as db:
                barrier.wait()
                try:
                    results.append(offers.accept(db, rider, offer.id).id)
                except HTTPException as error:
                    results.append(error.status_code)

        threads = [threading.Thread(target=tap) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(sorted(str(r) for r in results if r == 409), ["409"])
        with self.fdb.session() as db:
            self.assertEqual(db.scalar(select(func.count(RiderTrip.id)).where(RiderTrip.order_delivery_id == delivery)), 1)

    def test_accept_after_expiry_is_409_expired(self) -> None:
        rider = self._rider(NEAR)
        delivery = self._delivery()
        self._advance(delivery)
        offer = self._open_offer(delivery)
        with self.fdb.session() as db, self.assertRaises(HTTPException) as raised:
            offers.accept(db, rider, offer.id, now=datetime.now(UTC) + timedelta(seconds=40))
        self.assertEqual((raised.exception.status_code, raised.exception.detail), (409, "offer_expired"))

    def test_another_riders_offer_is_404(self) -> None:
        self._rider(NEAR)
        other = self._rider(FAR, status=RiderStatus.OFFLINE)
        delivery = self._delivery()
        self._advance(delivery)
        offer = self._open_offer(delivery)
        with self.fdb.session() as db, self.assertRaises(HTTPException) as raised:
            offers.accept(db, other, offer.id)
        self.assertEqual(raised.exception.status_code, 404)

    def test_current_offer_is_only_the_callers(self) -> None:
        rider = self._rider(NEAR)
        delivery = self._delivery()
        self._advance(delivery)
        with self.fdb.session() as db:
            self.assertIsNotNone(offers.current_offer(db, rider))

    def test_admin_reassign_withdraws_and_offers_named_rider(self) -> None:
        first = self._rider(NEAR)
        named = self._rider(MID)
        delivery = self._delivery()
        self._advance(delivery)
        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            db.commit()
            row = db.get(OrderDelivery, delivery)
            offer = offers.reassign(db, admin, row, named.id)
        self.assertEqual(offer.rider_user_id, named.id)
        with self.fdb.session() as db:
            outcomes = dict(db.execute(select(RiderOffer.rider_user_id, RiderOffer.outcome).where(
                RiderOffer.order_delivery_id == delivery)).tuples().all())
        self.assertEqual(outcomes[first.id], OfferOutcome.WITHDRAWN)
        self.assertEqual(outcomes[named.id], OfferOutcome.PENDING)

    def test_reassign_to_an_offline_rider_is_409(self) -> None:
        offline = self._rider(MID, status=RiderStatus.OFFLINE)
        delivery = self._delivery()
        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            db.commit()
            with self.assertRaises(HTTPException) as raised:
                offers.reassign(db, admin, db.get(OrderDelivery, delivery), offline.id)
        self.assertEqual(raised.exception.detail, "rider_offline")


if __name__ == "__main__":
    unittest.main()

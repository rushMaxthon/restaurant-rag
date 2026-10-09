"""Open orders: what a free rider can see and take while our fleet still holds it.

Our riders come first (2026-10-08). An order nobody has taken stays open for
the whole window, and any free rider nearby may claim it - including one whose
own offer ran out while they were not looking. The money question is the same
as for an offer: two riders, one order. `claim` locks the delivery row and the
partial unique index on live trips is the second guard, so a race ends with
exactly one trip and the loser told plainly.
"""

from __future__ import annotations

import os
import sys
import threading
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, client_for, postgres_available, reset_overrides  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from app.models.enums import OfferOutcome, OrderStatus, RiderStatus  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.models.platform_setting import PlatformSetting  # noqa: E402
from app.models.rider import Rider, RiderOffer, RiderTrip  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.fleet import offers  # noqa: E402

NEAR = (21.185, 72.84)  # ~0.55 km from the branch at (21.18, 72.84)
FAR = (21.27, 72.84)  # ~10 km, outside the 6 km radius


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class OpenOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_open_orders_test")

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
            setattr(self, target, p.start())
            self.addCleanup(p.stop)
        for target in ("schedule_expiry", "queue_advance"):
            p = mock.patch(f"app.services.fleet.offers.{target}")
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(reset_overrides)

    def _rider(self, where=NEAR, **kw) -> User:
        with self.fdb.session() as db:
            user = self.fdb.make_rider(db, lat=where[0], lng=where[1], **kw)
            db.commit()
            return user

    def _order(self, **kw):
        with self.fdb.session() as db:
            order = self.fdb.make_order(db, **kw)
            self.fdb.make_fleet_delivery(db, order)
            db.commit()
            return order

    def _open(self, rider: User) -> list[dict]:
        with self.fdb.session() as db:
            return offers.open_orders(db, db.get(User, rider.id))

    def test_a_free_rider_nearby_sees_it_with_pay_and_time_left(self) -> None:
        rider = self._rider()
        order = self._order()
        rows = self._open(rider)
        self.assertEqual([r["order_id"] for r in rows], [order.id])
        self.assertLess(rows[0]["pickup_distance_m"], 1000)
        self.assertGreater(rows[0]["earning_estimate"], 0)
        self.assertGreaterEqual(rows[0]["minutes_left"], 4)

    def test_the_board_is_visible_offline_or_mid_trip_but_never_from_far_away(self) -> None:
        # The Orders tab is a board a rider checks any time (2026-10-08):
        # seeing is open to every nearby rider; TAKING is what needs them free.
        order = self._order()
        self.assertEqual(self._open(self._rider(FAR)), [])
        self.assertEqual([r["order_id"] for r in self._open(self._rider(status=RiderStatus.OFFLINE))], [order.id])
        busy = self._rider()
        other = self._order()
        with self.fdb.session() as db:
            d = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == other.id))
            db.add(RiderTrip(order_delivery_id=d.id, rider_user_id=busy.id, accepted_at=datetime.now(UTC)))
            db.commit()
        self.assertEqual([r["order_id"] for r in self._open(busy)], [order.id])

    def test_says_which_orders_this_rider_missed(self) -> None:
        rider = self._rider()
        missed, fresh = self._order(), self._order()
        with self.fdb.session() as db:
            d = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == missed.id))
            past = datetime.now(UTC) - timedelta(seconds=40)
            db.add(RiderOffer(order_delivery_id=d.id, rider_user_id=rider.id, outcome=OfferOutcome.EXPIRED,
                              offered_at=past, expires_at=past + timedelta(seconds=30), distance_to_pickup_m=500.0))
            db.commit()
        rows = {r["order_id"]: r["missed"] for r in self._open(rider)}
        self.assertEqual(rows, {missed.id: True, fresh.id: False})

    def test_a_rider_mid_trip_cannot_take_another(self) -> None:
        busy = self._rider()
        carrying, waiting = self._order(), self._order()
        with self.fdb.session() as db:
            d = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == carrying.id))
            db.add(RiderTrip(order_delivery_id=d.id, rider_user_id=busy.id, accepted_at=datetime.now(UTC)))
            db.commit()
        with self.fdb.session() as db, self.assertRaises(HTTPException) as caught:
            offers.claim(db, db.get(User, busy.id), waiting.id)
        self.assertEqual(caught.exception.detail, "rider_busy")

    def test_leaves_out_what_is_carried_finished_or_the_couriers(self) -> None:
        rider = self._rider()
        carried = self._order()
        with self.fdb.session() as db:
            d = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == carried.id))
            other = self.fdb.make_rider(db, lat=NEAR[0], lng=NEAR[1])
            db.add(RiderTrip(order_delivery_id=d.id, rider_user_id=other.id, accepted_at=datetime.now(UTC)))
            done = self.fdb.make_order(db, status=OrderStatus.DELIVERED)
            self.fdb.make_fleet_delivery(db, done)
            pidge = self.fdb.make_order(db)
            self.fdb.make_fleet_delivery(db, pidge, provider="pidge")
            db.commit()
        self.assertEqual(self._open(rider), [])

    def test_claim_starts_the_trip_and_withdraws_anyone_elses_offer(self) -> None:
        asked = self._rider(name="Asked Rider")
        taker = self._rider(name="Quick Rider")
        order = self._order()
        with self.fdb.session() as db:
            d = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order.id))
            now = datetime.now(UTC)
            db.add(RiderOffer(order_delivery_id=d.id, rider_user_id=asked.id, outcome=OfferOutcome.PENDING,
                              offered_at=now, expires_at=now + timedelta(seconds=30), distance_to_pickup_m=500.0))
            db.commit()
        with self.fdb.session() as db:
            trip = offers.claim(db, db.get(User, taker.id), order.id)
            self.assertEqual(trip.rider_user_id, taker.id)
        with self.fdb.session() as db:
            outcomes = dict(db.execute(select(RiderOffer.rider_user_id, RiderOffer.outcome)).tuples().all())
            self.assertEqual(outcomes[asked.id], OfferOutcome.WITHDRAWN)
            self.assertEqual(outcomes[taker.id], OfferOutcome.ACCEPTED)
            self.assertEqual(db.get(Rider, taker.id).status, RiderStatus.ON_TRIP)
            state = db.scalar(select(OrderDelivery.state).where(OrderDelivery.order_id == order.id))
            self.assertEqual(state, "ASSIGNED")
        self.offer_withdrawn.assert_called_once()

    def test_two_riders_claim_at_once_and_exactly_one_wins(self) -> None:
        a, b = self._rider(), self._rider()
        order = self._order()
        results: list[str] = []

        def go(user: User) -> None:
            with self.fdb.session() as db:
                try:
                    offers.claim(db, db.get(User, user.id), order.id)
                    results.append("won")
                except HTTPException as error:
                    results.append(str(error.detail))

        threads = [threading.Thread(target=go, args=(u,)) for u in (a, b)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(results), ["order_taken", "won"])
        with self.fdb.session() as db:
            self.assertEqual(db.scalar(select(func.count(RiderTrip.id))), 1)

    def test_claim_is_refused_once_the_courier_has_it_or_the_window_closed(self) -> None:
        rider = self._rider()
        gone = self._order()
        with self.fdb.session() as db:
            row = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == gone.id))
            row.provider = "pidge"
            db.commit()
        with self.fdb.session() as db, self.assertRaises(HTTPException) as caught:
            offers.claim(db, db.get(User, rider.id), gone.id)
        self.assertEqual((caught.exception.status_code, caught.exception.detail), (409, "order_taken"))
        late = self._order()
        with self.fdb.session() as db:
            row = db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == late.id))
            row.created_at = datetime.now(UTC) - timedelta(minutes=6)
            db.commit()
        with self.fdb.session() as db, self.assertRaises(HTTPException) as caught:
            offers.claim(db, db.get(User, rider.id), late.id)
        self.assertEqual(caught.exception.detail, "order_taken")

    def test_an_offline_rider_cannot_claim(self) -> None:
        order = self._order()
        offline = self._rider(status=RiderStatus.OFFLINE)
        with self.fdb.session() as db, self.assertRaises(HTTPException) as caught:
            offers.claim(db, db.get(User, offline.id), order.id)
        self.assertEqual(caught.exception.detail, "rider_offline")

    def test_the_rider_api_lists_and_claims(self) -> None:
        rider = self._rider()
        order = self._order()
        with self.fdb.session() as db:
            me = db.get(User, rider.id)
        client = client_for(self.fdb, me)
        listed = client.get("/api/rider/open-orders")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()[0]["order_id"], str(order.id))
        claimed = client.post(f"/api/rider/open-orders/{order.id}/claim")
        self.assertEqual(claimed.status_code, 200, claimed.text)
        self.assertEqual(client.post(f"/api/rider/open-orders/{order.id}/claim").status_code, 409)


if __name__ == "__main__":
    unittest.main()

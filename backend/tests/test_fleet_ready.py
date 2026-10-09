"""Food-ready time: riders are told when the food will be ready, and hear of
the order only a little before then.

The owner's rule (2026-10-10): the kitchen accepts, and the branch's own
preparation time (set by the admin on the branch) says when the food will be
ready. A rider who sees the order at the moment of acceptance and rides over
straight away waits at the counter, so the order reaches riders
`ready_lead_minutes` (10) before it is ready - or at once, when it is ready
sooner than that. The window before the courier takes over, and the waves,
count from that moment, not from acceptance.

A branch with no preparation time set is unknown, not zero: the order goes
to riders at once, exactly as before, and no ready time is shown.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, postgres_available, reset_overrides  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.models.enums import OfferOutcome, OrderEventActor, OrderStatus, PaymentMethod, RiderStatus  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.models.order_status_event import OrderStatusEvent  # noqa: E402
from app.models.platform_setting import PlatformSetting  # noqa: E402
from app.models.rider import Rider, RiderOffer, RiderTrip  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.delivery.service import build_request  # noqa: E402
from app.services.fleet import offers, ready, trips  # noqa: E402
from app.services.fleet.config import FleetConfig, validate_fleet  # noqa: E402

NEAR = (21.19, 72.84)  # ~1.1 km from the branch


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class ReadyTimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_ready_test")

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
        for target in ("offer_made", "offer_withdrawn", "trip_changed", "riders_changed", "delivery_changed"):
            p = mock.patch(f"app.services.fleet.notify.{target}")
            p.start()
            self.addCleanup(p.stop)
        for target in ("schedule_expiry", "queue_advance"):
            p = mock.patch(f"app.services.fleet.offers.{target}")
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(reset_overrides)

    def _rider(self) -> User:
        with self.fdb.session() as db:
            user = self.fdb.make_rider(db, lat=NEAR[0], lng=NEAR[1])
            db.commit()
            return user

    def _order(self, prep: int | None, *, accepted_ago: timedelta = timedelta(0),
               payment: PaymentMethod = PaymentMethod.CARD):
        """An order the kitchen accepted `accepted_ago` before its delivery row was made."""

        with self.fdb.session() as db:
            order = self.fdb.make_order(db, payment=payment)
            order.restaurant_location.preparation_time_minutes = prep
            delivery = self.fdb.make_fleet_delivery(db, order)
            db.flush()
            start = _aware(delivery.created_at)
            db.add(OrderStatusEvent(
                order_id=order.id,
                restaurant_id=order.restaurant_id,
                restaurant_location_id=order.restaurant_location_id,
                from_status=OrderStatus.PLACED,
                to_status=OrderStatus.ACCEPTED,
                actor=OrderEventActor.SYSTEM,
                occurred_at=start - accepted_ago,
            ))
            db.commit()
            return order, delivery.id, start

    def _sees(self, rider: User, at: datetime) -> list:
        with self.fdb.session() as db:
            return [r["order_id"] for r in offers.open_orders(db, db.get(User, rider.id), now=at)]

    def test_ready_time_is_acceptance_plus_the_branch_preparation_time(self) -> None:
        order, _, start = self._order(prep=25)
        with self.fdb.session() as db:
            self.assertEqual(ready.ready_at(db, db.get(Order, order.id)), start + timedelta(minutes=25))

    def test_a_branch_without_a_preparation_time_has_no_ready_time(self) -> None:
        order, _, _ = self._order(prep=None)
        with self.fdb.session() as db:
            self.assertIsNone(ready.ready_at(db, db.get(Order, order.id)))

    def test_riders_hear_of_a_slow_order_ten_minutes_before_it_is_ready(self) -> None:
        rider = self._rider()
        order, _, start = self._order(prep=25)
        self.assertEqual(self._sees(rider, start + timedelta(minutes=1)), [])
        self.assertEqual(self._sees(rider, start + timedelta(minutes=14, seconds=50)), [])
        self.assertEqual(self._sees(rider, start + timedelta(minutes=15, seconds=5)), [order.id])

    def test_nobody_is_rung_before_then_either(self) -> None:
        rider = self._rider()
        _, delivery_id, start = self._order(prep=25)
        with self.fdb.session() as db:
            self.assertEqual(offers.advance(db, delivery_id, now=start + timedelta(minutes=1)), "holding")
        with self.fdb.session() as db:
            # Online and reporting at the moment it opens.
            row = db.get(Rider, rider.id)
            row.status, row.last_location_at = RiderStatus.ONLINE, start + timedelta(minutes=15)
            db.commit()
        with self.fdb.session() as db:
            self.assertEqual(offers.advance(db, delivery_id, now=start + timedelta(minutes=15, seconds=5)), "offered")

    def test_a_quick_order_goes_to_riders_at_once(self) -> None:
        rider = self._rider()
        order, _, start = self._order(prep=8)
        self.assertEqual(self._sees(rider, start + timedelta(seconds=5)), [order.id])

    def test_no_preparation_time_means_at_once_as_before(self) -> None:
        rider = self._rider()
        order, _, start = self._order(prep=None)
        self.assertEqual(self._sees(rider, start + timedelta(seconds=5)), [order.id])

    def test_the_courier_window_counts_from_when_riders_hear_of_it(self) -> None:
        # Opens at +15 min; with a 5 minute window it is still ours at +19.
        rider = self._rider()
        order, _, start = self._order(prep=25)
        rows = None
        with self.fdb.session() as db:
            rows = offers.open_orders(db, db.get(User, rider.id), now=start + timedelta(minutes=19))
        self.assertEqual([r["order_id"] for r in rows], [order.id])
        self.assertEqual(rows[0]["ready_at"], start + timedelta(minutes=25))

    def test_taking_it_before_it_opens_is_refused(self) -> None:
        rider = self._rider()
        with self.fdb.session() as db:
            db.get(Rider, rider.id).status = RiderStatus.ONLINE
            db.commit()
        order, _, start = self._order(prep=25)
        with self.fdb.session() as db, self.assertRaises(HTTPException) as caught:
            offers.claim(db, db.get(User, rider.id), order.id, now=start + timedelta(minutes=2))
        self.assertEqual((caught.exception.status_code, caught.exception.detail), (409, "order_not_open"))
        with self.fdb.session() as db:
            trip = offers.claim(db, db.get(User, rider.id), order.id, now=start + timedelta(minutes=16))
            view = trips.trip_view(db, trip)
        self.assertEqual(view["ready_at"], start + timedelta(minutes=25))

    def test_the_admin_sees_when_it_is_ready_and_when_riders_get_it(self) -> None:
        order, _, start = self._order(prep=25)
        with self.fdb.session() as db:
            with mock.patch.object(offers, "_now", return_value=start + timedelta(minutes=1)):
                rows = {r["order_id"]: r for r in offers.waiting_orders(db)}
        self.assertEqual(rows[order.id]["ready_at"], start + timedelta(minutes=25))
        self.assertEqual(rows[order.id]["opens_at"], start + timedelta(minutes=15))

    def test_the_courier_is_told_the_real_ready_time(self) -> None:
        order, _, start = self._order(prep=25)
        with self.fdb.session() as db:
            request = build_request(db.get(Order, order.id))
        self.assertEqual(request.ready_at, start + timedelta(minutes=25))


    def _online(self, rider: User, at: datetime) -> None:
        with self.fdb.session() as db:
            row = db.get(Rider, rider.id)
            row.status, row.last_location_at = RiderStatus.ONLINE, at
            db.commit()

    def test_a_cash_order_still_goes_to_the_courier_at_once(self) -> None:
        # Holding is for our riders; an order they can never carry is not held.
        _, delivery_id, start = self._order(prep=25, payment=PaymentMethod.COD)
        with mock.patch("app.services.delivery.service.fallback_to_pidge") as fallback:
            with self.fdb.session() as db:
                self.assertEqual(offers.advance(db, delivery_id, now=start + timedelta(seconds=5)), "fallback")
        self.assertEqual(fallback.call_args.args[2], "cash order")

    def test_a_late_dispatch_opens_at_once(self) -> None:
        # Accepted 20 minutes before the row was made (the dispatch net found
        # it late): ready in 5, inside the lead, so riders hear now.
        rider = self._rider()
        order, _, start = self._order(prep=25, accepted_ago=timedelta(minutes=20))
        self.assertEqual(self._sees(rider, start + timedelta(seconds=5)), [order.id])

    def test_the_admin_may_still_assign_a_rider_during_the_hold(self) -> None:
        rider = self._rider()
        order, delivery_id, start = self._order(prep=25)
        self._online(rider, start)
        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            db.commit()
            offer = offers.reassign(db, db.get(User, admin.id), db.get(OrderDelivery, delivery_id), rider.id)
            offer_id = offer.id
        with self.fdb.session() as db:
            trip = offers.accept(db, db.get(User, rider.id), offer_id, now=start + timedelta(seconds=10))
            self.assertEqual(trip.rider_user_id, rider.id)

    def test_an_admin_offer_that_runs_out_during_the_hold_goes_back_to_holding(self) -> None:
        rider = self._rider()
        _, delivery_id, start = self._order(prep=25)
        self._online(rider, start)
        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            db.commit()
            offers.reassign(db, db.get(User, admin.id), db.get(OrderDelivery, delivery_id), rider.id)
        with mock.patch("app.services.delivery.service.fallback_to_pidge") as fallback:
            with self.fdb.session() as db:
                self.assertEqual(offers.advance(db, delivery_id, now=start + timedelta(minutes=2)), "holding")
        fallback.assert_not_called()
        with self.fdb.session() as db:
            outcomes = list(db.scalars(
                select(RiderOffer.outcome).where(RiderOffer.order_delivery_id == delivery_id)
            ))
        self.assertEqual(outcomes, [OfferOutcome.EXPIRED])


class ReadyConfigTests(unittest.TestCase):
    def test_riders_hear_ten_minutes_before_by_default(self) -> None:
        self.assertEqual(FleetConfig().ready_lead_minutes, 10)

    def test_an_old_saved_config_still_loads(self) -> None:
        self.assertEqual(validate_fleet({"radius_km": 6}).ready_lead_minutes, 10)

    def test_refuses_a_lead_out_of_range(self) -> None:
        for bad in ({"ready_lead_minutes": -1}, {"ready_lead_minutes": 61}):
            with self.assertRaises(HTTPException):
                validate_fleet(bad)


if __name__ == "__main__":
    unittest.main()

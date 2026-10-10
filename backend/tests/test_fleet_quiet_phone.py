"""A rider whose app was killed still gets orders - by push (the owner's rule, 2026-10-10).

A killed app sends no location. Before this, a rider was "silent" after
`silent_minutes` (3): no longer offered anything, and the sweep took them off
shift - so the push that exists to wake a killed app was never sent. Now a
rider still ONLINE whose phone can be pushed (an FCM token) stays reachable
for `push_minutes` (15): offered after every rider whose phone IS reporting,
and only then taken off shift, with a push saying so. A phone with no token
cannot be woken, so for it nothing changed.
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

from app.models.enums import RiderStatus  # noqa: E402
from app.models.order_delivery import OrderDelivery  # noqa: E402
from app.models.rider import Rider  # noqa: E402
from app.services.fleet import offers, riders  # noqa: E402
from app.services.fleet.config import FleetConfig, validate_fleet  # noqa: E402


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class QuietPhoneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_quiet_test")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fdb.drop()

    def setUp(self) -> None:
        for target in ("offer_made", "offer_withdrawn", "riders_changed", "shift_ended", "order_moved"):
            p = mock.patch(f"app.services.fleet.notify.{target}", create=True)
            setattr(self, target, p.start())
            self.addCleanup(p.stop)
        for target in ("schedule_expiry", "queue_advance"):
            p = mock.patch(f"app.services.fleet.offers.{target}")
            p.start()
            self.addCleanup(p.stop)
        with self.fdb.session() as db:
            # Each test starts with nobody on shift, so riders from another test do not answer.
            db.query(Rider).update({Rider.status: RiderStatus.OFFLINE})
            db.commit()

    def _rider(self, minutes_quiet: float, *, token: str = "tok", lat: float = 21.17, **kw):
        with self.fdb.session() as db:
            user = self.fdb.make_rider(db, lat=lat, seen_at=datetime.now(UTC) - timedelta(minutes=minutes_quiet), **kw)
            db.get(Rider, user.id).fcm_token = token
            db.commit()
            return user

    def _delivery(self):
        with self.fdb.session() as db:
            order = self.fdb.make_order(db)
            row = self.fdb.make_fleet_delivery(db, order)
            db.commit()
            return row.id

    def _candidates(self, delivery_id, fleet=FleetConfig()):
        with self.fdb.session() as db:
            row = db.get(OrderDelivery, delivery_id)
            return [r.user_id for r, _ in offers.candidates(db, row, fleet, datetime.now(UTC))]

    # Who is asked -------------------------------------------------------------
    def test_a_killed_app_that_can_be_pushed_is_still_asked(self) -> None:
        quiet = self._rider(8)
        self.assertIn(quiet.id, self._candidates(self._delivery()))

    def test_a_quiet_phone_with_no_push_token_is_not(self) -> None:
        quiet = self._rider(8, token="")
        self.assertNotIn(quiet.id, self._candidates(self._delivery()))

    def test_past_push_minutes_nobody_is_asked(self) -> None:
        quiet = self._rider(16)
        self.assertNotIn(quiet.id, self._candidates(self._delivery()))

    def test_a_reporting_phone_is_asked_before_a_nearer_quiet_one(self) -> None:
        quiet = self._rider(8, lat=21.1701)
        fresh = self._rider(0, lat=21.18)
        self.assertEqual(self._candidates(self._delivery())[:2], [fresh.id, quiet.id])

    def test_push_minutes_zero_is_the_old_rule(self) -> None:
        quiet = self._rider(8)
        self.assertNotIn(quiet.id, self._candidates(self._delivery(), FleetConfig(push_minutes=0)))

    def test_the_offer_goes_out_so_the_push_is_sent(self) -> None:
        quiet = self._rider(8)
        delivery_id = self._delivery()
        with self.fdb.session() as db:
            self.assertEqual(offers.advance(db, delivery_id), "offered")
        self.offer_made.assert_called_once()
        self.assertEqual(self.offer_made.call_args.args[1].rider_user_id, quiet.id)

    def test_a_quiet_phone_counts_as_someone_in_the_ring(self) -> None:
        # Alone 1 km away: the first ring is not skipped as empty while they can be woken.
        self._rider(8, lat=21.179)
        delivery_id = self._delivery()
        with self.fdb.session() as db:
            row = db.get(OrderDelivery, delivery_id)
            self.assertEqual(offers.reach_m(db, row, FleetConfig(), datetime.now(UTC)), 2000)

    # The sweep ----------------------------------------------------------------
    def test_the_sweep_leaves_a_pushable_quiet_rider_on_shift(self) -> None:
        quiet = self._rider(8)
        with self.fdb.session() as db:
            riders.sweep_silent(db)
        with self.fdb.session() as db:
            self.assertEqual(db.get(Rider, quiet.id).status, RiderStatus.ONLINE)
        self.shift_ended.assert_not_called()

    def test_the_sweep_ends_the_shift_after_push_minutes_and_says_so(self) -> None:
        quiet = self._rider(16)
        with self.fdb.session() as db:
            riders.sweep_silent(db)
        with self.fdb.session() as db:
            self.assertEqual(db.get(Rider, quiet.id).status, RiderStatus.OFFLINE)
        self.assertEqual([c.args[1] for c in self.shift_ended.call_args_list], [quiet.id])

    def test_no_token_still_goes_off_after_silent_minutes(self) -> None:
        quiet = self._rider(4, token="")
        with self.fdb.session() as db:
            riders.sweep_silent(db)
        with self.fdb.session() as db:
            self.assertEqual(db.get(Rider, quiet.id).status, RiderStatus.OFFLINE)


class PushMinutesConfigTests(unittest.TestCase):
    def test_default_and_old_config(self) -> None:
        self.assertEqual(FleetConfig().push_minutes, 15)
        self.assertEqual(validate_fleet({"offer_seconds": 30}).push_minutes, 15)

    def test_range(self) -> None:
        self.assertEqual(validate_fleet({"push_minutes": 0}).push_minutes, 0)
        self.assertEqual(validate_fleet({"push_minutes": 60}).push_minutes, 60)
        for bad in (-1, 61):
            with self.assertRaises(HTTPException):
                validate_fleet({"push_minutes": bad})


if __name__ == "__main__":
    unittest.main()

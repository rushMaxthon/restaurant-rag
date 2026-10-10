"""Riders bring in riders (the owner's rule, 2026-10-10).

A rider shares a code; a new rider signs up with it; when the new rider has
made N deliveries within X days of approval, both are paid a bonus with
their next payout. Terms are frozen when the code is accepted. The unique
(referral, kind) row is the money guard: a reward is written once, ever.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, client_for, postgres_available, reset_overrides  # noqa: E402

from sqlalchemy import select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from app.models.enums import ReferralStatus, RiderBonusKind, RiderOnboarding, TripEndReason  # noqa: E402
from app.models.rider import Rider, RiderTrip  # noqa: E402
from app.models.rider_referral import RiderBonus, RiderReferral  # noqa: E402


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class ReferralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_referral_test")
        with cls.fdb.session() as db:
            cls.admin = cls.fdb.make_admin(db)
            cls.owner = cls.fdb.make_owner(db)
            db.commit()

    @classmethod
    def tearDownClass(cls) -> None:
        reset_overrides()
        cls.fdb.drop()

    def setUp(self) -> None:
        for target in ("trip_changed", "trip_cancelled", "order_moved", "offer_made", "offer_withdrawn",
                       "delivery_changed", "riders_changed"):
            p = mock.patch(f"app.services.fleet.notify.{target}")
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(reset_overrides)
        from sqlalchemy import delete

        from app.models.platform_setting import PlatformSetting

        with self.fdb.session() as db:
            db.execute(delete(PlatformSetting))
            db.commit()

    # helpers ---------------------------------------------------------------

    def _rider(self, db, name="Priya Shah", onboarding=RiderOnboarding.APPROVED):
        user = self.fdb.make_rider(db, name=name)
        db.get(Rider, user.id).onboarding = onboarding
        db.flush()
        return user

    # Task 1 ------------------------------------------------------------------

    def test_one_bonus_of_each_kind_per_referral(self) -> None:
        with self.fdb.session() as db:
            a, b = self._rider(db), self._rider(db, name="Ravi")
            ref = RiderReferral(referred_user_id=b.id, referrer_user_id=a.id, code="PRIYA1234",
                                referrer_amount=Decimal("500"), joiner_amount=Decimal("200"),
                                deliveries_required=20, days_allowed=30)
            db.add(ref)
            db.flush()
            now = datetime.now(UTC)
            db.add(RiderBonus(rider_user_id=a.id, kind=RiderBonusKind.REFERRAL_REFERRER,
                              amount=Decimal("500"), referral_id=b.id, earned_at=now))
            db.flush()
            db.add(RiderBonus(rider_user_id=a.id, kind=RiderBonusKind.REFERRAL_REFERRER,
                              amount=Decimal("500"), referral_id=b.id, earned_at=now))
            with self.assertRaises(IntegrityError):
                db.flush()
            db.rollback()

    def test_a_rider_cannot_refer_themselves_in_the_database(self) -> None:
        with self.fdb.session() as db:
            a = self._rider(db)
            db.add(RiderReferral(referred_user_id=a.id, referrer_user_id=a.id, code="X1234",
                                 referrer_amount=Decimal("1"), joiner_amount=Decimal("1"),
                                 deliveries_required=1, days_allowed=1))
            with self.assertRaises(IntegrityError):
                db.flush()
            db.rollback()

    def test_referral_codes_are_unique(self) -> None:
        with self.fdb.session() as db:
            a, b = self._rider(db), self._rider(db, name="Ravi")
            db.get(Rider, a.id).referral_code = "SAME1234"
            db.flush()
            db.get(Rider, b.id).referral_code = "SAME1234"
            with self.assertRaises(IntegrityError):
                db.flush()
            db.rollback()


if __name__ == "__main__":
    unittest.main()

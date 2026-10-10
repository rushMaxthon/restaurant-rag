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

    # Task 2 ------------------------------------------------------------------

    def test_settings_default_and_round_trip(self) -> None:
        from app.services.fleet import referral

        with self.fdb.session() as db:
            cfg = referral.load_config(db)
            self.assertEqual(
                (cfg.enabled, cfg.referrer_amount, cfg.joiner_amount, cfg.deliveries_required, cfg.days_allowed),
                (True, Decimal("500"), Decimal("200"), 20, 30),
            )
            admin = self.fdb.make_admin(db)
            referral.save_config(db, admin, {"enabled": True, "referrer_amount": "750", "joiner_amount": "0",
                                             "deliveries_required": 10, "days_allowed": 14})
            cfg = referral.load_config(db)
            self.assertEqual((cfg.referrer_amount, cfg.joiner_amount, cfg.deliveries_required, cfg.days_allowed),
                             (Decimal("750"), Decimal("0"), 10, 14))

    def test_settings_refuse_nonsense(self) -> None:
        from fastapi import HTTPException

        from app.services.fleet import referral

        good = {"enabled": True, "referrer_amount": "500", "joiner_amount": "200",
                "deliveries_required": 20, "days_allowed": 30}
        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            for bad in ({"referrer_amount": "-1"}, {"joiner_amount": "abc"}, {"referrer_amount": "10001"},
                        {"deliveries_required": 0}, {"deliveries_required": 501}, {"days_allowed": 0},
                        {"days_allowed": 366}):
                with self.subTest(bad=bad), self.assertRaises(HTTPException):
                    referral.save_config(db, admin, {**good, **bad})

    # Task 3 ------------------------------------------------------------------

    def test_a_code_is_first_name_and_four_digits(self) -> None:
        from app.services.fleet import referral

        with self.fdb.session() as db:
            a = self._rider(db, name="Priya Shah")
            code = referral.ensure_code(db, a.id)
            self.assertRegex(code, r"^PRIYA\d{4}$")
            self.assertEqual(referral.ensure_code(db, a.id), code)  # stable
            b = self._rider(db, name="  ")
            self.assertRegex(referral.ensure_code(db, b.id), r"^RIDER\d{4}$")
            c = self._rider(db, name="Venkatalakshmi")
            self.assertRegex(referral.ensure_code(db, c.id), r"^VENKAT\d{4}$")
            pending = self._rider(db, onboarding=RiderOnboarding.PENDING)
            self.assertIsNone(referral.ensure_code(db, pending.id))

    def test_code_is_normalised(self) -> None:
        from app.services.fleet import referral

        with self.fdb.session() as db:
            a = self._rider(db)
            code = referral.ensure_code(db, a.id)
            b = self._rider(db, name="New", onboarding=RiderOnboarding.PENDING)
            ref = referral.accept_code(db, b.id, f"  {code.lower()[:3]} {code.lower()[3:]} ")
            self.assertEqual((ref.referrer_user_id, ref.code, ref.status), (a.id, code, ReferralStatus.WAITING))

    def test_terms_are_frozen_when_the_code_is_accepted(self) -> None:
        from app.services.fleet import referral

        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            referral.save_config(db, admin, {"referrer_amount": "300", "joiner_amount": "100",
                                             "deliveries_required": 5, "days_allowed": 7})
            a = self._rider(db)
            b = self._rider(db, name="New", onboarding=RiderOnboarding.PENDING)
            ref = referral.accept_code(db, b.id, referral.ensure_code(db, a.id))
            referral.save_config(db, admin, {"referrer_amount": "999", "joiner_amount": "999",
                                             "deliveries_required": 50, "days_allowed": 90})
            db.refresh(ref)
            self.assertEqual((ref.referrer_amount, ref.joiner_amount, ref.deliveries_required, ref.days_allowed),
                             (Decimal("300.00"), Decimal("100.00"), 5, 7))

    def test_every_refusal_has_its_code(self) -> None:
        from fastapi import HTTPException

        from app.services.fleet import referral

        with self.fdb.session() as db:
            a = self._rider(db)
            code = referral.ensure_code(db, a.id)
            b = self._rider(db, name="New", onboarding=RiderOnboarding.PENDING)

            def refused(user_id, value) -> str:
                with self.assertRaises(HTTPException) as caught:
                    referral.accept_code(db, user_id, value)
                return caught.exception.detail

            self.assertEqual(refused(b.id, "NOPE0000"), "referral_unknown")
            pending_referrer = self._rider(db, name="Kiran", onboarding=RiderOnboarding.PENDING)
            db.get(Rider, pending_referrer.id).referral_code = "KIRAN1111"
            db.flush()
            self.assertEqual(refused(b.id, "KIRAN1111"), "referral_inactive")
            a_self = self._rider(db, name="Self", onboarding=RiderOnboarding.PENDING)
            db.get(Rider, a_self.id).referral_code = "SELF2222"
            db.flush()
            self.assertEqual(refused(a_self.id, "SELF2222"), "referral_self")
            approved = self._rider(db, name="Old")
            self.assertEqual(refused(approved.id, code), "referral_closed")
            referral.accept_code(db, b.id, code)
            self.assertEqual(refused(b.id, code), "referral_taken")
            from app.models.user import User

            db.get(User, a.id).is_active = False
            c = self._rider(db, name="Late", onboarding=RiderOnboarding.PENDING)
            db.flush()
            self.assertEqual(refused(c.id, code), "referral_inactive")


if __name__ == "__main__":
    unittest.main()

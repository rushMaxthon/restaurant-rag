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

    # Task 4 ------------------------------------------------------------------

    def _pair(self, db, **terms):
        """An approved referrer and a referred rider whose code was accepted, then approved."""

        from app.services.fleet import referral

        if terms:
            admin = self.fdb.make_admin(db)
            referral.save_config(db, admin, terms)
        a = self._rider(db, name="Priya")
        b = self._rider(db, name="New", onboarding=RiderOnboarding.PENDING)
        referral.accept_code(db, b.id, referral.ensure_code(db, a.id))
        db.get(Rider, b.id).onboarding = RiderOnboarding.APPROVED
        referral.on_approved(db, b.id)
        db.commit()
        return a, b

    def _delivered(self, db, rider_id, *, at=None, reason=TripEndReason.DELIVERED):
        order = self.fdb.make_order(db)
        delivery = self.fdb.make_fleet_delivery(db, order, state="DELIVERED")
        at = at or datetime.now(UTC)
        db.add(RiderTrip(order_delivery_id=delivery.id, rider_user_id=rider_id, accepted_at=at,
                         ended_at=at, end_reason=reason, earning_amount=Decimal("30")))
        db.flush()

    def test_approval_starts_the_clock(self) -> None:
        with self.fdb.session() as db:
            _, b = self._pair(db)
            ref = db.get(RiderReferral, b.id)
            self.assertEqual(ref.status, ReferralStatus.IN_PROGRESS)
            self.assertAlmostEqual((ref.deadline - ref.approved_at).total_seconds(), 30 * 86400, delta=1)
            self.assertIsNotNone(db.get(Rider, b.id).referral_code)

    def test_earned_exactly_at_n_and_both_paid(self) -> None:
        from app.services.fleet import referral

        with self.fdb.session() as db:
            a, b = self._pair(db, deliveries_required=3, referrer_amount="500", joiner_amount="200")
            self._delivered(db, b.id, reason=TripEndReason.CUSTOMER_UNAVAILABLE)
            self._delivered(db, b.id, reason=TripEndReason.CANCELLED_AFTER_PICKUP)
            for _ in range(2):
                self._delivered(db, b.id)
                self.assertFalse(referral.on_delivered(db, b.id))
            self._delivered(db, b.id)
            self.assertTrue(referral.on_delivered(db, b.id))
            db.commit()
            bonuses = {x.kind: (x.rider_user_id, x.amount) for x in db.scalars(select(RiderBonus))
                       if x.referral_id == b.id}
            self.assertEqual(bonuses, {
                RiderBonusKind.REFERRAL_REFERRER: (a.id, Decimal("500.00")),
                RiderBonusKind.REFERRAL_JOINER: (b.id, Decimal("200.00")),
            })
            self.assertEqual(db.get(RiderReferral, b.id).status, ReferralStatus.EARNED)

    def test_earning_twice_pays_once(self) -> None:
        from app.services.fleet import referral

        with self.fdb.session() as db:
            _, b = self._pair(db, deliveries_required=1)
            self._delivered(db, b.id)
            self.assertTrue(referral.on_delivered(db, b.id))
            self.assertFalse(referral.on_delivered(db, b.id))
            # A racing writer that slipped past the status check still cannot add a second row.
            ref = db.get(RiderReferral, b.id)
            ref.status = ReferralStatus.IN_PROGRESS
            db.flush()
            self.assertFalse(referral.on_delivered(db, b.id))
            db.commit()
            rows = [x for x in db.scalars(select(RiderBonus)) if x.referral_id == b.id]
            self.assertEqual(len(rows), 2)

    def test_zero_amount_writes_no_row(self) -> None:
        from app.services.fleet import referral

        with self.fdb.session() as db:
            _, b = self._pair(db, deliveries_required=1, joiner_amount="0")
            self._delivered(db, b.id)
            referral.on_delivered(db, b.id)
            db.commit()
            kinds = [x.kind for x in db.scalars(select(RiderBonus)) if x.referral_id == b.id]
            self.assertEqual(kinds, [RiderBonusKind.REFERRAL_REFERRER])

    def test_after_the_deadline_nothing_counts_and_it_expires(self) -> None:
        from app.services.fleet import referral

        with self.fdb.session() as db:
            _, b = self._pair(db, deliveries_required=1, days_allowed=1)
            ref = db.get(RiderReferral, b.id)
            later = ref.deadline + timedelta(hours=1)
            self._delivered(db, b.id, at=later)
            self.assertFalse(referral.on_delivered(db, b.id, now=later))
            referral.refresh_status(db, ref, now=later)
            db.commit()
            self.assertEqual(db.get(RiderReferral, b.id).status, ReferralStatus.EXPIRED)

    def test_a_delivery_before_approval_does_not_count(self) -> None:
        from app.services.fleet import referral

        with self.fdb.session() as db:
            _, b = self._pair(db, deliveries_required=1)
            ref = db.get(RiderReferral, b.id)
            self._delivered(db, b.id, at=ref.approved_at - timedelta(hours=1))
            self.assertEqual(referral.delivered_count(db, ref), 0)

    def test_programme_off_blocks_new_codes_and_earning(self) -> None:
        from fastapi import HTTPException

        from app.services.fleet import referral

        with self.fdb.session() as db:
            a, b = self._pair(db, deliveries_required=1)
            a2, b2 = self._pair(db, deliveries_required=1)
            self._delivered(db, b2.id)
            referral.on_delivered(db, b2.id)  # earned while on
            admin = self.fdb.make_admin(db)
            referral.save_config(db, admin, {"enabled": False})
            self._delivered(db, b.id)
            self.assertFalse(referral.on_delivered(db, b.id))
            c = self._rider(db, name="Late", onboarding=RiderOnboarding.PENDING)
            with self.assertRaises(HTTPException) as caught:
                referral.accept_code(db, c.id, referral.ensure_code(db, a.id))
            self.assertEqual(caught.exception.detail, "referral_closed")
            db.commit()
            earned = [x for x in db.scalars(select(RiderBonus)) if x.referral_id == b2.id]
            self.assertEqual(len(earned), 2)  # untouched

    def test_cancel(self) -> None:
        from fastapi import HTTPException

        from app.services.fleet import referral

        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            _, b = self._pair(db, deliveries_required=1)
            with self.assertRaises(HTTPException):
                referral.cancel(db, admin, b.id, "  ")
            self._delivered(db, b.id)
            referral.on_delivered(db, b.id)
            db.commit()
            ref = referral.cancel(db, admin, b.id, "Same person, two phones")
            self.assertEqual(ref.status, ReferralStatus.CANCELLED)
            self.assertEqual([x for x in db.scalars(select(RiderBonus)) if x.referral_id == b.id], [])
            with self.assertRaises(HTTPException) as caught:
                referral.cancel(db, admin, b.id, "again")
            self.assertEqual(caught.exception.status_code, 409)

    # Task 5 ------------------------------------------------------------------

    def _bonus(self, db, rider_id, amount="500", at=None):
        a = self._rider(db, name="Other")
        ref = RiderReferral(referred_user_id=a.id, referrer_user_id=rider_id, code=f"X{uuid.uuid4().hex[:6]}",
                            referrer_amount=Decimal(amount), joiner_amount=Decimal("0"),
                            deliveries_required=1, days_allowed=1, status=ReferralStatus.EARNED)
        db.add(ref)
        db.flush()
        db.add(RiderBonus(rider_user_id=rider_id, kind=RiderBonusKind.REFERRAL_REFERRER, amount=Decimal(amount),
                          referral_id=a.id, earned_at=at or datetime.now(UTC)))
        db.flush()

    def test_bonus_pays_without_trips(self) -> None:
        with self.fdb.session() as db:
            rider = self._rider(db)
            self._bonus(db, rider.id, "500")
            db.commit()
        admin = client_for(self.fdb, self.admin)
        rows = {r["rider_user_id"]: r for r in admin.get("/api/admin/riders/payouts/unpaid").json()}
        self.assertEqual((Decimal(rows[str(rider.id)]["amount"]), rows[str(rider.id)]["trips"]), (Decimal("500.00"), 0))
        later = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
        r = admin.post(f"/api/admin/riders/{rider.id}/payouts", json={"period_to": later, "reference": "UTR1"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((Decimal(r.json()["amount"]), r.json()["trips"]), (Decimal("500.00"), 0))
        again = admin.post(f"/api/admin/riders/{rider.id}/payouts", json={"period_to": later})
        self.assertEqual((again.status_code, again.json()["detail"]), (409, "nothing_to_pay"))

    def test_bonus_and_trips_pay_together_once(self) -> None:
        now = datetime.now(UTC)
        with self.fdb.session() as db:
            rider = self._rider(db)
            self._delivered(db, rider.id, at=now - timedelta(hours=2))  # Rs 30
            self._bonus(db, rider.id, "200", at=now - timedelta(hours=1))
            db.commit()
        earnings = client_for(self.fdb, rider).get("/api/rider/earnings").json()
        self.assertEqual(Decimal(earnings["unpaid"]), Decimal("230.00"))
        self.assertEqual(Decimal(earnings["today"]), Decimal("230.00"))
        self.assertEqual(earnings["today_trips"], 1)
        self.assertEqual([(Decimal(b["amount"]), b["kind"]) for b in earnings["bonuses"]],
                         [(Decimal("200.00"), "REFERRAL_REFERRER")])
        admin = client_for(self.fdb, self.admin)
        r = admin.post(f"/api/admin/riders/{rider.id}/payouts", json={"period_to": now.isoformat()})
        self.assertEqual(Decimal(r.json()["amount"]), Decimal("230.00"))
        with self.fdb.session() as db:
            self.assertTrue(all(b.payout_id for b in db.scalars(select(RiderBonus).where(RiderBonus.rider_user_id == rider.id))))


if __name__ == "__main__":
    unittest.main()

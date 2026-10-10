"""Referral v2 (the owner's call, 2026-10-10): Swiggy-style steps, pushes, leaderboard.

The programme pays in steps - e.g. Rs 100 + Rs 50 at 10 deliveries, Rs 400 +
Rs 150 more at 30 - each step written once (UNIQUE referral, kind, step).
Steps already earned survive expiry. Pushes go out only after the commit
that caused them. The leaderboard counts first steps reached this month.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

from fleet_harness import FleetDB, client_for, postgres_available, reset_overrides  # noqa: E402

from fastapi import HTTPException  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.models.enums import ReferralStatus, RiderBonusKind, RiderOnboarding, TripEndReason  # noqa: E402
from app.models.rider import Rider, RiderTrip  # noqa: E402
from app.models.rider_referral import RiderBonus, RiderReferral  # noqa: E402
from app.services.fleet import referral  # noqa: E402

TWO_STEPS = {"steps": [{"deliveries": 1, "referrer_amount": "100", "joiner_amount": "50"},
                       {"deliveries": 3, "referrer_amount": "400", "joiner_amount": "150"}],
             "days_allowed": 30}


@unittest.skipUnless(postgres_available(), "local Postgres is not running")
class ReferralStepsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fdb = FleetDB("restaurant_rag_fleet_referral_steps_test")
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
        p = mock.patch("app.services.rate_limit.hit")
        p.start()
        self.addCleanup(p.stop)
        # Every push in this file is recorded here instead of going to FCM.
        self.pushes: list[tuple] = []
        p = mock.patch("app.services.fleet.notify._push",
                       side_effect=lambda db, rider_id, data, **kw: self.pushes.append((rider_id, dict(data))) or "sent")
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

    def _pair(self, db, settings=None):
        referral.save_config(db, self.fdb.make_admin(db), settings or TWO_STEPS)
        a = self._rider(db, name="Priya Shah")
        b = self._rider(db, name="Ravi Kumar", onboarding=RiderOnboarding.PENDING)
        referral.accept_code(db, b.id, referral.ensure_code(db, a.id))
        db.get(Rider, b.id).onboarding = RiderOnboarding.APPROVED
        referral.on_approved(db, b.id)
        db.commit()
        return a, b

    def _delivered(self, db, rider_id, *, at=None, n=1):
        for _ in range(n):
            order = self.fdb.make_order(db)
            delivery = self.fdb.make_fleet_delivery(db, order, state="DELIVERED")
            when = at or datetime.now(UTC)
            db.add(RiderTrip(order_delivery_id=delivery.id, rider_user_id=rider_id, accepted_at=when,
                             ended_at=when, end_reason=TripEndReason.DELIVERED, earning_amount=Decimal("30")))
        db.flush()

    def _bonuses(self, db, referred_id):
        return sorted((b.kind.value, b.step, b.amount) for b in db.scalars(
            select(RiderBonus).where(RiderBonus.referral_id == referred_id)))

    # Task 1: steps ----------------------------------------------------------------

    def test_default_is_two_steps(self) -> None:
        with self.fdb.session() as db:
            cfg = referral.load_config(db)
            self.assertEqual([(s.deliveries, s.referrer_amount, s.joiner_amount) for s in cfg.steps],
                             [(10, Decimal("100.00"), Decimal("50.00")), (30, Decimal("400.00"), Decimal("150.00"))])
            self.assertEqual((cfg.days_allowed, cfg.enabled, cfg.leaderboard_enabled), (30, True, True))
            self.assertEqual((cfg.referrer_amount, cfg.joiner_amount, cfg.deliveries_required),
                             (Decimal("500.00"), Decimal("200.00"), 30))

    def test_v1_settings_read_as_one_step(self) -> None:
        with self.fdb.session() as db:
            referral.save_config(db, self.fdb.make_admin(db),
                                 {"referrer_amount": "300", "joiner_amount": "100", "deliveries_required": 5})
            cfg = referral.load_config(db)
            self.assertEqual([(s.deliveries, s.referrer_amount, s.joiner_amount) for s in cfg.steps],
                             [(5, Decimal("300.00"), Decimal("100.00"))])

    def test_steps_refuse_nonsense(self) -> None:
        step = {"deliveries": 5, "referrer_amount": "100", "joiner_amount": "50"}
        with self.fdb.session() as db:
            admin = self.fdb.make_admin(db)
            for bad in ([], [step] * 6, [step, step], [{**step, "deliveries": 0}], [{**step, "deliveries": 501}],
                        [{**step, "referrer_amount": "-1"}], [{**step, "referrer_amount": "0", "joiner_amount": "0"}]):
                with self.subTest(bad=bad), self.assertRaises(HTTPException):
                    referral.save_config(db, admin, {"steps": bad, "days_allowed": 30})

    def test_partial_then_final(self) -> None:
        with self.fdb.session() as db:
            _, b = self._pair(db)
            self._delivered(db, b.id)
            self.assertTrue(referral.on_delivered(db, b.id))
            db.commit()
            self.assertEqual(db.get(RiderReferral, b.id).status, ReferralStatus.IN_PROGRESS)
            self.assertEqual(self._bonuses(db, b.id), [("REFERRAL_JOINER", 0, Decimal("50.00")),
                                                        ("REFERRAL_REFERRER", 0, Decimal("100.00"))])
            self._delivered(db, b.id, n=2)
            self.assertTrue(referral.on_delivered(db, b.id))
            db.commit()
            self.assertEqual(db.get(RiderReferral, b.id).status, ReferralStatus.EARNED)
            self.assertEqual(len(self._bonuses(db, b.id)), 4)

    def test_two_steps_at_once(self) -> None:
        with self.fdb.session() as db:
            _, b = self._pair(db)
            self._delivered(db, b.id, n=3)
            written = referral.on_delivered(db, b.id)
            db.commit()
            self.assertEqual(len(written), 4)
            self.assertEqual(db.get(RiderReferral, b.id).status, ReferralStatus.EARNED)

    def test_each_step_paid_once(self) -> None:
        with self.fdb.session() as db:
            _, b = self._pair(db)
            self._delivered(db, b.id, n=3)
            referral.on_delivered(db, b.id)
            ref = db.get(RiderReferral, b.id)
            ref.status = ReferralStatus.IN_PROGRESS  # a racing caller that slipped past the status
            db.flush()
            self.assertFalse(referral.on_delivered(db, b.id))
            db.commit()
            self.assertEqual(len(self._bonuses(db, b.id)), 4)

    def test_expiry_keeps_earned_steps(self) -> None:
        with self.fdb.session() as db:
            _, b = self._pair(db)
            self._delivered(db, b.id)
            referral.on_delivered(db, b.id)
            ref = db.get(RiderReferral, b.id)
            later = ref.deadline + timedelta(hours=1)
            self._delivered(db, b.id, at=later, n=2)
            self.assertFalse(referral.on_delivered(db, b.id, now=later))
            referral.refresh_status(db, ref, now=later)
            db.commit()
            self.assertEqual(db.get(RiderReferral, b.id).status, ReferralStatus.EXPIRED)
            self.assertEqual(len(self._bonuses(db, b.id)), 2)
        later_utc = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
        r = client_for(self.fdb, self.admin).post(f"/api/admin/riders/{b.id}/payouts", json={"period_to": later_utc})
        # Step 0's Rs 50 joining bonus plus the one Rs 30 trip inside the window.
        self.assertEqual((r.status_code, Decimal(r.json()["amount"])), (201, Decimal("80.00")))

    # Task 2: pushes after commit ---------------------------------------------

    def _events(self, rider_id=None):
        return [(rid, d["event"], d.get("name", ""), d.get("amount", "")) for rid, d in self.pushes
                if d.get("type") == "rider_referral" and (rider_id is None or rid == rider_id)]

    def test_joined_and_approved_pushes_go_after_commit(self) -> None:
        with self.fdb.session() as db:
            referral.save_config(db, self.fdb.make_admin(db), TWO_STEPS)
            a = self._rider(db, name="Priya Shah")
            b = self._rider(db, name="Ravi Kumar", onboarding=RiderOnboarding.PENDING)
            referral.accept_code(db, b.id, referral.ensure_code(db, a.id))
            self.assertEqual(self._events(), [])  # nothing before the commit
            db.commit()
            self.assertEqual(self._events(a.id), [(a.id, "joined", "Ravi K.", "")])
            db.get(Rider, b.id).onboarding = RiderOnboarding.APPROVED
            referral.on_approved(db, b.id)
            db.commit()
            approved = [d for rid, d in self.pushes if d.get("event") == "approved"]
            self.assertEqual(len(approved), 1)
            self.assertEqual((approved[0]["deliveries"], approved[0]["days"]), ("1", "30"))

    def test_earned_push_to_each_side_with_money(self) -> None:
        with self.fdb.session() as db:
            a, b = self._pair(db, {"steps": [{"deliveries": 1, "referrer_amount": "100", "joiner_amount": "0"}],
                                   "days_allowed": 30})
            self.pushes.clear()
            self._delivered(db, b.id)
            referral.on_delivered(db, b.id)
            db.commit()
            self.assertEqual(self._events(), [(a.id, "earned", "Ravi K.", "100.00")])

    def test_push_not_sent_after_rollback(self) -> None:
        with self.fdb.session() as db:
            referral.save_config(db, self.fdb.make_admin(db), TWO_STEPS)
            a = self._rider(db, name="Priya Shah")
            b = self._rider(db, name="Ravi Kumar", onboarding=RiderOnboarding.PENDING)
            code = referral.ensure_code(db, a.id)
            db.commit()
            referral.accept_code(db, b.id, code)
            db.rollback()
            db.get(Rider, a.id).notes = "something else"
            db.commit()
            self.assertEqual(self._events(), [])

    # Task 3: view, leaderboard, settings API --------------------------------------

    def test_view_has_totals_and_step_progress(self) -> None:
        with self.fdb.session() as db:
            a, b = self._pair(db)
            self._delivered(db, b.id)
            referral.on_delivered(db, b.id)
            db.commit()
        mine = client_for(self.fdb, a).get("/api/rider/referral").json()
        self.assertEqual((Decimal(mine["earned_total"]), Decimal(mine["pending_total"]), Decimal(mine["paid_total"])),
                         (Decimal("100"), Decimal("100"), Decimal("0")))
        self.assertEqual([s["deliveries"] for s in mine["terms"]["steps"]], [1, 3])
        row = mine["referrals"][0]
        self.assertEqual([(s["deliveries"], Decimal(s["amount"]), s["earned"], s["paid"]) for s in row["steps"]],
                         [(1, Decimal("100"), True, False), (3, Decimal("400"), False, False)])
        self.assertEqual((Decimal(row["earned_amount"]), Decimal(row["paid_amount"])), (Decimal("100"), Decimal("0")))
        theirs = client_for(self.fdb, b).get("/api/rider/referral").json()["joined_with"]
        self.assertEqual([Decimal(s["amount"]) for s in theirs["steps"]], [Decimal("50"), Decimal("150")])

    def _bonus(self, db, referrer_id, *, kind=RiderBonusKind.REFERRAL_REFERRER, step=0, at=None):
        friend = self._rider(db, name="Friend Rider")
        db.add(RiderReferral(referred_user_id=friend.id, referrer_user_id=referrer_id, code="X",
                             referrer_amount=Decimal("1"), joiner_amount=Decimal("1"),
                             deliveries_required=1, days_allowed=1, status=ReferralStatus.EARNED))
        db.flush()
        db.add(RiderBonus(rider_user_id=referrer_id, kind=kind, amount=Decimal("1"), referral_id=friend.id,
                          step=step, earned_at=at or datetime.now(UTC)))
        db.flush()

    def test_leaderboard_this_month_first_steps_only(self) -> None:
        from app.models.rider_referral import RiderBonus as _B, RiderReferral as _R

        with self.fdb.session() as db:
            db.query(_B).delete()
            db.query(_R).delete()
            x = self._rider(db, name="Xena Top")
            y = self._rider(db, name="Yash Second")
            z = self._rider(db, name="Zoya Joiner")
            self._bonus(db, x.id)
            self._bonus(db, x.id)
            self._bonus(db, y.id)
            self._bonus(db, y.id, at=datetime.now(UTC) - timedelta(days=40))  # last month
            self._bonus(db, y.id, step=1)  # not a first step
            self._bonus(db, z.id, kind=RiderBonusKind.REFERRAL_JOINER)  # a joiner's own bonus
            db.commit()
        board = client_for(self.fdb, y).get("/api/rider/referral").json()["leaderboard"]
        self.assertEqual([(r["rank"], r["name"], r["count"], r["me"]) for r in board["top"]],
                         [(1, "Xena T.", 2, False), (2, "Yash S.", 1, True)])
        self.assertEqual((board["my_rank"], board["my_count"]), (2, 1))

    def test_leaderboard_off(self) -> None:
        with self.fdb.session() as db:
            a, _ = self._pair(db, {**TWO_STEPS, "leaderboard_enabled": False})
        self.assertIsNone(client_for(self.fdb, a).get("/api/rider/referral").json()["leaderboard"])

    def test_admin_settings_and_rows_speak_steps(self) -> None:
        admin = client_for(self.fdb, self.admin)
        r = admin.put("/api/admin/riders/settings/referral", json={**TWO_STEPS, "enabled": True,
                                                                  "leaderboard_enabled": False})
        self.assertEqual(r.status_code, 200, r.text)
        body = admin.get("/api/admin/riders/settings/referral").json()
        self.assertEqual(([s["deliveries"] for s in body["steps"]], body["leaderboard_enabled"]), ([1, 3], False))
        with self.fdb.session() as db:
            _, b = self._pair(db)
            self._delivered(db, b.id)
            referral.on_delivered(db, b.id)
            db.commit()
        rows = {r["referred_user_id"]: r for r in client_for(self.fdb, self.admin).get("/api/admin/riders/referrals").json()}
        self.assertEqual((rows[str(b.id)]["steps_total"], rows[str(b.id)]["steps_earned"]), (2, 1))


if __name__ == "__main__":
    unittest.main()

# Rider Referral Programme Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A rider shares a code; a new rider who signs up with it and completes N deliveries within X days of approval earns both riders a bonus, paid with their next payout; the admin sets every number.

**Architecture:** Two new tables (`rider_referrals`, one row per referred rider with frozen terms; `rider_bonuses`, one row per reward with a payout link) plus `riders.referral_code`. One service module `app/services/fleet/referral.py` owns codes, acceptance, the approval hook, the delivery hook, expiry-on-read, cancellation and the views; settings live in `platform_settings` like the rest of the fleet. Payouts add unpaid bonuses to unpaid trips. Admin gets a Referrals tab; the rider app gets a Refer & earn screen, a joining-bonus card and an optional code at sign-up.

**Tech Stack:** FastAPI + SQLAlchemy 2 + Alembic + Postgres (unittest suites); React 19 + Vite admin (vitest, no new deps); React Native rider app (jest, TypeScript, no new deps).

**Spec:** `docs/superpowers/specs/2026-10-10-rider-referral-design.md`

## Global Constraints

- Defaults: referrer Rs 500, joiner Rs 200, 20 deliveries, 30 days, programme on.
- Ranges: amounts 0-10000, deliveries 1-500, days 1-365.
- Code: first name A-Z letters (max 6, uppercase; `RIDER` if none) + 4 digits; unique; compared uppercase with spaces removed; max 16 chars.
- Refusal codes (exact strings): `referral_unknown`, `referral_self`, `referral_inactive`, `referral_taken`, `referral_closed`.
- Only `end_reason = DELIVERED` trips with `approved_at <= ended_at <= deadline` count.
- `UNIQUE (referral_id, kind)` on `rider_bonuses` is the money guard; a bonus with a `payout_id` is never deleted or changed.
- Migration `0091_rider_referrals`, `down_revision = "0090_rider_onboarding"`, RLS enabled on both new tables in the migration; mirrored in models (`create_all` builds the test DBs).
- No new dependencies anywhere (`frontend-admin` house rule). The rider app shares with React Native's built-in `Share` (the share sheet also offers Copy); no clipboard library.
- Rider-app strings in en/hi/gu; `Translations<typeof en>` must compile; placeholders survive (`dictionaries.test.ts`).
- Backend runs: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_fleet_referral` (Windows venv path).
- Commit trailer on every commit:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and
  `Claude-Session: https://claude.ai/code/session_01JFJkFSMqqK5aVpJZytBUDN`. Never commit `rider/metro.log`.

## Review Focus

1. A delivery confirmed by an admin (`admin_confirm_delivered`) must count like a rider's own - it goes through `_finish`; pinned in Task 6 test `test_admin_confirmed_delivery_counts`.
2. Two deliveries finishing at the same moment for the same referred rider must not write bonuses twice - the unique constraint plus `IntegrityError` handling in a savepoint; pinned in Task 4 test `test_earning_twice_pays_once`.
3. A referral code typed with spaces/lower case (`" priya 4821 "`) must be accepted; pinned in Task 3 test `test_code_is_normalised`.
4. A referred rider who is deactivated after earning still has their unpaid bonus paid (bonus rows don't depend on `is_active`); pinned in Task 5 test `test_bonus_pays_without_trips`.
5. Turning the programme off after a referral EARNED must not delete or block the unpaid bonus; pinned in Task 4 test `test_programme_off_blocks_new_codes_and_earning` (asserts existing bonus untouched).

---

## File Structure

Backend
- Modify `backend/app/models/enums.py` - `ReferralStatus`, `RiderBonusKind`.
- Create `backend/app/models/rider_referral.py` - `RiderReferral`, `RiderBonus`.
- Modify `backend/app/models/rider.py` - `Rider.referral_code`.
- Modify `backend/app/models/__init__.py` - export the new models.
- Create `backend/alembic/versions/0091_rider_referrals.py`.
- Create `backend/app/services/fleet/referral.py` - all referral rules.
- Modify `backend/app/services/fleet/payouts.py` - bonuses in unpaid/earnings/pay.
- Modify `backend/app/services/fleet/trips.py` - call the delivery hook in `_finish`.
- Modify `backend/app/services/fleet/onboarding/applications.py` - call the approval hook in `approve`.
- Modify `backend/app/schemas/rider_onboarding.py` - `SignupRequest.referral_code`.
- Modify `backend/app/schemas/rider.py` - referral schemas, `Earnings.bonuses`.
- Modify `backend/app/api/rider_signup.py` - accept a code at sign-up.
- Modify `backend/app/api/rider.py` - `GET /rider/referral`, `POST /rider/referral/code`.
- Modify `backend/app/api/admin_riders.py` - list, settings, cancel.
- Create `backend/tests/test_fleet_referral.py`.

Admin
- Modify `frontend-admin/src/types/app.ts`, `src/services/api.ts`.
- Create `frontend-admin/src/services/riderReferral.ts` + `.test.ts`.
- Create `frontend-admin/src/components/riders/ReferralsTab.tsx`.
- Modify `frontend-admin/src/pages/RidersPage.tsx` - the tab.

Rider app
- Modify `rider/src/types/api.ts`, `rider/src/services/rider.ts`, `rider/src/services/http.ts`.
- Create `rider/src/utils/referral.ts` + `.test.ts`.
- Create `rider/src/i18n/strings/referral.ts`; modify `rider/src/i18n/strings/index.ts`.
- Create `rider/src/screens/profile/ReferralScreen.tsx`, `rider/src/components/JoiningBonusCard.tsx`.
- Modify `rider/src/navigation/types.ts`, `RootNavigator.tsx`, `screens/profile/ProfileScreen.tsx`, `screens/home/HomeScreen.tsx`, `screens/earnings/EarningsScreen.tsx`, `screens/signup/SignupAccountScreen.tsx`, `screens/onboarding/OnboardingHomeScreen.tsx`.

Docs: `CLAUDE.md` (fleet section bullet), `.claude/worklog.md`.

---

### Task 1: Tables, models and migration

**Files:**
- Modify: `backend/app/models/enums.py` (after `TripEndReason`)
- Create: `backend/app/models/rider_referral.py`
- Modify: `backend/app/models/rider.py` (`Rider` columns + `__table_args__`)
- Modify: `backend/app/models/__init__.py:44`
- Create: `backend/alembic/versions/0091_rider_referrals.py`
- Test: `backend/tests/test_fleet_referral.py`

**Interfaces:**
- Produces: `ReferralStatus` (WAITING, IN_PROGRESS, EARNED, EXPIRED, CANCELLED), `RiderBonusKind` (REFERRAL_REFERRER, REFERRAL_JOINER), models `RiderReferral`, `RiderBonus`, column `Rider.referral_code: str | None`.

- [ ] **Step 1: Write the failing test** - create `backend/tests/test_fleet_referral.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_fleet_referral`
Expected: ERROR - `ImportError: cannot import name 'ReferralStatus'`.

- [ ] **Step 3: Write the models and migration**

`backend/app/models/enums.py`, after `class TripEndReason`:

```python
class ReferralStatus(StrEnum):
    """A referred rider's progress towards the referral reward (`fleet/referral.py`)."""

    WAITING = "WAITING"  # code accepted, rider not approved yet
    IN_PROGRESS = "IN_PROGRESS"  # approved: the clock runs
    EARNED = "EARNED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class RiderBonusKind(StrEnum):
    REFERRAL_REFERRER = "REFERRAL_REFERRER"
    REFERRAL_JOINER = "REFERRAL_JOINER"
```

`backend/app/models/rider_referral.py`:

```python
"""Referrals between riders and the bonuses they pay (`services/fleet/referral.py`).

`rider_referrals` is keyed by the REFERRED rider: one referrer per rider,
ever. Its terms are copied from the admin's settings when the code is
accepted, so a later change never breaks a promise already made.

`rider_bonuses` is money owed outside trips. UNIQUE (referral_id, kind) is
the guard that a reward is written once, whatever races; `payout_id` is set
by the payout that paid it, after which the row never changes. Both are
mirrored in migration 0091, because the test suites build from create_all.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import ReferralStatus, RiderBonusKind


def _enum(cls: type, name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda members: [m.value for m in members])


class RiderReferral(TimestampMixin, Base):
    __tablename__ = "rider_referrals"

    referred_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.user_id", ondelete="CASCADE"), primary_key=True
    )
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    referrer_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    joiner_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    deliveries_required: Mapped[int] = mapped_column(Integer, nullable=False)
    days_allowed: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ReferralStatus] = mapped_column(
        _enum(ReferralStatus, "rider_referral_status"),
        nullable=False,
        default=ReferralStatus.WAITING,
        server_default="WAITING",
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    earned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    cancelled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (CheckConstraint("referred_user_id <> referrer_user_id", name="not_self"),)


class RiderBonus(TimestampMixin, Base):
    __tablename__ = "rider_bonuses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rider_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[RiderBonusKind] = mapped_column(_enum(RiderBonusKind, "rider_bonus_kind"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    referral_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rider_referrals.referred_user_id", ondelete="CASCADE"), nullable=False
    )
    payout_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rider_payouts.id", ondelete="SET NULL"), nullable=True
    )
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("referral_id", "kind", name="uq_rider_bonuses_referral_kind"),
        CheckConstraint("amount > 0", name="positive"),
    )
```

`backend/app/models/rider.py` - in `Rider`, after `onboarding`:

```python
    # The rider's own code to share (`fleet/referral.ensure_code`): made on
    # approval, or the first time an older rider opens Refer & earn.
    referral_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
```

and change `__table_args__` to:

```python
    __table_args__ = (
        Index("ix_riders_status", "status"),
        UniqueConstraint("referral_code", name="uq_riders_referral_code"),
    )
```

(add `UniqueConstraint` to the `sqlalchemy` import line.)

`backend/app/models/__init__.py` - after line 44:

```python
from app.models.rider_referral import RiderBonus, RiderReferral
```

and add `"RiderBonus", "RiderReferral",` to `__all__` if the module has one (check the file's bottom; match its style).

`backend/alembic/versions/0091_rider_referrals.py`:

```python
"""Rider referrals: who referred whom on what terms, and the bonuses they pay.

Additive only. RLS is enabled on both new tables in the migration (0070+).
Constraint names are passed bare: the metadata naming convention is applied
to DROP as well as CREATE (CLAUDE.md, 0071).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0091_rider_referrals"
down_revision = "0090_rider_onboarding"
branch_labels = None
depends_on = None


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    postgresql.ENUM("WAITING", "IN_PROGRESS", "EARNED", "EXPIRED", "CANCELLED",
                    name="rider_referral_status").create(op.get_bind(), checkfirst=True)
    postgresql.ENUM("REFERRAL_REFERRER", "REFERRAL_JOINER", name="rider_bonus_kind").create(
        op.get_bind(), checkfirst=True
    )
    op.add_column("riders", sa.Column("referral_code", sa.String(16), nullable=True))
    op.create_unique_constraint("uq_riders_referral_code", "riders", ["referral_code"])

    op.create_table(
        "rider_referrals",
        sa.Column("referred_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("riders.user_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("referrer_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("riders.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("referrer_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("joiner_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("deliveries_required", sa.Integer(), nullable=False),
        sa.Column("days_allowed", sa.Integer(), nullable=False),
        sa.Column("status", _enum("rider_referral_status"), nullable=False, server_default="WAITING"),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("earned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("cancelled_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("referred_user_id <> referrer_user_id", name="not_self"),
    )
    op.create_index("ix_rider_referrals_referrer_user_id", "rider_referrals", ["referrer_user_id"])

    op.create_table(
        "rider_bonuses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("rider_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("riders.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", _enum("rider_bonus_kind"), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("referral_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("rider_referrals.referred_user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("payout_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("rider_payouts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("earned_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("referral_id", "kind", name="uq_rider_bonuses_referral_kind"),
        sa.CheckConstraint("amount > 0", name="positive"),
    )
    op.create_index("ix_rider_bonuses_rider_user_id", "rider_bonuses", ["rider_user_id"])

    for table in ("rider_referrals", "rider_bonuses"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("rider_bonuses")
    op.drop_table("rider_referrals")
    op.drop_constraint("uq_riders_referral_code", "riders", type_="unique")
    op.drop_column("riders", "referral_code")
    op.execute("DROP TYPE IF EXISTS rider_bonus_kind")
    op.execute("DROP TYPE IF EXISTS rider_referral_status")
```

- [ ] **Step 4: Run tests**

Run: `cd backend && ./.venv/Scripts/python.exe -m unittest tests.test_fleet_referral` → Expected: `Ran 3 tests ... OK`.
Run: `./.venv/Scripts/python.exe -m compileall -q app alembic` → no output.
Check the chain: `./.venv/Scripts/python.exe -m alembic heads` → Expected: `0091_rider_referrals (head)` (needs only the files; if it needs a DB URL, set `DATABASE_URL` to the local test postgres).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models backend/alembic/versions/0091_rider_referrals.py backend/tests/test_fleet_referral.py
git commit -m "feat(fleet): rider referral tables - referrals with frozen terms, bonuses with a payout link"
```

---

### Task 2: Referral settings

**Files:**
- Create: `backend/app/services/fleet/referral.py` (settings part)
- Test: `backend/tests/test_fleet_referral.py`

**Interfaces:**
- Produces: `REFERRAL_KEY = "rider_referral"`, frozen dataclass `ReferralConfig(enabled: bool, referrer_amount: Decimal, joiner_amount: Decimal, deliveries_required: int, days_allowed: int)`, `load_config(db) -> ReferralConfig`, `save_config(db, user, data: dict) -> ReferralConfig` (422 on bad input), `config_value(cfg) -> dict` (wire/stored shape, amounts as str).

- [ ] **Step 1: Write the failing tests** (append to the class):

```python
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
```

- [ ] **Step 2: Run** `./.venv/Scripts/python.exe -m unittest tests.test_fleet_referral` → Expected: ERROR `ModuleNotFoundError ... referral` (or ImportError).

- [ ] **Step 3: Implement** - create `backend/app/services/fleet/referral.py`:

```python
"""Riders bring in riders (the owner's rule, 2026-10-10).

A rider shares their code; a new rider signs up with it. Once the new rider
is approved, the clock runs: N successful deliveries within X days and both
are paid - the referrer A, the new rider B - as bonus rows that the next
payout includes (`payouts.py`). The terms are copied onto the referral when
the code is accepted, so the admin changing them later never breaks a
promise. Expiry is applied when a referral is read; no beat task.

Settings live in `platform_settings` ("rider_referral"), the same shape as
`fleet/config.py`: defaults in code, an admin row overrides, refused rather
than repaired.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.services.fleet.config import _read, _write

logger = logging.getLogger(__name__)

REFERRAL_KEY = "rider_referral"


@dataclass(frozen=True, slots=True)
class ReferralConfig:
    enabled: bool = True
    referrer_amount: Decimal = Decimal("500")
    joiner_amount: Decimal = Decimal("200")
    deliveries_required: int = 20
    days_allowed: int = 30


def _refuse(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


def _amount(value: Any, name: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise _refuse(f"{name} must be a number") from None
    if not amount.is_finite() or amount < 0 or amount > 10000:
        raise _refuse(f"{name} must be between 0 and 10000")
    return amount.quantize(Decimal("0.01"))


def _whole(value: Any, name: str, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise _refuse(f"{name} must be a whole number") from None
    if not low <= number <= high:
        raise _refuse(f"{name} must be between {low} and {high}")
    return number


def validate_config(data: dict[str, Any]) -> ReferralConfig:
    base = ReferralConfig()
    return ReferralConfig(
        enabled=bool(data.get("enabled", base.enabled)),
        referrer_amount=_amount(data.get("referrer_amount", base.referrer_amount), "Referrer bonus"),
        joiner_amount=_amount(data.get("joiner_amount", base.joiner_amount), "New rider bonus"),
        deliveries_required=_whole(data.get("deliveries_required", base.deliveries_required),
                                   "Deliveries needed", 1, 500),
        days_allowed=_whole(data.get("days_allowed", base.days_allowed), "Days allowed", 1, 365),
    )


def config_value(cfg: ReferralConfig) -> dict[str, Any]:
    return {
        "enabled": cfg.enabled,
        "referrer_amount": str(cfg.referrer_amount),
        "joiner_amount": str(cfg.joiner_amount),
        "deliveries_required": cfg.deliveries_required,
        "days_allowed": cfg.days_allowed,
    }


def load_config(db: Session | None) -> ReferralConfig:
    raw = _read(db, REFERRAL_KEY)
    if not raw:
        return ReferralConfig()
    try:
        return validate_config(raw)
    except HTTPException:
        logger.error("Saved referral settings are invalid; using defaults: %s", raw)
        return ReferralConfig()


def save_config(db: Session, user: Any, data: dict[str, Any]) -> ReferralConfig:
    cfg = validate_config(data)
    _write(db, user, REFERRAL_KEY, config_value(cfg))
    return load_config(db)
```

- [ ] **Step 4: Run** → Expected: `Ran 5 tests ... OK`.

- [ ] **Step 5: Commit** - `git add backend/app/services/fleet/referral.py backend/tests/test_fleet_referral.py` and `git commit -m "feat(fleet): referral settings, admin-set with defaults in code"`.

---

### Task 3: Codes and accepting a code

**Files:**
- Modify: `backend/app/services/fleet/referral.py`
- Test: `backend/tests/test_fleet_referral.py`

**Interfaces:**
- Consumes: `load_config`, models from Task 1.
- Produces: `normalise(code: str) -> str`; `ensure_code(db, rider_user_id) -> str | None` (None unless APPROVED; flushes, does not commit); `accept_code(db, referred_user_id, code: str) -> RiderReferral` (raises 422 with one of the five refusal codes; adds and flushes, does not commit).

- [ ] **Step 1: Write the failing tests**:

```python
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
```

- [ ] **Step 2: Run** → Expected: 4 new tests ERROR with `AttributeError: module ... has no attribute 'ensure_code'`.

- [ ] **Step 3: Implement** - append to `referral.py` (and add imports at the top: `import re`, `import secrets`, `import uuid`, `from datetime import UTC, datetime, timedelta`, `from sqlalchemy import select`, `from app.models.enums import ReferralStatus, RiderBonusKind, RiderOnboarding`, `from app.models.rider import Rider`, `from app.models.rider_referral import RiderBonus, RiderReferral`, `from app.models.user import User`):

```python
# --- codes ----------------------------------------------------------------------


def normalise(code: str) -> str:
    """What a rider typed, as stored: uppercase, no spaces."""

    return re.sub(r"\s+", "", code or "").upper()[:16]


def _stem(full_name: str) -> str:
    first = (full_name or "").split()[0] if (full_name or "").split() else ""
    letters = re.sub(r"[^A-Za-z]", "", first).upper()[:6]
    return letters or "RIDER"


def ensure_code(db: Session, rider_user_id: uuid.UUID) -> str | None:
    """The rider's code, made the first time it is asked for. APPROVED riders only."""

    rider = db.get(Rider, rider_user_id)
    if rider is None or rider.onboarding != RiderOnboarding.APPROVED:
        return None
    if rider.referral_code:
        return rider.referral_code
    user = db.get(User, rider_user_id)
    stem = _stem(user.full_name if user else "")
    for _ in range(50):
        candidate = f"{stem}{secrets.randbelow(10_000):04d}"
        if db.scalar(select(Rider.user_id).where(Rider.referral_code == candidate)) is None:
            rider.referral_code = candidate
            db.flush()
            return candidate
    raise RuntimeError("could not find a free referral code")


# --- accepting a code ----------------------------------------------------------


def _refused(code: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=code)


def accept_code(db: Session, referred_user_id: uuid.UUID, raw_code: str) -> RiderReferral:
    """Link a not-yet-approved rider to the rider whose code they typed, on today's terms."""

    cfg = load_config(db)
    referred = db.get(Rider, referred_user_id)
    if not cfg.enabled or referred is None or referred.onboarding == RiderOnboarding.APPROVED:
        raise _refused("referral_closed")
    if db.get(RiderReferral, referred_user_id) is not None:
        raise _refused("referral_taken")
    code = normalise(raw_code)
    referrer = db.scalar(select(Rider).where(Rider.referral_code == code)) if code else None
    if referrer is None:
        raise _refused("referral_unknown")
    if referrer.user_id == referred_user_id:
        raise _refused("referral_self")
    referrer_user = db.get(User, referrer.user_id)
    if referrer.onboarding != RiderOnboarding.APPROVED or referrer_user is None or not referrer_user.is_active:
        raise _refused("referral_inactive")
    ref = RiderReferral(
        referred_user_id=referred_user_id,
        referrer_user_id=referrer.user_id,
        code=code,
        referrer_amount=cfg.referrer_amount,
        joiner_amount=cfg.joiner_amount,
        deliveries_required=cfg.deliveries_required,
        days_allowed=cfg.days_allowed,
        status=ReferralStatus.WAITING,
    )
    db.add(ref)
    db.flush()
    return ref
```

Note the order in `test_every_refusal_has_its_code`: `a_self` is PENDING and holds a code - `referral_self` is checked before `referral_inactive`, matching the implementation's order.

- [ ] **Step 4: Run** → Expected: `Ran 9 tests ... OK`.

- [ ] **Step 5: Commit** - `git commit -m "feat(fleet): referral codes and accepting one on frozen terms"` (add both files).

---

### Task 4: Approval, delivery, earning, expiry, cancellation

**Files:**
- Modify: `backend/app/services/fleet/referral.py`
- Test: `backend/tests/test_fleet_referral.py`

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces:
  - `on_approved(db, rider_user_id, *, now=None) -> None` - WAITING -> IN_PROGRESS with `approved_at`, `deadline`; ensures the new rider's own code. Flushes, no commit.
  - `on_delivered(db, rider_user_id, *, now=None) -> bool` - True when this call EARNED the referral. Flushes, no commit.
  - `refresh_status(db, ref, *, now=None) -> RiderReferral` - saves EXPIRED past the deadline.
  - `delivered_count(db, ref) -> int`.
  - `cancel(db, admin, referred_user_id, reason: str) -> RiderReferral` - commits; 409 `already_paid` / `state_changed`, 422 `reason` empty, 404 `referral_not_found`.

- [ ] **Step 1: Write the failing tests**:

```python
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
```

- [ ] **Step 2: Run** → Expected: the 8 new tests ERROR (`on_approved` missing).

- [ ] **Step 3: Implement** - append to `referral.py` (add `from sqlalchemy import func` and `from sqlalchemy.exc import IntegrityError`; add `from app.models.enums import TripEndReason`; `from app.models.rider import RiderTrip`):

```python
# --- the clock --------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def on_approved(db: Session, rider_user_id: uuid.UUID, *, now: datetime | None = None) -> None:
    """The referred rider was approved: their clock starts, and they get their own code."""

    now = now or _now()
    ref = db.get(RiderReferral, rider_user_id)
    if ref is not None and ref.status == ReferralStatus.WAITING:
        ref.status = ReferralStatus.IN_PROGRESS
        ref.approved_at = now
        ref.deadline = now + timedelta(days=ref.days_allowed)
    ensure_code(db, rider_user_id)
    db.flush()


def delivered_count(db: Session, ref: RiderReferral) -> int:
    if ref.approved_at is None or ref.deadline is None:
        return 0
    return int(
        db.scalar(
            select(func.count(RiderTrip.id)).where(
                RiderTrip.rider_user_id == ref.referred_user_id,
                RiderTrip.end_reason == TripEndReason.DELIVERED,
                RiderTrip.ended_at >= ref.approved_at,
                RiderTrip.ended_at <= ref.deadline,
            )
        )
        or 0
    )


def refresh_status(db: Session, ref: RiderReferral, *, now: datetime | None = None) -> RiderReferral:
    """IN_PROGRESS past its deadline is EXPIRED, saved the first time anyone looks."""

    now = now or _now()
    deadline = _aware(ref.deadline)
    if ref.status == ReferralStatus.IN_PROGRESS and deadline is not None and now > deadline:
        ref.status = ReferralStatus.EXPIRED
        db.flush()
    return ref


def _pay(db: Session, ref: RiderReferral, rider_id: uuid.UUID, kind: RiderBonusKind,
         amount: Decimal, now: datetime) -> bool:
    if amount <= 0:
        return False
    try:
        with db.begin_nested():
            db.add(RiderBonus(rider_user_id=rider_id, kind=kind, amount=amount,
                              referral_id=ref.referred_user_id, earned_at=now))
    except IntegrityError:
        # Already written - by an earlier call or a racing one. The unique
        # (referral, kind) row is the guard; this is the expected outcome.
        return False
    return True


def on_delivered(db: Session, rider_user_id: uuid.UUID, *, now: datetime | None = None) -> bool:
    """A trip of this rider ended DELIVERED: earn the referral if this was the Nth."""

    now = now or _now()
    ref = db.scalar(
        select(RiderReferral).where(RiderReferral.referred_user_id == rider_user_id).with_for_update()
    )
    if ref is None or ref.status != ReferralStatus.IN_PROGRESS:
        return False
    refresh_status(db, ref, now=now)
    if ref.status != ReferralStatus.IN_PROGRESS or not load_config(db).enabled:
        return False
    if delivered_count(db, ref) < ref.deliveries_required:
        return False
    paid_referrer = _pay(db, ref, ref.referrer_user_id, RiderBonusKind.REFERRAL_REFERRER, ref.referrer_amount, now)
    paid_joiner = _pay(db, ref, ref.referred_user_id, RiderBonusKind.REFERRAL_JOINER, ref.joiner_amount, now)
    ref.status = ReferralStatus.EARNED
    ref.earned_at = ref.earned_at or now
    db.flush()
    logger.info("Referral of %s earned (referrer %s)", ref.referred_user_id, ref.referrer_user_id)
    return paid_referrer or paid_joiner


# --- cancelling ---------------------------------------------------------------------


def cancel(db: Session, admin: Any, referred_user_id: uuid.UUID, reason: str) -> RiderReferral:
    reason = " ".join((reason or "").split())[:500]
    if not reason:
        raise _refuse("A reason is required")
    ref = db.scalar(
        select(RiderReferral).where(RiderReferral.referred_user_id == referred_user_id).with_for_update()
    )
    if ref is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "referral_not_found")
    if ref.status in (ReferralStatus.CANCELLED, ReferralStatus.EXPIRED):
        raise HTTPException(status.HTTP_409_CONFLICT, "state_changed")
    bonuses = list(db.scalars(select(RiderBonus).where(RiderBonus.referral_id == ref.referred_user_id)
                              .with_for_update()))
    if any(b.payout_id is not None for b in bonuses):
        raise HTTPException(status.HTTP_409_CONFLICT, "already_paid")
    for bonus in bonuses:
        db.delete(bonus)
    ref.status = ReferralStatus.CANCELLED
    ref.cancelled_at, ref.cancel_reason, ref.cancelled_by_user_id = _now(), reason, admin.id
    db.commit()
    logger.info("Referral of %s cancelled by %s: %s", referred_user_id, admin.id, reason)
    return ref
```

The racing case in `test_earning_twice_pays_once` sets the status back to IN_PROGRESS by hand; `on_delivered` then tries both inserts, both hit the unique constraint inside savepoints, it returns False and leaves two rows.

- [ ] **Step 4: Run** → Expected: `Ran 17 tests ... OK`.

- [ ] **Step 5: Commit** - `git commit -m "feat(fleet): referral clock - start on approval, earn at N, expire on read, admin cancel"`.

---

### Task 5: Bonuses in payouts and earnings

**Files:**
- Modify: `backend/app/services/fleet/payouts.py` (`rider_earnings`, `unpaid_summary`, `pay_rider`)
- Modify: `backend/app/schemas/rider.py` (`Earnings` gains `bonuses`)
- Test: `backend/tests/test_fleet_referral.py`

**Interfaces:**
- Consumes: `RiderBonus`.
- Produces: `rider_earnings(...)["bonuses"] -> list[{"amount": Decimal, "kind": str, "earned_at": datetime}]`; bonuses counted in `today`, `period_total`, day series amounts (not in trip counts), `unpaid`; `unpaid_summary` rows include riders with only bonuses (`trips` = unpaid trip count); `pay_rider` sets `payout_id` on bonuses earned up to `period_to` and includes them in `amount`.

- [ ] **Step 1: Write the failing tests**:

```python
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
```

- [ ] **Step 2: Run** → Expected: both FAIL (unpaid row missing / amount 30).

- [ ] **Step 3: Implement** in `backend/app/services/fleet/payouts.py`:

Add the import `from app.models.rider_referral import RiderBonus`.

In `rider_earnings`, after `rows = ...` (trip rows), add:

```python
    bonus_rows = db.execute(
        select(RiderBonus.earned_at, RiderBonus.amount, RiderBonus.kind).where(
            RiderBonus.rider_user_id == rider_user_id,
            RiderBonus.earned_at >= period_start.astimezone(UTC),
        ).order_by(RiderBonus.earned_at)
    ).all()
    bonus_by_day: dict[str, list[Decimal]] = defaultdict(list)
    for earned_at, amount, _kind in bonus_rows:
        local = (earned_at if earned_at.tzinfo else earned_at.replace(tzinfo=UTC)).astimezone(tz)
        bonus_by_day[local.date().isoformat()].append(Decimal(amount))
```

Change the series loop so a day's amount includes its bonuses (trip count unchanged):

```python
        amounts = by_day.get(day, [])
        extra = bonus_by_day.get(day, [])
        series.append({"date": day, "trips": len(amounts), "amount": sum(amounts + extra, Decimal("0"))})
```

Change `unpaid` to add unpaid bonuses:

```python
    unpaid_bonus = db.scalar(
        select(func.coalesce(func.sum(RiderBonus.amount), 0)).where(
            RiderBonus.rider_user_id == rider_user_id, RiderBonus.payout_id.is_(None)
        )
    )
```

and return `"unpaid": Decimal(unpaid or 0) + Decimal(unpaid_bonus or 0)` and `"bonuses": [{"amount": Decimal(a), "kind": str(k.value if hasattr(k, "value") else k), "earned_at": e} for e, a, k in bonus_rows]`.

Replace `unpaid_summary` with a version that merges trips and bonuses:

```python
def unpaid_summary(db: Session) -> list[dict[str, Any]]:
    trips = {
        r: (int(c), Decimal(a), o)
        for r, c, a, o in db.execute(
            select(RiderTrip.rider_user_id, func.count(RiderTrip.id),
                   func.coalesce(func.sum(RiderTrip.earning_amount), 0), func.min(RiderTrip.ended_at))
            .where(RiderTrip.ended_at.is_not(None), RiderTrip.payout_id.is_(None), RiderTrip.earning_amount > 0)
            .group_by(RiderTrip.rider_user_id)
        ).all()
    }
    bonuses = {
        r: (Decimal(a), o)
        for r, a, o in db.execute(
            select(RiderBonus.rider_user_id, func.coalesce(func.sum(RiderBonus.amount), 0),
                   func.min(RiderBonus.earned_at))
            .where(RiderBonus.payout_id.is_(None))
            .group_by(RiderBonus.rider_user_id)
        ).all()
    }
    ids = set(trips) | set(bonuses)
    if not ids:
        return []
    names = dict(db.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())
    out = []
    for rider_id in ids:
        count, trip_amount, trip_oldest = trips.get(rider_id, (0, Decimal("0"), None))
        bonus_amount, bonus_oldest = bonuses.get(rider_id, (Decimal("0"), None))
        oldest = min((x for x in (trip_oldest, bonus_oldest) if x is not None), default=None)
        out.append({"rider_user_id": rider_id, "full_name": names.get(rider_id, ""), "trips": count,
                    "amount": trip_amount + bonus_amount, "oldest": oldest})
    return sorted(out, key=lambda row: row["full_name"])
```

In `pay_rider`, after `due = list(...)` (trips), add bonuses, change the empty check and the amount, and stamp them:

```python
    due_bonuses = list(
        db.scalars(
            select(RiderBonus)
            .where(RiderBonus.rider_user_id == rider_user_id, RiderBonus.payout_id.is_(None),
                   RiderBonus.earned_at <= period_to)
            .order_by(RiderBonus.earned_at)
            .with_for_update()
        )
    )
    if not due and not due_bonuses:
        raise HTTPException(status.HTTP_409_CONFLICT, "nothing_to_pay")
    starts = [t.ended_at for t in due] + [b.earned_at for b in due_bonuses]
    payout = RiderPayout(
        rider_user_id=rider_user_id,
        period_from=min(starts),
        period_to=period_to,
        amount=sum((Decimal(t.earning_amount) for t in due), Decimal("0"))
        + sum((Decimal(b.amount) for b in due_bonuses), Decimal("0")),
        trips=len(due),
        reference=reference.strip()[:120],
        paid_at=datetime.now(UTC),
        created_by_user_id=admin.id,
    )
```

(remove the old `if not due:` check and old `RiderPayout(...)`), and after `for trip in due: trip.payout_id = payout.id` add `for bonus in due_bonuses: bonus.payout_id = payout.id`.

In `backend/app/schemas/rider.py`, before `class Earnings`, add:

```python
class EarningBonus(BaseModel):
    amount: Decimal
    kind: str
    earned_at: datetime
```

and in `Earnings` add `bonuses: list[EarningBonus] = []`.

- [ ] **Step 4: Run** `tests.test_fleet_referral` (19 OK) and `tests.test_fleet_admin_ops` (payout tests unchanged, OK).

- [ ] **Step 5: Commit** - `git commit -m "feat(fleet): referral bonuses ride the payout - unpaid, earnings and Mark paid include them"`.

---

### Task 6: Hooks and API

**Files:**
- Modify: `backend/app/services/fleet/trips.py` (`_finish`)
- Modify: `backend/app/services/fleet/onboarding/applications.py` (`approve`)
- Modify: `backend/app/schemas/rider_onboarding.py` (`SignupRequest`)
- Modify: `backend/app/api/rider_signup.py` (`signup`)
- Modify: `backend/app/schemas/rider.py` (referral views)
- Modify: `backend/app/services/fleet/referral.py` (views)
- Modify: `backend/app/api/rider.py`, `backend/app/api/admin_riders.py`
- Test: `backend/tests/test_fleet_referral.py`

**Interfaces:**
- Consumes: Tasks 2-5.
- Produces:
  - `referral.rider_view(db, rider_user_id) -> dict` matching `RiderReferralView` (below).
  - `referral.admin_rows(db, status: ReferralStatus | None) -> list[dict]` matching `AdminReferralRow`.
  - HTTP: `POST /api/rider/signup` (`referral_code` optional), `GET /api/rider/referral`, `POST /api/rider/referral/code` `{code}`, `GET /api/admin/riders/referrals?status=`, `GET|PUT /api/admin/riders/settings/referral`, `POST /api/admin/riders/referrals/{referred_user_id}/cancel` `{reason}`.

- [ ] **Step 1: Write the failing tests**:

```python
    # Task 6 ------------------------------------------------------------------

    def test_signup_with_a_bad_code_makes_no_account(self) -> None:
        from app.models.user import User
        from app.services.fleet.onboarding import phone as phone_codes

        number = f"+9197{uuid.uuid4().int % 10**8:08d}"
        with mock.patch.object(phone_codes, "verify_code", return_value=None):
            r = client_for(self.fdb, None).post("/api/rider/signup", json={
                "phone_number": number, "code": "123456", "password": "password123",
                "full_name": "New Rider", "referral_code": "NOPE0000"})
        self.assertEqual((r.status_code, r.json()["detail"]), (422, "referral_unknown"))
        with self.fdb.session() as db:
            self.assertIsNone(db.scalar(select(User).where(User.phone_number == number)))

    def test_signup_with_a_good_code_links_the_riders(self) -> None:
        from app.models.user import User
        from app.services.fleet import referral
        from app.services.fleet.onboarding import phone as phone_codes

        with self.fdb.session() as db:
            a = self._rider(db, name="Priya")
            code = referral.ensure_code(db, a.id)
            db.commit()
        number = f"+9196{uuid.uuid4().int % 10**8:08d}"
        with mock.patch.object(phone_codes, "verify_code", return_value=None):
            r = client_for(self.fdb, None).post("/api/rider/signup", json={
                "phone_number": number, "code": "123456", "password": "password123",
                "full_name": "New Rider", "referral_code": code.lower()})
        self.assertEqual(r.status_code, 201, r.text)
        with self.fdb.session() as db:
            user = db.scalar(select(User).where(User.phone_number == number))
            self.assertEqual(db.get(RiderReferral, user.id).referrer_user_id, a.id)

    def test_rider_views_their_programme(self) -> None:
        with self.fdb.session() as db:
            a, b = self._pair(db, deliveries_required=2)
            self._delivered(db, b.id)
            db.commit()
        mine = client_for(self.fdb, a).get("/api/rider/referral").json()
        self.assertRegex(mine["code"], r"^PRIYA\d{4}$")
        self.assertEqual(mine["terms"]["deliveries_required"], 20)  # today's terms, for new referrals
        self.assertEqual([(x["status"], x["delivered"], x["required"]) for x in mine["referrals"]],
                         [("IN_PROGRESS", 1, 2)])
        self.assertEqual(mine["referrals"][0]["name"], "New")
        theirs = client_for(self.fdb, b).get("/api/rider/referral").json()
        self.assertEqual((theirs["joined_with"]["delivered"], theirs["joined_with"]["required"]), (1, 2))

    def test_a_pending_rider_adds_a_code_later_once(self) -> None:
        from app.services.fleet import referral

        with self.fdb.session() as db:
            a = self._rider(db, name="Priya")
            code = referral.ensure_code(db, a.id)
            b = self._rider(db, name="New", onboarding=RiderOnboarding.PENDING)
            db.commit()
        client = client_for(self.fdb, b)
        self.assertEqual(client.post("/api/rider/referral/code", json={"code": code}).status_code, 200)
        again = client.post("/api/rider/referral/code", json={"code": code})
        self.assertEqual((again.status_code, again.json()["detail"]), (422, "referral_taken"))
        self.assertIsNone(client.get("/api/rider/referral").json()["code"])

    def test_admin_confirmed_delivery_counts(self) -> None:
        """Any DELIVERED end goes through trips._finish, which calls the hook."""

        from app.models.enums import OrderStatus, RiderStatus
        from app.models.order_delivery import OrderDelivery
        from app.services.fleet import trips

        with self.fdb.session() as db:
            _, b = self._pair(db, deliveries_required=1)
            db.get(Rider, b.id).status = RiderStatus.ON_TRIP
            order = self.fdb.make_order(db, status=OrderStatus.OUT_FOR_DELIVERY)
            delivery = self.fdb.make_fleet_delivery(db, order, state="IN_TRANSIT", distance_metres=2000.0)
            db.add(RiderTrip(order_delivery_id=delivery.id, rider_user_id=b.id, accepted_at=datetime.now(UTC),
                             picked_up_at=datetime.now(UTC)))
            db.commit()
            trips.admin_confirm_delivered(db, self.admin, db.get(OrderDelivery, delivery.id), "code locked")
        with self.fdb.session() as db:
            self.assertEqual(db.get(RiderReferral, b.id).status, ReferralStatus.EARNED)

    def test_admin_lists_sets_and_cancels(self) -> None:
        with self.fdb.session() as db:
            _, b = self._pair(db)
            db.commit()
        admin = client_for(self.fdb, self.admin)
        rows = admin.get("/api/admin/riders/referrals").json()
        self.assertIn(str(b.id), [r["referred_user_id"] for r in rows])
        self.assertEqual(admin.get("/api/admin/riders/settings/referral").json()["deliveries_required"], 20)
        r = admin.put("/api/admin/riders/settings/referral", json={
            "enabled": True, "referrer_amount": "600", "joiner_amount": "250",
            "deliveries_required": 25, "days_allowed": 45})
        self.assertEqual(Decimal(r.json()["referrer_amount"]), Decimal("600.00"))
        r = admin.post(f"/api/admin/riders/referrals/{b.id}/cancel", json={"reason": "duplicate person"})
        self.assertEqual((r.status_code, r.json()["status"]), (200, "CANCELLED"))
        owner = client_for(self.fdb, self.owner)
        self.assertEqual(owner.get("/api/admin/riders/referrals").status_code, 403)
```

(If `phone.verify_code`'s module path differs, check `app/api/rider_signup.py` imports - it calls `phone.verify_code(db, number, payload.code)`; patch the same object it calls.)

- [ ] **Step 2: Run** → Expected: the 6 new tests fail (404s / no `referral_code` field / status stays IN_PROGRESS).

- [ ] **Step 3: Implement.**

`backend/app/services/fleet/trips.py` - in `_finish`, after `_free_rider(db, trip.rider_user_id)`:

```python
    if reason == TripEndReason.DELIVERED:
        from app.services.fleet import referral

        # The referral clock (fleet/referral.py): this may be the Nth delivery.
        referral.on_delivered(db, trip.rider_user_id)
```

`backend/app/services/fleet/onboarding/applications.py` - in `approve`, just before `_event(db, app, ApplicationAction.APPROVED, admin)`:

```python
    from app.services.fleet import referral

    # A referred rider's clock starts now; every approved rider gets a code.
    referral.on_approved(db, rider_user_id)
```

`backend/app/schemas/rider_onboarding.py` - `SignupRequest` gains:

```python
    #: Optional: the code of the rider who referred them (`fleet/referral.py`).
    referral_code: str | None = Field(default=None, max_length=24)
```

`backend/app/api/rider_signup.py` - in `signup`, after `applications.start(db, user)` and before `db.commit()`:

```python
    if payload.referral_code and payload.referral_code.strip():
        from app.services.fleet import referral

        # Checked before the commit: a bad code fails the whole sign-up, so
        # nothing is half-made and the rider fixes the code and tries again.
        try:
            referral.accept_code(db, user.id, payload.referral_code)
        except HTTPException:
            db.rollback()
            raise
```

`backend/app/schemas/rider.py` - add:

```python
class ReferralTerms(BaseModel):
    referrer_amount: Decimal
    joiner_amount: Decimal
    deliveries_required: int
    days_allowed: int


class ReferralProgress(BaseModel):
    name: str
    status: str
    delivered: int
    required: int
    deadline: datetime | None
    amount: Decimal


class RiderReferralView(BaseModel):
    code: str | None
    enabled: bool
    terms: ReferralTerms
    earned_total: Decimal
    referrals: list[ReferralProgress]
    joined_with: ReferralProgress | None


class ReferralCodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=24)


class ReferralSettings(BaseModel):
    enabled: bool = True
    referrer_amount: Decimal = Field(default=Decimal("500"), ge=0, le=10000)
    joiner_amount: Decimal = Field(default=Decimal("200"), ge=0, le=10000)
    deliveries_required: int = Field(default=20, ge=1, le=500)
    days_allowed: int = Field(default=30, ge=1, le=365)


class AdminReferralRow(BaseModel):
    referred_user_id: uuid.UUID
    referred_name: str
    referrer_user_id: uuid.UUID
    referrer_name: str
    code: str
    status: str
    delivered: int
    required: int
    deadline: datetime | None
    referrer_amount: Decimal
    joiner_amount: Decimal
    created_at: datetime
    paid: bool


class CancelReferralIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
```

`backend/app/services/fleet/referral.py` - views:

```python
# --- views ----------------------------------------------------------------------------


def _short_name(full_name: str) -> str:
    """First name and last initial: enough to recognise a friend, no more."""

    parts = (full_name or "").split()
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0]}."


def _progress(db: Session, ref: RiderReferral, name: str, amount: Decimal) -> dict[str, Any]:
    refresh_status(db, ref)
    return {
        "name": name,
        "status": ref.status.value,
        "delivered": delivered_count(db, ref),
        "required": ref.deliveries_required,
        "deadline": ref.deadline,
        "amount": amount,
    }


def rider_view(db: Session, rider_user_id: uuid.UUID) -> dict[str, Any]:
    cfg = load_config(db)
    code = ensure_code(db, rider_user_id)
    mine = list(db.scalars(
        select(RiderReferral).where(RiderReferral.referrer_user_id == rider_user_id)
        .order_by(RiderReferral.created_at.desc())
    ))
    names = dict(db.execute(select(User.id, User.full_name).where(
        User.id.in_([r.referred_user_id for r in mine] or [uuid.uuid4()]))).all())
    referrals = [_progress(db, r, _short_name(names.get(r.referred_user_id, "")), r.referrer_amount) for r in mine]
    own = db.get(RiderReferral, rider_user_id)
    joined_with = None
    if own is not None and own.status != ReferralStatus.CANCELLED:
        referrer = db.get(User, own.referrer_user_id)
        joined_with = _progress(db, own, _short_name(referrer.full_name if referrer else ""), own.joiner_amount)
    earned = db.scalar(select(func.coalesce(func.sum(RiderBonus.amount), 0)).where(
        RiderBonus.rider_user_id == rider_user_id))
    db.commit()  # a code made or an expiry saved on this read
    return {
        "code": code,
        "enabled": cfg.enabled,
        "terms": {
            "referrer_amount": cfg.referrer_amount,
            "joiner_amount": cfg.joiner_amount,
            "deliveries_required": cfg.deliveries_required,
            "days_allowed": cfg.days_allowed,
        },
        "earned_total": Decimal(earned or 0),
        "referrals": referrals,
        "joined_with": joined_with,
    }


def admin_rows(db: Session, wanted: ReferralStatus | None = None) -> list[dict[str, Any]]:
    refs = list(db.scalars(select(RiderReferral).order_by(RiderReferral.created_at.desc()).limit(500)))
    ids = {r.referred_user_id for r in refs} | {r.referrer_user_id for r in refs}
    names = dict(db.execute(select(User.id, User.full_name).where(User.id.in_(ids or {uuid.uuid4()}))).all())
    paid = set(db.scalars(select(RiderBonus.referral_id).where(RiderBonus.payout_id.is_not(None))))
    rows = []
    for ref in refs:
        refresh_status(db, ref)
        if wanted is not None and ref.status != wanted:
            continue
        rows.append({
            "referred_user_id": ref.referred_user_id,
            "referred_name": names.get(ref.referred_user_id, ""),
            "referrer_user_id": ref.referrer_user_id,
            "referrer_name": names.get(ref.referrer_user_id, ""),
            "code": ref.code,
            "status": ref.status.value,
            "delivered": delivered_count(db, ref),
            "required": ref.deliveries_required,
            "deadline": ref.deadline,
            "referrer_amount": ref.referrer_amount,
            "joiner_amount": ref.joiner_amount,
            "created_at": ref.created_at,
            "paid": ref.referred_user_id in paid,
        })
    db.commit()
    return rows
```

`backend/app/api/rider.py` - add (import `RiderReferralView, ReferralCodeIn` from `app.schemas.rider`; `RiderUser` is the existing dependency used by `/me` - it must also admit PENDING riders, check how `/rider/application` authenticates and use the same dependency for these two routes if `RiderUser` refuses PENDING):

```python
@router.get("/referral", response_model=RiderReferralView)
def my_referral(user: RiderUser, db: Db) -> RiderReferralView:
    """The rider's code, today's terms, who they referred, and their own joining bonus."""

    from app.services.fleet import referral

    return RiderReferralView(**referral.rider_view(db, user.id))


@router.post("/referral/code", response_model=RiderReferralView)
def add_referral_code(body: ReferralCodeIn, user: RiderUser, db: Db) -> RiderReferralView:
    """A code the rider skipped at sign-up, until they are approved."""

    from app.services.fleet import referral

    referral.accept_code(db, user.id, body.code)
    db.commit()
    return RiderReferralView(**referral.rider_view(db, user.id))
```

`backend/app/api/admin_riders.py` - add (import `AdminReferralRow, CancelReferralIn, ReferralSettings` from `app.schemas.rider`, `ReferralStatus` from `app.models.enums`); place these BEFORE any `/{user_id}` route:

```python
@router.get("/referrals", response_model=list[AdminReferralRow])
def referrals(_: Admin, db: Db, status_filter: ReferralStatus | None = Query(default=None, alias="status")):
    from app.services.fleet import referral

    return [AdminReferralRow(**row) for row in referral.admin_rows(db, status_filter)]


@router.get("/settings/referral", response_model=ReferralSettings)
def get_referral_settings(_: Admin, db: Db) -> ReferralSettings:
    from app.services.fleet import referral

    return ReferralSettings(**referral.config_value(referral.load_config(db)))


@router.put("/settings/referral", response_model=ReferralSettings)
def put_referral_settings(body: ReferralSettings, admin: Admin, db: Db) -> ReferralSettings:
    from app.services.fleet import referral

    cfg = referral.save_config(db, admin, body.model_dump(mode="json"))
    return ReferralSettings(**referral.config_value(cfg))


@router.post("/referrals/{referred_user_id}/cancel", response_model=AdminReferralRow)
def cancel_referral(referred_user_id: uuid.UUID, body: CancelReferralIn, admin: Admin, db: Db) -> AdminReferralRow:
    from app.services.fleet import referral

    referral.cancel(db, admin, referred_user_id, body.reason)
    row = next(r for r in referral.admin_rows(db) if r["referred_user_id"] == referred_user_id)
    return AdminReferralRow(**row)
```

- [ ] **Step 4: Run** `tests.test_fleet_referral` (25 OK); then the whole fleet set: `./.venv/Scripts/python.exe -m unittest discover -s tests -p "test_fleet*"` and `-p "test_rider*"` → OK; `compileall -q app alembic` silent.

- [ ] **Step 5: Commit** - `git commit -m "feat(fleet): referral hooks on approval and delivery; rider and admin referral API; code at sign-up"`.

---

### Task 7: Admin Referrals tab

**Files:**
- Modify: `frontend-admin/src/types/app.ts`, `frontend-admin/src/services/api.ts`
- Create: `frontend-admin/src/services/riderReferral.ts`, `frontend-admin/src/services/riderReferral.test.ts`
- Create: `frontend-admin/src/components/riders/ReferralsTab.tsx`
- Modify: `frontend-admin/src/pages/RidersPage.tsx`

**Interfaces:**
- Consumes: the admin endpoints of Task 6.
- Produces: `ReferralSettings`, `AdminReferralRow` types; `api.getReferralSettings`, `api.saveReferralSettings`, `api.listReferrals(token, status?)`, `api.cancelReferral(token, id, reason)`; helpers `referralSettingsError(draft) -> string | null`, `referralExample(draft) -> string`, `progressLabel(row) -> string`.

- [ ] **Step 1: Write the failing test** - `frontend-admin/src/services/riderReferral.test.ts`:

```ts
import { describe, expect, it } from 'vitest';

import { progressLabel, referralExample, referralSettingsError, type ReferralDraft } from './riderReferral';

const draft = (): ReferralDraft => ({
  enabled: true,
  referrer_amount: '500',
  joiner_amount: '200',
  deliveries_required: '20',
  days_allowed: '30',
});

describe('referral settings form', () => {
  it('accepts the defaults', () => {
    expect(referralSettingsError(draft())).toBeNull();
  });
  it('refuses out-of-range numbers', () => {
    expect(referralSettingsError({ ...draft(), referrer_amount: '-1' })).toBeTruthy();
    expect(referralSettingsError({ ...draft(), joiner_amount: 'abc' })).toBeTruthy();
    expect(referralSettingsError({ ...draft(), deliveries_required: '0' })).toBeTruthy();
    expect(referralSettingsError({ ...draft(), days_allowed: '366' })).toBeTruthy();
    expect(referralSettingsError({ ...draft(), deliveries_required: '2.5' })).toBeTruthy();
  });
  it('says the deal in one line', () => {
    expect(referralExample(draft())).toBe(
      'A new rider who makes 20 deliveries within 30 days of approval earns their referrer ₹500 and themselves ₹200.',
    );
  });
});

describe('progressLabel', () => {
  it('reads progress and what is left', () => {
    const now = new Date('2026-10-10T00:00:00Z');
    expect(
      progressLabel({ status: 'IN_PROGRESS', delivered: 12, required: 20, deadline: '2026-10-28T00:00:00Z' }, now),
    ).toBe('12/20 deliveries · 18 days left');
    expect(progressLabel({ status: 'WAITING', delivered: 0, required: 20, deadline: null }, now)).toBe(
      'Waiting for approval',
    );
    expect(progressLabel({ status: 'EARNED', delivered: 20, required: 20, deadline: null }, now)).toBe('20/20 deliveries');
  });
});
```

- [ ] **Step 2: Run** `cd frontend-admin && npx vitest run src/services/riderReferral.test.ts` → FAIL (module not found).

- [ ] **Step 3: Implement.**

`frontend-admin/src/types/app.ts` (append):

```ts
/** Rider referral programme settings (`fleet/referral.py`). Amounts as decimal strings. */
export interface ReferralSettings {
  enabled: boolean;
  referrer_amount: string;
  joiner_amount: string;
  deliveries_required: number;
  days_allowed: number;
}

export type ReferralStatus = 'WAITING' | 'IN_PROGRESS' | 'EARNED' | 'EXPIRED' | 'CANCELLED';

export interface AdminReferralRow {
  referred_user_id: string;
  referred_name: string;
  referrer_user_id: string;
  referrer_name: string;
  code: string;
  status: ReferralStatus;
  delivered: number;
  required: number;
  deadline: string | null;
  referrer_amount: string;
  joiner_amount: string;
  created_at: string;
  paid: boolean;
}
```

`frontend-admin/src/services/api.ts` - add `AdminReferralRow, ReferralSettings, ReferralStatus` to the type import and, beside `saveFleetConfig`:

```ts
  getReferralSettings(token: string): Promise<ReferralSettings> {
    return request<ReferralSettings>('/admin/riders/settings/referral', { token });
  },
  saveReferralSettings(token: string, body: ReferralSettings): Promise<ReferralSettings> {
    return request<ReferralSettings>('/admin/riders/settings/referral', { method: 'PUT', token, body });
  },
  listReferrals(token: string, status?: ReferralStatus): Promise<AdminReferralRow[]> {
    const query = status ? `?status=${status}` : '';
    return request<AdminReferralRow[]>(`/admin/riders/referrals${query}`, { token });
  },
  cancelReferral(token: string, referredUserId: string, reason: string): Promise<AdminReferralRow> {
    return request<AdminReferralRow>(`/admin/riders/referrals/${referredUserId}/cancel`, {
      method: 'POST',
      token,
      body: { reason },
    });
  },
```

`frontend-admin/src/services/riderReferral.ts`:

```ts
/**
 * The Referrals tab's rules, out of the component so they can be tested.
 * The server owns them (`fleet/referral.py validate_config`); these repeat
 * them so a mistake shows beside the field instead of as a 422 after Save.
 */

import type { ReferralSettings, ReferralStatus } from '../types/app';

export interface ReferralDraft {
  enabled: boolean;
  referrer_amount: string;
  joiner_amount: string;
  deliveries_required: string;
  days_allowed: string;
}

export function draftFrom(s: ReferralSettings): ReferralDraft {
  return {
    enabled: s.enabled,
    referrer_amount: String(Number(s.referrer_amount)),
    joiner_amount: String(Number(s.joiner_amount)),
    deliveries_required: String(s.deliveries_required),
    days_allowed: String(s.days_allowed),
  };
}

export function settingsFrom(d: ReferralDraft): ReferralSettings {
  return {
    enabled: d.enabled,
    referrer_amount: d.referrer_amount.trim(),
    joiner_amount: d.joiner_amount.trim(),
    deliveries_required: Number(d.deliveries_required),
    days_allowed: Number(d.days_allowed),
  };
}

const num = (v: string): number | null => (v.trim() === '' || !Number.isFinite(Number(v)) ? null : Number(v));

export function referralSettingsError(d: ReferralDraft): string | null {
  const a = num(d.referrer_amount);
  const b = num(d.joiner_amount);
  if (a === null || b === null || a < 0 || b < 0 || a > 10000 || b > 10000) {
    return 'Bonus amounts must be between ₹0 and ₹10,000.';
  }
  const n = num(d.deliveries_required);
  if (n === null || !Number.isInteger(n) || n < 1 || n > 500) return 'Deliveries needed must be a whole number from 1 to 500.';
  const days = num(d.days_allowed);
  if (days === null || !Number.isInteger(days) || days < 1 || days > 365) return 'Days allowed must be a whole number from 1 to 365.';
  return null;
}

export function referralExample(d: ReferralDraft): string {
  return `A new rider who makes ${d.deliveries_required} deliveries within ${d.days_allowed} days of approval earns their referrer ₹${d.referrer_amount} and themselves ₹${d.joiner_amount}.`;
}

export function progressLabel(
  row: { status: ReferralStatus; delivered: number; required: number; deadline: string | null },
  now: Date = new Date(),
): string {
  if (row.status === 'WAITING') return 'Waiting for approval';
  const done = `${Math.min(row.delivered, row.required)}/${row.required} deliveries`;
  if (row.status !== 'IN_PROGRESS' || !row.deadline) return done;
  const days = Math.max(0, Math.ceil((new Date(row.deadline).getTime() - now.getTime()) / 86_400_000));
  return `${done} · ${days} days left`;
}

export const STATUS_LABEL: Record<ReferralStatus, string> = {
  WAITING: 'Waiting',
  IN_PROGRESS: 'In progress',
  EARNED: 'Earned',
  EXPIRED: 'Expired',
  CANCELLED: 'Cancelled',
};
```

`frontend-admin/src/components/riders/ReferralsTab.tsx` - follow `SettingsTab`/`PayoutsTab` in `RidersPage.tsx` for markup and classes (`admin-surface`, `form-grid`, `field`, `ResponsiveTable`, `StatusPill`, `ConfirmDialog`, `Modal`):

```tsx
import { Gift, Save, XCircle } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

import { EmptyPanel } from '../EmptyPanel';
import { Modal } from '../Modal';
import { ResponsiveTable, type TableColumn } from '../ResponsiveTable';
import { StatusPill } from '../StatusPill';
import { useMoney } from '../../hooks/useMoney';
import { ApiError, api } from '../../services/api';
import {
  STATUS_LABEL,
  draftFrom,
  progressLabel,
  referralExample,
  referralSettingsError,
  settingsFrom,
  type ReferralDraft,
} from '../../services/riderReferral';
import type { AdminReferralRow, ReferralStatus, ToastMessage } from '../../types/app';

interface Props {
  token: string;
  onToast: (title: string, description: string, tone?: ToastMessage['tone']) => void;
}

const FILTERS: Array<ReferralStatus | 'ALL'> = ['ALL', 'IN_PROGRESS', 'WAITING', 'EARNED', 'EXPIRED', 'CANCELLED'];

export function ReferralsTab({ token, onToast }: Props) {
  const money = useMoney();
  const [saved, setSaved] = useState<ReferralDraft | null>(null);
  const [draft, setDraft] = useState<ReferralDraft | null>(null);
  const [rows, setRows] = useState<AdminReferralRow[] | null>(null);
  const [filter, setFilter] = useState<ReferralStatus | 'ALL'>('ALL');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cancelling, setCancelling] = useState<AdminReferralRow | null>(null);
  const [reason, setReason] = useState('');

  useEffect(() => {
    api
      .getReferralSettings(token)
      .then((s) => {
        setSaved(draftFrom(s));
        setDraft(draftFrom(s));
      })
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Please try again.'));
  }, [token]);

  const load = useCallback(() => {
    api
      .listReferrals(token, filter === 'ALL' ? undefined : filter)
      .then(setRows)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : 'Please try again.'));
  }, [token, filter]);
  useEffect(load, [load]);

  async function save() {
    if (!draft || referralSettingsError(draft)) return;
    setBusy(true);
    try {
      const next = draftFrom(await api.saveReferralSettings(token, settingsFrom(draft)));
      setSaved(next);
      setDraft(next);
      onToast('Referral settings saved', 'They apply to codes accepted from now on.', 'success');
    } catch (e: unknown) {
      onToast('Could not save', e instanceof ApiError ? e.message : 'Please try again.', 'error');
    } finally {
      setBusy(false);
    }
  }

  async function confirmCancel() {
    if (!cancelling || !reason.trim()) return;
    setBusy(true);
    try {
      await api.cancelReferral(token, cancelling.referred_user_id, reason.trim());
      onToast('Referral cancelled', `${cancelling.referred_name} no longer earns ${cancelling.referrer_name} a bonus.`, 'success');
      setCancelling(null);
      setReason('');
      load();
    } catch (e: unknown) {
      onToast('Could not cancel', e instanceof ApiError ? e.message : 'Please try again.', 'error');
    } finally {
      setBusy(false);
    }
  }

  if (error) {
    return (
      <section className="admin-surface">
        <EmptyPanel description={error} title="Referrals didn't load" />
      </section>
    );
  }

  const formError = draft ? referralSettingsError(draft) : null;
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  const set = (key: keyof ReferralDraft) => (e: React.ChangeEvent<HTMLInputElement>) =>
    draft && setDraft({ ...draft, [key]: key === 'enabled' ? e.target.checked : e.target.value });

  const columns: Array<TableColumn<AdminReferralRow>> = [
    { id: 'new', header: 'New rider', render: (r) => <strong>{r.referred_name}</strong>, mobileLabel: 'New rider', hideOnMobile: true },
    { id: 'by', header: 'Referred by', render: (r) => `${r.referrer_name} (${r.code})`, mobileLabel: 'Referred by' },
    { id: 'progress', header: 'Progress', render: (r) => progressLabel(r), mobileLabel: 'Progress' },
    {
      id: 'bonus',
      header: 'Bonus',
      render: (r) => `${money.format(Number(r.referrer_amount))} + ${money.format(Number(r.joiner_amount))}${r.paid ? ' · paid' : ''}`,
      mobileLabel: 'Bonus',
    },
    { id: 'status', header: 'Status', render: (r) => <StatusPill status={r.status} label={STATUS_LABEL[r.status]} />, mobileLabel: 'Status' },
  ];

  return (
    <>
      <section className="admin-surface">
        <div className="admin-surface__header">
          <div>
            <span className="eyebrow">Refer &amp; earn</span>
            <h2>Rider referral programme</h2>
            <p className="hint-text">{draft ? referralExample(draft) : 'Loading…'}</p>
          </div>
        </div>
        {draft ? (
          <>
            <div className="form-grid">
              <label className="field">
                <span>Programme on</span>
                <input checked={draft.enabled} onChange={set('enabled')} type="checkbox" />
                <small>Off: no new codes are accepted and nothing new is earned. Earned bonuses still pay.</small>
              </label>
              <label className="field">
                <span>Referrer gets (₹)</span>
                <input inputMode="decimal" min={0} onChange={set('referrer_amount')} type="number" value={draft.referrer_amount} />
              </label>
              <label className="field">
                <span>New rider gets (₹)</span>
                <input inputMode="decimal" min={0} onChange={set('joiner_amount')} type="number" value={draft.joiner_amount} />
              </label>
              <label className="field">
                <span>Deliveries needed</span>
                <input min={1} onChange={set('deliveries_required')} type="number" value={draft.deliveries_required} />
              </label>
              <label className="field">
                <span>Days allowed after approval</span>
                <input min={1} onChange={set('days_allowed')} type="number" value={draft.days_allowed} />
              </label>
            </div>
            {formError ? <p role="alert">{formError}</p> : null}
            <div className="modal-actions">
              <button className="primary-button" disabled={!dirty || Boolean(formError) || busy} onClick={() => void save()} type="button">
                <Save size={15} /> {busy ? 'Saving…' : 'Save'}
              </button>
            </div>
          </>
        ) : null}
      </section>

      <section className="admin-surface">
        <div className="admin-surface__header">
          <div>
            <span className="eyebrow">Referrals</span>
            <h2>Who referred whom</h2>
          </div>
          <select aria-label="Status" onChange={(e) => setFilter(e.target.value as ReferralStatus | 'ALL')} value={filter}>
            {FILTERS.map((f) => (
              <option key={f} value={f}>
                {f === 'ALL' ? 'All' : STATUS_LABEL[f]}
              </option>
            ))}
          </select>
        </div>
        <ResponsiveTable
          actions={[
            {
              id: 'cancel',
              label: 'Cancel',
              icon: XCircle,
              onClick: (r: AdminReferralRow) => setCancelling(r),
              tone: 'danger' as const,
              hidden: (r: AdminReferralRow) => r.paid || r.status === 'CANCELLED' || r.status === 'EXPIRED',
            },
          ]}
          columns={columns}
          emptyDescription="When a new rider signs up with a code, they show up here."
          emptyTitle="No referrals yet"
          keyExtractor={(r) => r.referred_user_id}
          loading={rows === null}
          mobileStatus={(r) => <StatusPill status={r.status} label={STATUS_LABEL[r.status]} />}
          mobileSubtitle={(r) => progressLabel(r)}
          mobileTitle={(r) => r.referred_name}
          onRetry={load}
          rows={rows ?? []}
        />
      </section>

      {cancelling ? (
        <Modal busy={busy} className="modal-card--compact" labelledBy="cancel-ref-title" onClose={() => setCancelling(null)}>
          <div className="panel__header modal-card__header">
            <div>
              <span className="eyebrow">
                <Gift size={14} /> Referral
              </span>
              <h2 id="cancel-ref-title">Cancel {cancelling.referred_name}&rsquo;s referral?</h2>
              <p className="hint-text">Nobody is paid for it. This cannot be undone.</p>
            </div>
          </div>
          <div className="form-grid modal-card__body">
            <label className="field form-grid__wide">
              <span>Reason</span>
              <input autoFocus onChange={(e) => setReason(e.target.value)} value={reason} />
            </label>
            <div className="form-grid__wide modal-actions">
              <button className="secondary-button" disabled={busy} onClick={() => setCancelling(null)} type="button">
                Keep it
              </button>
              <button className="danger-button" disabled={busy || !reason.trim()} onClick={() => void confirmCancel()} type="button">
                Cancel referral
              </button>
            </div>
          </div>
        </Modal>
      ) : null}
    </>
  );
}
```

Before writing it, open `src/components/ResponsiveTable.tsx` and `src/components/StatusPill.tsx` and adapt the props used above to their real signatures (`actions[].hidden`, `tone: 'danger'`, `StatusPill`'s `label` prop, the `danger-button` class) - if a prop does not exist, use the closest existing one (e.g. filter rows for the action, or render the label text as `StatusPill status`) rather than adding a feature to the shared component.

`frontend-admin/src/pages/RidersPage.tsx`: `type Tab = 'applications' | 'map' | 'roster' | 'settings' | 'payouts' | 'referrals';`, add `{ key: 'referrals', label: 'Referrals', icon: Gift }` to `TABS` after payouts, import `Gift` from lucide and `ReferralsTab` from `../components/riders/ReferralsTab`, render `{tab === 'referrals' ? <ReferralsTab onToast={onToast} token={token} /> : null}`. Check `tabFromAddress` accepts the new key (it reads `?tab=`).

- [ ] **Step 4: Run** `npx vitest run` (all pass), `npm run build` (OK), `npx eslint src/components/riders/ReferralsTab.tsx src/services/riderReferral.ts` (no new errors).

- [ ] **Step 5: Commit** - `git commit -m "feat(admin): Referrals tab - programme settings, who referred whom, cancel"`.

---

### Task 8: Rider app - Refer & earn

**Files:**
- Modify: `rider/src/types/api.ts`, `rider/src/services/rider.ts`, `rider/src/services/http.ts`
- Create: `rider/src/utils/referral.ts`, `rider/src/utils/referral.test.ts`
- Create: `rider/src/i18n/strings/referral.ts`; modify `rider/src/i18n/strings/index.ts`
- Create: `rider/src/screens/profile/ReferralScreen.tsx`, `rider/src/components/JoiningBonusCard.tsx`
- Modify: `rider/src/navigation/types.ts`, `rider/src/navigation/RootNavigator.tsx`, `rider/src/screens/profile/ProfileScreen.tsx`, `rider/src/screens/home/HomeScreen.tsx`, `rider/src/screens/earnings/EarningsScreen.tsx`, `rider/src/screens/signup/SignupAccountScreen.tsx`, `rider/src/screens/onboarding/OnboardingHomeScreen.tsx`

**Interfaces:**
- Consumes: `GET /rider/referral`, `POST /rider/referral/code`, `referral_code` on sign-up, `Earnings.bonuses`.
- Produces: `RiderReferral`, `ReferralProgress` types; `api.referral()`, `api.addReferralCode(code)`; `signup({..., referral_code?})`; helpers `daysLeft(deadline, now)`, `progressFraction(p)`, `shareMessage(code, terms, t)`.

- [ ] **Step 1: Write the failing test** - `rider/src/utils/referral.test.ts`:

```ts
import { daysLeft, normaliseCode, progressFraction, shareMessage } from './referral';

describe('referral helpers', () => {
  const now = new Date('2026-10-10T00:00:00Z');

  it('counts whole days left, never below zero', () => {
    expect(daysLeft('2026-10-28T00:00:00Z', now)).toBe(18);
    expect(daysLeft('2026-10-10T05:00:00Z', now)).toBe(1);
    expect(daysLeft('2026-10-01T00:00:00Z', now)).toBe(0);
    expect(daysLeft(null, now)).toBeNull();
  });

  it('fills the bar by deliveries, capped at full', () => {
    expect(progressFraction({ delivered: 5, required: 20 })).toBe(0.25);
    expect(progressFraction({ delivered: 25, required: 20 })).toBe(1);
    expect(progressFraction({ delivered: 0, required: 0 })).toBe(0);
  });

  it('cleans what the rider typed the way the server does', () => {
    expect(normaliseCode('  priya 4821 ')).toBe('PRIYA4821');
  });

  it('builds the share message from the terms', () => {
    const t = (key: string, vars?: Record<string, string | number>) => `${key}:${JSON.stringify(vars)}`;
    expect(shareMessage('PRIYA4821', { joiner_amount: '200.00', deliveries_required: 20, days_allowed: 30 }, t)).toBe(
      'referral.shareMessage:{"code":"PRIYA4821","amount":"₹200","n":20,"days":30}',
    );
  });
});
```

- [ ] **Step 2: Run** `cd rider && npx jest src/utils/referral.test.ts` → FAIL (module not found).

- [ ] **Step 3: Implement.**

`rider/src/utils/referral.ts`:

```ts
/**
 * Refer & earn, the parts with no screen (backend `fleet/referral.py`).
 */

import { rupees } from './format';

export function daysLeft(deadline: string | null, now: Date = new Date()): number | null {
  if (!deadline) return null;
  return Math.max(0, Math.ceil((new Date(deadline).getTime() - now.getTime()) / 86_400_000));
}

export function progressFraction(p: { delivered: number; required: number }): number {
  if (p.required <= 0) return 0;
  return Math.min(1, p.delivered / p.required);
}

/** As the server stores it: uppercase, no spaces. */
export function normaliseCode(code: string): string {
  return code.replace(/\s+/g, '').toUpperCase();
}

type Translate = (key: string, vars?: Record<string, string | number>) => string;

export function shareMessage(
  code: string,
  terms: { joiner_amount: string; deliveries_required: number; days_allowed: number },
  t: Translate,
): string {
  return t('referral.shareMessage', {
    code,
    amount: rupees(terms.joiner_amount),
    n: terms.deliveries_required,
    days: terms.days_allowed,
  });
}
```

`rider/src/i18n/strings/referral.ts` (follow the shape of `money.ts`: `const en = {...} as const; const hi: Translations<typeof en> = {...}; const gu = ...; export default { en, hi, gu };` - import `Translations` the way `money.ts` does):

```ts
const en = {
  'referral.title': 'Refer & earn',
  'referral.lead': 'Bring a friend to ride with Rydorgo. When they make {n} deliveries within {days} days, you get {referrer} and they get {joiner}.',
  'referral.yourCode': 'YOUR CODE',
  'referral.share': 'Share code',
  'referral.shareMessage': 'Join me on Rydorgo as a delivery partner! Sign up with my code {code} and get {amount} after your first {n} deliveries (within {days} days).',
  'referral.how1': 'Share your code with a friend',
  'referral.how2': 'They sign up and enter it',
  'referral.how3': '{n} deliveries in {days} days - you both get paid',
  'referral.earned': 'Earned from referrals',
  'referral.yours': 'YOUR REFERRALS',
  'referral.none': 'No referrals yet. Share your code to start.',
  'referral.progress': '{done}/{n} deliveries',
  'referral.daysLeft': '{days} days left',
  'referral.status.WAITING': 'Waiting for approval',
  'referral.status.IN_PROGRESS': 'In progress',
  'referral.status.EARNED': 'Earned',
  'referral.status.EXPIRED': 'Expired',
  'referral.status.CANCELLED': 'Cancelled',
  'referral.off': 'Referrals are paused right now.',
  'referral.joinTitle': 'Joining bonus {amount}',
  'referral.joinBody': '{done}/{n} deliveries - {days} days left',
  'referral.joinEarned': 'Joining bonus earned! It comes with your next payout.',
  'referral.codeLabel': 'Referral code (optional)',
  'referral.haveCode': 'Have a referral code?',
  'referral.add': 'Add code',
  'referral.added': 'Code added',
  'referral.bonus': 'Referral bonus',
  'referral.errUnknown': 'That code does not exist. Check it and try again.',
  'referral.errSelf': 'You cannot use your own code.',
  'referral.errInactive': 'That rider cannot refer anyone right now.',
  'referral.errTaken': 'You have already used a referral code.',
  'referral.errClosed': 'A referral code can no longer be added.',
} as const;
```

with `hi` and `gu` objects carrying every key (keep `{placeholders}` exactly; Hindi/Gujarati sentences in the same register as `money.ts`, terms per `i18n/GLOSSARY.md`; `Rydorgo` stays in Latin letters). Add `referral` to the imports and the `areas` array in `strings/index.ts` and to the area list in its comment.

`rider/src/services/http.ts` - add to `SENTENCES`:

```ts
  referral_unknown: 'referral.errUnknown',
  referral_self: 'referral.errSelf',
  referral_inactive: 'referral.errInactive',
  referral_taken: 'referral.errTaken',
  referral_closed: 'referral.errClosed',
```

`rider/src/types/api.ts` (append):

```ts
export type ReferralStatus = 'WAITING' | 'IN_PROGRESS' | 'EARNED' | 'EXPIRED' | 'CANCELLED';

export type ReferralProgress = {
  name: string;
  status: ReferralStatus;
  delivered: number;
  required: number;
  deadline: string | null;
  amount: string;
};

export type RiderReferral = {
  code: string | null;
  enabled: boolean;
  terms: { referrer_amount: string; joiner_amount: string; deliveries_required: number; days_allowed: number };
  earned_total: string;
  referrals: ReferralProgress[];
  joined_with: ReferralProgress | null;
};
```

and in `Earnings` add `bonuses?: { amount: string; kind: string; earned_at: string }[];`.

`rider/src/services/rider.ts`: `signup` body gains `referral_code?: string;`; in the authed API object add:

```ts
  referral: () => request<RiderReferral>('/rider/referral', { token }),
  addReferralCode: (code: string) =>
    request<RiderReferral>('/rider/referral/code', { method: 'POST', body: { code }, token }),
```

(import `RiderReferral`).

`rider/src/navigation/types.ts`: add `Referral: undefined;` to `RootStackParamList`. `RootNavigator.tsx`: import `ReferralScreen`, add `ReferralScreen: withBoundary(ReferralScreen)` to `Bounded`, and `<Stack.Screen name="Referral" component={Bounded.ReferralScreen} />` beside `TripDetail`.

`rider/src/screens/profile/ReferralScreen.tsx` - built from existing parts (`Screen`, `IconButton`, `Card`, `AppText`, `Button`, `Pill`, `Illustration`), all strings via `t`:

```tsx
import React, { useCallback, useState } from 'react';
import { Share, StyleSheet, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';
import Animated, { FadeInDown } from 'react-native-reanimated';

import { Illustration } from '@components/illustrations/Illustration';
import { AppText } from '@components/ui/AppText';
import { Button } from '@components/ui/Button';
import { Card } from '@components/ui/Card';
import { IconButton } from '@components/ui/IconButton';
import { Pill } from '@components/ui/Pill';
import { Screen } from '@components/ui/Screen';
import { useI18n } from '@/i18n';
import { useNav } from '@navigation/types';
import { useApi } from '@/store/SessionProvider';
import type { ReferralProgress, RiderReferral } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { motion, radius, space } from '@theme/tokens';
import { rupees } from '@utils/format';
import { daysLeft, progressFraction, shareMessage } from '@utils/referral';

const TONE: Record<ReferralProgress['status'], 'success' | 'warning' | 'muted' | 'danger'> = {
  WAITING: 'muted',
  IN_PROGRESS: 'warning',
  EARNED: 'success',
  EXPIRED: 'muted',
  CANCELLED: 'danger',
};

export function ReferralScreen() {
  const nav = useNav();
  const api = useApi();
  const { t } = useI18n();
  const { colors } = useTheme();
  const [data, setData] = useState<RiderReferral | null>(null);
  const [error, setError] = useState<string | null>(null);

  useFocusEffect(
    useCallback(() => {
      api
        .referral()
        .then(next => {
          setData(next);
          setError(null);
        })
        .catch((e: Error) => setError(e.message));
    }, [api]),
  );

  const terms = data?.terms;
  const share = () => {
    if (!data?.code || !terms) return;
    void Share.share({ message: shareMessage(data.code, terms, t) });
  };

  return (
    <Screen scroll contentStyle={styles.content}>
      <View style={styles.header}>
        <IconButton icon="chevron-back" label={t('common.back')} onPress={() => nav.goBack()} />
        <AppText variant="heading">{t('referral.title')}</AppText>
      </View>

      <Illustration name="approved" width={220} style={styles.center} />

      {error ? (
        <AppText tone="danger" align="center">
          {error}
        </AppText>
      ) : null}

      {data && terms ? (
        <Animated.View entering={FadeInDown.duration(motion.base)} style={styles.gap}>
          <AppText tone="muted" align="center">
            {t('referral.lead', {
              n: terms.deliveries_required,
              days: terms.days_allowed,
              referrer: rupees(terms.referrer_amount),
              joiner: rupees(terms.joiner_amount),
            })}
          </AppText>
          {!data.enabled ? (
            <AppText tone="warning" align="center">
              {t('referral.off')}
            </AppText>
          ) : null}

          {data.code ? (
            <Card style={styles.codeCard}>
              <AppText variant="micro" tone="muted" align="center">
                {t('referral.yourCode')}
              </AppText>
              <AppText variant="display" align="center" selectable accessibilityLabel={data.code.split('').join(' ')}>
                {data.code}
              </AppText>
              <Button label={t('referral.share')} icon="share-social" onPress={share} disabled={!data.enabled} />
            </Card>
          ) : null}

          <Card style={styles.gapSm}>
            {(['referral.how1', 'referral.how2', 'referral.how3'] as const).map((key, i) => (
              <View key={key} style={styles.howRow}>
                <View style={[styles.step, { backgroundColor: colors.primarySoft }]}>
                  <AppText variant="label" tone="primary">
                    {i + 1}
                  </AppText>
                </View>
                <AppText style={styles.flex}>{t(key, { n: terms.deliveries_required, days: terms.days_allowed })}</AppText>
              </View>
            ))}
          </Card>

          <Card style={styles.row}>
            <AppText style={styles.flex}>{t('referral.earned')}</AppText>
            <AppText variant="heading" tone="success">
              {rupees(data.earned_total)}
            </AppText>
          </Card>

          <AppText variant="micro" tone="muted">
            {t('referral.yours')}
          </AppText>
          {data.referrals.length === 0 ? (
            <AppText tone="muted">{t('referral.none')}</AppText>
          ) : (
            data.referrals.map((r, i) => (
              <Card key={`${r.name}-${i}`} style={styles.gapSm}>
                <View style={styles.row}>
                  <AppText variant="bodyStrong" style={styles.flex}>
                    {r.name}
                  </AppText>
                  <Pill label={t(`referral.status.${r.status}`)} tone={TONE[r.status]} />
                </View>
                <View style={[styles.track, { backgroundColor: colors.border }]}>
                  <View style={[styles.bar, { width: `${progressFraction(r) * 100}%`, backgroundColor: colors.primary }]} />
                </View>
                <AppText variant="caption" tone="muted">
                  {t('referral.progress', { done: Math.min(r.delivered, r.required), n: r.required })}
                  {r.status === 'IN_PROGRESS' && daysLeft(r.deadline) !== null
                    ? ` · ${t('referral.daysLeft', { days: daysLeft(r.deadline) ?? 0 })}`
                    : ''}
                  {` · ${rupees(r.amount)}`}
                </AppText>
              </Card>
            ))
          )}
        </Animated.View>
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { gap: space.lg },
  header: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  center: { alignSelf: 'center' },
  gap: { gap: space.md },
  gapSm: { gap: space.sm },
  codeCard: { gap: space.md, paddingVertical: space.xl },
  howRow: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  step: { width: 28, height: 28, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  row: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  flex: { flex: 1 },
  track: { height: 6, borderRadius: radius.pill ?? 3, overflow: 'hidden' },
  bar: { height: 6 },
});
```

Before writing, open `Pill.tsx`, `Button.tsx` and `AppText.tsx` and match the real prop names (`tone` values, `icon` names, `selectable`, `variant`s) - adjust the code above to them; check `radius` has a `pill` key or use a number. `t` with a dynamic key: cast as the codebase does elsewhere (e.g. `t(\`referral.status.${r.status}\` as Key)` importing `Key` from `@/i18n`).

`rider/src/components/JoiningBonusCard.tsx`:

```tsx
import React, { useCallback, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { useFocusEffect } from '@react-navigation/native';

import { AppText } from '@components/ui/AppText';
import { Card } from '@components/ui/Card';
import { Icon } from '@components/ui/Icon';
import { useI18n } from '@/i18n';
import { useApi } from '@/store/SessionProvider';
import type { ReferralProgress } from '@/types/api';
import { useTheme } from '@theme/ThemeProvider';
import { space } from '@theme/tokens';
import { rupees } from '@utils/format';
import { daysLeft, progressFraction } from '@utils/referral';

/**
 * The rider's own joining bonus while they are working towards it, and once
 * when it is earned. Nothing at all for a rider who joined without a code.
 */
export function JoiningBonusCard() {
  const api = useApi();
  const { t } = useI18n();
  const { colors } = useTheme();
  const [mine, setMine] = useState<ReferralProgress | null>(null);

  useFocusEffect(
    useCallback(() => {
      api
        .referral()
        .then(r => setMine(r.joined_with))
        .catch(() => undefined);
    }, [api]),
  );

  if (!mine || (mine.status !== 'IN_PROGRESS' && mine.status !== 'EARNED')) return null;
  const earned = mine.status === 'EARNED';
  return (
    <Card tone="alt" style={styles.card}>
      <View style={[styles.badge, { backgroundColor: earned ? colors.successSoft : colors.primarySoft }]}>
        <Icon name="gift-outline" size={18} color={earned ? colors.success : colors.primary} />
      </View>
      <View style={styles.flex}>
        <AppText variant="bodyStrong">{t('referral.joinTitle', { amount: rupees(mine.amount) })}</AppText>
        <AppText variant="caption" tone={earned ? 'success' : 'muted'}>
          {earned
            ? t('referral.joinEarned')
            : t('referral.joinBody', { done: Math.min(mine.delivered, mine.required), n: mine.required, days: daysLeft(mine.deadline) ?? 0 })}
        </AppText>
        {!earned ? (
          <View style={[styles.track, { backgroundColor: colors.border }]}>
            <View style={[styles.bar, { width: `${progressFraction(mine) * 100}%`, backgroundColor: colors.primary }]} />
          </View>
        ) : null}
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  badge: { width: 34, height: 34, borderRadius: 17, alignItems: 'center', justifyContent: 'center' },
  flex: { flex: 1, gap: space.xs },
  track: { height: 5, borderRadius: 3, overflow: 'hidden', marginTop: space.xs },
  bar: { height: 5 },
});
```

Wire it:
- `HomeScreen.tsx`: render `<JoiningBonusCard />` just above `{!trip ? <HomeInsights /> : null}` (only when `!trip`).
- `EarningsScreen.tsx`: render `<JoiningBonusCard />` under the hero card; and where the period's rows/summary are drawn, if `earnings.bonuses?.length`, a row per bonus: label `t('referral.bonus')`, amount `rupees(b.amount)`, date `dayLabel(localDate(b.earned_at))` (use the same row component the screen uses for its list; read the file first).
- `ProfileScreen.tsx`: in the GUIDE group (line ~179), before "How the app works": `<GroupRow icon="gift-outline" label={t('referral.title')} onPress={() => nav.navigate('Referral')} />`.
- `SignupAccountScreen.tsx`: a `referralCode` state, a `TextField` labelled `t('referral.codeLabel')` (icon `gift-outline`, `autoCapitalize="characters"`, `maxLength={16}`) after the confirm-password field; pass `referral_code: referralCode.trim() || undefined` in the `signup({...})` call (line ~59). The API's 422 message already lands in the screen's existing error display via `ApiError.message`.
- `OnboardingHomeScreen.tsx`: in the Help `Group`, while `view?.status !== 'APPROVED'` and the rider has no referrer (`api.referral()` → `joined_with === null`), a `GroupRow` `t('referral.haveCode')` opening a small `Sheet` (`components/ui/Sheet`) with a `TextField` and `Button` `t('referral.add')` calling `api.addReferralCode(normaliseCode(code))`; on success close and show `t('referral.added')`; on `ApiError` show `e.message` under the field. Keep it in a small component in the same file, `ReferralCodeRow`.

- [ ] **Step 4: Run** `npx jest` (all pass, incl. `dictionaries.test.ts` for the new strings), `./node_modules/.bin/tsc --noEmit` (clean), `npx eslint src` (0 errors), `npx prettier --check` on the new/changed files.

- [ ] **Step 5: Commit** - `git commit -m "feat(rider): Refer & earn - share code, referrals with progress, joining bonus card, code at sign-up"`.

---

### Task 9: Docs and full verification

**Files:**
- Modify: `CLAUDE.md` (Own delivery fleet section - append a bullet), `.claude/worklog.md` (append an entry)

- [ ] **Step 1:** Append to CLAUDE.md's fleet section:

```markdown
- **Rider referral (2026-10-10, the owner's rule).** `fleet/referral.py`:
  an APPROVED rider's code (`riders.referral_code`, first name + 4 digits);
  a new rider enters it at sign-up or until approved (`accept_code`; refusal
  codes `referral_unknown|self|inactive|taken|closed`). Terms are frozen on
  `rider_referrals` (one row per referred rider). Approval starts the clock
  (`on_approved`); `trips._finish` calls `on_delivered` for every DELIVERED
  end - N delivered trips between approval and the deadline write two
  `rider_bonuses` rows (UNIQUE referral+kind is the money guard; zero amounts
  write nothing). Expiry is saved on read (`refresh_status`). Bonuses join
  the next payout (`payouts.py`: unpaid, earnings `bonuses`, `pay_rider`
  stamps `payout_id`). Admin: Riders -> Referrals (settings in
  `platform_settings` "rider_referral", cancel until paid). App: Profile ->
  Refer & earn, joining-bonus card on Home/Earnings, code at sign-up and on
  the application home. Migration 0091 (RLS on).
```

- [ ] **Step 2:** Run everything:
  - `cd backend && ./.venv/Scripts/python.exe -m unittest discover -s tests` → OK (record the count).
  - `cd frontend-admin && npx vitest run && npm run build` → pass.
  - `cd rider && npx jest && ./node_modules/.bin/tsc --noEmit && npx eslint src` → pass, 0 errors.

- [ ] **Step 3:** Apply `0091` to the local dev database used by the 8001 API (`rr_rider_dev`) - with the devenv variables sourced so `DATABASE_URL` points at `rr_rider_dev`, assert it in Python first, then `./.venv/Scripts/python.exe -m alembic upgrade head`. Do NOT run it against Supabase: Render's pre-deploy upgrade applies it there.

- [ ] **Step 4:** Append a worklog entry (what was built, the counts, that Supabase is not migrated by hand), commit: `git commit -m "docs: rider referral programme"`.

---

## Self-review

- Spec coverage: rules 1-9 → Tasks 3 (codes, refusals, frozen terms), 4 (clock, qualifying, expiry, cancel, programme off), 6 (sign-up, add-later, views, hooks); data → Task 1; money path → Task 5; API → Task 6; admin panel → Task 7; rider app → Task 8; testing list → spread over Tasks 1-8; docs → Task 9.
- No placeholders: every code step has code; Tasks 7 and 8 name the exact shared components to open first to match props (that is a check, not a gap).
- Types: `ReferralStatus`/`RiderBonusKind` values identical in Python, admin TS and rider TS; `rider_view` keys match `RiderReferralView`; `admin_rows` keys match `AdminReferralRow` and the admin TS type; `normalise`/`normaliseCode` agree (strip whitespace, uppercase).

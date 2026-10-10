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
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.enums import ReferralStatus, RiderBonusKind, RiderOnboarding, TripEndReason
from app.models.rider import Rider, RiderTrip
from app.models.rider_referral import RiderBonus, RiderReferral
from app.models.user import User
from app.services.fleet.config import _read, _write

logger = logging.getLogger(__name__)

REFERRAL_KEY = "rider_referral"


@dataclass(frozen=True, slots=True)
class ReferralStep:
    """Reach `deliveries` and the referrer gets `referrer_amount`, the new rider `joiner_amount`."""

    deliveries: int
    referrer_amount: Decimal
    joiner_amount: Decimal


#: The owner's Swiggy-style default (2026-10-10): a first reward early, the
#: bigger one once the new rider has really started working.
DEFAULT_STEPS = (
    ReferralStep(10, Decimal("100.00"), Decimal("50.00")),
    ReferralStep(30, Decimal("400.00"), Decimal("150.00")),
)
MAX_STEPS = 5


@dataclass(frozen=True, slots=True)
class ReferralConfig:
    enabled: bool = True
    leaderboard_enabled: bool = True
    days_allowed: int = 30
    steps: tuple[ReferralStep, ...] = DEFAULT_STEPS

    # The v1 single-step view, still read by the referral row's own columns.
    @property
    def referrer_amount(self) -> Decimal:
        return sum((s.referrer_amount for s in self.steps), Decimal("0.00"))

    @property
    def joiner_amount(self) -> Decimal:
        return sum((s.joiner_amount for s in self.steps), Decimal("0.00"))

    @property
    def deliveries_required(self) -> int:
        return self.steps[-1].deliveries


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


def _steps(data: dict[str, Any]) -> tuple[ReferralStep, ...]:
    raw = data.get("steps")
    if raw is None:
        # A v1 settings row (one N, two amounts): it is one step. Missing
        # fields take v1's own defaults, so nothing saved before changes.
        raw = [{
            "deliveries": data.get("deliveries_required", 20),
            "referrer_amount": data.get("referrer_amount", "500"),
            "joiner_amount": data.get("joiner_amount", "200"),
        }]
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_STEPS:
        raise _refuse(f"Add between 1 and {MAX_STEPS} steps")
    steps: list[ReferralStep] = []
    for row in raw:
        if not isinstance(row, dict):
            raise _refuse("Each step needs deliveries and two amounts")
        step = ReferralStep(
            deliveries=_whole(row.get("deliveries"), "Deliveries needed", 1, 500),
            referrer_amount=_amount(row.get("referrer_amount"), "Referrer bonus"),
            joiner_amount=_amount(row.get("joiner_amount"), "New rider bonus"),
        )
        if steps and step.deliveries <= steps[-1].deliveries:
            raise _refuse("Each step must need more deliveries than the one before it")
        steps.append(step)
    if all(s.referrer_amount == 0 and s.joiner_amount == 0 for s in steps):
        raise _refuse("A referral must pay somebody something")
    return tuple(steps)


def validate_config(data: dict[str, Any]) -> ReferralConfig:
    base = ReferralConfig()
    return ReferralConfig(
        enabled=bool(data.get("enabled", base.enabled)),
        leaderboard_enabled=bool(data.get("leaderboard_enabled", base.leaderboard_enabled)),
        days_allowed=_whole(data.get("days_allowed", base.days_allowed), "Days allowed", 1, 365),
        steps=_steps(data),
    )


def steps_value(steps: tuple[ReferralStep, ...] | list[ReferralStep]) -> list[dict[str, Any]]:
    return [
        {"deliveries": s.deliveries, "referrer_amount": str(s.referrer_amount), "joiner_amount": str(s.joiner_amount)}
        for s in steps
    ]


def config_value(cfg: ReferralConfig) -> dict[str, Any]:
    """Stored and wire shape. The v1 totals ride along for older readers."""

    return {
        "enabled": cfg.enabled,
        "leaderboard_enabled": cfg.leaderboard_enabled,
        "days_allowed": cfg.days_allowed,
        "steps": steps_value(cfg.steps),
        "referrer_amount": str(cfg.referrer_amount),
        "joiner_amount": str(cfg.joiner_amount),
        "deliveries_required": cfg.deliveries_required,
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


# --- codes ----------------------------------------------------------------------


def normalise(code: str) -> str:
    """What a rider typed, as stored: uppercase, no spaces."""

    return re.sub(r"\s+", "", code or "").upper()[:16]


def _stem(full_name: str) -> str:
    words = (full_name or "").split()
    letters = re.sub(r"[^A-Za-z]", "", words[0] if words else "").upper()[:6]
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


def check_code(db: Session, raw_code: str) -> Rider:
    """The referrer a code names, or the refusal - changing nothing.

    Sign-up asks this BEFORE it uses up the phone code: a mistyped referral
    code must leave the rider able to fix it and send the form again
    (`verify_code` consumes the code and commits).
    """

    if not load_config(db).enabled:
        raise _refused("referral_closed")
    code = normalise(raw_code)
    referrer = db.scalar(select(Rider).where(Rider.referral_code == code)) if code else None
    if referrer is None:
        raise _refused("referral_unknown")
    referrer_user = db.get(User, referrer.user_id)
    if referrer.onboarding != RiderOnboarding.APPROVED or referrer_user is None or not referrer_user.is_active:
        raise _refused("referral_inactive")
    return referrer


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
        steps=steps_value(cfg.steps),
        status=ReferralStatus.WAITING,
    )
    db.add(ref)
    db.flush()
    return ref


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


def steps_of(ref: RiderReferral) -> list[ReferralStep]:
    """The steps this referral was accepted on; a v1 row is its one step."""

    rows = ref.steps or []
    if not rows:
        return [ReferralStep(ref.deliveries_required, Decimal(ref.referrer_amount), Decimal(ref.joiner_amount))]
    return [
        ReferralStep(int(r["deliveries"]), Decimal(str(r["referrer_amount"])), Decimal(str(r["joiner_amount"])))
        for r in rows
    ]


def _pay(db: Session, ref: RiderReferral, rider_id: uuid.UUID, kind: RiderBonusKind,
         amount: Decimal, now: datetime, step: int) -> bool:
    if amount <= 0:
        return False
    try:
        with db.begin_nested():
            db.add(RiderBonus(rider_user_id=rider_id, kind=kind, amount=amount,
                              referral_id=ref.referred_user_id, earned_at=now, step=step))
    except IntegrityError:
        # Already written - by an earlier call or a racing one. The unique
        # (referral, kind, step) row is the guard; this is the expected outcome.
        return False
    return True


def on_delivered(
    db: Session, rider_user_id: uuid.UUID, *, now: datetime | None = None
) -> list[tuple[RiderBonusKind, int, Decimal]]:
    """A trip of this rider ended DELIVERED: pay every step now reached, once.

    Returns the bonuses this call wrote (empty when none) - the pushes say so.
    The last step reached makes the referral EARNED; before that it stays
    IN_PROGRESS, its earned steps already payable.
    """

    now = now or _now()
    ref = db.scalar(
        select(RiderReferral).where(RiderReferral.referred_user_id == rider_user_id).with_for_update()
    )
    if ref is None or ref.status != ReferralStatus.IN_PROGRESS:
        return []
    refresh_status(db, ref, now=now)
    if ref.status != ReferralStatus.IN_PROGRESS or not load_config(db).enabled:
        return []
    count = delivered_count(db, ref)
    steps = steps_of(ref)
    written: list[tuple[RiderBonusKind, int, Decimal]] = []
    for index, step in enumerate(steps):
        if count < step.deliveries:
            break
        for rider_id, kind, amount in (
            (ref.referrer_user_id, RiderBonusKind.REFERRAL_REFERRER, step.referrer_amount),
            (ref.referred_user_id, RiderBonusKind.REFERRAL_JOINER, step.joiner_amount),
        ):
            if _pay(db, ref, rider_id, kind, amount, now, index):
                written.append((kind, index, amount))
    if count >= steps[-1].deliveries:
        ref.status = ReferralStatus.EARNED
        ref.earned_at = ref.earned_at or now
    db.flush()
    if written:
        logger.info("Referral of %s: %d bonus rows written", ref.referred_user_id, len(written))
    return written


# --- cancelling ---------------------------------------------------------------------


def cancel(db: Session, admin: Any, referred_user_id: uuid.UUID, reason: str) -> RiderReferral:
    """An admin's no to a suspicious referral - never to a bonus already paid out."""

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
    bonuses = list(db.scalars(
        select(RiderBonus).where(RiderBonus.referral_id == ref.referred_user_id).with_for_update()
    ))
    if any(b.payout_id is not None for b in bonuses):
        raise HTTPException(status.HTTP_409_CONFLICT, "already_paid")
    for bonus in bonuses:
        db.delete(bonus)
    ref.status = ReferralStatus.CANCELLED
    ref.cancelled_at, ref.cancel_reason, ref.cancelled_by_user_id = _now(), reason, admin.id
    db.commit()
    logger.info("Referral of %s cancelled by %s: %s", referred_user_id, admin.id, reason)
    return ref


# --- views ----------------------------------------------------------------------------


def _short_name(full_name: str) -> str:
    """First name and last initial: enough to recognise a friend, no more."""

    parts = (full_name or "").split()
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0]}."


def _progress(
    db: Session, ref: RiderReferral, name: str, amount: Decimal, kind: RiderBonusKind
) -> dict[str, Any]:
    refresh_status(db, ref)
    # Paid = this side's bonus is in a payout: "it comes with your next
    # payout" is then no longer true, and the app stops saying it.
    paid = db.scalar(
        select(RiderBonus.id).where(
            RiderBonus.referral_id == ref.referred_user_id,
            RiderBonus.kind == kind,
            RiderBonus.payout_id.is_not(None),
        )
    )
    return {
        "name": name,
        "status": ref.status.value,
        "delivered": delivered_count(db, ref),
        "required": ref.deliveries_required,
        "deadline": ref.deadline,
        "amount": amount,
        "paid": paid is not None,
    }


def _names(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())


def rider_view(db: Session, rider_user_id: uuid.UUID) -> dict[str, Any]:
    """Refer & earn for one rider: their code, today's terms, their referrals, their own bonus."""

    cfg = load_config(db)
    code = ensure_code(db, rider_user_id)
    mine = list(db.scalars(
        select(RiderReferral).where(RiderReferral.referrer_user_id == rider_user_id)
        .order_by(RiderReferral.created_at.desc())
    ))
    names = _names(db, {r.referred_user_id for r in mine})
    referrals = [
        _progress(db, r, _short_name(names.get(r.referred_user_id, "")), r.referrer_amount,
                  RiderBonusKind.REFERRAL_REFERRER)
        for r in mine
    ]
    own = db.get(RiderReferral, rider_user_id)
    joined_with = None
    if own is not None and own.status != ReferralStatus.CANCELLED:
        referrer = db.get(User, own.referrer_user_id)
        joined_with = _progress(db, own, _short_name(referrer.full_name if referrer else ""), own.joiner_amount,
                                RiderBonusKind.REFERRAL_JOINER)
    earned = db.scalar(
        select(func.coalesce(func.sum(RiderBonus.amount), 0)).where(RiderBonus.rider_user_id == rider_user_id)
    )
    db.commit()  # a code made, or an expiry saved, on this read
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


#: The admin list's length. A row asked for by id is always found, cap or not.
ADMIN_ROWS_LIMIT = 500


def admin_rows(
    db: Session, wanted: ReferralStatus | None = None, *, only: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    """Every referral, newest first (capped), with progress and whether it was paid."""

    query = select(RiderReferral).order_by(RiderReferral.created_at.desc())
    if only is not None:
        query = query.where(RiderReferral.referred_user_id == only)
    else:
        query = query.limit(ADMIN_ROWS_LIMIT)
    refs = list(db.scalars(query))
    names = _names(db, {r.referred_user_id for r in refs} | {r.referrer_user_id for r in refs})
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

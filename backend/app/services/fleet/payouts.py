"""What riders have earned, and the admin marking it paid.

The money itself moves outside the app (a bank transfer); this module is the
ledger of it. A trip belongs to at most one payout, and paying locks the
trips it pays, so two clicks on "Mark paid" cannot pay the same trip twice.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.rider import RiderPayout, RiderTrip
from app.models.rider_referral import RiderBonus
from app.models.user import User


def _ended_paid_trips(rider_user_id: uuid.UUID):
    return select(RiderTrip).where(
        RiderTrip.rider_user_id == rider_user_id,
        RiderTrip.ended_at.is_not(None),
        RiderTrip.earning_amount.is_not(None),
        RiderTrip.earning_amount > 0,
    )


def rider_earnings(db: Session, rider_user_id: uuid.UUID, *, days: int, tz: ZoneInfo) -> dict[str, Any]:
    """Today, the last `days` days by local date, and what is paid and unpaid."""

    now_local = datetime.now(tz)
    today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    period_start = today_start - timedelta(days=days - 1)
    rows = db.execute(
        _ended_paid_trips(rider_user_id)
        .where(RiderTrip.ended_at >= period_start.astimezone(UTC))
        .with_only_columns(RiderTrip.ended_at, RiderTrip.earning_amount)
    ).all()
    by_day: dict[str, list[Decimal]] = defaultdict(list)
    for ended_at, amount in rows:
        local = (ended_at if ended_at.tzinfo else ended_at.replace(tzinfo=UTC)).astimezone(tz)
        by_day[local.date().isoformat()].append(Decimal(amount))
    # Referral bonuses are money earned too: counted on the day they were
    # earned, in the totals and the chart - never in the trip counts.
    bonus_rows = db.execute(
        select(RiderBonus.earned_at, RiderBonus.amount, RiderBonus.kind)
        .where(RiderBonus.rider_user_id == rider_user_id, RiderBonus.earned_at >= period_start.astimezone(UTC))
        .order_by(RiderBonus.earned_at)
    ).all()
    bonus_by_day: dict[str, list[Decimal]] = defaultdict(list)
    for earned_at, amount, _kind in bonus_rows:
        local = (earned_at if earned_at.tzinfo else earned_at.replace(tzinfo=UTC)).astimezone(tz)
        bonus_by_day[local.date().isoformat()].append(Decimal(amount))
    series = []
    for offset in range(days):
        day = (period_start + timedelta(days=offset)).date().isoformat()
        amounts = by_day.get(day, [])
        extra = bonus_by_day.get(day, [])
        series.append({"date": day, "trips": len(amounts), "amount": sum(amounts + extra, Decimal("0"))})
    today = series[-1]
    unpaid = db.scalar(
        select(func.coalesce(func.sum(RiderTrip.earning_amount), 0)).where(
            RiderTrip.rider_user_id == rider_user_id,
            RiderTrip.ended_at.is_not(None),
            RiderTrip.payout_id.is_(None),
        )
    )
    unpaid_bonus = db.scalar(
        select(func.coalesce(func.sum(RiderBonus.amount), 0)).where(
            RiderBonus.rider_user_id == rider_user_id, RiderBonus.payout_id.is_(None)
        )
    )
    paid = db.scalar(
        select(func.coalesce(func.sum(RiderPayout.amount), 0)).where(RiderPayout.rider_user_id == rider_user_id)
    )
    return {
        "today": today["amount"],
        "today_trips": today["trips"],
        "period_total": sum((d["amount"] for d in series), Decimal("0")),
        "period_trips": sum(d["trips"] for d in series),
        "unpaid": Decimal(unpaid or 0) + Decimal(unpaid_bonus or 0),
        "paid_total": Decimal(paid or 0),
        "days": series,
        "bonuses": [
            {"amount": Decimal(amount), "kind": getattr(kind, "value", kind), "earned_at": earned_at}
            for earned_at, amount, kind in bonus_rows
        ],
    }


def rider_payouts(db: Session, rider_user_id: uuid.UUID, *, limit: int = 50) -> list[RiderPayout]:
    """What this rider has been paid, newest first: the app's Payments list."""

    return list(
        db.scalars(
            select(RiderPayout)
            .where(RiderPayout.rider_user_id == rider_user_id)
            # id breaks a tie: two payouts in one second keep a stable order between loads.
            .order_by(RiderPayout.paid_at.desc(), RiderPayout.id.desc())
            .limit(limit)
        )
    )


def unpaid_summary(db: Session) -> list[dict[str, Any]]:
    """Everyone owed money: unpaid trips plus unpaid bonuses, a rider with only a bonus included."""

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


def pay_rider(db: Session, admin: Any, rider_user_id: uuid.UUID, *, period_to: datetime, reference: str) -> RiderPayout:
    """Mark every unpaid, finished trip up to `period_to` as paid in one payout."""

    period_to = period_to if period_to.tzinfo else period_to.replace(tzinfo=UTC)
    due = list(
        db.scalars(
            _ended_paid_trips(rider_user_id)
            .where(RiderTrip.payout_id.is_(None), RiderTrip.ended_at <= period_to)
            .order_by(RiderTrip.ended_at)
            .with_for_update()
        )
    )
    # Referral bonuses earned in the period go out with the trips, locked the
    # same way, so two clicks cannot pay a bonus twice either.
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
    payout = RiderPayout(
        rider_user_id=rider_user_id,
        period_from=min([t.ended_at for t in due] + [b.earned_at for b in due_bonuses]),
        period_to=period_to,
        amount=sum((Decimal(t.earning_amount) for t in due), Decimal("0"))
        + sum((Decimal(b.amount) for b in due_bonuses), Decimal("0")),
        trips=len(due),
        reference=reference.strip()[:120],
        paid_at=datetime.now(UTC),
        created_by_user_id=admin.id,
    )
    db.add(payout)
    db.flush()
    for trip in due:
        trip.payout_id = payout.id
    for bonus in due_bonuses:
        bonus.payout_id = payout.id
    db.commit()
    return payout


__all__ = ["pay_rider", "rider_earnings", "unpaid_summary"]

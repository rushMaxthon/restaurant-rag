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
    series = []
    for offset in range(days):
        day = (period_start + timedelta(days=offset)).date().isoformat()
        amounts = by_day.get(day, [])
        series.append({"date": day, "trips": len(amounts), "amount": sum(amounts, Decimal("0"))})
    today = series[-1]
    unpaid = db.scalar(
        select(func.coalesce(func.sum(RiderTrip.earning_amount), 0)).where(
            RiderTrip.rider_user_id == rider_user_id,
            RiderTrip.ended_at.is_not(None),
            RiderTrip.payout_id.is_(None),
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
        "unpaid": Decimal(unpaid or 0),
        "paid_total": Decimal(paid or 0),
        "days": series,
    }


def unpaid_summary(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            RiderTrip.rider_user_id,
            User.full_name,
            func.count(RiderTrip.id),
            func.coalesce(func.sum(RiderTrip.earning_amount), 0),
            func.min(RiderTrip.ended_at),
        )
        .join(User, User.id == RiderTrip.rider_user_id)
        .where(RiderTrip.ended_at.is_not(None), RiderTrip.payout_id.is_(None), RiderTrip.earning_amount > 0)
        .group_by(RiderTrip.rider_user_id, User.full_name)
        .order_by(User.full_name)
    ).all()
    return [
        {"rider_user_id": r, "full_name": n, "trips": int(c), "amount": Decimal(a), "oldest": o}
        for r, n, c, a, o in rows
    ]


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
    if not due:
        raise HTTPException(status.HTTP_409_CONFLICT, "nothing_to_pay")
    payout = RiderPayout(
        rider_user_id=rider_user_id,
        period_from=due[0].ended_at,
        period_to=period_to,
        amount=sum((Decimal(t.earning_amount) for t in due), Decimal("0")),
        trips=len(due),
        reference=reference.strip()[:120],
        paid_at=datetime.now(UTC),
        created_by_user_id=admin.id,
    )
    db.add(payout)
    db.flush()
    for trip in due:
        trip.payout_id = payout.id
    db.commit()
    return payout


__all__ = ["pay_rider", "rider_earnings", "unpaid_summary"]

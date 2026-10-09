"""When an order's food will be ready - what a rider is told, and what times their arrival.

The owner's rule (2026-10-10): the branch's preparation time, which the admin
already sets on the branch, counted from the moment the kitchen accepted. Not
a column on the order: it is derived from two facts we already keep (the
ACCEPTED event and the branch setting), so there is nothing to fall out of
step and no migration.

A branch with no preparation time is UNKNOWN, not zero. Five of eight stored
branches had none when this was written; inventing 15 minutes for them would
tell riders a time nobody promised and hold every one of their orders back.
They get no ready time and dispatch exactly as before.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import OrderStatus
from app.models.order import Order
from app.models.order_status_event import OrderStatusEvent


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def prep_minutes(order: Order) -> int | None:
    location = order.restaurant_location
    minutes = getattr(location, "preparation_time_minutes", None) if location is not None else None
    return int(minutes) if minutes else None


def accepted_at(db: Session, order: Order) -> datetime | None:
    """The last time the kitchen accepted it, from the event log (`orders` has no column)."""

    at = db.scalar(
        select(OrderStatusEvent.occurred_at)
        .where(OrderStatusEvent.order_id == order.id, OrderStatusEvent.to_status == OrderStatus.ACCEPTED)
        .order_by(OrderStatusEvent.occurred_at.desc())
        .limit(1)
    )
    return _aware(at) if at is not None else None


def ready_at(db: Session, order: Order, *, accepted_fallback: datetime | None = None) -> datetime | None:
    """Acceptance plus the branch's preparation time; None when the branch has none set.

    `accepted_fallback` stands in for an order with no ACCEPTED event - one
    accepted before the event log, or a test - so a branch with a preparation
    time still says something sensible.
    """

    minutes = prep_minutes(order)
    if minutes is None:
        return None
    started = accepted_at(db, order) or accepted_fallback
    if started is None:
        return None
    return _aware(started) + timedelta(minutes=minutes)


__all__ = ["accepted_at", "prep_minutes", "ready_at"]

"""Recording operational history: order transitions and dish availability.

These helpers are deliberately thin. They are called from the order and payment
paths, which are the most correctness-critical code in the platform, so they:

* only ever `db.add(...)` — never commit, never flush, never query. The caller's
  transaction owns the write, so an event cannot commit a half-finished order,
  and a rolled-back order takes its event with it.
* never raise on bad input. Recording history must not be able to fail a
  customer's order; a missing event is a gap in analytics, a failed order is
  lost revenue.
* record the actor, because "who changed this" is the first question asked of
  any operational log.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.enums import (
    OrderCancellationReason,
    OrderEventActor,
    OrderStatus,
    UserRole,
)
from app.models.menu_availability_event import MenuItemAvailabilityEvent
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.user import User

logger = logging.getLogger(__name__)


def actor_for_user(user: User | None) -> OrderEventActor:
    """Map a user onto an actor, defaulting to SYSTEM for unattended work."""

    if user is None:
        return OrderEventActor.SYSTEM
    if user.role == UserRole.ADMIN:
        return OrderEventActor.ADMIN
    if user.role == UserRole.OWNER:
        return OrderEventActor.OWNER
    if user.role == UserRole.CUSTOMER:
        return OrderEventActor.CUSTOMER
    return OrderEventActor.SYSTEM


def record_order_status_event(
    db: Session,
    *,
    order: Order,
    to_status: OrderStatus,
    from_status: OrderStatus | None = None,
    actor: OrderEventActor = OrderEventActor.SYSTEM,
    actor_user_id: uuid.UUID | None = None,
    cancellation_reason: OrderCancellationReason | None = None,
    note: str | None = None,
    occurred_at: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Add one transition row to the caller's open transaction.

    Imported lazily so this module can be pulled into the order path without
    dragging the whole model graph along with it.
    """

    from app.models.order_status_event import OrderStatusEvent

    try:
        db.add(
            OrderStatusEvent(
                id=uuid.uuid4(),
                order_id=order.id,
                restaurant_id=order.restaurant_id,
                restaurant_location_id=order.restaurant_location_id,
                from_status=from_status,
                to_status=to_status,
                actor=actor,
                actor_user_id=actor_user_id,
                cancellation_reason=cancellation_reason,
                note=note[:255] if note else None,
                occurred_at=occurred_at or datetime.now(UTC),
                event_metadata=metadata or {},
            )
        )
    except Exception:  # noqa: BLE001 - history must never break an order
        logger.exception(
            "Could not record order status event order_id=%s to_status=%s",
            getattr(order, "id", None),
            to_status,
        )


def mark_order_cancelled(
    db: Session,
    *,
    order: Order,
    reason: OrderCancellationReason,
    actor: OrderEventActor = OrderEventActor.SYSTEM,
    actor_user_id: uuid.UUID | None = None,
    note: str | None = None,
    occurred_at: datetime | None = None,
) -> None:
    """Stamp the cancellation fields and record the matching transition.

    Kept together so a cancellation cannot be written without its reason: every
    cancellation on this platform is system-derived, so there is never a case
    where the reason is genuinely unknown at the time it happens.
    """

    moment = occurred_at or datetime.now(UTC)
    previous_status = order.status

    order.cancellation_reason = reason
    order.cancelled_by = actor
    order.cancelled_at = moment

    record_order_status_event(
        db,
        order=order,
        from_status=previous_status,
        to_status=OrderStatus.CANCELLED,
        actor=actor,
        actor_user_id=actor_user_id,
        cancellation_reason=reason,
        note=note,
        occurred_at=moment,
    )


def record_menu_availability_event(
    db: Session,
    *,
    menu_item: MenuItem,
    is_available: bool,
    previous_available: bool | None = None,
    actor: OrderEventActor = OrderEventActor.SYSTEM,
    actor_user_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
) -> None:
    """Record a dish being switched off or back on.

    A no-op when the state did not actually change, so the log holds real
    transitions rather than one row per save.
    """

    if previous_available is not None and previous_available == is_available:
        return

    try:
        db.add(
            MenuItemAvailabilityEvent(
                id=uuid.uuid4(),
                menu_item_id=menu_item.id,
                restaurant_id=menu_item.restaurant_id,
                restaurant_location_id=menu_item.restaurant_location_id,
                is_available=is_available,
                item_name_snapshot=(menu_item.name or "")[:255],
                actor=actor,
                actor_user_id=actor_user_id,
                occurred_at=occurred_at or datetime.now(UTC),
            )
        )
    except Exception:  # noqa: BLE001 - history must never break a menu update
        logger.exception(
            "Could not record availability event menu_item_id=%s",
            getattr(menu_item, "id", None),
        )


__all__ = [
    "actor_for_user",
    "mark_order_cancelled",
    "record_menu_availability_event",
    "record_order_status_event",
]

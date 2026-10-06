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

from sqlalchemy import event
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
from app.services import stock
from app.services.kitchen_push import queue_kitchen_new_order
from app.services.realtime.outbox import queue_order_updated

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
    # Before this branch existed a cook's advance was logged as SYSTEM, which
    # reads as "the platform did this by itself" — the opposite of what this
    # table is for.
    if user.role == UserRole.KITCHEN:
        return OrderEventActor.KITCHEN
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

    # Every transition on the platform passes through here — created, advanced,
    # paid, reaped, abandoned — so this one line is what makes all of them
    # live. Queued, not sent: the push goes out from `after_commit`, so a
    # rolled-back order announces nothing. Never raises (see `outbox`).
    queue_order_updated(
        db,
        order_id=order.id,
        restaurant_id=order.restaurant_id,
        restaurant_location_id=order.restaurant_location_id,
        customer_id=getattr(order, "customer_id", None),
        to_status=to_status,
        from_status=from_status,
        occurred_at=occurred_at,
    )

    # Arriving on the board is the moment a kitchen wants to hear about. Every
    # path that makes an order PLACED (created as COD, paid by card) records
    # it here, so this one line covers all of them. After-commit, flagged, and
    # never raises — see `kitchen_push`.
    if to_status == OrderStatus.PLACED:
        queue_kitchen_new_order(db, order_id=order.id)

    # And the ticket, for the two transitions a printer cares about.
    #
    # Here for the same reason the push is: every transition on the platform
    # passes through this function, so a path that advances an order cannot
    # forget to print. Unlike the push, the rows are written INSIDE the
    # caller's transaction — a database row becomes visible exactly when that
    # transaction commits, which is the "only after commit" property the push
    # needs an outbox to get. A rolled-back order takes its tickets with it.
    _queue_print_jobs(db, order=order, to_status=to_status, reason=cancellation_reason)

    # And the restaurant's share: released when the food is handed over,
    # taken back when the order is called off. Queued after commit like the
    # push, and never raising: history and payouts must not break an order.
    if to_status in (OrderStatus.DELIVERED, OrderStatus.CANCELLED):
        try:
            from app.services.payouts.service import queue_payout_step

            queue_payout_step(db, "release" if to_status == OrderStatus.DELIVERED else "reverse", order.id)
        except Exception:  # noqa: BLE001
            logger.exception("Could not queue the payout step for order %s", getattr(order, "id", None))


def _queue_print_jobs(
    db: Session,
    *,
    order: Order,
    to_status: OrderStatus,
    reason: OrderCancellationReason | None,
) -> None:
    """Which transitions put paper in a kitchen.

    PLACED and nothing earlier. `PAYMENT_PENDING` deliberately prints nothing:
    an order whose money has not arrived is not an order, and a docket for one
    has a kitchen cooking food nobody has paid for. That is the single most
    expensive mistake this feature could make, so it is a condition here
    rather than a filter somewhere downstream.

    CANCELLED prints a void slip, because by then a docket may already be in
    somebody's hand and the only way to recall it is another piece of paper.

    ACCEPTED, PREPARING and the rest print nothing. The kitchen is the thing
    moving them along; telling it what it just did is noise with a cost in
    paper.

    Never raises: `enqueue_for_order` swallows everything, and this adds a
    second guard around the import and the dispatch so a packaging mistake
    cannot reach an order either.
    """

    try:
        from app.models.enums import PrintJobKind
        from app.services.print.queue import enqueue_for_order

        if to_status == OrderStatus.PLACED:
            enqueue_for_order(db, order, kind=PrintJobKind.KITCHEN_DOCKET)
            enqueue_for_order(db, order, kind=PrintJobKind.CUSTOMER_BILL)
        elif to_status == OrderStatus.CANCELLED:
            enqueue_for_order(
                db,
                order,
                kind=PrintJobKind.VOID_SLIP,
                reason=reason.value.replace("_", " ").title() if reason else None,
            )
    except Exception:  # noqa: BLE001 - a ticket is never worth an order
        logger.exception(
            "Could not queue print jobs for order %s at %s",
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
    # Here for the reason the rider is: there is one way an order is
    # cancelled, so there is one place its stock can be forgotten. Today that
    # is an unpaid checkout, which is exactly the order holding loaves nobody
    # is going to collect.
    stock.release(db, order.items)
    _queue_courier_cancel(db, order)


def _queue_courier_cancel(db: Session, order: Order) -> None:
    """If a rider was booked for this order, arrange for them to be called off.

    Here rather than at each call site, for the reason `mark_order_cancelled`
    exists at all: there is one way an order is cancelled, so there is one
    place a rider can be forgotten. Today every cancellation is of an unpaid
    order, which was never dispatched, and this does nothing — it is here for
    the first cancellation path that is not, because that one will be written
    by somebody thinking about refunds rather than about a bike.

    Queued after the commit, never called inline: the courier is somebody
    else's server, and the task re-reads the order and refuses to act unless
    it really is cancelled, which is what makes a rollback harmless.
    """

    delivery = getattr(order, "delivery", None)
    if delivery is None or not getattr(delivery, "provider_order_id", ""):
        return
    order_id = str(order.id)

    def _send(_session: Session) -> None:
        try:
            from app.config.celery import celery_app

            celery_app.send_task(
                "app.tasks.delivery.cancel_order_delivery_task",
                kwargs={"order_id": order_id},
            )
        except Exception:  # noqa: BLE001 - a broker that is down must not undo a cancellation
            logger.warning("Could not queue a courier cancel for order %s", order_id, exc_info=True)

    event.listen(db, "after_commit", _send, once=True)


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

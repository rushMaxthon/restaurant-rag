"""A person cancelling an order, and the refund that follows.

Until 2026-10-06 every cancellation here was system-derived - an unpaid
checkout reaped - so an owner whose kitchen ran out had no way to call an
order off. The rules, as decided with the platform owner:

- **Who:** the platform admin and the restaurant's owner. A cook cannot: the
  board is a shared tablet, and a cancellation refunds money.
- **Until when:** before the rider has the food - PLACED, ACCEPTED or
  PREPARING, and no courier reporting it collected. After that the food is
  out of the building and a cancel would refund a meal already on its way.
- **Why:** one of `STAFF_CANCELLATION_REASONS`, never free text; a note rides
  beside it and is required for "other".
- **Money:** an order paid online is refunded in full through the account
  that took it (`provider_for_transaction`), from Celery after the commit -
  a gateway is somebody else's server and must not hold a transaction open.

Everything else a cancellation does is already wired to the CANCELLED
transition and is used here for the first time: `mark_order_cancelled`
releases stock and calls the rider off, and `record_order_status_event`
reverses the payout, prints the slip and pushes the change to every screen.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import (
    OrderCancellationReason,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    UserRole,
)
from app.models.order import Order
from app.models.order_delivery import OrderDelivery
from app.models.payment import PaymentTransaction
from app.models.user import User
from app.services.order_events import actor_for_user, mark_order_cancelled
from app.services.payments.base import PaymentProviderError

logger = logging.getLogger(__name__)

STAFF_CANCELLATION_REASONS: frozenset[OrderCancellationReason] = frozenset({
    OrderCancellationReason.OUT_OF_STOCK,
    OrderCancellationReason.KITCHEN_UNAVAILABLE,
    OrderCancellationReason.CUSTOMER_REQUEST,
    OrderCancellationReason.DUPLICATE_OR_TEST,
    OrderCancellationReason.OTHER_BY_STAFF,
})

#: The statuses a person may cancel from: the food has not left the kitchen.
CANCELLABLE_STATUSES: frozenset[OrderStatus] = frozenset({
    OrderStatus.PLACED,
    OrderStatus.ACCEPTED,
    OrderStatus.PREPARING,
})

#: Courier states that mean the rider has the food, whatever the kitchen
#: tapped. The kitchen can be a step behind the courier, never ahead of it.
_FOOD_WITH_THE_RIDER = {"PICKED_UP", "IN_TRANSIT", "DELIVERED", "RETURNED"}

_REFUND_TASK = "app.tasks.payments.refund_cancelled_order_task"


def _delivery(db: Session | None, order: Order) -> OrderDelivery | None:
    # The relationship when the caller loaded it (every order list does), a
    # query only when it did not.
    if "delivery" in order.__dict__ or db is None:
        return order.__dict__.get("delivery")
    return db.scalar(select(OrderDelivery).where(OrderDelivery.order_id == order.id))


def cancel_refusal(db: Session | None, order: Order) -> str:
    """Why this order cannot be cancelled now, or "" when it can."""

    if order.status == OrderStatus.CANCELLED:
        return "This order is already cancelled."
    if order.status not in CANCELLABLE_STATUSES:
        return "The rider already has this order, so it can no longer be cancelled."
    delivery = _delivery(db, order)
    if delivery is not None and (delivery.state or "").upper() in _FOOD_WITH_THE_RIDER:
        return "The rider has already collected this order, so it can no longer be cancelled."
    return ""


def can_be_cancelled(order: Order, db: Session | None = None) -> bool:
    """For the screen: whether to offer Cancel. The server checks again."""

    if order.status not in CANCELLABLE_STATUSES:
        return False
    if db is None:
        from sqlalchemy.orm import object_session

        db = object_session(order)
    return not cancel_refusal(db, order)


def _owes_a_refund(order: Order) -> bool:
    return order.payment_method != PaymentMethod.COD and order.payment_status == PaymentStatus.PAID


def _queue_after_commit(db: Session, task: str, **kwargs: str) -> None:
    from app.services.payouts.webhooks import after_commit_task

    after_commit_task(db, task, **kwargs)


def _staff_order(
    db: Session, user: User, order_id: uuid.UUID, scope_restaurant_id: uuid.UUID | None
) -> Order:
    if user.role not in (UserRole.ADMIN, UserRole.OWNER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the restaurant's owner or the platform admin can cancel an order.",
        )
    query = select(Order).where(Order.id == order_id).with_for_update()
    # Narrowed, not checked after: an order outside the caller's restaurant is
    # a 404, so nothing is learned about it.
    if scope_restaurant_id is not None:
        query = query.where(Order.restaurant_id == scope_restaurant_id)
    order = db.scalar(query)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


def cancel_by_staff(
    db: Session,
    user: User,
    *,
    order_id: uuid.UUID,
    scope_restaurant_id: uuid.UUID | None,
    reason: OrderCancellationReason,
    note: str = "",
) -> Order:
    if reason not in STAFF_CANCELLATION_REASONS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Choose a reason for cancelling.")
    note = (note or "").strip()[:500]
    if reason == OrderCancellationReason.OTHER_BY_STAFF and not note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Say why in the note when the reason is 'Other'.",
        )

    order = _staff_order(db, user, order_id, scope_restaurant_id)
    refusal = cancel_refusal(db, order)
    if refusal:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=refusal)

    mark_order_cancelled(
        db,
        order=order,
        reason=reason,
        actor=actor_for_user(user),
        actor_user_id=user.id,
        note=note or None,
    )
    order.status = OrderStatus.CANCELLED
    order.cancellation_note = note or None
    if _owes_a_refund(order):
        order.refund_status = "PENDING"
        order.refund_error = None
        _queue_after_commit(db, _REFUND_TASK, order_id=str(order.id))
    _queue_after_commit(
        db,
        "app.tasks.notifications.send_order_status_notification",
        order_id=str(order.id),
        customer_id=str(order.customer_id),
        restaurant_id=str(order.restaurant_id),
        new_status=OrderStatus.CANCELLED.value,
    )
    db.add(order)
    db.commit()
    return order


def retry_refund(
    db: Session, user: User, *, order_id: uuid.UUID, scope_restaurant_id: uuid.UUID | None
) -> Order:
    """Try a FAILED refund again, once whatever the gateway objected to is fixed."""

    order = _staff_order(db, user, order_id, scope_restaurant_id)
    if order.refund_status != "FAILED":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="There is no failed refund to try again.")
    order.refund_status = "PENDING"
    order.refund_error = None
    _queue_after_commit(db, _REFUND_TASK, order_id=str(order.id))
    db.commit()
    return order


def _latest_transaction(db: Session, order_id: uuid.UUID) -> PaymentTransaction | None:
    return db.scalar(
        select(PaymentTransaction)
        .where(PaymentTransaction.order_id == order_id)
        .order_by(PaymentTransaction.created_at.desc())
        .limit(1)
    )


def _refund_provider(db: Session, order: Order, transaction: PaymentTransaction | None):
    """The gateway that took the payment - the restaurant's, or the platform's."""

    from app.services.payments.service import provider_for_transaction

    return provider_for_transaction(db, order=order, transaction=transaction)


def refund_cancelled_order(db: Session, order_id: uuid.UUID) -> Order | None:
    """Refund a cancelled order in full. Safe to call twice; runs in Celery.

    A refusal (4xx) is FAILED with the gateway's sentence, for a person to
    read and Retry; a network error stays PENDING and is raised, so Celery
    tries again.
    """

    order = db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None or order.status != OrderStatus.CANCELLED or order.refund_status != "PENDING":
        db.commit()
        return order
    transaction = _latest_transaction(db, order.id)
    provider = _refund_provider(db, order, transaction)
    if provider is None or not hasattr(provider, "refund") or transaction is None:
        order.refund_status = "FAILED"
        order.refund_error = "The payment's gateway account is not available to refund from; refund it from the gateway's dashboard."
        db.commit()
        return order
    try:
        provider.refund(
            intent_id=transaction.provider_intent_id,
            payment_id=transaction.provider_payment_id or "",
            amount=Decimal(order.total_amount),
            currency=order.currency or "INR",
            order_id=order.id,
        )
    except PaymentProviderError as error:
        order.refund_error = str(error)
        if error.retryable:
            db.commit()
            raise
        order.refund_status = "FAILED"
        db.commit()
        return order

    order.refund_status = "REFUNDED"
    order.refund_error = None
    order.payment_status = PaymentStatus.REFUNDED
    transaction.status = PaymentStatus.REFUNDED
    db.commit()
    return order

"""An order that is placed but not paid, and what a customer can still do with it.

A card order sits in `PAYMENT_PENDING` until the provider confirms the
charge. The kitchen never sees it, nothing has been taken, and the cart it
came from was emptied the moment it was created. So for that window the
order is the only record of what somebody wanted — and a customer who says
"actually, tomorrow" or "forget it" is talking about a row nothing in the
conversation could reach.

Three things can be done with such an order, and all three are here so they
are done the same way wherever they are asked for:

- **moved**, when the branch can take it at the new time. Only while it is
  unpaid: once money has changed hands the kitchen may have started, and a
  time change is a conversation with the restaurant, not a field edit.
- **abandoned**, which is `PAYMENT_ABANDONED` — the reason this platform
  already has for a customer who walked away from the payment sheet. It is
  reconciled with the provider first, exactly as the reaper does, because
  cancelling an order whose webhook was merely late would tell somebody
  their order was gone while their card had already been charged.
- **put back in the basket**, so abandoning loses nothing. The items are
  read off the order's own rows, ids only, which is the same shape the
  cart speaks in.

Nothing here decides *when* to do any of it. That is the conversation's
job; this module is the doing.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import (
    OrderCancellationReason,
    OrderEventActor,
    OrderFulfillmentType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.models.order import Order
from app.schemas.suggestions import CartLinePayload
from app.services import restaurant_locations as branch_hours
from app.services.order_events import mark_order_cancelled

logger = logging.getLogger(__name__)


def waiting_order(db: Session | None, scope) -> Order | None:
    """The order this conversation left unpaid, if there is one.

    The customer's most recent card order at this branch that is still
    waiting for payment. Never raises: a conversation whose database is
    unreachable is a worse conversation, not a failed one.
    """

    if db is None or getattr(scope, "customer", None) is None:
        return None
    try:
        return db.scalars(
            select(Order)
            .where(
                Order.customer_id == scope.customer.id,
                Order.status == OrderStatus.PAYMENT_PENDING,
                Order.payment_method == PaymentMethod.CARD,
            )
            .order_by(Order.placed_at.desc())
            .limit(1)
        ).first()
    except Exception:  # noqa: BLE001 - never lose a turn looking for an order
        logger.warning("Could not look for an unpaid order", exc_info=True)
        return None


def lines_of(order: Order) -> list[CartLinePayload]:
    """The order's items as a basket again — ids and quantities, nothing else.

    Names and prices are deliberately absent: the cart speaks in ids and is
    re-resolved against the branch's live menu, so a dish whose price moved
    or whose option was retired is caught the same way it would be for any
    other cart, rather than being restored from a snapshot nobody rechecked.
    """

    lines: list[CartLinePayload] = []
    for item in order.items:
        options: list[uuid.UUID] = []
        for chosen in item.selected_options_snapshot or []:
            raw = chosen.get("option_id") if isinstance(chosen, dict) else None
            if not raw:
                continue
            try:
                options.append(uuid.UUID(str(raw)))
            except (TypeError, ValueError):
                continue
        lines.append(
            CartLinePayload(
                menu_item_id=item.menu_item_id,
                quantity=max(1, int(item.quantity or 1)),
                size_id=item.menu_item_size_id,
                customization_option_ids=options,
            )
        )
    return lines


def can_move(order: Order) -> bool:
    """Whether this order's time is still the conversation's to change.

    Only while nothing has been charged. Once it is paid the kitchen may
    have started, and moving it is a conversation with the restaurant
    rather than a field this agent gets to edit.
    """

    return (
        order.status == OrderStatus.PAYMENT_PENDING
        and order.payment_status != PaymentStatus.PAID
    )


def move_to(db: Session, order: Order, *, when: datetime) -> tuple[bool, str | None]:
    """Move an unpaid order to a new time, if the branch can take it then.

    Returns (moved, reason). The branch's own `schedule_slot_is_available`
    decides, so a time this accepts is a time the order would have been
    accepted for in the first place.
    """

    if not can_move(order):
        return False, "that order is already paid for"
    location = order.restaurant_location
    if location is not None:
        fulfillment = OrderFulfillmentType(order.fulfillment_type)
        ok, reason = branch_hours.schedule_slot_is_available(
            location, fulfillment_type=fulfillment, scheduled_at=when
        )
        if not ok:
            return False, reason
    order.scheduled_at = when
    db.add(order)
    db.commit()
    db.refresh(order)
    logger.info("Moved unpaid order %s to %s", order.id, when.isoformat())
    return True, None


def abandon(db: Session, order: Order) -> bool:
    """The customer does not want it after all.

    `PAYMENT_ABANDONED` is the reason this platform already has for somebody
    who walked away from the payment sheet, and that is exactly what has
    happened — said in words rather than by closing a tab.

    Reconciled with the provider first, as the reaper does: cancelling an
    order whose webhook was merely late would tell a customer their order
    was gone while their card had already been charged. Returns False when
    that check finds the money did land.
    """

    from app.services.payments.service import (
        RETRYABLE_PAYMENT_STATUSES,
        _latest_transaction,
        _reconcile_with_provider,
        provider_for,
    )

    _reconcile_with_provider(db, order)
    if order.payment_status == PaymentStatus.PAID:
        return False

    transaction = _latest_transaction(db, order.id)
    if transaction is not None and transaction.status in RETRYABLE_PAYMENT_STATUSES:
        provider = provider_for(
            db, restaurant_id=order.restaurant_id, method=PaymentMethod.CARD
        )
        if provider is not None and provider.is_configured():
            try:
                provider.cancel_intent(transaction.provider_intent_id)
            except Exception:  # noqa: BLE001 - the order is cancelled either way
                logger.warning("Could not cancel the intent for %s", order.id, exc_info=True)
        transaction.status = PaymentStatus.CANCELLED
        db.add(transaction)

    mark_order_cancelled(
        db,
        order=order,
        reason=OrderCancellationReason.PAYMENT_ABANDONED,
        actor=OrderEventActor.CUSTOMER,
        note="the customer said they no longer wanted it",
    )
    order.status = OrderStatus.CANCELLED
    order.payment_status = PaymentStatus.CANCELLED
    db.add(order)
    db.commit()
    logger.info("Abandoned unpaid order %s at the customer's word", order.id)
    return True


def payment_link_for(db: Session, order: Order) -> str | None:
    """The short link for this order's payment, or None if one cannot be made.

    Idempotent at the provider: a Checkout session stays open after a
    declined or dismissed attempt, so this is the same page again rather
    than a second charge waiting to happen.
    """

    from app.services.payments.service import create_payment_link
    from app.services.short_links import shorten

    customer = order.customer
    if customer is None:
        return None
    try:
        link = create_payment_link(db, customer, order.id)
    except Exception:  # noqa: BLE001 - an order without a link is still an order
        logger.warning("Could not make a payment link for %s", order.id, exc_info=True)
        return None
    return shorten(link.url) if link.url else None

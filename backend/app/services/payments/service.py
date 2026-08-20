"""Payment orchestration: intents, cancellation, webhooks, and cleanup.

The rule this module exists to enforce: **only a verified provider event can
mark an order paid.** Nothing a client sends is trusted — not the amount, not
the provider, not the reference.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import (
    OrderCancellationReason,
    OrderEventActor,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.models.order import Order
from app.models.payment import PaymentTransaction, PaymentWebhookEvent
from app.models.user import User
from app.schemas.payment import PaymentIntentResponse, PaymentStatusResponse
from app.services.order_events import mark_order_cancelled, record_order_status_event
from app.services.payments.base import (
    PaymentProviderError,
    WebhookEvent,
    WebhookVerificationError,
)
from app.services.payments.registry import (
    available_payment_methods,
    get_stripe_provider,
    provider_name_for,
    resolve_provider,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# Payment states a new attempt may start from. PAID is absent on purpose.
RETRYABLE_PAYMENT_STATUSES = {
    PaymentStatus.PENDING,
    PaymentStatus.FAILED,
    PaymentStatus.CANCELLED,
}

# Intent states that can still be paid, so a fresh sheet can reuse the intent
# instead of stacking a second one on the same order.
REUSABLE_INTENT_STATUSES = {
    "requires_payment_method",
    "requires_confirmation",
    "requires_action",
    "processing",
}


def _load_customer_order(
    db: Session,
    customer: User,
    order_id: uuid.UUID,
    *,
    app_scope_restaurant_id: uuid.UUID | None = None,
) -> Order:
    order = db.scalar(
        select(Order).where(Order.id == order_id, Order.customer_id == customer.id)
    )
    if order is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Order not found")
    # A branded build must not touch an order from another restaurant, even one
    # the same person placed in the marketplace app. 404, not 403, so the app
    # cannot be used to probe which orders exist elsewhere.
    if app_scope_restaurant_id is not None and order.restaurant_id != app_scope_restaurant_id:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


def _latest_transaction(db: Session, order_id: uuid.UUID) -> PaymentTransaction | None:
    return db.scalar(
        select(PaymentTransaction)
        .where(PaymentTransaction.order_id == order_id)
        .order_by(PaymentTransaction.created_at.desc())
        .limit(1)
    )


def _attempt_count(db: Session, order_id: uuid.UUID) -> int:
    return len(
        list(
            db.scalars(
                select(PaymentTransaction.id).where(PaymentTransaction.order_id == order_id)
            )
        )
    )


def _status_response(db: Session, order: Order) -> PaymentStatusResponse:
    transaction = _latest_transaction(db, order.id)
    return PaymentStatusResponse(
        order_id=order.id,
        order_status=order.status,
        payment_status=order.payment_status,
        payment_method=order.payment_method,
        payment_reference=order.payment_reference,
        amount=order.total_amount,
        currency=order.currency,
        failure_code=transaction.failure_code if transaction else None,
        failure_message=transaction.failure_message if transaction else None,
        is_payable=(
            order.payment_method == PaymentMethod.CARD
            and order.payment_status in RETRYABLE_PAYMENT_STATUSES
            and order.status == OrderStatus.PAYMENT_PENDING
        ),
    )


def get_payment_status(
    db: Session,
    customer: User,
    order_id: uuid.UUID,
    *,
    app_scope_restaurant_id: uuid.UUID | None = None,
) -> PaymentStatusResponse:
    return _status_response(
        db,
        _load_customer_order(
            db, customer, order_id, app_scope_restaurant_id=app_scope_restaurant_id
        ),
    )


def create_payment_intent(
    db: Session,
    customer: User,
    order_id: uuid.UUID,
    *,
    app_scope_restaurant_id: uuid.UUID | None = None,
) -> PaymentIntentResponse:
    """Create (or reuse) the payment intent for a card order.

    The amount comes from the stored order total, never from the request, so a
    tampered client cannot pay less than the order is worth.
    """

    order = _load_customer_order(
        db, customer, order_id, app_scope_restaurant_id=app_scope_restaurant_id
    )

    if order.payment_method != PaymentMethod.CARD:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="This order is not a card order.",
        )
    if order.payment_status == PaymentStatus.PAID:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="This order has already been paid.",
        )
    if order.status == OrderStatus.CANCELLED:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="This order was cancelled and can no longer be paid.",
        )
    if order.payment_status not in RETRYABLE_PAYMENT_STATUSES:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="This order cannot be paid right now.",
        )

    provider = resolve_provider(order.payment_method)
    if provider is None or not provider.is_configured():
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Card payments are not available right now.",
        )

    # Reuse an intent that can still be paid; a double tap must not create two.
    existing = _latest_transaction(db, order.id)
    if existing is not None and existing.status in RETRYABLE_PAYMENT_STATUSES:
        try:
            remote = provider.retrieve_intent(existing.provider_intent_id)
        except PaymentProviderError:
            remote = None
        if (
            remote is not None
            and remote.status in REUSABLE_INTENT_STATUSES
            and remote.amount == order.total_amount
            and remote.client_secret
        ):
            return PaymentIntentResponse(
                order_id=order.id,
                payment_intent_id=remote.intent_id,
                client_secret=remote.client_secret,
                amount=remote.amount,
                currency=remote.currency,
                publishable_key=settings.stripe_publishable_key,
            )

    attempt = _attempt_count(db, order.id) + 1
    try:
        result = provider.create_intent(
            order_id=order.id,
            customer_id=customer.id,
            restaurant_id=order.restaurant_id,
            amount=order.total_amount,
            currency=order.currency,
            idempotency_key=f"order:{order.id}:attempt:{attempt}",
            # `orders` also has app_client_id and order_number columns, but the
            # Order model does not map them, so they are not readable here.
            metadata={
                "restaurant_location_id": str(order.restaurant_location_id),
            },
        )
    except PaymentProviderError as error:
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error

    transaction = PaymentTransaction(
        order_id=order.id,
        provider=provider.name,
        provider_intent_id=result.intent_id,
        status=PaymentStatus.PENDING,
        amount=result.amount,
        currency=result.currency,
    )
    db.add(transaction)
    order.payment_reference = result.intent_id
    order.payment_status = PaymentStatus.PENDING
    db.add(order)
    db.commit()

    return PaymentIntentResponse(
        order_id=order.id,
        payment_intent_id=result.intent_id,
        client_secret=result.client_secret,
        amount=result.amount,
        currency=result.currency,
        publishable_key=settings.stripe_publishable_key,
    )


def cancel_payment(
    db: Session,
    customer: User,
    order_id: uuid.UUID,
    *,
    app_scope_restaurant_id: uuid.UUID | None = None,
) -> PaymentStatusResponse:
    """Record that the customer dismissed the payment sheet.

    The order survives so it can be retried; only the attempt is cancelled.
    """

    order = _load_customer_order(
        db, customer, order_id, app_scope_restaurant_id=app_scope_restaurant_id
    )

    if order.payment_status == PaymentStatus.PAID:
        # The webhook won the race; do not undo a real payment.
        return _status_response(db, order)
    if order.payment_method != PaymentMethod.CARD:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="This order is not a card order.",
        )

    transaction = _latest_transaction(db, order.id)
    if transaction is not None and transaction.status in RETRYABLE_PAYMENT_STATUSES:
        provider = resolve_provider(order.payment_method)
        if provider is not None and provider.is_configured():
            provider.cancel_intent(transaction.provider_intent_id)
        transaction.status = PaymentStatus.CANCELLED
        db.add(transaction)

    order.payment_status = PaymentStatus.CANCELLED
    db.add(order)
    db.commit()
    return _status_response(db, order)


# --- webhooks --------------------------------------------------------------


def _record_webhook_event(db: Session, provider: str, event: WebhookEvent) -> bool:
    """Persist the event. Returns False when it was already recorded."""

    record = PaymentWebhookEvent(
        provider=provider,
        provider_event_id=event.event_id,
        event_type=event.event_type,
        payload=event.payload,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    return True


def _order_for_intent(db: Session, intent_id: str) -> tuple[Order, PaymentTransaction] | None:
    transaction = db.scalar(
        select(PaymentTransaction).where(PaymentTransaction.provider_intent_id == intent_id)
    )
    if transaction is None:
        return None
    order = db.get(Order, transaction.order_id)
    if order is None:
        return None
    return order, transaction


def _mark_paid(db: Session, order: Order, transaction: PaymentTransaction, event: WebhookEvent) -> None:
    if order.payment_status == PaymentStatus.PAID:
        return

    # Defence in depth: never mark an order paid for less than it costs.
    if event.amount is not None and event.amount < order.total_amount:
        logger.error(
            "Stripe amount mismatch order_id=%s expected=%s received=%s",
            order.id,
            order.total_amount,
            event.amount,
        )
        transaction.status = PaymentStatus.FAILED
        transaction.failure_code = "amount_mismatch"
        transaction.failure_message = (
            f"Captured {event.amount} for an order totalling {order.total_amount}"
        )
        order.payment_status = PaymentStatus.FAILED
        db.add_all([order, transaction])
        db.commit()
        return

    transaction.status = PaymentStatus.PAID
    transaction.failure_code = None
    transaction.failure_message = None
    order.payment_status = PaymentStatus.PAID
    order.payment_reference = transaction.provider_intent_id
    if order.status == OrderStatus.PAYMENT_PENDING:
        record_order_status_event(
            db,
            order=order,
            from_status=OrderStatus.PAYMENT_PENDING,
            to_status=OrderStatus.PLACED,
            actor=OrderEventActor.PAYMENT_PROVIDER,
            note="payment confirmed",
        )
        order.status = OrderStatus.PLACED
    db.add_all([order, transaction])
    db.commit()

    # Imported lazily: the order service imports the payment registry, so a
    # module-level import here would close the cycle.
    from app.services.orders import run_order_placed_side_effects

    customer = db.get(User, order.customer_id)
    if customer is not None:
        run_order_placed_side_effects(db, customer=customer, order_id=order.id)


def _mark_failed(db: Session, order: Order, transaction: PaymentTransaction, event: WebhookEvent) -> None:
    if order.payment_status == PaymentStatus.PAID:
        # A late failure event must not unpay a paid order.
        return
    transaction.status = PaymentStatus.FAILED
    transaction.failure_code = event.failure_code
    transaction.failure_message = event.failure_message
    order.payment_status = PaymentStatus.FAILED
    db.add_all([order, transaction])
    db.commit()


def _mark_cancelled(db: Session, order: Order, transaction: PaymentTransaction) -> None:
    if order.payment_status == PaymentStatus.PAID:
        return
    transaction.status = PaymentStatus.CANCELLED
    order.payment_status = PaymentStatus.CANCELLED
    db.add_all([order, transaction])
    db.commit()


def _mark_refunded(db: Session, order: Order, transaction: PaymentTransaction) -> None:
    transaction.status = PaymentStatus.REFUNDED
    order.payment_status = PaymentStatus.REFUNDED
    db.add_all([order, transaction])
    db.commit()


def handle_stripe_webhook(db: Session, *, payload: bytes, signature: str | None) -> dict[str, str]:
    """Verify, deduplicate, and apply a Stripe event.

    Raises 400 only for an unverifiable payload. Anything else returns 2xx so
    Stripe stops retrying an event we have durably recorded.
    """

    provider = get_stripe_provider()
    try:
        event = provider.parse_webhook(payload=payload, signature=signature)
    except WebhookVerificationError as error:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error

    if not _record_webhook_event(db, provider.name, event):
        return {"status": "duplicate", "event_id": event.event_id}

    handled = "ignored"
    if event.intent_id:
        found = _order_for_intent(db, event.intent_id)
        if found is None:
            logger.warning(
                "Stripe event %s references unknown intent %s", event.event_id, event.intent_id
            )
        else:
            order, transaction = found
            if event.event_type == "payment_intent.succeeded":
                _mark_paid(db, order, transaction, event)
                handled = "paid"
            elif event.event_type == "payment_intent.payment_failed":
                _mark_failed(db, order, transaction, event)
                handled = "failed"
            elif event.event_type == "payment_intent.canceled":
                _mark_cancelled(db, order, transaction)
                handled = "cancelled"
            elif event.event_type == "charge.refunded":
                _mark_refunded(db, order, transaction)
                handled = "refunded"

    record = db.scalar(
        select(PaymentWebhookEvent).where(PaymentWebhookEvent.provider_event_id == event.event_id)
    )
    if record is not None:
        record.processed_at = datetime.now(UTC)
        db.add(record)
        db.commit()

    return {"status": handled, "event_id": event.event_id}


# --- cleanup ---------------------------------------------------------------


def reap_expired_unpaid_orders(db: Session, *, now: datetime | None = None) -> int:
    """Cancel card orders that were never paid, and their Stripe intents.

    Without this, an abandoned checkout sits in the customer's order list
    forever and holds an open intent at the provider.
    """

    ttl_minutes = max(1, settings.payment_intent_ttl_minutes)
    cutoff = (now or datetime.now(UTC)) - timedelta(minutes=ttl_minutes)

    stale_orders = list(
        db.scalars(
            select(Order).where(
                Order.status == OrderStatus.PAYMENT_PENDING,
                Order.payment_method == PaymentMethod.CARD,
                Order.placed_at < cutoff,
            )
        )
    )
    if not stale_orders:
        return 0

    provider = resolve_provider(PaymentMethod.CARD)
    cancelled = 0
    for order in stale_orders:
        if order.payment_status == PaymentStatus.PAID:
            continue
        transaction = _latest_transaction(db, order.id)
        if transaction is not None and transaction.status in RETRYABLE_PAYMENT_STATUSES:
            if provider is not None and provider.is_configured():
                provider.cancel_intent(transaction.provider_intent_id)
            transaction.status = PaymentStatus.CANCELLED
            db.add(transaction)
        # Records the reason alongside the cancellation. Every cancellation on
        # this platform is system-derived, so it is always knowable here.
        mark_order_cancelled(
            db,
            order=order,
            reason=OrderCancellationReason.PAYMENT_NOT_COMPLETED,
            actor=OrderEventActor.SYSTEM,
            note="unpaid card order past its intent TTL",
        )
        order.status = OrderStatus.CANCELLED
        order.payment_status = PaymentStatus.CANCELLED
        db.add(order)
        cancelled += 1

    db.commit()
    logger.info("Reaped %s unpaid card orders older than %s minutes", cancelled, ttl_minutes)
    return cancelled


def payment_config() -> dict[str, object]:
    """Client bootstrap: publishable key and the methods this deployment offers."""

    return {
        "publishable_key": settings.stripe_publishable_key
        if settings.stripe_is_configured
        else "",
        "stripe_enabled": settings.stripe_is_configured,
        "currency": settings.payment_currency.upper(),
        "supported_methods": [method.value for method in available_payment_methods()],
    }


__all__ = [
    "cancel_payment",
    "create_payment_intent",
    "get_payment_status",
    "handle_stripe_webhook",
    "payment_config",
    "provider_name_for",
    "reap_expired_unpaid_orders",
]

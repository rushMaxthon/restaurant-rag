"""Payment orchestration: intents, cancellation, webhooks, and cleanup.

The rule this module exists to enforce: **only a verified provider event can
mark an order paid.** Nothing a client sends is trusted — not the amount, not
the provider, not the reference.
"""

from __future__ import annotations

import json
import logging
from functools import partial
from typing import Callable
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.currency import currency_for
from app.models.enums import (
    OrderScheduleType,
    OrderCancellationReason,
    OrderEventActor,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)
from app.models.order import Order
from app.models.payment import PaymentTransaction, PaymentWebhookEvent
from app.models.user import User
from app.schemas.payment import PaymentIntentResponse, PaymentLinkResponse, PaymentStatusResponse
from app.services.order_events import mark_order_cancelled, record_order_status_event
from app.services.payments.base import (
    PaymentProviderError,
    WebhookEvent,
    WebhookVerificationError,
)
from app.models.enums import PaymentGateway
from app.services.payment_accounts import read_credentials
from app.services.payments.razorpay_provider import RAZORPAY_WEBHOOK_EVENTS
from app.services.payments.registry import (
    GATEWAY_FOR_METHOD,
    available_payment_methods,
    build_provider,
    platform_provider_for,
    provider_for,
    provider_name_for,
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
    order = _load_customer_order(
        db, customer, order_id, app_scope_restaurant_id=app_scope_restaurant_id
    )
    # The client polls this endpoint while it waits for the webhook. Asking the
    # provider directly here is what stops a lost or late webhook from stranding
    # a genuinely paid order at PENDING forever.
    _reconcile_with_provider(db, order)
    return _status_response(db, order)


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

    if order.payment_method == PaymentMethod.COD:
        # Nothing to pay online. Every other method settles through a gateway
        # and can be sent a link; this used to refuse everything but CARD,
        # which left a Razorpay restaurant's chat orders with no way to pay
        # at all — and the chat is exactly where a link is the only way.
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="This order is paid in cash, so there is nothing to pay online.",
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

    provider = provider_for(db, restaurant_id=order.restaurant_id, method=order.payment_method)
    if provider is None or not provider.is_configured():
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="That payment method is not available right now.",
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


def create_payment_link(
    db: Session,
    customer: User,
    order_id: uuid.UUID,
    *,
    app_scope_restaurant_id: uuid.UUID | None = None,
) -> PaymentLinkResponse:
    """A link the customer can pay on, for an order that is theirs.

    Every guard `create_payment_intent` applies is applied here, for the same
    reasons: the amount is read off the stored order, a paid or cancelled
    order is refused, and a provider that is not configured fails loudly
    rather than handing back a dead link.

    The idempotency key is per ORDER rather than per attempt, which is the one
    real difference. An intent is consumed by the sheet that requested it; a
    link is sent to someone and may be tapped later, twice, or forwarded. A
    stable key means Stripe returns the SAME session every time, so a customer
    can never be holding two payable links for one order.
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

    provider = provider_for(db, restaurant_id=order.restaurant_id, method=order.payment_method)
    if provider is None or not provider.is_configured():
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Card payments are not available right now.",
        )
    if not hasattr(provider, "create_checkout_session"):
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment links are not available right now.",
        )

    success_url, cancel_url = _return_urls(order)
    try:
        result = provider.create_checkout_session(
            order_id=order.id,
            customer_id=customer.id,
            restaurant_id=order.restaurant_id,
            amount=order.total_amount,
            currency=order.currency,
            description=f"Order {str(order.id)[:8]}",
            customer_email=getattr(customer, "email", None),
            success_url=success_url,
            cancel_url=cancel_url,
            idempotency_key=f"order:{order.id}:checkout",
            metadata={"restaurant_location_id": str(order.restaurant_location_id)},
        )
    except PaymentProviderError as error:
        raise HTTPException(
            status_code=http_status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error

    # The same session comes back on a repeat, and with it the same intent —
    # so the transaction row is created once and found thereafter. The unique
    # index on `provider_intent_id` would refuse a second anyway; this is what
    # keeps that from being an error the customer sees.
    existing = db.scalar(
        select(PaymentTransaction).where(PaymentTransaction.provider_intent_id == result.intent_id)
    )
    if existing is None:
        db.add(
            PaymentTransaction(
                order_id=order.id,
                provider=provider.name,
                provider_intent_id=result.intent_id,
                status=PaymentStatus.PENDING,
                amount=result.amount,
                currency=result.currency,
            )
        )
    order.payment_reference = result.intent_id
    order.payment_status = PaymentStatus.PENDING
    db.add(order)
    db.commit()

    logger.info(
        "Payment link issued order_id=%s intent_id=%s", order.id, result.intent_id
    )
    return PaymentLinkResponse(
        order_id=order.id,
        url=result.url,
        amount=result.amount,
        currency=result.currency,
        expires_at=(
            datetime.fromtimestamp(result.expires_at, tz=UTC) if result.expires_at else None
        ),
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
        provider = provider_for(db, restaurant_id=order.restaurant_id, method=order.payment_method)
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


def _reconcile_with_provider(db: Session, order: Order) -> None:
    """Ask the provider what really became of a card order that still looks unpaid.

    Webhooks are the primary path, but delivery is not guaranteed: Stripe gives
    up after its retry window, an endpoint can be registered late or not at all,
    and a sleeping free-tier instance can miss the window entirely. Any of those
    leaves a customer who was actually charged looking at PENDING forever, and
    leaves the reaper ready to cancel the order out from under them.

    This does not weaken the rule at the top of this module. The intent is read
    straight from the provider over an authenticated server-to-server call --
    the same source of truth the webhook carries, pulled instead of pushed.
    Nothing the client sent is consulted, and the amount check in `_mark_paid`
    still applies.

    Deliberately silent on failure: a status read must keep working during a
    provider outage, and the next poll simply tries again.
    """

    if order.payment_method != PaymentMethod.CARD:
        return
    if order.payment_status not in RETRYABLE_PAYMENT_STATUSES:
        return

    transaction = _latest_transaction(db, order.id)
    if transaction is None or not transaction.provider_intent_id:
        return

    provider = provider_for(db, restaurant_id=order.restaurant_id, method=PaymentMethod.CARD)
    if provider is None or not provider.is_configured():
        return

    try:
        remote = provider.retrieve_intent(transaction.provider_intent_id)
    except PaymentProviderError as error:
        logger.warning(
            "Payment reconciliation failed order_id=%s intent=%s error=%s",
            order.id,
            transaction.provider_intent_id,
            error,
        )
        return

    if remote.status != "succeeded":
        return

    logger.info(
        "Reconciled paid order missed by webhook order_id=%s intent=%s",
        order.id,
        remote.intent_id,
    )
    # `_mark_paid` is idempotent, so the real webhook arriving later is a no-op.
    _mark_paid(
        db,
        order,
        transaction,
        WebhookEvent(
            event_id=f"reconcile:{remote.intent_id}",
            event_type="payment_intent.succeeded",
            intent_id=remote.intent_id,
            amount=remote.amount,
            currency=remote.currency,
        ),
    )


# What an event means, in the two vocabularies that reach this module.
#
# Stripe's own event names on the left of each set; the normalised words on the
# right come from `razorpay_provider`, which cannot use Stripe's names because
# Razorpay does not have PaymentIntents. Both are accepted here rather than
# forcing one gateway to speak the other's language, which is how a mapping
# quietly stops matching after somebody renames a constant.
_PAID_EVENTS = frozenset(
    {"payment_intent.succeeded", "checkout.session.completed", "succeeded"}
)
_FAILED_EVENTS = frozenset({"payment_intent.payment_failed", "failed"})
_CANCELLED_EVENTS = frozenset({"payment_intent.canceled", "cancelled"})
_REFUNDED_EVENTS = frozenset({"charge.refunded", "refunded"})


def webhook_events_for(gateway: PaymentGateway) -> tuple[str, ...]:
    """The gateway's own event names this app acts on, for its dashboard.

    Derived rather than listed. Razorpay's come from the provider's map;
    Stripe's from the four sets above, where a dotted name is Stripe's and a
    bare word is the normalised one Razorpay is translated into — the same
    distinction the comment above those sets already draws. So teaching the
    webhook a new event updates what the screen tells an operator to tick,
    with nothing to remember.
    """

    if gateway == PaymentGateway.RAZORPAY:
        return RAZORPAY_WEBHOOK_EVENTS
    stripe_names = {
        name
        for names in (_PAID_EVENTS, _FAILED_EVENTS, _CANCELLED_EVENTS, _REFUNDED_EVENTS)
        for name in names
        if "." in name
    }
    return tuple(sorted(stripe_names))


def webhook_url_for(gateway: PaymentGateway, *, restaurant_id: uuid.UUID) -> str | None:
    """Where this restaurant's gateway should post its events, or None.

    None means `public_base_url` is unset, and the screen says to set it. The
    alternative — guessing from the request's own Host header — would put
    whatever address the admin happens to be open on into a field that has to
    be reachable from the gateway's servers, and `localhost` pasted into
    Razorpay fails silently for as long as nobody looks.
    """

    base = (get_settings().public_base_url or "").strip().rstrip("/")
    if not base:
        return None
    prefix = get_settings().api_v1_prefix.rstrip("/")
    return f"{base}{prefix}/payments/webhook/{gateway.value}/{restaurant_id}"


def _apply_webhook_event(
    db: Session, *, provider_name: str, event: WebhookEvent
) -> dict[str, str]:
    """Record a verified event and move the order it refers to.

    Shared by the platform's Stripe endpoint and the per-restaurant one, so
    the two cannot drift into treating the same outcome differently. Verifying
    the signature is the caller's job and has already happened by here — this
    function trusts its `event` completely, which is exactly why nothing
    unverified may reach it.
    """

    if not _record_webhook_event(db, provider_name, event):
        return {"status": "duplicate", "event_id": event.event_id}

    handled = "ignored"
    # What to say once the change is safely recorded. Said after the commit
    # below, never inside it: a message is not worth a database transaction
    # held open on a call to Meta.
    announce: Callable[[], None] | None = None
    if event.intent_id:
        found = _order_for_intent(db, event.intent_id)
        if found is None:
            logger.warning(
                "%s event %s references unknown intent %s",
                provider_name,
                event.event_id,
                event.intent_id,
            )
        else:
            order, transaction = found
            if event.event_type in _PAID_EVENTS:
                _mark_paid(db, order, transaction, event)
                handled = "paid"
                announce = partial(_confirm_in_chat, order)
            elif event.event_type in _FAILED_EVENTS:
                _mark_failed(db, order, transaction, event)
                handled = "failed"
                announce = partial(_report_failure_in_chat, db, order, transaction)
            elif event.event_type in _CANCELLED_EVENTS:
                _mark_cancelled(db, order, transaction)
                handled = "cancelled"
                announce = partial(_report_cancelled_in_chat, order)
            elif event.event_type in _REFUNDED_EVENTS:
                _mark_refunded(db, order, transaction)
                handled = "refunded"
                announce = partial(_report_refunded_in_chat, order)

    record = db.scalar(
        select(PaymentWebhookEvent).where(PaymentWebhookEvent.provider_event_id == event.event_id)
    )
    if record is not None:
        record.processed_at = datetime.now(UTC)
        db.add(record)
        db.commit()

    if announce is not None:
        announce()

    return {"status": handled, "event_id": event.event_id}


def handle_gateway_webhook(
    db: Session,
    *,
    gateway: PaymentGateway,
    restaurant_id: uuid.UUID,
    payload: bytes,
    signature: str | None,
) -> dict[str, str]:
    """A webhook for one restaurant's own gateway account.

    **The restaurant comes from the URL, not from the body.** Each restaurant
    holds its own webhook secret, so the secret to verify with has to be known
    before anything in the payload is believed — and the only thing available
    before verification is the address the request arrived at. Every gateway
    lets an account configure its own webhook URL, so each restaurant's
    dashboard points at its own path here.

    The alternative — read the order id out of the body, find our order, learn
    the restaurant, then verify — means making a database decision on an
    unverified payload. It works, and it is the shape to avoid: it puts a
    lookup driven by attacker-controlled input in front of the check that
    exists to establish whether the input is trustworthy at all.

    Posting to another restaurant's URL fails, because the signature will not
    match that restaurant's secret. A restaurant with no webhook secret stored
    refuses everything rather than trusting anything, which is a configuration
    problem the admin screen already reports.
    """

    method = next(
        (m for m, g in GATEWAY_FOR_METHOD.items() if g == gateway),
        None,
    )
    if method is None:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="Unknown payment gateway.",
        )

    # `require_enabled=False`: a gateway that has just been paused is still
    # owed the confirmations for money it already took. Refusing them would
    # leave paid orders sitting unpaid in this database.
    credentials = read_credentials(
        db, restaurant_id=restaurant_id, gateway=gateway, require_enabled=False
    )
    if credentials is None:
        # Deliberately not 404: the caller is a gateway, not a person, and
        # what it needs to know is that this delivery cannot be accepted.
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="This restaurant has no credentials for that gateway.",
        )

    provider = build_provider(gateway, credentials)
    try:
        event = provider.parse_webhook(payload=payload, signature=signature)
    except WebhookVerificationError as error:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error

    return _apply_webhook_event(db, provider_name=provider.name, event=event)


def confirm_razorpay_checkout(
    db: Session,
    *,
    order: Order,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> dict[str, str]:
    """Believe a success the browser reported, once it is signed.

    Razorpay Checkout hands the browser three values and the browser posts
    them back. Without this check a customer could post a made-up payment id
    and have an order marked paid — so the signature is verified against the
    restaurant's own API secret before anything moves.

    This is the fast path, not the source of truth. The webhook is what
    settles an order whose customer closed the tab before the callback ran,
    and both routes end at `_mark_paid`, which is idempotent.
    """

    credentials = read_credentials(
        db, restaurant_id=order.restaurant_id, gateway=PaymentGateway.RAZORPAY
    )
    if credentials is None:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Razorpay is not available for this restaurant.",
        )

    provider = build_provider(PaymentGateway.RAZORPAY, credentials)
    if not provider.verify_checkout_signature(
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
        razorpay_signature=razorpay_signature,
    ):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="That payment could not be verified.",
        )

    transaction = _latest_transaction(db, order.id)
    if transaction is None or transaction.provider_intent_id != razorpay_order_id:
        # The signature was genuine but names an order that is not this one.
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="That payment belongs to a different order.",
        )

    _mark_paid(
        db,
        order,
        transaction,
        WebhookEvent(
            event_id=f"checkout:{razorpay_payment_id}",
            event_type="succeeded",
            intent_id=razorpay_order_id,
            amount=order.total_amount,
            currency=order.currency,
        ),
    )
    db.commit()
    _confirm_in_chat(order)
    return {"status": "paid", "order_id": str(order.id)}


def handle_stripe_webhook(db: Session, *, payload: bytes, signature: str | None) -> dict[str, str]:
    """Verify, deduplicate, and apply a Stripe event.

    Raises 400 only for an unverifiable payload. Anything else returns 2xx so
    Stripe stops retrying an event we have durably recorded.
    """

    # Still the platform's own Stripe endpoint. Per-restaurant webhooks need
    # the order looked up from the payload FIRST, to know whose secret to
    # verify with — see `handle_gateway_webhook` below, which does that for
    # restaurants holding their own accounts.
    provider = platform_provider_for(PaymentMethod.CARD)
    if provider is None:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="This deployment has no platform payment account.",
        )
    try:
        event = provider.parse_webhook(payload=payload, signature=signature)
    except WebhookVerificationError as error:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error

    return _apply_webhook_event(db, provider_name=provider.name, event=event)


def _return_urls(order: Order) -> tuple[str, str]:
    """Where Stripe sends the customer once they have paid, or given up.

    A web order goes back to the web app, as it always has. An order placed
    in a chat is being paid on a phone, and `frontend_base_url` on a phone is
    the phone — so it returns to a page this API serves at its public
    address instead, which says the payment landed and points back to the
    chat. With no public address configured, chat orders take the web path
    too, which is the behaviour this deployment had before.
    """

    web = settings.frontend_base_url.rstrip("/")
    web_urls = (f"{web}/orders/{order.id}?paid=1", f"{web}/orders/{order.id}")

    public = (settings.public_base_url or "").strip().rstrip("/")
    if not public:
        return web_urls
    from app.services.ordering_agent import order_channel

    if not order_channel.phone_for(order.id):
        return web_urls
    return (
        f"{public}/api/payments/return/{order.id}?outcome=paid",
        f"{public}/api/payments/return/{order.id}?outcome=cancelled",
    )


def _scheduled_line(order: Order) -> str:
    """' It is scheduled for Thu 10:30.' for an order placed for later."""

    if getattr(order, "schedule_type", None) != OrderScheduleType.SCHEDULED or not order.scheduled_at:
        return ""
    from app.services.restaurant_locations import BUSINESS_TIMEZONE

    when = order.scheduled_at.astimezone(BUSINESS_TIMEZONE).strftime("%a %H:%M")
    return f" It is scheduled for {when}."


def _tell_in_chat(order: Order, body: str, *, finished: bool) -> None:
    """Say something about this order where it was placed, if it was a chat.

    Never raises, and never fails the webhook. Stripe reads anything but a
    200 as a delivery to retry, and retrying a payment that was recorded
    perfectly well because a message would not send is the tail wagging the
    dog — so a failure here is logged and the payment stands.

    `finished` says whether anything more can happen to this order. A paid,
    cancelled or refunded order is done and the conversation is forgotten; a
    failed one is not, because the next thing that happens may well be the
    customer paying.
    """

    from app.services.ordering_agent import order_channel

    phone = order_channel.phone_for(order.id)
    if not phone:
        return  # A web order, or a chat order old enough to have expired.

    try:
        from app.tasks.whatsapp import send_text

        if send_text(phone, body):
            logger.info("Told a customer about their order in chat order_id=%s", order.id)
            if finished:
                order_channel.forget(order.id)
        else:
            logger.warning("Could not reach a customer in chat order_id=%s", order.id)
    except Exception:  # noqa: BLE001 - the payment is recorded whether or not we can say so
        logger.warning(
            "Telling a customer about their order raised order_id=%s", order.id, exc_info=True
        )


def _called(order: Order) -> str:
    """How to address this customer in a message, including the space.

    Empty when we have no name worth saying, so every line it appears in
    reads correctly without one.
    """

    from app.services.ordering_agent.order_draft import first_name

    name = first_name(getattr(order, "contact_name", None))
    return f" {name}" if name else ""


def _confirm_in_chat(order: Order) -> None:
    """The payment landed."""

    _tell_in_chat(
        order,
        f"Payment received, thank you{_called(order)}. Your order is confirmed and the kitchen "
        f"has it.{_scheduled_line(order)}\n\nTotal paid: ${order.total_amount:.2f}\n"
        f"Order reference: {str(order.id)[:8]}",
        finished=True,
    )


def _report_failure_in_chat(db: Session, order: Order, transaction: PaymentTransaction) -> None:
    """The payment did not go through, and here is the way to try again.

    Silence after a declined card reads exactly like a success, and the cart
    was emptied when the order was placed — so without a link back there is
    no way to pay through the conversation at all.
    """

    # The bank's own words when they are short enough to be useful; a card
    # number in the wrong century is something only the customer can fix.
    reason = (transaction.failure_message or "").strip().rstrip(".")
    because = f" ({reason})" if 0 < len(reason) <= 90 else ""
    retry = ""
    try:
        customer = order.customer
        if customer is not None:
            # Idempotent per order, and a Checkout session stays open after a
            # declined attempt: this is the same page, ready for another card.
            link = create_payment_link(db, customer, order.id)
            if link.url:
                from app.services.short_links import shorten

                retry = f"\n\nTry again here:\n{shorten(link.url)}"
    except Exception:  # noqa: BLE001 - a failure is worth reporting without a link
        logger.warning("Could not offer a retry link order_id=%s", order.id, exc_info=True)

    _tell_in_chat(
        order,
        f"Your payment did not go through{because}. Nothing has been charged and "
        f"your order is still held{_called(order)}.{retry}",
        # Not finished: the next thing that happens may well be them paying.
        finished=False,
    )


def _report_cancelled_in_chat(order: Order) -> None:
    """The payment sheet was dismissed, and what they chose is not lost.

    This used to end the conversation — "tell me when you would like to
    order again" — with the cart emptied at placement and the order
    cancelled by the webhook. Everything they had chosen was gone, and
    starting from nothing is how a customer decides not to bother.
    """

    _offer_the_dishes_back(order)
    _tell_in_chat(
        order,
        f"Your payment was cancelled{_called(order)}, so the order has not gone to the "
        "kitchen and nothing has been charged.\n\n"
        "Shall I put those dishes back in your basket?",
        # Not finished: the answer to that question arrives in this thread.
        finished=False,
    )


def _offer_the_dishes_back(order: Order) -> None:
    """Hold the question, so "yes" on the next turn means these dishes.

    The conversation's own mechanism — the same standing question the agent
    uses — reached from here because this is where the news arrives.
    """

    from app.services.ordering_agent import order_channel, order_draft

    phone = order_channel.phone_for(order.id)
    if not phone:
        return
    try:
        from app.tasks.whatsapp import session_for

        session_id = session_for(phone)
        draft = order_draft.load(session_id)
        draft.awaiting = json.dumps({
            "question": "Shall I put those dishes back in your basket?",
            "yes": "restore_cart",
            "subject": str(order.id),
            "asks": "Shall I put those dishes back in your basket?",
        })
        order_draft.save(session_id, draft)
    except Exception:  # noqa: BLE001 - an offer that cannot be held is still made
        logger.warning("Could not hold the basket question for %s", order.id, exc_info=True)


def _report_refunded_in_chat(order: Order) -> None:
    _tell_in_chat(
        order,
        f"Your refund of ${order.total_amount:.2f} is on its way back to the card you "
        "paid with. Banks usually take a few working days to show it.",
        finished=True,
    )


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

    cancelled = 0
    for order in stale_orders:
        # Resolved per order, not once for the batch. These orders come from
        # every restaurant on the platform and each one settles through its
        # own gateway account — a single provider hoisted out of the loop
        # would cancel one restaurant's intents against another's account.
        provider = provider_for(
            db, restaurant_id=order.restaurant_id, method=PaymentMethod.CARD
        )
        # Confirm with the provider before cancelling. Cancelling an order whose
        # webhook was merely lost would leave the customer charged for an order
        # we told them was cancelled.
        _reconcile_with_provider(db, order)
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


def payment_config(
    db: Session | None = None,
    *,
    currency: str | None = None,
    restaurant_id: uuid.UUID | None = None,
    location: "RestaurantLocation | None" = None,
) -> dict[str, object]:
    """Client bootstrap: publishable key, methods on offer, and the currency.

    `currency` is the calling app's restaurant's. None — the marketplace, the
    admin panel, curl — falls back to the platform default, because there is
    no single right answer across restaurants that charge in different money.
    """

    # The public key of every gateway this restaurant can settle through.
    # Razorpay Checkout cannot open without its `key_id`, and the browser has
    # no other way to obtain it. Nothing secret is in here — each of these is
    # already in the page source of the checkout that uses it.
    gateway_keys: dict[str, str] = {}
    if db is not None and restaurant_id is not None:
        for method in available_payment_methods(
            db, restaurant_id=restaurant_id, location=location
        ):
            gateway = GATEWAY_FOR_METHOD.get(method)
            if gateway is None:
                continue
            credentials = read_credentials(db, restaurant_id=restaurant_id, gateway=gateway)
            if credentials is not None and credentials.public_key:
                gateway_keys[gateway.value] = credentials.public_key

    return {
        "gateway_keys": gateway_keys,
        # Stripe's own, still separate: a restaurant with no Stripe account of
        # its own is settled through the platform's, and that key is not in
        # `gateway_keys` because it does not belong to the restaurant.
        "publishable_key": (
            gateway_keys.get(PaymentGateway.STRIPE.value)
            or (settings.stripe_publishable_key if settings.stripe_is_configured else "")
        ),
        "stripe_enabled": settings.stripe_is_configured,
        "currency": currency_for(currency or settings.payment_currency).code,
        # This restaurant's methods, not the deployment's. A caller with no
        # database session — there is one, in a test — gets the empty list
        # rather than a wrong one.
        "supported_methods": (
            [
                method.value
                for method in available_payment_methods(
                    db, restaurant_id=restaurant_id, location=location
                )
            ]
            if db is not None
            else []
        ),
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

"""Moving one order's share to its restaurant, and recording every step.

Every function here is safe to call twice. Three things make it so:

- **One row per order** (`restaurant_payouts.order_id` is unique).
- **A row lock around every Razorpay call** (`with_for_update`). Two workers
  handed the same order serialise on the row, and the second one finds the
  `transfer_id` the first one wrote.
- **A row that holds a `transfer_id` is never transferred again.** Razorpay
  would accept a second transfer from the same payment as long as the total
  stays under the payment, so this check is the only thing between a retry
  and paying a restaurant twice.

Razorpay is only called from Celery, after the order's own transaction has
committed (`queue_payout_step`), and only with `ENABLE_RESTAURANT_PAYOUTS`
on. With it off, every row is still written and computed, so the screen
shows what would be paid.

Nothing here may cost a sale. The order path calls `record_paid_order` and
`queue_payout_step` inside try/except, and a refusal from Razorpay becomes
`FAILED` on the row, never an error on the order.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import OrderStatus, PaymentMethod, PaymentStatus, PayoutStatus
from app.models.order import Order
from app.models.payment import PaymentTransaction
from app.models.restaurant_payout import RestaurantPayout
from app.services.payments.base import PaymentProviderError
from app.services.payouts.accounts import get_account, payout_account_active
from app.services.payouts.split import split_order

logger = logging.getLogger(__name__)

_STEPS = {"transfer", "release", "reverse"}


def default_client():
    """The Route client on the platform's account, or None when it has none."""

    from app.services.payments.registry import platform_razorpay_provider
    from app.services.payouts.route_client import RouteClient

    provider = platform_razorpay_provider(require_enabled=False)
    return RouteClient(provider) if provider is not None else None


def _latest_transaction(db: Session, order_id: uuid.UUID) -> PaymentTransaction | None:
    return db.scalar(
        select(PaymentTransaction)
        .where(PaymentTransaction.order_id == order_id)
        .order_by(PaymentTransaction.created_at.desc())
        .limit(1)
    )


def record_paid_order(db: Session, order: Order, transaction: PaymentTransaction | None) -> RestaurantPayout:
    """Write this order's ledger row, once. Inside the caller's transaction."""

    existing = db.scalar(select(RestaurantPayout).where(RestaurantPayout.order_id == order.id))
    if existing is not None:
        return existing

    split = split_order(order)
    on_platform = bool(transaction is not None and transaction.on_platform_account)
    if order.payment_method == PaymentMethod.COD or not on_platform:
        status, error = PayoutStatus.NOT_APPLICABLE, None
    elif split.blocked_reason:
        status, error = PayoutStatus.BLOCKED, split.blocked_reason
    else:
        status, error = PayoutStatus.WAITING_ACCOUNT, None

    row = RestaurantPayout(
        order_id=order.id,
        restaurant_id=order.restaurant_id,
        payment_id=(transaction.provider_payment_id or "") if transaction is not None else "",
        restaurant_share=split.restaurant_share,
        platform_keeps=split.platform_keeps,
        currency=order.currency or "INR",
        status=status.value,
        last_error=error,
    )
    db.add(row)
    db.flush()
    return row


def queue_payout_step(db: Session, step: str, order_id: uuid.UUID) -> None:
    """Run a step in Celery once the caller's transaction commits. Never raises."""

    if step not in _STEPS:
        raise ValueError(step)
    from app.services.payouts.webhooks import after_commit_task

    after_commit_task(db, f"app.tasks.payouts.{step}_payout_task", order_id=str(order_id))


def note_partial_refund(db: Session, order_id: uuid.UUID, refunded) -> None:
    """Write a refund that was not the whole order onto its payout row."""

    row = db.scalar(select(RestaurantPayout).where(RestaurantPayout.order_id == order_id))
    if row is None:
        return
    amount = f"{refunded}" if refunded is not None else "an unknown amount"
    row.last_error = (
        f"A refund of {amount} was made on this order. The restaurant's share was not taken "
        "back automatically; reverse it by hand if the restaurant should bear it."
    )


def _locked_row(db: Session, order_id: uuid.UUID) -> RestaurantPayout | None:
    return db.scalar(
        select(RestaurantPayout).where(RestaurantPayout.order_id == order_id).with_for_update()
        .execution_options(populate_existing=True)
    )


def _ensure_row(db: Session, order: Order) -> RestaurantPayout:
    row = _locked_row(db, order.id)
    if row is None:
        record_paid_order(db, order, _latest_transaction(db, order.id))
        db.commit()
        row = _locked_row(db, order.id)
    return row


def _fail(db: Session, row: RestaurantPayout, error: PaymentProviderError) -> None:
    row.attempts += 1
    row.last_error = str(error)
    if not error.retryable:
        row.status = PayoutStatus.FAILED.value
    db.commit()


def transfer(db: Session, order_id: uuid.UUID, *, client: Any = None) -> RestaurantPayout | None:
    order = db.get(Order, order_id, populate_existing=True)
    if order is None:
        return None
    row = _ensure_row(db, order)
    if row.status != PayoutStatus.WAITING_ACCOUNT.value or row.transfer_id:
        db.commit()
        return row
    # The order, not the row, decides whether anything is owed: a capture
    # that lands after the order was reaped, or a Retry on a refunded one,
    # must not pay a restaurant for food it never cooked.
    if order.status == OrderStatus.CANCELLED or order.payment_status != PaymentStatus.PAID:
        row.status = PayoutStatus.NOT_APPLICABLE.value
        row.last_error = "The order was cancelled or refunded before anything was paid out."
        db.commit()
        return row
    if not get_settings().enable_restaurant_payouts or not payout_account_active(db, order.restaurant_id):
        db.commit()
        return row
    if not row.payment_id:
        # Paid through the browser before the confirmation recorded payment
        # ids, or the webhook carrying it has not arrived yet.
        transaction = _latest_transaction(db, order.id)
        row.payment_id = (transaction.provider_payment_id or "") if transaction is not None else ""
    if not row.payment_id:
        row.last_error = "Waiting for Razorpay's payment id for this order; the webhook will bring it."
        db.commit()
        return row

    client = client or default_client()
    if client is None:
        row.last_error = "The platform has no Razorpay account configured."
        db.commit()
        return row
    account = get_account(db, order.restaurant_id)
    delivered = order.status == OrderStatus.DELIVERED
    try:
        # A create that timed out may still have been accepted; adopt that
        # transfer rather than making a second one. See `find_transfer`.
        state = client.find_transfer(payment_id=row.payment_id, order_id=order.id) or client.create_transfer(
            payment_id=row.payment_id, account_id=account.razorpay_account_id,
            amount=row.restaurant_share, currency=row.currency, order_id=order.id, on_hold=not delivered,
        )
    except PaymentProviderError as error:
        _fail(db, row, error)
        if error.retryable:
            raise
        return row

    row.transfer_id = state.transfer_id
    row.attempts += 1
    row.last_error = None
    if delivered and state.on_hold:
        # Adopted a transfer made on hold before the order was delivered.
        client.release(state.transfer_id)
    if delivered:
        row.status = PayoutStatus.RELEASED.value
        row.released_at = datetime.now(UTC)
    else:
        row.status = PayoutStatus.HELD.value
    db.commit()
    return row


def release(db: Session, order_id: uuid.UUID, *, client: Any = None) -> RestaurantPayout | None:
    order = db.get(Order, order_id, populate_existing=True)
    if order is None:
        return None
    row = _ensure_row(db, order)
    if row.status == PayoutStatus.WAITING_ACCOUNT.value:
        db.commit()
        return transfer(db, order_id, client=client)
    if row.status != PayoutStatus.HELD.value or not row.transfer_id or not get_settings().enable_restaurant_payouts:
        db.commit()
        return row
    client = client or default_client()
    if client is None:
        db.commit()
        return row
    try:
        client.release(row.transfer_id)
    except PaymentProviderError as error:
        _fail(db, row, error)
        if error.retryable:
            raise
        return row
    row.status = PayoutStatus.RELEASED.value
    row.released_at = datetime.now(UTC)
    row.last_error = None
    db.commit()
    return row


def reverse(db: Session, order_id: uuid.UUID, *, client: Any = None) -> RestaurantPayout | None:
    order = db.get(Order, order_id, populate_existing=True)
    if order is None:
        return None
    row = _ensure_row(db, order)
    # Only a cancelled or refunded order is reversed. A reversal queued by a
    # write that was later undone, or a stray Retry, must not claw back the
    # share of an order that is still going ahead.
    if order.status != OrderStatus.CANCELLED and order.payment_status != PaymentStatus.REFUNDED:
        db.commit()
        return row
    if row.status in {PayoutStatus.WAITING_ACCOUNT.value, PayoutStatus.BLOCKED.value}:
        row.status = PayoutStatus.NOT_APPLICABLE.value
        row.last_error = "Cancelled or refunded before anything was paid out."
        db.commit()
        return row
    if row.status == PayoutStatus.SETTLED.value:
        # Already in the restaurant's bank. Razorpay can claw it back from
        # the linked account's balance, but that is a decision for a person.
        row.last_error = "Cancelled or refunded after the share reached the restaurant's bank; recover it by hand."
        db.commit()
        return row
    if row.status not in {PayoutStatus.HELD.value, PayoutStatus.RELEASED.value} or not row.transfer_id:
        db.commit()
        return row
    if not get_settings().enable_restaurant_payouts:
        row.last_error = "Cancelled while payouts are switched off; reverse this transfer by hand."
        db.commit()
        return row
    client = client or default_client()
    if client is None:
        db.commit()
        return row
    try:
        client.reverse(row.transfer_id)
    except PaymentProviderError as error:
        _fail(db, row, error)
        if error.retryable:
            raise
        return row
    row.status = PayoutStatus.REVERSED.value
    row.reversed_at = datetime.now(UTC)
    row.last_error = None
    db.commit()
    return row


def refresh_transfer(db: Session, transfer_id: str, *, client: Any = None) -> RestaurantPayout | None:
    """A webhook said something happened; ask Razorpay what."""

    if not transfer_id:
        return None
    row = db.scalar(
        select(RestaurantPayout).where(RestaurantPayout.transfer_id == transfer_id).with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        return None
    client = client or default_client()
    if client is None:
        db.commit()
        return row
    try:
        state = client.fetch_transfer(transfer_id)
    except PaymentProviderError:
        db.commit()
        return row
    now = datetime.now(UTC)
    if state.status in {"reversed", "partially_reversed"}:
        row.status, row.reversed_at = PayoutStatus.REVERSED.value, row.reversed_at or now
    elif state.status == "failed":
        row.status = PayoutStatus.FAILED.value
        row.last_error = state.error or "Razorpay reports the transfer failed."
    elif state.settlement_status == "settled":
        row.status = PayoutStatus.SETTLED.value
        row.settled_at = row.settled_at or now
        row.settlement_id = state.settlement_id
    elif not state.on_hold and row.status == PayoutStatus.HELD.value:
        row.status, row.released_at = PayoutStatus.RELEASED.value, row.released_at or now
    db.commit()
    return row


def flush_waiting(db: Session, restaurant_id: uuid.UUID, *, client: Any = None) -> int:
    """A linked account just became ACTIVE: transfer what was waiting for it."""

    order_ids = db.scalars(
        select(RestaurantPayout.order_id).where(
            RestaurantPayout.restaurant_id == restaurant_id,
            RestaurantPayout.status == PayoutStatus.WAITING_ACCOUNT.value,
        )
    ).all()
    moved = 0
    for order_id in order_ids:
        try:
            row = transfer(db, order_id, client=client)
        except PaymentProviderError:
            continue
        if row is not None and row.transfer_id:
            moved += 1
    return moved


def retry_stuck(db: Session, *, client: Any = None) -> int:
    """The hourly sweep: whatever a lost task or webhook left behind."""

    limit = get_settings().payouts_retry_limit
    cutoff = datetime.now(UTC) - timedelta(minutes=10)
    rows = db.execute(
        select(RestaurantPayout.order_id, RestaurantPayout.status)
        .join(Order, Order.id == RestaurantPayout.order_id)
        .where(RestaurantPayout.attempts < limit)
        .where(or_(
            and_(RestaurantPayout.status == PayoutStatus.WAITING_ACCOUNT.value, RestaurantPayout.created_at < cutoff),
            and_(RestaurantPayout.status == PayoutStatus.HELD.value, Order.status == OrderStatus.DELIVERED),
        ))
    ).all()
    # Money released more than a day ago and not yet seen in the bank: ask
    # Razorpay. Transfer webhooks are the fast path; this is what records a
    # settlement when one was missed.
    released = db.scalars(
        select(RestaurantPayout.transfer_id).where(
            RestaurantPayout.status == PayoutStatus.RELEASED.value,
            RestaurantPayout.transfer_id != "",
            RestaurantPayout.released_at < datetime.now(UTC) - timedelta(days=1),
        )
    ).all()
    for transfer_id in released:
        refresh_transfer(db, transfer_id, client=client)
    touched = len(released)
    for order_id, payout_status in rows:
        try:
            if payout_status == PayoutStatus.HELD.value:
                release(db, order_id, client=client)
            else:
                transfer(db, order_id, client=client)
            touched += 1
        except PaymentProviderError:
            continue
    return touched


def retry(db: Session, payout_id: uuid.UUID) -> RestaurantPayout:
    """An admin's Retry on a FAILED or BLOCKED row, once the cause is fixed."""

    row = db.get(RestaurantPayout, payout_id, with_for_update=True, populate_existing=True)
    if row is None:
        raise LookupError("payout not found")
    order = db.get(Order, row.order_id, populate_existing=True)
    if row.status == PayoutStatus.BLOCKED.value:
        split = split_order(order)
        row.restaurant_share, row.platform_keeps = split.restaurant_share, split.platform_keeps
        if split.blocked_reason:
            row.last_error = split.blocked_reason
            db.commit()
            return row
    if row.status in {PayoutStatus.BLOCKED.value, PayoutStatus.FAILED.value} and not row.transfer_id:
        row.status = PayoutStatus.WAITING_ACCOUNT.value
        row.attempts = 0
        row.last_error = None
        queue_payout_step(db, "release" if order.status == OrderStatus.DELIVERED else "transfer", row.order_id)
    db.commit()
    return row

"""Asking a courier to collect an order, off the request that accepted it.

On the queue rather than inline for the same reason the WhatsApp reply is:
the courier's API is somebody else's server, and an order must not fail to be
accepted because a third party is slow. A refused dispatch leaves the order
accepted and the failure recorded; nobody's dinner is cancelled because Pidge
had a bad minute.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
import uuid

from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.models.order import Order
from sqlalchemy import select

from app.models.order_delivery import OrderDelivery
from app.services.delivery.base import DeliveryProviderError, DeliveryState
from app.services.delivery.registry import delivery_provider
from app.models.enums import OrderStatus
from app.services.delivery.service import cancel, dispatch, record

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.delivery.dispatch_order_task",
    bind=True,
    max_retries=4,
    # A courier that is down comes back; one that refuses our payload never
    # will. `DeliveryProviderError.retryable` decides which this was, and only
    # the first kind is retried — see the raise below.
    default_retry_delay=60,
)
def dispatch_order_task(self, order_id: str) -> dict[str, str]:
    """Hand one order to the courier."""

    with SessionLocal() as db:
        order = db.get(Order, uuid.UUID(str(order_id)))
        if order is None:
            logger.warning("Delivery dispatch: no order %s", order_id)
            return {"status": "missing", "order_id": str(order_id)}
        try:
            row = dispatch(db, order)
        except DeliveryProviderError as error:
            # The row carrying `last_error` was written before the raise, so
            # commit it: a failure nobody can see is a failure nobody fixes.
            db.commit()
            if error.retryable and self.request.retries < self.max_retries:
                raise self.retry(exc=error) from error
            logger.error("Delivery dispatch gave up for order %s: %s", order_id, error)
            return {"status": "failed", "order_id": str(order_id), "error": str(error)[:200]}
        db.commit()
        if row is None:
            return {"status": "skipped", "order_id": str(order_id)}
        return {
            "status": "dispatched",
            "order_id": str(order_id),
            "provider_order_id": row.provider_order_id,
        }


@celery_app.task(
    name="app.tasks.delivery.cancel_order_delivery_task",
    bind=True,
    max_retries=4,
    default_retry_delay=30,
)
def cancel_order_delivery_task(self, order_id: str) -> dict[str, str]:
    """Call off the rider for an order that has been cancelled.

    The order is re-read and must actually BE cancelled. This task is queued
    from inside the transaction that cancels the order, to run after its
    commit — and a transaction can roll back. Without this check a cancellation
    that never happened would still send a rider home, and the kitchen would
    be holding food nobody is coming for.
    """

    with SessionLocal() as db:
        order = db.get(Order, uuid.UUID(str(order_id)))
        if order is None:
            logger.warning("Delivery cancel: no order %s", order_id)
            return {"status": "missing", "order_id": str(order_id)}
        if order.status != OrderStatus.CANCELLED:
            logger.warning(
                "Delivery cancel: order %s is %s, not cancelled; leaving its rider alone",
                order_id,
                order.status,
            )
            return {"status": "skipped", "order_id": str(order_id)}
        try:
            row = cancel(db, order)
        except DeliveryProviderError as error:
            # As with dispatch: the row carries why, so commit it.
            db.commit()
            if error.retryable and self.request.retries < self.max_retries:
                raise self.retry(exc=error) from error
            logger.error("Delivery cancel gave up for order %s: %s", order_id, error)
            return {"status": "failed", "order_id": str(order_id), "error": str(error)[:200]}
        db.commit()
        if row is None:
            return {"status": "skipped", "order_id": str(order_id)}
        return {
            "status": "cancelled",
            "order_id": str(order_id),
            "provider_order_id": row.provider_order_id,
        }


@celery_app.task(name="app.tasks.delivery.refresh_deliveries_task")
def refresh_deliveries_task() -> dict[str, int]:
    """Ask the courier what is happening to every delivery still in flight.

    The webhook is an accelerator, not the mechanism. Pidge offers no API to
    register a push URL — it is configured on their side — so a deployment that
    has not arranged that yet would otherwise show a rider as PENDING forever.
    Worse, a push that is dropped, retried into a closed port, or sent while
    this service is restarting is simply lost, and nothing would ever correct
    it.

    So the status is PULLED on a schedule and pushed as a bonus. Both paths run
    through the same `record`, so there is one way a delivery's state changes
    however the news arrived, and a push that beats the poll costs nothing.

    Only unfinished deliveries are asked about. A terminal one cannot change,
    and polling it forever would turn a fixed cost into a growing one.
    """

    provider = delivery_provider()
    if provider is None:
        return {"checked": 0, "changed": 0}

    done = [s.value for s in DeliveryState if s.is_terminal]
    checked = changed = 0
    with SessionLocal() as db:
        rows = db.scalars(
            select(OrderDelivery)
            .where(OrderDelivery.state.notin_(done))
            .where(OrderDelivery.provider_order_id != "")
            .limit(200)
        ).all()
        for row in rows:
            checked += 1
            was = row.state
            try:
                result = provider.fetch(row.provider_order_id)
            except DeliveryProviderError as error:
                # One courier having a bad minute must not stop the rest of the
                # sweep; the next run picks this row up again.
                logger.warning("Could not refresh delivery %s: %s", row.id, error)
                continue
            record(db, row, result)
            # A rider on the road: where exactly. Pidge allows this once per
            # 30 seconds per order, which a one-minute sweep stays inside.
            if row.state in {DeliveryState.ASSIGNED.value, DeliveryState.PICKED_UP.value, DeliveryState.IN_TRANSIT.value}:
                track = getattr(provider, "track", None)
                point = track(row.provider_order_id) if track else None
                if point is not None:
                    row.rider_latitude, row.rider_longitude = point
                    row.rider_location_at = datetime.now(UTC)
            if row.state != was:
                changed += 1
                logger.info("Delivery %s moved %s -> %s", row.id, was, row.state)
        db.commit()
    return {"checked": checked, "changed": changed}

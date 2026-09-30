"""Asking a courier to collect an order, off the request that accepted it.

On the queue rather than inline for the same reason the WhatsApp reply is:
the courier's API is somebody else's server, and an order must not fail to be
accepted because a third party is slow. A refused dispatch leaves the order
accepted and the failure recorded; nobody's dinner is cancelled because Pidge
had a bad minute.
"""

from __future__ import annotations

import logging
import uuid

from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.models.order import Order
from app.services.delivery.base import DeliveryProviderError
from app.services.delivery.service import dispatch

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

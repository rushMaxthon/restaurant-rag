from __future__ import annotations

import logging
import uuid

from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.services.order_cancellation import refund_cancelled_order
from app.services.payments import reap_expired_unpaid_orders
from app.services.payments.base import PaymentProviderError

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.payments.reap_unpaid_orders_task")
def reap_unpaid_orders_task() -> dict[str, int]:
    """Cancel card orders that were never paid within the intent TTL."""

    with SessionLocal() as db:
        cancelled = reap_expired_unpaid_orders(db)

    logger.info("Unpaid order reaper cancelled=%s", cancelled)
    return {"cancelled": cancelled}


@celery_app.task(
    name="app.tasks.payments.refund_cancelled_order_task",
    autoretry_for=(PaymentProviderError,),
    retry_backoff=30,
    retry_kwargs={"max_retries": 5},
)
def refund_cancelled_order_task(order_id: str) -> str:
    """Refund an order a person cancelled. A refusal is recorded, not retried."""

    with SessionLocal() as db:
        order = refund_cancelled_order(db, uuid.UUID(order_id))
        return (order.refund_status or "") if order else "missing"

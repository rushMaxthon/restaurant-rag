from __future__ import annotations

import logging

from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.services.payments import reap_expired_unpaid_orders

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.payments.reap_unpaid_orders_task")
def reap_unpaid_orders_task() -> dict[str, int]:
    """Cancel card orders that were never paid within the intent TTL."""

    with SessionLocal() as db:
        cancelled = reap_expired_unpaid_orders(db)

    logger.info("Unpaid order reaper cancelled=%s", cancelled)
    return {"cancelled": cancelled}

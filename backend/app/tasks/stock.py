"""The morning refill.

A bakery bakes forty loaves every day. Without this the owner types 40 into
forty dishes every morning, or - what actually happens - stops counting.

One task, once a day, in the business's own timezone (Celery's `timezone` is
`business_timezone`), early enough to be done before any kitchen opens. The
rule itself is `stock.restock_daily`; this only gives it a clock.
"""

from __future__ import annotations

import logging

from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.services import stock

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.stock.restock_daily_task")
def restock_daily_task() -> int:
    with SessionLocal() as db:
        changed = stock.restock_daily(db)
        db.commit()
    logger.info("Daily restock: %s counts set back to their daily amount", changed)
    return changed

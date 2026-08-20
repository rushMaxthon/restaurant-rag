from __future__ import annotations

import logging
from typing import Any

from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.services.generated_combos import rebuild_generated_combos

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.generated_combos.rebuild_generated_combos_task",
    bind=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 2},
)
def rebuild_generated_combos_task(self: Any, *, lookback_days: int | None = None) -> dict[str, int]:
    with SessionLocal() as db:
        result = rebuild_generated_combos(db, lookback_days=lookback_days)

    logger.info(
        "Generated combo rebuild task finished created=%s updated=%s deactivated=%s scanned_orders=%s",
        result.created_count,
        result.updated_count,
        result.deactivated_count,
        result.scanned_order_count,
    )
    return result.model_dump(mode="json")

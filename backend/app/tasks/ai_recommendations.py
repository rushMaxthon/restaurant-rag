from __future__ import annotations

import logging
import uuid
from typing import Any

from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.services.ai_recommendations import generate_ai_recommendation_snapshot

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.tasks.ai_recommendations.generate_ai_recommendations_task",
    bind=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 2},
)
def generate_ai_recommendations_task(
    self: Any,
    *,
    user_id: str,
    reason: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    with SessionLocal() as db:
        summary = generate_ai_recommendation_snapshot(
            db,
            user_id=uuid.UUID(user_id),
            reason=reason,
            force_refresh=force_refresh,
        )
    logger.info(
        "AI recommendation task finished user_id=%s status=%s",
        user_id,
        summary.get("status"),
    )
    return summary

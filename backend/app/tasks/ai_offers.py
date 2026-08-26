from __future__ import annotations

import logging
import uuid
from typing import Any

from app.config import get_settings
from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.services.ai_offer_generation import generate_ai_offers
from app.services.ai_offer_segments import generate_segment_offers

logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(
    name="app.tasks.ai_offers.generate_ai_offers_task",
    bind=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 2},
)
def generate_ai_offers_task(
    self: Any,
    *,
    user_limit: int | None = None,
    batch_size: int | None = None,
    force_refresh: bool = False,
    allow_disabled: bool = False,
    restaurant_id: str | None = None,
) -> dict[str, int]:
    """Generate personalized offers, optionally for one restaurant only.

    `restaurant_id` arrives as a string because Celery serialises arguments to
    JSON, which has no UUID type. It is parsed here rather than trusted: a
    malformed id must fail the run, not silently widen it to every restaurant.
    """

    scope_id: uuid.UUID | None = None
    if restaurant_id is not None:
        try:
            scope_id = uuid.UUID(str(restaurant_id))
        except ValueError as error:
            raise ValueError(f"Invalid restaurant_id for AI offer generation: {restaurant_id!r}") from error

    if not settings.enable_ai_offer_generation and not allow_disabled:
        logger.info("AI offer task skipped because ENABLE_AI_OFFER_GENERATION is disabled")
        return {
            "users_scanned": 0,
            "offers_generated": 0,
            "offers_replaced": 0,
            "fallbacks_used": 0,
            "validation_failures": 0,
            "skipped_users": 0,
            "llm_failures": 0,
            "elapsed_ms": 0,
        }

    with SessionLocal() as db:
        if scope_id is not None:
            # A scoped run is an owner asking about their own restaurant, and
            # that question is answered by analysing the restaurant once and
            # producing a few segment offers - not by walking its customer list
            # and writing one offer each. The unscoped platform-wide run below
            # is unchanged.
            summary = generate_segment_offers(
                db,
                restaurant_id=scope_id,
                force_refresh=force_refresh,
                allow_disabled=allow_disabled,
            )
        else:
            summary = generate_ai_offers(
                db,
                user_limit=user_limit,
                batch_size=batch_size,
                force_refresh=force_refresh,
                allow_disabled=allow_disabled,
            )

    logger.info(
        "AI offer generation task finished users_scanned=%s offers_generated=%s fallbacks=%s llm_failures=%s elapsed_ms=%s",
        summary.users_scanned,
        summary.offers_generated,
        summary.fallbacks_used,
        summary.llm_failures,
        summary.elapsed_ms,
    )
    return summary.to_dict()

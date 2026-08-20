from __future__ import annotations

import logging
import uuid
from typing import Any

from app.config import get_settings
from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.services.insights.generation import RunSummary, generate_all_briefings
from app.services.insights.outcomes import measure_due_outcomes
from app.services.insights.analyst.runner import run_analysis
from app.services.insights.scope import InsightsScope

logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(
    name="app.tasks.insights.generate_owner_briefings_task",
    bind=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 2},
)
def generate_owner_briefings_task(
    self: Any,
    *,
    restaurant_limit: int | None = None,
    allow_disabled: bool = False,
) -> dict[str, int]:
    """Nightly briefing generation for every active restaurant.

    `allow_disabled` exists so an admin can trigger a run by hand while the
    feature flag is still off, which is how it gets exercised before rollout.
    """

    if not settings.enable_ai_manager_insights and not allow_disabled:
        logger.info(
            "Owner briefing task skipped because ENABLE_AI_MANAGER_INSIGHTS is disabled"
        )
        return RunSummary().to_dict()

    with SessionLocal() as db:
        summary = generate_all_briefings(db, restaurant_limit=restaurant_limit)

    return summary.to_dict()


@celery_app.task(
    name="app.tasks.insights.measure_action_outcomes_task",
    bind=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 2},
)
def measure_action_outcomes_task(
    self: Any,
    *,
    limit: int | None = None,
    allow_disabled: bool = False,
) -> dict[str, int]:
    """Measure what happened after approved actions ran.

    Separate from briefing generation: measurement reads the same data whether
    or not new insights are being produced, and an owner who has switched
    generation off should still learn how their existing offers did.
    """

    if not settings.enable_ai_manager_actions and not allow_disabled:
        logger.info(
            "Outcome measurement skipped because ENABLE_AI_MANAGER_ACTIONS is disabled"
        )
        return {}

    with SessionLocal() as db:
        summary = measure_due_outcomes(db, limit=limit)

    return summary.to_dict()


@celery_app.task(
    name="app.tasks.insights.run_shadow_analysis_task",
    bind=True,
    # No autoretry. A failed analyst run is a recorded outcome, not an error to
    # paper over — and retrying a minutes-long CPU generation makes a slow host
    # slower for no benefit.
)
def run_shadow_analysis_task(
    self: Any,
    *,
    restaurant_id: str,
    restaurant_location_id: str | None = None,
    allow_disabled: bool = False,
) -> dict[str, Any]:
    """One analyst run for one restaurant, in shadow mode.

    Deliberately per-restaurant rather than a sweep. Each run is minutes of CPU
    generation on a host that also serves the customer assistant, so scheduling
    is left to the caller until 8C's latency numbers are known.

    `allow_disabled` mirrors the briefing task: an operator can exercise a run
    by hand while the flag is still off, which is how it gets evaluated before
    anyone turns it on.
    """

    if not settings.enable_ai_manager_analyst and not allow_disabled:
        logger.info(
            "Analyst task skipped because ENABLE_AI_MANAGER_ANALYST is disabled"
        )
        return {"status": "SKIPPED", "reason": "analyst disabled"}

    scope = InsightsScope(
        restaurant_id=uuid.UUID(restaurant_id),
        restaurant_location_id=(
            uuid.UUID(restaurant_location_id) if restaurant_location_id else None
        ),
    )

    with SessionLocal() as db:
        result = run_analysis(db, scope=scope, enabled=True)

    return result.to_dict()

"""Writing an analyst run, and whatever survived validation, to the database.

Three switches govern this, and they are deliberately separate:

* `enable_ai_manager_analyst` — whether a run happens at all.
* `ai_manager_analyst_shadow_mode` — when true, the run and its rejections are
  recorded but no finding or recommendation is written. This is the state 8B
  ships in: the evidence for whether the analyst is any good is collected
  without anything reaching an owner.
* `enable_ai_manager_ai_findings` — whether written AI rows are visible. The
  read paths filter on origin, so even rows written by a future phase stay
  invisible until this is turned on.

Collapsing these into one flag is precisely how shadow output reaches a user by
accident, so they stay apart.

Executable recommendations are written as `PROPOSED` and nothing more. The owner
approval boundary is untouched: `actions.approve_proposal` remains the only path
from a proposal to a live offer.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import (
    AnalysisRunStatus,
    InsightOrigin,
    OwnerActionStatus,
    OwnerInsightStatus,
    OwnerInsightType,
)
from app.models.owner_action import OwnerActionProposal
from app.models.owner_analysis_run import OwnerAnalysisRun
from app.models.owner_insight import OwnerInsight
from app.services.insights.analyst.ledger import FactLedger
from app.services.insights.analyst.validation import (
    CoverageContext,
    ValidationOutcome,
)
from app.services.insights.periods import PeriodComparison
from app.services.insights.scope import InsightsScope

settings = get_settings()
logger = logging.getLogger(__name__)


def _dedupe_key(prefix: str, restaurant_id: uuid.UUID, title: str) -> str:
    normalized = "-".join(title.strip().lower().split())[:120]
    return f"AI:{prefix}:{restaurant_id}:{normalized}"


def record_run(
    db: Session,
    *,
    scope: InsightsScope,
    comparison: PeriodComparison,
    ledger: FactLedger,
    outcome: ValidationOutcome,
    coverage: CoverageContext,
    status: AnalysisRunStatus,
    started_at: datetime,
    elapsed_ms: int,
    model_name: str | None = None,
    failure_reason: str | None = None,
    extra_transcript: dict[str, Any] | None = None,
    commit: bool = True,
) -> OwnerAnalysisRun:
    """Write the audit row for one run, successful or not.

    Always written. A run that produced nothing usable is the most informative
    row in this table, and it only exists because failure is recorded as
    carefully as success.
    """

    run = OwnerAnalysisRun(
        id=uuid.uuid4(),
        restaurant_id=scope.restaurant_id,
        restaurant_location_id=scope.restaurant_location_id,
        status=status,
        shadow_mode=settings.ai_manager_analyst_shadow_mode,
        period_start=comparison.current.start_date,
        period_end=comparison.current.end_date,
        model_name=model_name,
        prompt_version=settings.analyst_prompt_version,
        tool_call_count=len(ledger.entries),
        elapsed_ms=elapsed_ms,
        findings_proposed=len(outcome.findings) + sum(
            1 for rejection in outcome.rejections if rejection.kind == "finding"
        ),
        findings_accepted=len(outcome.findings),
        findings_rejected=sum(
            1 for rejection in outcome.rejections if rejection.kind == "finding"
        ),
        recommendations_proposed=len(outcome.recommendations) + sum(
            1 for rejection in outcome.rejections if rejection.kind == "recommendation"
        ),
        recommendations_accepted=len(outcome.recommendations),
        failure_reason=failure_reason,
        transcript={
            **ledger.to_transcript(),
            "coverage": coverage.to_payload(),
            **(extra_transcript or {}),
        },
        rejection_reasons=outcome.rejection_payload(),
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )
    db.add(run)
    if commit:
        db.commit()
        db.refresh(run)
    return run


def persist_outcome(
    db: Session,
    *,
    scope: InsightsScope,
    comparison: PeriodComparison,
    outcome: ValidationOutcome,
    run: OwnerAnalysisRun,
    model_name: str | None = None,
    commit: bool = True,
) -> tuple[int, int]:
    """Write validated findings and recommendations. Returns (insights, proposals).

    A no-op in shadow mode, which is the configured default. The caller does not
    have to remember to check: writing nothing is the safe behaviour, so it is
    the behaviour that happens without a decision.
    """

    if settings.ai_manager_analyst_shadow_mode:
        logger.info(
            "Analyst run in shadow mode, nothing persisted restaurant_id=%s run_id=%s",
            scope.restaurant_id,
            run.id,
        )
        return 0, 0

    now = datetime.now(UTC)
    insights_written = 0
    proposals_written = 0

    for validated in outcome.findings:
        finding = validated.finding
        db.add(
            OwnerInsight(
                id=uuid.uuid4(),
                briefing_id=None,
                restaurant_id=scope.restaurant_id,
                restaurant_location_id=scope.restaurant_location_id,
                insight_type=OwnerInsightType.AI_DISCOVERED,
                severity=validated.severity,
                status=OwnerInsightStatus.NEW,
                dedupe_key=_dedupe_key("FINDING", scope.restaurant_id, finding.title),
                score=0,
                title=finding.title[:255],
                body=finding.body,
                dimension=None,
                subject=finding.subject[:255] if finding.subject else None,
                period_start=comparison.current.start_date,
                period_end=comparison.current.end_date,
                generated_at=now,
                # The analyst's explanation is kept apart from its observation,
                # so a reader is never shown a guess in the voice of a measurement.
                root_cause=finding.interpretation,
                facts={
                    "metrics": [metric.model_dump() for metric in finding.metrics],
                },
                origin=InsightOrigin.AI,
                confidence=validated.confidence,
                ai_category=finding.category[:120],
                evidence=validated.evidence,
                analysis_run_id=run.id,
                model_name=model_name,
            )
        )
        insights_written += 1

    for validated in outcome.recommendations:
        recommendation = validated.recommendation
        if validated.action_type is None:
            # Nothing to hang an action on. Advisory text without a type would
            # be a suggestion the action system cannot describe or measure.
            continue
        db.add(
            OwnerActionProposal(
                id=uuid.uuid4(),
                restaurant_id=scope.restaurant_id,
                restaurant_location_id=scope.restaurant_location_id,
                insight_id=None,
                briefing_id=None,
                action_type=validated.action_type,
                status=OwnerActionStatus.PROPOSED,
                dedupe_key=_dedupe_key("ACTION", scope.restaurant_id, recommendation.title),
                priority=validated.priority,
                title=recommendation.title[:255],
                rationale=recommendation.rationale,
                is_executable=validated.is_executable,
                expected_impact_amount=recommendation.expected_impact_amount,
                expected_impact_basis=recommendation.expected_impact_basis,
                # Empty on purpose. The offer payload is built by the backend
                # from a validated action type, never taken from generated text.
                action_payload={},
                source_facts={"evidence": validated.evidence},
                generated_at=now,
                origin=InsightOrigin.AI,
                confidence=validated.confidence,
                evidence=validated.evidence,
                analysis_run_id=run.id,
                model_name=model_name,
            )
        )
        proposals_written += 1

    if commit:
        db.commit()

    logger.info(
        "Analyst output persisted restaurant_id=%s run_id=%s insights=%s proposals=%s",
        scope.restaurant_id,
        run.id,
        insights_written,
        proposals_written,
    )
    return insights_written, proposals_written


def ai_findings_visible() -> bool:
    """Whether AI-origin rows may be shown to an owner at all."""

    return settings.enable_ai_manager_ai_findings


def visible_origins() -> tuple[InsightOrigin, ...]:
    """Origins the read paths may return, given the current configuration."""

    if ai_findings_visible():
        return (InsightOrigin.RULES, InsightOrigin.AI)
    return (InsightOrigin.RULES,)


def run_summary(run: OwnerAnalysisRun) -> dict[str, Any]:
    """A compact operator view of one run."""

    return {
        "id": str(run.id),
        "status": run.status.value,
        "shadow_mode": run.shadow_mode,
        "tool_calls": run.tool_call_count,
        "findings_proposed": run.findings_proposed,
        "findings_accepted": run.findings_accepted,
        "findings_rejected": run.findings_rejected,
        "rejection_rate": (
            round(run.findings_rejected / run.findings_proposed, 3)
            if run.findings_proposed
            else None
        ),
        "elapsed_ms": run.elapsed_ms,
    }


__all__ = [
    "ai_findings_visible",
    "persist_outcome",
    "record_run",
    "run_summary",
    "visible_origins",
]

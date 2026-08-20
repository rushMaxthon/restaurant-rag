"""Generates, deduplicates, and persists owner briefings and insights.

One run per restaurant: compute the diagnostics snapshot, apply the rules, drop
findings already raised recently, narrate the period, and store the result.

The briefing always describes the whole period, including findings that were
suppressed as repeats. The feed only receives what is new, so a continuing slump
does not produce an identical card every night.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter

from sqlalchemy import func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import (
    InsightNarrationSource,
    OwnerInsightType,
    OwnerActionStatus,
    OwnerInsightStatus,
)
from app.models.generated_combo import GeneratedCombo
from app.models.menu_item import MenuItem
from app.models.owner_action import OwnerActionProposal
from app.models.owner_insight import OwnerBriefing, OwnerInsight
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.schemas.insights import DiagnosticsSnapshotResponse
from app.services.insights.actions import default_expiry, expire_stale_proposals
from app.services.insights.facts import build_fact_pack
from app.services.insights.narrator import narrate
from app.services.insights.playbooks import ComboOpportunity, build_proposals
from app.services.insights.root_cause import (
    acceptance_latency,
    cancellations_by_reason,
    explain_cancellations,
    explain_item_decline,
    explain_latency,
    stockouts_in_period,
)
from app.services.insights.periods import PeriodComparison, resolve_period_comparison
from app.services.insights.rules import CandidateInsight, evaluate_rules
from app.services.insights.analyst.persistence import visible_origins
from app.services.insights.scope import InsightsScope
from app.services.insights.service import build_diagnostics_snapshot

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GenerationResult:
    restaurant_id: uuid.UUID
    # The window actually analysed. Differs from the default when the recent
    # period was too sparse and a longer one was used instead.
    window_days: int | None = None
    briefing_id: uuid.UUID | None = None
    candidates_found: int = 0
    insights_created: int = 0
    insights_suppressed: int = 0
    narration_source: str = InsightNarrationSource.TEMPLATE.value
    proposals_created: int = 0
    proposals_suppressed: int = 0
    skipped_reason: str | None = None
    # The window had too little trade for a comparison to mean much. The run
    # still produced a briefing; this says how much weight to put on it.
    low_confidence: bool = False


@dataclass(slots=True)
class RunSummary:
    restaurants_scanned: int = 0
    briefings_created: int = 0
    insights_created: int = 0
    insights_suppressed: int = 0
    llm_narrations: int = 0
    template_narrations: int = 0
    proposals_created: int = 0
    proposals_expired: int = 0
    skipped: int = 0
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _recent_dedupe_keys(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    now: datetime,
) -> set[str]:
    """Findings already raised for this restaurant inside the cooldown window.

    Dismissed cards are included: an owner who waved a finding away should not
    see it again the next night either.
    """

    cutoff = now - timedelta(hours=settings.insight_dedupe_cooldown_hours)
    rows = db.scalars(
        select(OwnerInsight.dedupe_key).where(
            OwnerInsight.restaurant_id == restaurant_id,
            OwnerInsight.generated_at >= cutoff,
        )
    ).all()
    return set(rows)


def _menu_item_resolver(db: Session, *, scope: InsightsScope):
    """Resolve a dish name back to a menu item id inside this restaurant only.

    Item metrics group by dish name so branch duplicates collapse into one row,
    which means an offer needs the id looked up again. Scoped to the restaurant,
    so a name shared with another tenant can never resolve across the boundary.
    """

    def resolve(dish_name: str) -> uuid.UUID | None:
        query = select(MenuItem.id).where(
            MenuItem.restaurant_id == scope.restaurant_id,
            func.lower(func.trim(MenuItem.name)) == dish_name.strip().lower(),
        )
        if scope.restaurant_location_id is not None:
            query = query.where(
                MenuItem.restaurant_location_id == scope.restaurant_location_id
            )
        return db.scalars(query.order_by(MenuItem.created_at.asc()).limit(1)).first()

    return resolve


def _combo_opportunities(db: Session, *, scope: InsightsScope) -> list[ComboOpportunity]:
    """Live basket pairs this restaurant could turn into a bundle."""

    query = select(GeneratedCombo).where(
        GeneratedCombo.restaurant_id == scope.restaurant_id,
        GeneratedCombo.is_active.is_(True),
    )
    if scope.restaurant_location_id is not None:
        query = query.where(
            GeneratedCombo.restaurant_location_id == scope.restaurant_location_id
        )

    try:
        rows = db.scalars(
            query.order_by(GeneratedCombo.order_count.desc()).limit(
                settings.insights_max_combo_proposals
            )
        ).all()
    except ProgrammingError:
        # The combo tables are optional in some deployments; their absence just
        # means no cross-sell proposals this run.
        db.rollback()
        return []

    return [
        ComboOpportunity(
            combo_id=row.id,
            combo_name=row.combo_name,
            order_count=row.order_count,
            unique_user_count=row.unique_user_count,
            confidence_score=row.confidence_score,
            original_total_price=row.original_total_price,
            suggested_combo_price=row.suggested_combo_price,
        )
        for row in rows
    ]




def _resolve_analysable_comparison(
    db: Session,
    *,
    scope: InsightsScope,
    comparison: PeriodComparison | None,
) -> tuple[PeriodComparison, DiagnosticsSnapshotResponse]:
    """Pick a window with enough trade in it to say something about.

    A low-volume restaurant would otherwise produce nothing on the default
    seven-day window, every night, forever — indistinguishable from the job
    being broken. Widening the window is allowed; lowering the materiality gates
    is not, so a genuinely quiet restaurant still yields nothing.

    An explicitly requested comparison is honoured as-is.
    """

    if comparison is not None:
        return comparison, build_diagnostics_snapshot(db, scope=scope, comparison=comparison)

    attempted: DiagnosticsSnapshotResponse | None = None
    resolved: PeriodComparison | None = None

    for window_days in settings.insights_adaptive_window_days_list:
        candidate = resolve_period_comparison(window_days=window_days)
        snapshot = build_diagnostics_snapshot(db, scope=scope, comparison=candidate)
        if attempted is None:
            attempted, resolved = snapshot, candidate
        if snapshot.data_quality.sufficient_volume:
            return candidate, snapshot

    # Nothing had enough volume. The narrowest window is returned so the caller
    # reports "too quiet" against the period the owner would expect.
    return resolved, attempted


def _branch_states(db: Session, *, scope: InsightsScope) -> dict[str, str]:
    """A one-line explanation per branch that is currently switched off.

    Only closed branches produce an entry: "it is open" explains nothing, and a
    finding with no explanation correctly leaves `root_cause` empty.
    """

    rows = db.scalars(
        select(RestaurantLocation).where(
            RestaurantLocation.restaurant_id == scope.restaurant_id
        )
    ).all()

    states: dict[str, str] = {}
    for row in rows:
        if row.is_open and row.is_active:
            continue
        if not row.is_active:
            reason = "This branch is not active on the platform."
        else:
            reason = "This branch is currently marked closed"
            reason += (
                f" ({row.temporary_closed_reason})."
                if row.temporary_closed_reason
                else ", with no reason recorded."
            )
        states[row.branch_name] = reason
    return states


def _attach_root_causes(
    db: Session,
    *,
    scope: InsightsScope,
    comparison: PeriodComparison,
    candidates: list[CandidateInsight],
) -> list[CandidateInsight]:
    """Explain findings where the operational history supports an explanation.

    Runs a bounded set of queries per generation, not per insight. Leaving
    `root_cause` as None is the common case: events only exist from the 0042
    migration onward, and most declines have no recorded cause.
    """

    if not candidates:
        return candidates

    try:
        stockouts = stockouts_in_period(db, scope, comparison.current)
        cancellations = cancellations_by_reason(db, scope, comparison.current)
        latency_now = acceptance_latency(db, scope, comparison.current)
        latency_before = acceptance_latency(db, scope, comparison.previous)
    except Exception:  # noqa: BLE001 - an explanation is a bonus, never a blocker
        logger.exception(
            "Root cause analysis failed restaurant_id=%s", scope.restaurant_id
        )
        return candidates

    cancellation_reason = explain_cancellations(cancellations)
    latency_reason = explain_latency(latency_now, latency_before)
    branch_states = _branch_states(db, scope=scope)

    enriched: list[CandidateInsight] = []
    for candidate in candidates:
        explanation: str | None = None

        if candidate.insight_type in {
            OwnerInsightType.ITEM_DECLINE,
            OwnerInsightType.CATEGORY_DECLINE,
        }:
            explanation = explain_item_decline(
                subject=candidate.subject, stockouts=stockouts
            )
        elif candidate.insight_type == OwnerInsightType.CANCELLATION_SPIKE:
            explanation = cancellation_reason
        elif candidate.insight_type == OwnerInsightType.LOCATION_DECLINE:
            # A branch's own state is the explanation far more often than
            # anything in its order history, and it is the one thing no
            # order-based query can see.
            explanation = branch_states.get(candidate.subject or "")
        elif candidate.insight_type in {
            OwnerInsightType.REVENUE_DROP,
            OwnerInsightType.DAYPART_WEAKNESS,
        }:
            explanation = latency_reason

        candidate.root_cause = explanation
        enriched.append(candidate)

    return enriched


def _persist_proposals(
    db: Session,
    *,
    scope: InsightsScope,
    briefing: OwnerBriefing,
    insight_rows: dict[str, OwnerInsight],
    candidates: list[CandidateInsight],
    now: datetime,
) -> tuple[int, int]:
    """Write the recommended actions for this run, skipping ones already open.

    Proposals are only raised for findings that were themselves fresh, so a
    suppressed insight does not quietly regenerate its recommendation.
    """

    if not settings.enable_ai_manager_actions:
        return 0, 0

    fresh_candidates = [
        candidate for candidate in candidates if candidate.dedupe_key in insight_rows
    ]
    proposals = build_proposals(
        fresh_candidates,
        resolve_menu_item=_menu_item_resolver(db, scope=scope),
        combos=_combo_opportunities(db, scope=scope),
    )
    if not proposals:
        return 0, 0

    open_keys = set(
        db.scalars(
            select(OwnerActionProposal.dedupe_key).where(
                OwnerActionProposal.restaurant_id == scope.restaurant_id,
                OwnerActionProposal.status.in_(
                    [OwnerActionStatus.PROPOSED, OwnerActionStatus.APPROVED]
                ),
            )
        ).all()
    )

    created = 0
    suppressed = 0
    for proposal in proposals:
        if proposal.dedupe_key in open_keys:
            suppressed += 1
            continue

        insight = (
            insight_rows.get(proposal.insight_dedupe_key)
            if proposal.insight_dedupe_key
            else None
        )
        db.add(
            OwnerActionProposal(
                id=uuid.uuid4(),
                restaurant_id=scope.restaurant_id,
                restaurant_location_id=scope.restaurant_location_id,
                insight_id=insight.id if insight is not None else None,
                briefing_id=briefing.id,
                action_type=proposal.action_type,
                status=OwnerActionStatus.PROPOSED,
                dedupe_key=proposal.dedupe_key,
                priority=proposal.priority,
                title=proposal.title,
                rationale=proposal.rationale,
                is_executable=proposal.is_executable,
                expected_impact_amount=proposal.expected_impact_amount,
                expected_impact_basis=proposal.expected_impact_basis,
                action_payload=proposal.action_payload,
                source_facts=proposal.source_facts,
                generated_at=now,
                expires_at=default_expiry(now),
            )
        )
        created += 1

    return created, suppressed


def _persist(
    db: Session,
    *,
    scope: InsightsScope,
    comparison: PeriodComparison,
    snapshot: DiagnosticsSnapshotResponse,
    candidates: list[CandidateInsight],
    fresh: list[CandidateInsight],
    now: datetime,
) -> tuple[OwnerBriefing, dict[str, OwnerInsight]]:
    pack = build_fact_pack(snapshot, candidates)
    narration = narrate(
        pack,
        candidates,
        period_dates=(
            comparison.current.start_date,
            comparison.current.end_date,
            comparison.previous.start_date,
            comparison.previous.end_date,
        ),
    )

    briefing = OwnerBriefing(
        id=uuid.uuid4(),
        restaurant_id=scope.restaurant_id,
        restaurant_location_id=scope.restaurant_location_id,
        period_start=comparison.current.start_date,
        period_end=comparison.current.end_date,
        previous_period_start=comparison.previous.start_date,
        previous_period_end=comparison.previous.end_date,
        headline=narration.headline,
        narrative=narration.narrative,
        narration_source=narration.source,
        fallback_reason=narration.fallback_reason,
        insight_count=len(fresh),
        facts=pack.to_payload(),
        snapshot=snapshot.model_dump(mode="json"),
        generated_at=now,
    )
    db.add(briefing)
    db.flush()

    insight_rows: dict[str, OwnerInsight] = {}
    for candidate in fresh:
        insight = OwnerInsight(
                id=uuid.uuid4(),
                briefing_id=briefing.id,
                restaurant_id=scope.restaurant_id,
                restaurant_location_id=scope.restaurant_location_id,
                insight_type=candidate.insight_type,
                severity=candidate.severity,
                status=OwnerInsightStatus.NEW,
                dedupe_key=candidate.dedupe_key,
                score=candidate.score,
                title=candidate.title,
                body=candidate.body,
                dimension=candidate.dimension,
                subject=candidate.subject,
                period_start=comparison.current.start_date,
                period_end=comparison.current.end_date,
                generated_at=now,
                root_cause=candidate.root_cause,
                facts=candidate.facts,
        )
        db.add(insight)
        insight_rows[candidate.dedupe_key] = insight

    # Flushed so the proposals written next can reference real insight ids.
    db.flush()
    return briefing, insight_rows


def generate_for_restaurant(
    db: Session,
    *,
    scope: InsightsScope,
    comparison: PeriodComparison | None = None,
    now: datetime | None = None,
    commit: bool = True,
) -> GenerationResult:
    """Run one restaurant's generation cycle and persist the outcome."""

    resolved_now = now or datetime.now(UTC)
    resolved_comparison, snapshot = _resolve_analysable_comparison(
        db, scope=scope, comparison=comparison
    )
    candidates = evaluate_rules(snapshot)

    # A quiet restaurant used to be skipped here, which meant its owner opened
    # the AI manager every day to an empty screen and no explanation — the
    # feature looked broken rather than honest. A briefing is still recorded:
    # it describes whatever trade there was, and the data-quality notes already
    # say the volume is below the threshold where trends mean anything.
    #
    # The materiality gates are untouched. Thin data produces a briefing with
    # no findings under it, never an invented finding — the fix is to stop
    # withholding what is real, not to lower the bar for what counts.
    low_confidence = not snapshot.data_quality.sufficient_volume

    candidates = _attach_root_causes(
        db, scope=scope, comparison=resolved_comparison, candidates=candidates
    )

    seen_keys = _recent_dedupe_keys(db, restaurant_id=scope.restaurant_id, now=resolved_now)
    fresh = [candidate for candidate in candidates if candidate.dedupe_key not in seen_keys]

    briefing, insight_rows = _persist(
        db,
        scope=scope,
        comparison=resolved_comparison,
        snapshot=snapshot,
        candidates=candidates,
        fresh=fresh,
        now=resolved_now,
    )
    created = len(insight_rows)

    expire_stale_proposals(db, restaurant_id=scope.restaurant_id, now=resolved_now)
    proposals_created, proposals_suppressed = _persist_proposals(
        db,
        scope=scope,
        briefing=briefing,
        insight_rows=insight_rows,
        candidates=candidates,
        now=resolved_now,
    )

    if commit:
        db.commit()

    return GenerationResult(
        restaurant_id=scope.restaurant_id,
        window_days=resolved_comparison.current.day_count,
        briefing_id=briefing.id,
        candidates_found=len(candidates),
        insights_created=created,
        insights_suppressed=len(candidates) - created,
        proposals_created=proposals_created,
        proposals_suppressed=proposals_suppressed,
        narration_source=briefing.narration_source.value,
        low_confidence=low_confidence,
    )


def _active_restaurant_ids(db: Session, *, limit: int) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(Restaurant.id)
            .where(Restaurant.is_active.is_(True), Restaurant.is_approved.is_(True))
            .order_by(Restaurant.created_at.asc())
            .limit(limit)
        ).all()
    )


def generate_all_briefings(
    db: Session,
    *,
    restaurant_limit: int | None = None,
    now: datetime | None = None,
    comparison: PeriodComparison | None = None,
) -> RunSummary:
    """Generate briefings for every active restaurant, one at a time.

    Sequential on purpose: narration runs against a CPU-only Ollama host, where
    concurrent generations contend for the same cores and finish later than if
    they had queued.
    """

    started_at = perf_counter()
    summary = RunSummary()
    limit = restaurant_limit or settings.ai_manager_max_restaurants_per_run
    resolved_now = now or datetime.now(UTC)
    # Resolved once so every restaurant in a run is compared over the same
    # window, and overridable so a backfill can target a historical period.
    resolved_comparison = comparison or resolve_period_comparison()

    for restaurant_id in _active_restaurant_ids(db, limit=limit):
        summary.restaurants_scanned += 1
        scope = InsightsScope(restaurant_id=restaurant_id)
        try:
            result = generate_for_restaurant(
                db,
                scope=scope,
                comparison=resolved_comparison,
                now=resolved_now,
            )
        except Exception:  # noqa: BLE001 - one bad restaurant must not stop the run
            db.rollback()
            summary.skipped += 1
            logger.exception("Insight generation failed restaurant_id=%s", restaurant_id)
            continue

        if result.skipped_reason is not None:
            summary.skipped += 1
            continue

        summary.briefings_created += 1
        summary.insights_created += result.insights_created
        summary.insights_suppressed += result.insights_suppressed
        summary.proposals_created += result.proposals_created
        if result.narration_source == InsightNarrationSource.LLM.value:
            summary.llm_narrations += 1
        else:
            summary.template_narrations += 1

    summary.elapsed_ms = int((perf_counter() - started_at) * 1000)
    logger.info(
        "Insight generation finished scanned=%s briefings=%s insights=%s suppressed=%s "
        "proposals=%s llm=%s template=%s skipped=%s elapsed_ms=%s",
        summary.restaurants_scanned,
        summary.briefings_created,
        summary.insights_created,
        summary.insights_suppressed,
        summary.proposals_created,
        summary.llm_narrations,
        summary.template_narrations,
        summary.skipped,
        summary.elapsed_ms,
    )
    return summary


# --- read paths for the API ------------------------------------------------


def get_latest_briefing(db: Session, *, scope: InsightsScope) -> OwnerBriefing | None:
    query = select(OwnerBriefing).where(OwnerBriefing.restaurant_id == scope.restaurant_id)
    if scope.restaurant_location_id is not None:
        query = query.where(
            OwnerBriefing.restaurant_location_id == scope.restaurant_location_id
        )
    return db.scalars(query.order_by(OwnerBriefing.generated_at.desc()).limit(1)).first()


def list_insights(
    db: Session,
    *,
    scope: InsightsScope,
    statuses: list[OwnerInsightStatus] | None = None,
    limit: int = 50,
) -> list[OwnerInsight]:
    query = select(OwnerInsight).where(
        OwnerInsight.restaurant_id == scope.restaurant_id,
        # See `list_proposals`: origin is filtered on read as well as on write,
        # so AI findings cannot reach the feed while they are still being
        # evaluated, whatever wrote them.
        OwnerInsight.origin.in_(visible_origins()),
    )
    if scope.restaurant_location_id is not None:
        query = query.where(
            OwnerInsight.restaurant_location_id == scope.restaurant_location_id
        )
    if statuses:
        query = query.where(OwnerInsight.status.in_(statuses))
    return list(
        db.scalars(
            query.order_by(
                OwnerInsight.period_end.desc(),
                OwnerInsight.score.desc(),
            ).limit(limit)
        ).all()
    )


def get_insight_for_scope(
    db: Session,
    *,
    scope: InsightsScope,
    insight_id: uuid.UUID,
) -> OwnerInsight | None:
    """Load one insight, scoped so another restaurant's id resolves to nothing."""

    return db.scalars(
        select(OwnerInsight).where(
            OwnerInsight.id == insight_id,
            OwnerInsight.restaurant_id == scope.restaurant_id,
        )
    ).first()


def set_insight_status(
    db: Session,
    *,
    insight: OwnerInsight,
    status: OwnerInsightStatus,
    now: datetime | None = None,
) -> OwnerInsight:
    insight.status = status
    if status in {OwnerInsightStatus.SEEN, OwnerInsightStatus.DISMISSED}:
        insight.acknowledged_at = now or datetime.now(UTC)
    else:
        insight.acknowledged_at = None
    db.add(insight)
    db.commit()
    db.refresh(insight)
    return insight


__all__ = [
    "GenerationResult",
    "RunSummary",
    "generate_all_briefings",
    "generate_for_restaurant",
    "get_insight_for_scope",
    "get_latest_briefing",
    "list_insights",
    "set_insight_status",
]


def live_findings_for(
    db: Session,
    *,
    scope: InsightsScope,
    comparison: PeriodComparison,
) -> list[CandidateInsight]:
    """The findings for one period, computed and not persisted.

    The same call the live briefing makes, so the briefing and the feed can be
    driven from one analysis. They used to be two: the briefing narrated
    findings it had just worked out while the feed listed stored rows from
    whatever window the nightly run had chosen, so a quiet restaurant could read
    "Lunch revenue fell from ₹142 to ₹31" directly above "Nothing to flag".
    """

    snapshot = build_diagnostics_snapshot(db, scope=scope, comparison=comparison)
    candidates = evaluate_rules(snapshot)
    return _attach_root_causes(
        db, scope=scope, comparison=comparison, candidates=candidates
    )


def build_live_briefing(
    db: Session,
    *,
    scope: InsightsScope,
    comparison: PeriodComparison,
) -> tuple[str, str, list[CandidateInsight]]:
    """A briefing for the period the owner is looking at, computed and discarded.

    The nightly run stores a briefing for the window it chose. An owner who then
    selects a different period was shown that stored briefing beside figures for
    their own — one card describing two periods, with the stored headline
    winning because it is the largest text on the screen.

    This runs the same rules and the same deterministic template against the
    selected window and persists nothing: no insight rows, no proposals, no
    briefing. It is read-only in the same sense every other panel is.
    """

    snapshot = build_diagnostics_snapshot(db, scope=scope, comparison=comparison)
    candidates = evaluate_rules(snapshot)
    candidates = _attach_root_causes(
        db, scope=scope, comparison=comparison, candidates=candidates
    )
    pack = build_fact_pack(snapshot, candidates)
    # Deliberately the template, never the model: this runs on every page load
    # and on a CPU-only host a generation call would put a minute in front of
    # the screen. The wording is the same one the nightly run falls back to.
    narration = narrate(pack, candidates, enabled=False)
    return narration.headline, narration.narrative, candidates

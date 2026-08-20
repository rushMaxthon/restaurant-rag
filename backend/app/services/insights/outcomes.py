"""Measuring what happened after an approved recommendation ran.

This closes the loop the manager left open: it could propose an action and
create the offer, but never looked back. `executed_offer_id` was written at
approval and never read again — this module reads it.

**These are observations, not proof of cause.** There is no holdout group and no
control, so the figures describe what occurred in the window after the offer
went live. A festival, a seasonal swing, or an unrelated menu change would land
in exactly the same numbers. Every string this module produces is worded to keep
that distinction, because an owner told "this offer earned you ₹6,200" will act
differently from one told "₹6,200 of orders used this offer".
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.action_outcome import ActionOutcome
from app.models.enums import ActionOutcomeVerdict, OwnerActionStatus
from app.models.owner_action import OwnerActionProposal
from app.services.insights.offer_performance import fetch_offer_performance
from app.services.insights.periods import build_period, local_today
from app.services.insights.rules import money
from app.services.insights.scope import InsightsScope

settings = get_settings()
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OutcomeRunSummary:
    proposals_examined: int = 0
    outcomes_written: int = 0
    outcomes_updated: int = 0
    not_yet_mature: int = 0
    not_measurable: int = 0
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _measurement_window(proposal: OwnerActionProposal, *, today: date) -> tuple[date, date]:
    """The window to measure: from execution up to today, capped.

    Capped so a long-running offer does not accumulate an ever-growing window
    that quietly stops being comparable to the estimate it is judged against.
    """

    executed = proposal.executed_at or proposal.generated_at
    start = executed.astimezone(UTC).date()
    end = min(today, start + timedelta(days=settings.action_outcome_max_window_days))
    if end < start:
        end = start
    return start, end


def is_mature(proposal: OwnerActionProposal, *, now: datetime | None = None) -> bool:
    """Whether enough time has passed for a measurement to mean anything."""

    if proposal.executed_at is None:
        return False
    resolved_now = now or datetime.now(UTC)
    age = resolved_now - proposal.executed_at
    return age >= timedelta(days=settings.action_outcome_maturity_days)


def _verdict_for(
    attributed_orders: int,
    attributed_revenue: Decimal,
    estimated: Decimal | None,
) -> ActionOutcomeVerdict:
    if attributed_orders == 0:
        return ActionOutcomeVerdict.NO_UPTAKE
    if estimated is None or estimated <= 0:
        # Something happened, but there was no estimate to judge it against.
        return ActionOutcomeVerdict.NOT_MEASURABLE

    tolerance = Decimal(str(settings.action_outcome_met_tolerance))
    lower = estimated * (Decimal("1") - tolerance)
    upper = estimated * (Decimal("1") + tolerance)

    if attributed_revenue < lower:
        return ActionOutcomeVerdict.BELOW_ESTIMATE
    if attributed_revenue > upper:
        return ActionOutcomeVerdict.ABOVE_ESTIMATE
    return ActionOutcomeVerdict.MET_ESTIMATE


def _summary_for(
    *,
    verdict: ActionOutcomeVerdict,
    orders: int,
    revenue: Decimal,
    discount: Decimal,
    window_days: int,
    estimated: Decimal | None,
) -> str:
    """A plain-English result, written deterministically. No model involved.

    Phrased as "orders used this offer", never "this offer produced", because
    the data supports the former and not the latter.
    """

    if verdict == ActionOutcomeVerdict.NO_UPTAKE:
        return (
            f"No orders used this offer in the {window_days} days after it went live. "
            "It cost nothing, but it also did nothing."
        )

    base = (
        f"{orders} order{'s' if orders != 1 else ''} used this offer in the "
        f"{window_days} days after it went live, worth {money(float(revenue))} "
        f"at a discount cost of {money(float(discount))}."
    )

    if estimated is None or verdict == ActionOutcomeVerdict.NOT_MEASURABLE:
        return f"{base} There was no estimate to compare this against."

    comparison = {
        ActionOutcomeVerdict.ABOVE_ESTIMATE: "more than",
        ActionOutcomeVerdict.BELOW_ESTIMATE: "less than",
        ActionOutcomeVerdict.MET_ESTIMATE: "close to",
    }[verdict]

    return (
        f"{base} That is {comparison} the {money(float(estimated))} estimated when "
        "it was suggested. These are orders that used the offer, not proof the "
        "offer caused them."
    )


def measure_proposal(
    db: Session,
    *,
    proposal: OwnerActionProposal,
    now: datetime | None = None,
) -> ActionOutcome | None:
    """Measure one executed proposal, writing or refreshing its outcome.

    Returns None when there is nothing measurable: the proposal never executed,
    it produced no offer (an advisory), or it has not matured yet.
    """

    if proposal.status != OwnerActionStatus.EXECUTED or proposal.executed_offer_id is None:
        return None

    resolved_now = now or datetime.now(UTC)
    if not is_mature(proposal, now=resolved_now):
        return None

    today = local_today()
    window_start, window_end = _measurement_window(proposal, today=today)
    period = build_period(window_start, window_end)

    scope = InsightsScope(
        restaurant_id=proposal.restaurant_id,
        restaurant_location_id=proposal.restaurant_location_id,
    )
    rows = fetch_offer_performance(db, scope, period)
    row = next((item for item in rows if item.offer_id == proposal.executed_offer_id), None)

    orders = row.orders if row else 0
    customers = row.customers if row else 0
    revenue = Decimal(str(round(row.gross_revenue, 2))) if row else Decimal("0.00")
    discount = Decimal(str(round(row.discount_cost, 2))) if row else Decimal("0.00")
    net = Decimal(str(round(row.net_revenue, 2))) if row else Decimal("0.00")
    estimated = proposal.expected_impact_amount

    verdict = _verdict_for(orders, revenue, estimated)
    window_days = (window_end - window_start).days + 1
    summary = _summary_for(
        verdict=verdict,
        orders=orders,
        revenue=revenue,
        discount=discount,
        window_days=window_days,
        estimated=estimated,
    )

    existing = db.scalars(
        select(ActionOutcome).where(ActionOutcome.proposal_id == proposal.id)
    ).first()

    if existing is None:
        existing = ActionOutcome(id=uuid.uuid4(), proposal_id=proposal.id)
        db.add(existing)

    # Updated in place rather than appended, so a re-measure refreshes the
    # verdict instead of filling the feed with repeated rows.
    existing.restaurant_id = proposal.restaurant_id
    existing.offer_id = proposal.executed_offer_id
    existing.verdict = verdict
    existing.window_start = window_start
    existing.window_end = window_end
    existing.window_days = window_days
    existing.attributed_orders = orders
    existing.attributed_customers = customers
    existing.attributed_revenue = revenue
    existing.discount_cost = discount
    existing.net_revenue = net
    existing.estimated_impact = estimated
    existing.summary = summary
    existing.measured_at = resolved_now

    return existing


def measure_due_outcomes(
    db: Session,
    *,
    restaurant_id: uuid.UUID | None = None,
    now: datetime | None = None,
    limit: int | None = None,
) -> OutcomeRunSummary:
    """Measure every executed proposal that has matured."""

    started_at = perf_counter()
    summary = OutcomeRunSummary()
    resolved_now = now or datetime.now(UTC)

    query = select(OwnerActionProposal).where(
        OwnerActionProposal.status == OwnerActionStatus.EXECUTED,
        OwnerActionProposal.executed_offer_id.is_not(None),
    )
    if restaurant_id is not None:
        query = query.where(OwnerActionProposal.restaurant_id == restaurant_id)

    proposals = db.scalars(
        query.order_by(OwnerActionProposal.executed_at.asc()).limit(
            limit or settings.action_outcome_batch_limit
        )
    ).all()

    for proposal in proposals:
        summary.proposals_examined += 1
        if not is_mature(proposal, now=resolved_now):
            summary.not_yet_mature += 1
            continue

        had_outcome = (
            db.scalars(
                select(ActionOutcome.id).where(ActionOutcome.proposal_id == proposal.id)
            ).first()
            is not None
        )

        try:
            outcome = measure_proposal(db, proposal=proposal, now=resolved_now)
        except Exception:  # noqa: BLE001 - one bad proposal must not stop the run
            db.rollback()
            logger.exception(
                "Outcome measurement failed proposal_id=%s", proposal.id
            )
            continue

        if outcome is None:
            summary.not_measurable += 1
            continue
        if had_outcome:
            summary.outcomes_updated += 1
        else:
            summary.outcomes_written += 1

    db.commit()
    summary.elapsed_ms = int((perf_counter() - started_at) * 1000)
    logger.info(
        "Action outcome measurement finished examined=%s written=%s updated=%s "
        "immature=%s elapsed_ms=%s",
        summary.proposals_examined,
        summary.outcomes_written,
        summary.outcomes_updated,
        summary.not_yet_mature,
        summary.elapsed_ms,
    )
    return summary


def list_outcomes(
    db: Session,
    *,
    scope: InsightsScope,
    limit: int = 50,
) -> list[ActionOutcome]:
    return list(
        db.scalars(
            select(ActionOutcome)
            .where(ActionOutcome.restaurant_id == scope.restaurant_id)
            .order_by(ActionOutcome.measured_at.desc())
            .limit(limit)
        ).all()
    )


def get_outcomes_by_proposal(
    db: Session,
    *,
    scope: InsightsScope,
    proposal_ids: list[uuid.UUID],
) -> dict[uuid.UUID, ActionOutcome]:
    """Outcomes keyed by proposal, for decorating a list of recommendations."""

    if not proposal_ids:
        return {}
    rows = db.scalars(
        select(ActionOutcome).where(
            ActionOutcome.restaurant_id == scope.restaurant_id,
            ActionOutcome.proposal_id.in_(proposal_ids),
        )
    ).all()
    return {row.proposal_id: row for row in rows}


__all__ = [
    "OutcomeRunSummary",
    "get_outcomes_by_proposal",
    "is_mature",
    "list_outcomes",
    "measure_due_outcomes",
    "measure_proposal",
]

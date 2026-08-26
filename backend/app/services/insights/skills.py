"""The analyses an owner can ask for.

A fixed registry, not text-to-SQL. Three reasons that matter here: `qwen3:8b` on
a CPU host is not reliable enough at SQL; generated SQL would bypass the tenancy
scoping every other query goes through; and each retry costs a full generation
round-trip the host cannot spare.

Every skill returns a `SkillResult` carrying both a deterministic answer and the
fact pack behind it. The template answer is what an owner sees when narration is
off or the model produces something unusable, so it has to be correct and
readable on its own — not a placeholder.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import OwnerActionStatus
from app.models.restaurant_location import RestaurantLocation
from app.schemas.insights import DiagnosticsSnapshotResponse
from app.services.insights import metrics as metrics_layer
from app.services.insights.actions import list_proposals
from app.services.insights.facts import FactPack
from app.services.insights.generation import get_latest_briefing
from app.services.insights.offer_performance import fetch_offer_performance
from app.services.insights.suggestion_cards import (
    combo_cards,
    offer_cards_from_catalogue,
    offer_cards_from_proposals,
)
from app.services.insights.periods import PeriodComparison, resolve_period_comparison
from app.services.insights.presentation import (
    action,
    blocks,
    bold,
    bullets,
    labelled,
    numbered,
    paragraph,
)
from app.services.insights.rules import is_material_change, money, percent
from app.services.insights.scope import InsightsScope
from app.services.insights.service import build_diagnostics_snapshot

settings = get_settings()

# What the platform simply does not record. Naming these lets the assistant say
# so plainly instead of improvising an answer from adjacent data.
UNSUPPORTED_TOPICS = {
    "reviews": "customer reviews or ratings",
    "profit": "profit or food cost",
    "competitors": "competitor or market data",
    "staff": "staff or labour data",
    # `cancellation_reasons` used to live here. Phase 6A records a reason for
    # every cancellation, so it is answered by a real skill now.
    #
    # `stock` stays: availability events say when a dish was switched off, which
    # is not the same as knowing stock levels or wastage. Treating one as the
    # other would be exactly the overreach these refusals exist to prevent.
    "stock": "stock levels or wastage",
}


@dataclass(slots=True)
class SkillParams:
    date_from: date | None = None
    date_to: date | None = None
    window_days: int | None = None
    metric: str | None = None
    subject: str | None = None
    topic: str | None = None
    # Branch names the question named, already resolved against this
    # restaurant's own branches. Never free text from the question.
    branches: tuple[str, ...] = ()
    # What the question wants beyond which analysis answers it. A skill that
    # cannot honour one of these must say so rather than quietly ignore it:
    # silently dropping `direction` is what made "fewest orders" and "biggest
    # drop" produce the same reply.
    direction: str | None = None  # top | bottom | rising | falling
    rank_by: str | None = None  # revenue | orders | quantity
    limit: int | None = None
    # Something the question is about that the platform does not model.
    entity: str | None = None
    # Tier 2 only: the data tool a planner chose, and its validated arguments.
    tool: str | None = None
    tool_args: dict[str, Any] | None = None
    # The parts a multi-part question decomposed into, in the order they will be
    # reported. Empty for an ordinary single-intent question.
    parts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "window_days": self.window_days,
            "metric": self.metric,
            "subject": self.subject,
            "topic": self.topic,
            "branches": list(self.branches),
            "direction": self.direction,
            "rank_by": self.rank_by,
            "limit": self.limit,
            "entity": self.entity,
            "tool": self.tool,
            "tool_args": self.tool_args,
            "parts": list(self.parts),
        }


@dataclass(slots=True)
class SkillResult:
    skill: str
    answer: str
    fact_pack: FactPack
    data: dict[str, Any] = field(default_factory=dict)
    # Actionable cards for the client to render beside the answer. Deliberately
    # not part of `data`: `data` is handed to the narrator as `details`, and a
    # model shown its own cards writes the prose the cards exist to replace.
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    # Set when the question cannot be answered from the data at all, so the
    # caller knows not to dress it up with narration.
    unsupported: bool = False


HEADLINE_LABELS = {
    "gross_revenue": "Revenue",
    "orders": "Orders",
    "average_order_value": "Average order value",
    "customers": "Customers",
    "items_sold": "Items sold",
    "cancelled_orders": "Cancelled orders",
    "cancelled_value": "Cancelled order value",
}

MONEY_METRICS = {
    "gross_revenue",
    "average_order_value",
    "item_revenue",
    "cancelled_value",
    "discount_total",
}


UNANSWERABLE_FALLBACK = (
    "I could not find data that answers that. I can help with revenue, orders, "
    "dishes, categories, busy times, customer retention, offer performance, "
    "cancellations, order timings, stock availability, payment failures, branch "
    "status, and menu gaps."
)

# Named so a refusal can list them rather than saying "a metric".
SUPPORTED_METRIC_NAMES = (
    "revenue",
    "orders",
    "average order value",
    "customers",
    "items sold",
    "cancelled orders",
)

# What the platform holds instead of the thing that was asked about. Each entry
# names the nearest real answer, so a refusal points somewhere rather than
# just closing the door.
UNANSWERABLE_ENTITY_REPLIES: dict[str, str] = {
    "registered_users": (
        "I can only see customers who placed an order in a period, not your "
        "registered user list. Ask me how many customers ordered, and I can "
        "answer that. The full user list is on the Users page."
    ),
    "marketing_spend": (
        "No marketing or advertising spend is recorded anywhere, so I cannot "
        "tell you what it cost or what it returned. I can show you the push "
        "campaigns you have sent and how many were opened."
    ),
    "reservations": (
        "The platform does not take table bookings, so there is nothing "
        "recorded to report on. I can tell you about orders instead."
    ),
    "refunds": (
        "Refunds are not tracked separately. I can show you cancelled orders "
        "and the reasons they were cancelled, including payments that never "
        "completed."
    ),
    "delivery_partners": (
        "Delivery partners are not recorded against orders, so I cannot report "
        "on them. I can show you how long orders took to be accepted and "
        "prepared."
    ),
    "not_enabled_yet": (
        "I can see the data behind that question, but I am not set up to answer "
        "it here yet. Ask your administrator to enable it, or ask me about "
        "revenue, orders, dishes, branches, customers, offers or cancellations."
    ),
    "offer_validity": (
        "I can show how your offers performed, but not which are live or when "
        "they expire."
    ),
}


def _resolve_comparison(params: SkillParams) -> PeriodComparison:
    return resolve_period_comparison(
        date_from=params.date_from,
        date_to=params.date_to,
        window_days=params.window_days,
    )


def _has_explicit_period(params: SkillParams) -> bool:
    return (
        params.date_from is not None
        or params.date_to is not None
        or params.window_days is not None
    )


def _snapshot(
    db: Session, scope: InsightsScope, params: SkillParams
) -> tuple[DiagnosticsSnapshotResponse, PeriodComparison]:
    """The diagnostics behind an answer, over a window with trade in it.

    When the owner named a period, that period is used exactly — answering a
    different question than the one asked would be worse than answering
    "nothing happened".

    When they did not, the same widening ladder the nightly generation uses
    applies. Otherwise a low-volume restaurant is told "no dishes declined" on a
    seven-day window while a month of real declines sits just outside it. The
    window used is always stated in the reply's caveats.
    """

    if _has_explicit_period(params):
        comparison = _resolve_comparison(params)
        return build_diagnostics_snapshot(db, scope=scope, comparison=comparison), comparison

    first: tuple[DiagnosticsSnapshotResponse, PeriodComparison] | None = None
    for window_days in settings.insights_adaptive_window_days_list:
        comparison = resolve_period_comparison(window_days=window_days)
        snapshot = build_diagnostics_snapshot(db, scope=scope, comparison=comparison)
        if first is None:
            first = (snapshot, comparison)
        if snapshot.data_quality.sufficient_volume:
            return snapshot, comparison

    return first


def _format_metric(metric: str, value: float) -> str:
    return money(value) if metric in MONEY_METRICS else f"{round(value):,}"


def _pack(
    comparison: PeriodComparison,
    *,
    headline: dict[str, Any] | None = None,
    findings: list[dict[str, Any]] | None = None,
    notes: list[str] | None = None,
) -> FactPack:
    return FactPack(
        period_label=comparison.current.label(),
        previous_period_label=comparison.previous.label(),
        timezone=comparison.timezone_name,
        headline=headline or {},
        insights=findings or [],
        notes=notes or [],
    )


def _headline_map(snapshot: DiagnosticsSnapshotResponse) -> dict[str, Any]:
    return {
        row.metric: {
            "current": round(row.current, 2),
            "previous": round(row.previous, 2),
            "change": round(row.absolute_change, 2),
            "percent_change": (
                round(row.percent_change, 1) if row.percent_change is not None else None
            ),
            "direction": row.direction,
        }
        for row in snapshot.headline
    }


def _breakdown(snapshot: DiagnosticsSnapshotResponse, dimension: str):
    for row in snapshot.breakdowns:
        if row.dimension == dimension:
            return row
    return None


def _volume_note(snapshot: DiagnosticsSnapshotResponse) -> list[str]:
    return list(snapshot.data_quality.notes)


# --- skills ----------------------------------------------------------------


def revenue_diagnosis(db: Session, scope: InsightsScope, params: SkillParams) -> SkillResult:
    """Why did the numbers move? Decomposes the change across every dimension."""

    snapshot, comparison = _snapshot(db, scope, params)
    revenue = next(
        (row for row in snapshot.headline if row.metric == "gross_revenue"), None
    )

    findings: list[dict[str, Any]] = []
    lead = ""
    movers: list[str] = []

    if revenue is None or (revenue.current == 0 and revenue.previous == 0):
        lead = f"There were no counted orders in {comparison.current.label()}."
    else:
        direction = revenue.direction
        if direction == "flat":
            lead = (
                f"Revenue held steady at {bold(money(revenue.current))} in "
                f"{comparison.current.label()}."
            )
        else:
            movement = "down" if direction == "down" else "up"
            share = (
                f" ({percent(revenue.percent_change)})"
                if revenue.percent_change is not None
                else ""
            )
            lead = (
                f"Revenue was {bold(money(revenue.current))} in "
                f"{comparison.current.label()}, {movement} "
                f"{money(revenue.absolute_change)}{share} from "
                f"{money(revenue.previous)} the period before."
            )

        # Name the biggest mover in each dimension that actually moved.
        for dimension, label in (
            ("item", "dish"),
            ("category", "category"),
            ("daypart", "time of day"),
            ("customer_cohort", "customer group"),
        ):
            breakdown = _breakdown(snapshot, dimension)
            if breakdown is None or not breakdown.contributions:
                continue
            top = breakdown.contributions[0]
            if abs(top.absolute_change) < 1:
                continue
            moved = "fell" if top.absolute_change < 0 else "grew"
            movers.append(
                labelled(
                    label.capitalize(),
                    f"{top.label} {moved} by {bold(money(top.absolute_change))}",
                )
            )
            findings.append(
                {
                    "dimension": dimension,
                    "subject": top.label,
                    "numbers": {
                        "current": round(top.current, 2),
                        "previous": round(top.previous, 2),
                        "change": round(top.absolute_change, 2),
                        "share_of_total_change": (
                            round(top.contribution_share, 1)
                            if top.contribution_share is not None
                            else None
                        ),
                    },
                }
            )

    caveat = (
        "Order volume is low enough that these percentages are unreliable."
        if not snapshot.data_quality.sufficient_volume
        else ""
    )

    return SkillResult(
        skill="revenue_diagnosis",
        # A list only when there is a list to show: one mover reads better as a
        # sentence than as a single bullet under a heading.
        answer=blocks(
            lead,
            "Here is what moved most:" if len(movers) > 1 else "",
            bullets(movers) if len(movers) > 1 else (movers[0] if movers else ""),
            caveat,
        ),
        fact_pack=_pack(
            comparison,
            headline=_headline_map(snapshot),
            findings=findings,
            notes=_volume_note(snapshot),
        ),
        data={"snapshot": snapshot.model_dump(mode="json")},
    )


def metric_lookup(db: Session, scope: InsightsScope, params: SkillParams) -> SkillResult:
    """A straight number, with its change against the previous period."""

    snapshot, comparison = _snapshot(db, scope, params)
    metric = params.metric

    if metric is None:
        # No default. Falling back to revenue answered a question nobody asked,
        # in the same confident voice as a correct answer — which is worse than
        # saying nothing, because there is no way to tell the two apart.
        return SkillResult(
            skill="metric_lookup",
            answer=blocks(
                "I could not tell which figure you meant, so I would rather ask "
                "than guess.",
                "I can give you any of these:",
                bullets(SUPPORTED_METRIC_NAMES),
            ),
            fact_pack=_pack(comparison),
            unsupported=True,
        )

    row = next((item for item in snapshot.headline if item.metric == metric), None)

    if row is None:
        return SkillResult(
            skill="metric_lookup",
            answer=blocks(
                f"I do not track a metric called {metric}.",
                "I can give you any of these:",
                bullets(SUPPORTED_METRIC_NAMES),
            ),
            fact_pack=_pack(comparison),
            unsupported=True,
        )

    label = HEADLINE_LABELS.get(metric, metric.replace("_", " ").capitalize())
    sentence = (
        f"{label} was {_format_metric(metric, row.current)} in "
        f"{comparison.current.label()}."
    )
    if row.direction != "flat":
        movement = "down" if row.direction == "down" else "up"
        share = (
            f" ({percent(row.percent_change)})" if row.percent_change is not None else ""
        )
        sentence += (
            f" That is {movement} {_format_metric(metric, row.absolute_change)}{share} "
            f"from {_format_metric(metric, row.previous)} the period before."
        )

    return SkillResult(
        skill="metric_lookup",
        answer=sentence,
        fact_pack=_pack(
            comparison,
            headline={metric: _headline_map(snapshot).get(metric, {})},
            notes=_volume_note(snapshot),
        ),
        data={"metric": metric},
    )


def item_performance(db: Session, scope: InsightsScope, params: SkillParams) -> SkillResult:
    """Which dishes are carrying the period, and which are slipping."""

    snapshot, comparison = _snapshot(db, scope, params)
    breakdown = _breakdown(snapshot, "item")

    if breakdown is None or not breakdown.contributions:
        return SkillResult(
            skill="item_performance",
            answer=f"No dish sales were recorded in {comparison.current.label()}.",
            fact_pack=_pack(comparison, notes=_volume_note(snapshot)),
        )

    rows = breakdown.contributions
    if params.subject:
        wanted = params.subject.strip().lower()
        matched = [row for row in rows if wanted in row.label.lower()]
        if matched:
            row = matched[0]
            return SkillResult(
                skill="item_performance",
                answer=(
                    f"{row.label} brought in {money(row.current)} in "
                    f"{comparison.current.label()}, against {money(row.previous)} the "
                    f"period before, a change of {money(row.absolute_change)}."
                ),
                fact_pack=_pack(
                    comparison,
                    findings=[
                        {
                            "subject": row.label,
                            "numbers": {
                                "current": round(row.current, 2),
                                "previous": round(row.previous, 2),
                                "change": round(row.absolute_change, 2),
                            },
                        }
                    ],
                    notes=_volume_note(snapshot),
                ),
                data={"subject": row.label},
            )

    return _ranked_items(db, scope, rows, comparison, snapshot, params)


# How a dish is measured when a question asks for the "most" or "fewest" of it.
# Every basis here is already carried on a contribution row, so ranking needs no
# extra query.
ITEM_RANK_VALUE = {
    "revenue": lambda row: row.current,
    "orders": lambda row: row.current_orders,
    "quantity": lambda row: row.current_quantity,
}
ITEM_RANK_LABEL = {
    "revenue": ("revenue", lambda row: money(row.current)),
    "orders": ("order count", lambda row: f"{row.current_orders} orders"),
    "quantity": ("units sold", lambda row: f"{row.current_quantity} sold"),
}


def _ranked_items(
    db: Session,
    scope: InsightsScope,
    rows: list,
    comparison: PeriodComparison,
    snapshot: DiagnosticsSnapshotResponse,
    params: SkillParams,
) -> SkillResult:
    """Answer the item question that was actually asked.

    Four directions, three ranking bases. Previously this rendered one fixed
    shape — biggest earner, biggest fall, biggest rise — whatever was asked, so
    "which sell least" and "which dropped most" produced the same reply. The
    direction and basis now come from the question, and the answer states which
    it used so a wrong reading is visible rather than silent.
    """

    direction = params.direction or "top"
    basis = params.rank_by or "revenue"
    limit = params.limit or 3
    basis_name, render = ITEM_RANK_LABEL[basis]
    value_of = ITEM_RANK_VALUE[basis]
    period = comparison.current.label()

    if direction in {"falling", "rising"}:
        # The basis applies to movement too. "The biggest drop in orders" is a
        # question about order counts, and answering it with a revenue ranking
        # would be the same silent substitution this rewrite exists to remove.
        if basis == "orders":
            change_of = lambda row: row.current_orders - row.previous_orders
            render_change = lambda row: (
                f"{abs(change_of(row))} fewer orders"
                if change_of(row) < 0
                else f"{change_of(row)} more orders"
            )
            change_basis = "order count"
        elif basis == "quantity":
            change_of = lambda row: row.current_quantity - row.previous_quantity
            render_change = lambda row: (
                f"{abs(change_of(row))} fewer sold"
                if change_of(row) < 0
                else f"{change_of(row)} more sold"
            )
            change_basis = "units sold"
        else:
            change_of = lambda row: row.absolute_change
            render_change = lambda row: money(row.absolute_change)
            change_basis = "revenue"

        moving = [
            row
            for row in rows
            if (change_of(row) < 0 if direction == "falling" else change_of(row) > 0)
        ]
        if not moving:
            # Said plainly instead of substituting the opposite movement, which
            # is how a question about drops was answered with a rise.
            word = "fell" if direction == "falling" else "grew"
            return SkillResult(
                skill="item_performance",
                answer=f"No dish {word} in {period}.",
                fact_pack=_pack(comparison, notes=_volume_note(snapshot)),
                data={"items": []},
            )

        moving.sort(key=change_of, reverse=direction == "rising")
        picked = moving[:limit]
        verb = "fell" if direction == "falling" else "grew"
        lead = f"Dishes that {verb} most in {period}, by {change_basis}:"
        listed = [
            labelled(
                row.label,
                f"{verb} by {bold(render_change(row))}, now {money(row.current)} "
                f"against {money(row.previous)}",
            )
            for row in picked
        ]
        findings = [
            {
                "subject": row.label,
                "numbers": {
                    "current": round(row.current, 2),
                    "previous": round(row.previous, 2),
                    "change": round(row.absolute_change, 2),
                    "orders": row.current_orders,
                    "previous_orders": row.previous_orders,
                    "quantity": row.current_quantity,
                    "previous_quantity": row.previous_quantity,
                },
            }
            for row in picked
        ]
    else:
        # Every dish, not the ranked contributions. Contributions are the top
        # movers by size of change — the right input for attributing a change,
        # and the wrong one for "which sells least", where the answer is
        # precisely the dishes too small to appear in that list. Ranking the
        # truncated set returned the bottom of the top eight.
        all_items = metrics_layer.fetch_item_metrics(db, scope, comparison.current)
        if not all_items:
            return SkillResult(
                skill="item_performance",
                answer=f"No dish sales were recorded in {period}.",
                fact_pack=_pack(comparison, notes=_volume_note(snapshot)),
                data={"items": []},
            )

        level_of = {
            "revenue": lambda item: item.revenue,
            "orders": lambda item: item.orders,
            "quantity": lambda item: item.quantity,
        }[basis]
        level_text = {
            "revenue": lambda item: money(item.revenue),
            "orders": lambda item: f"{item.orders} order{'s' if item.orders != 1 else ''}",
            "quantity": lambda item: f"{item.quantity} sold",
        }[basis]

        ranked = sorted(
            all_items, key=lambda item: (level_of(item), item.name), reverse=direction == "top"
        )
        picked = ranked[:limit]
        end = "best" if direction == "top" else "weakest"
        lead = f"Your {end} dishes in {period}, by {basis_name}:"
        listed = [labelled(item.name, bold(level_text(item))) for item in picked]
        findings = [
            {
                "subject": item.name,
                "numbers": {
                    "revenue": round(item.revenue, 2),
                    "orders": item.orders,
                    "quantity": item.quantity,
                },
            }
            for item in picked
        ]

    return SkillResult(
        skill="item_performance",
        answer=blocks(lead, bullets(listed)),
        fact_pack=_pack(comparison, findings=findings, notes=_volume_note(snapshot)),
        data={"items": findings, "direction": direction, "rank_by": basis},
    )


def time_patterns(db: Session, scope: InsightsScope, params: SkillParams) -> SkillResult:
    """When the restaurant is busy, in its own local time."""

    snapshot, comparison = _snapshot(db, scope, params)
    dayparts = _breakdown(snapshot, "daypart")
    weekdays = _breakdown(snapshot, "weekday")

    findings: list[dict[str, Any]] = []
    sentences: list[str] = []

    if dayparts is not None and dayparts.contributions:
        busiest = max(dayparts.contributions, key=lambda row: row.current)
        sentences.append(
            labelled(
                "Busiest stretch",
                f"{busiest.label}, taking {bold(money(busiest.current))} across "
                f"{busiest.current_orders} orders",
            )
        )
        findings.extend(
            {
                "daypart": row.label,
                "numbers": {
                    "revenue": round(row.current, 2),
                    "orders": row.current_orders,
                    "change": round(row.absolute_change, 2),
                },
            }
            for row in dayparts.contributions
        )

    if weekdays is not None and weekdays.contributions:
        busiest_day = max(weekdays.contributions, key=lambda row: row.current)
        quietest_day = min(weekdays.contributions, key=lambda row: row.current)
        sentences.append(
            labelled(
                "Busiest day",
                f"{busiest_day.label} at {bold(money(busiest_day.current))} — "
                f"{quietest_day.label} was quietest at "
                f"{money(quietest_day.current)}",
            )
        )
        findings.extend(
            {
                "weekday": row.label,
                "numbers": {
                    "revenue": round(row.current, 2),
                    "orders": row.current_orders,
                },
            }
            for row in weekdays.contributions
        )

    caveat = ""
    if not sentences:
        lead = f"No orders were recorded in {comparison.current.label()}."
    else:
        lead = f"Here is how {comparison.current.label()} was distributed:"
        if not snapshot.data_quality.weekday_aligned:
            caveat = (
                "The two periods cover different weekdays, so day-to-day "
                "comparisons are not like-for-like."
            )

    return SkillResult(
        skill="time_patterns",
        answer=blocks(lead, bullets(sentences), caveat),
        fact_pack=_pack(comparison, findings=findings, notes=_volume_note(snapshot)),
        data={"patterns": findings},
    )


def customer_retention(db: Session, scope: InsightsScope, params: SkillParams) -> SkillResult:
    """New versus returning customers, and which of them moved."""

    snapshot, comparison = _snapshot(db, scope, params)
    cohorts = _breakdown(snapshot, "customer_cohort")

    if cohorts is None or not cohorts.contributions:
        return SkillResult(
            skill="customer_retention",
            answer=f"No customer activity was recorded in {comparison.current.label()}.",
            fact_pack=_pack(comparison, notes=_volume_note(snapshot)),
        )

    # How many customers each cohort actually contains. The contribution rows
    # carry money and orders but no headcount, so "how many new customers did I
    # get" had no figure to answer it — and an answer built from what was there
    # reported the cohort's revenue as a customer count.
    headcount = {
        row.cohort.lower(): row.customers
        for row in metrics_layer.fetch_customer_cohorts(db, scope, comparison.current)
    }

    rows = []
    findings = []
    for row in cohorts.contributions:
        movement = (
            "unchanged"
            if row.direction == "flat"
            else ("down" if row.direction == "down" else "up")
        )
        change = (
            ""
            if row.direction == "flat"
            else f", {movement} {money(row.absolute_change)} from {money(row.previous)}"
        )
        customers = headcount.get(row.key.lower())
        who = (
            f"{bold(str(customers))} {'customer' if customers == 1 else 'customers'} spending "
            if customers is not None
            else ""
        )
        rows.append(
            labelled(
                row.label,
                f"{who}{bold(money(row.current))} across {row.current_orders} "
                f"orders{change}",
            )
        )
        findings.append(
            {
                "cohort": row.label,
                "numbers": {
                    "customers": customers,
                    "current": round(row.current, 2),
                    "previous": round(row.previous, 2),
                    "change": round(row.absolute_change, 2),
                    "orders": row.current_orders,
                },
            }
        )

    return SkillResult(
        skill="customer_retention",
        answer=blocks(
            f"Here is how your customer groups compare in {comparison.current.label()}:",
            bullets(rows),
        ),
        fact_pack=_pack(comparison, findings=findings, notes=_volume_note(snapshot)),
        data={"cohorts": findings},
    )


def offer_performance(db: Session, scope: InsightsScope, params: SkillParams) -> SkillResult:
    """Did the promotions pay for themselves?"""

    comparison = _resolve_comparison(params)
    rows = fetch_offer_performance(db, scope, comparison.current)

    if not rows:
        return SkillResult(
            skill="offer_performance",
            answer=(
                f"No orders in {comparison.current.label()} were placed with an offer, "
                "so there is nothing to measure yet."
            ),
            fact_pack=_pack(comparison),
        )

    sentences = []
    findings = []
    for row in rows[:3]:
        ratio = (
            f" That is {money(row.gross_revenue)} of revenue for every "
            f"{money(row.discount_cost)} discounted."
            if row.return_per_unit_discount is not None
            else ""
        )
        sentences.append(
            labelled(
                row.offer_name,
                f"{row.orders} orders worth {bold(money(row.gross_revenue))}, at a "
                f"discount cost of {money(row.discount_cost)}.{ratio}",
            )
        )
        findings.append(
            {
                "offer": row.offer_name,
                "numbers": {
                    "orders": row.orders,
                    "gross_revenue": round(row.gross_revenue, 2),
                    "discount_cost": round(row.discount_cost, 2),
                    "net_revenue": round(row.net_revenue, 2),
                },
            }
        )

    return SkillResult(
        skill="offer_performance",
        answer=blocks(
            f"Here is how your offers did in {comparison.current.label()}:",
            bullets(sentences),
            # Said plainly, because "net revenue" invites being read as profit.
            "These figures are revenue after discount, not profit: food and "
            "delivery costs are not recorded.",
        ),
        fact_pack=_pack(comparison, findings=findings),
        data={"offers": findings},
    )


def _widest_analysable(
    db: Session, scope: InsightsScope, params: SkillParams
) -> tuple[Any, Any]:
    """The narrowest window that actually contains trade, and its snapshot.

    A restaurant taking a few orders a week has nothing in the last 7 days to
    reason about. Rather than reporting that emptiness as the answer, the window
    widens until there is something real in it.
    """

    explicit = params.date_from or params.date_to or params.window_days
    if explicit:
        comparison = _resolve_comparison(params)
        return comparison, build_diagnostics_snapshot(db, scope=scope, comparison=comparison)

    # Widened until the window has enough trade to reason about, not merely a
    # single order in it. Stopping at the first non-empty window meant a quiet
    # restaurant was judged on the one order it took this week, which is how
    # "too little to say" became the permanent answer for anyone small.
    best_with_orders = None
    widest = None
    for window_days in settings.insights_adaptive_window_days_list:
        comparison = resolve_period_comparison(window_days=window_days)
        snapshot = build_diagnostics_snapshot(db, scope=scope, comparison=comparison)
        widest = (comparison, snapshot)
        if snapshot.data_quality.sufficient_volume:
            return comparison, snapshot
        orders = next(
            (row for row in snapshot.headline if row.metric == "orders"), None
        )
        if orders is not None and orders.current > 0:
            best_with_orders = (comparison, snapshot)
    return best_with_orders or widest


def _starter_guidance(
    db: Session, scope: InsightsScope, params: SkillParams
) -> SkillResult:
    """Grounded suggestions for a restaurant with nothing queued to act on.

    Every line below names a figure from this restaurant's own window. Nothing
    is invented and nothing is ranked by expected impact, because there is not
    enough movement to estimate one — and saying so is part of the answer.
    """

    comparison, snapshot = _widest_analysable(db, scope, params)
    period = comparison.current.label()
    orders = next((row for row in snapshot.headline if row.metric == "orders"), None)
    revenue = next(
        (row for row in snapshot.headline if row.metric == "gross_revenue"), None
    )

    if orders is None or orders.current <= 0:
        return SkillResult(
            skill="recommendations",
            answer=blocks(
                f"No orders were recorded in {period}, so there is nothing in the "
                "data to base a suggestion on yet.",
                "Once orders start coming in I can tell you which dishes sell, "
                "when you are busiest, and who is coming back.",
            ),
            fact_pack=_pack(comparison, notes=_volume_note(snapshot)),
        )

    lines: list[str] = []
    findings: list[dict[str, Any]] = []

    items = _breakdown(snapshot, "item")
    if items and items.contributions:
        best = max(items.contributions, key=lambda row: row.current)
        if best.current > 0:
            lines.append(
                action(
                    f"Lead with {best.label}",
                    f"It brought in {bold(money(best.current))} across "
                    f"{best.current_orders} orders in {period} — your strongest "
                    "dish in this window, so it is the one worth putting in front "
                    "of people.",
                )
            )
            findings.append(
                {
                    "suggestion": f"Lead with {best.label}",
                    "numbers": {
                        "revenue": round(best.current, 2),
                        "orders": best.current_orders,
                    },
                }
            )

    dayparts = _breakdown(snapshot, "daypart")
    if dayparts and len(dayparts.contributions) > 1:
        quietest = min(dayparts.contributions, key=lambda row: row.current)
        busiest = max(dayparts.contributions, key=lambda row: row.current)
        if busiest.current > quietest.current:
            # Heading and body both lead with the quiet stretch. Written the
            # other way round — "Look at lunch" over "Afternoon took ₹259
            # while lunch took ₹31" — the first figure sat next to the wrong
            # label, and a summariser duly reported lunch taking ₹259.
            lines.append(
                action(
                    f"{quietest.label} is your quietest stretch",
                    f"{quietest.label} took {bold(money(quietest.current))} in "
                    f"{period}, against {bold(money(busiest.current))} in the "
                    f"{busiest.label.lower()}. The gap is where there is room to "
                    "grow, not a fault.",
                )
            )
            findings.append(
                {
                    "suggestion": f"Look at {quietest.label}",
                    "numbers": {
                        "busiest_revenue": round(busiest.current, 2),
                        "quietest_revenue": round(quietest.current, 2),
                    },
                }
            )

    cohorts = _breakdown(snapshot, "customer_cohort")
    if cohorts and cohorts.contributions:
        returning = next(
            (row for row in cohorts.contributions if "return" in row.label.lower()), None
        )
        new_customers = next(
            (row for row in cohorts.contributions if "new" in row.label.lower()), None
        )
        if new_customers is not None and (returning is None or returning.current <= 0):
            lines.append(
                action(
                    "Give first-time customers a reason to come back",
                    f"All {bold(money(new_customers.current))} in {period} came from "
                    "first-time customers, with nothing recorded from returning "
                    "ones. Repeat trade is the cheapest growth there is.",
                )
            )
            findings.append(
                {
                    "suggestion": "Bring first-time customers back",
                    "numbers": {"new_customer_revenue": round(new_customers.current, 2)},
                }
            )

    if not lines:
        return SkillResult(
            skill="recommendations",
            answer=blocks(
                f"There {'was' if int(orders.current) == 1 else 'were'} "
                f"{int(orders.current)} order{'' if int(orders.current) == 1 else 's'} "
                f"in {period}"
                + (f", worth {money(revenue.current)}" if revenue else "")
                + ". That is too little for me to suggest anything specific "
                "without guessing, and a guess is worse than nothing.",
                "Ask me about dishes, busy times or customers and I will tell you "
                "what the orders you do have show.",
            ),
            fact_pack=_pack(comparison, notes=_volume_note(snapshot)),
        )

    opening = (
        f"Nothing is queued for approval, so here is what your own figures for "
        f"{period} point at."
    )
    caveat = (
        f"These come from {int(orders.current)} order"
        f"{'' if int(orders.current) == 1 else 's'}, which is too few to rank "
        "by expected impact — treat them as a starting point rather than a plan."
        if not snapshot.data_quality.sufficient_volume
        else "These are drawn straight from your figures for this period."
    )

    return SkillResult(
        skill="recommendations",
        answer=blocks(opening, *lines, caveat),
        fact_pack=_pack(comparison, findings=findings, notes=_volume_note(snapshot)),
        data={"source": "live", "low_confidence": not snapshot.data_quality.sufficient_volume},
    )


def recommendations(db: Session, scope: InsightsScope, params: SkillParams) -> SkillResult:
    """What the manager currently suggests doing."""

    comparison = _resolve_comparison(params)
    proposals = list_proposals(
        db, scope=scope, statuses=[OwnerActionStatus.PROPOSED], limit=5
    )

    if not proposals:
        # No stored proposals does not mean nothing to say. A quiet restaurant
        # was told "there are no open recommendations" and left there, which
        # reads as the feature not working — while its own data held a best
        # seller, a quiet stretch of the day and a customer mix worth knowing
        # about. Everything below is read from that restaurant's own records and
        # labelled for what it is: a starting point, not a ranked plan.
        return _starter_guidance(db, scope, params)

    items = []
    findings = []
    for proposal in proposals:
        impact = (
            f" Estimated recovery {bold(money(float(proposal.expected_impact_amount)))}."
            if proposal.expected_impact_amount is not None
            else ""
        )
        # The instruction first, the evidence under it: an owner deciding whether
        # to act should not have to find the action inside a paragraph of
        # justification.
        items.append(action(proposal.title, f"{proposal.rationale}{impact}"))
        findings.append(
            {
                "recommendation": proposal.title,
                "executable": proposal.is_executable,
                "numbers": {
                    "expected_impact": (
                        round(float(proposal.expected_impact_amount), 2)
                        if proposal.expected_impact_amount is not None
                        else None
                    ),
                },
            }
        )

    cards = offer_cards_from_proposals(db, proposals)
    if cards:
        # The cards carry the name, the discount and the rationale, so repeating
        # all of it in prose above them is noise. The lead-in stays, the list goes.
        answer = blocks(
            f"Here {'is' if len(cards) == 1 else 'are'} {len(cards)} "
            f"thing{'s' if len(cards) != 1 else ''} worth doing. "
            "Impact figures are estimates, and nothing runs until you approve it.",
        )
    else:
        answer = blocks(
            f"Here {'is' if len(items) == 1 else 'are'} {len(items)} "
            f"thing{'s' if len(items) != 1 else ''} worth doing:",
            numbered(items),
            "Impact figures are estimates. Nothing runs until you approve it.",
        )

    return SkillResult(
        skill="recommendations",
        answer=answer,
        fact_pack=_pack(comparison, findings=findings),
        data={"proposals": [str(proposal.id) for proposal in proposals]},
        suggestions=cards,
    )


def branch_comparison(db: Session, scope: InsightsScope, params: SkillParams) -> SkillResult:
    """Two or more named branches, side by side over the same window.

    Each branch is measured under its own narrowed scope rather than by slicing
    a restaurant-wide total, so the figures here are the same ones a
    branch-scoped question would produce.
    """

    # The same widening ladder the other skills use. On the default seven days a
    # branch that closed a month ago reads as "₹0 against ₹0", which is true and
    # useless; the window that actually contains the change is the one to answer
    # over, and the reply states which window that was.
    if _has_explicit_period(params):
        comparison = _resolve_comparison(params)
    else:
        _, comparison = _snapshot(db, scope, params)

    branch_names = list(params.branches)

    if len(branch_names) < 2:
        return SkillResult(
            skill="branch_comparison",
            answer=(
                "I need two branches to compare. Name them both, for example "
                "\"how is X doing compared to Y\"."
            ),
            fact_pack=_pack(comparison),
        )

    locations = {
        row.branch_name: row
        for row in db.scalars(
            select(RestaurantLocation).where(
                RestaurantLocation.restaurant_id == scope.restaurant_id,
                RestaurantLocation.branch_name.in_(branch_names),
            )
        )
    }

    sentences: list[str] = []
    findings: list[dict[str, Any]] = []
    for name in branch_names:
        location = locations.get(name)
        if location is None:
            continue
        branch_scope = InsightsScope(
            restaurant_id=scope.restaurant_id,
            restaurant_location_id=location.id,
        )
        current = metrics_layer.fetch_totals(db, branch_scope, comparison.current)
        previous = metrics_layer.fetch_totals(db, branch_scope, comparison.previous)
        change = current.gross_revenue - previous.gross_revenue

        closed_note = "" if location.is_open else " Currently marked closed."
        if current.orders == 0 and previous.orders > 0:
            sentences.append(
                labelled(
                    name,
                    f"{bold('no orders')} this period, against {previous.orders} "
                    f"worth {money(previous.gross_revenue)} before.{closed_note}",
                )
            )
        else:
            sentences.append(
                labelled(
                    name,
                    f"{current.orders} orders worth "
                    f"{bold(money(current.gross_revenue))}, against "
                    f"{money(previous.gross_revenue)} the period before."
                    f"{closed_note}",
                )
            )

        findings.append(
            {
                "branch": name,
                "is_open": location.is_open,
                "numbers": {
                    "orders": current.orders,
                    "gross_revenue": round(current.gross_revenue, 2),
                    "previous_gross_revenue": round(previous.gross_revenue, 2),
                    "absolute_change": round(change, 2),
                    "customers": current.customers,
                },
            }
        )

    return SkillResult(
        skill="branch_comparison",
        answer=blocks(
            "Side by side:",
            bullets(sentences),
            f"Figures cover {comparison.current.label()}.",
        ),
        fact_pack=_pack(comparison, findings=findings),
        data={"branches": branch_names},
    )


def tool_answer(db: Session, scope: InsightsScope, params: SkillParams) -> SkillResult:
    """Run the data tool a Tier 2 planner chose, and state what it returned.

    The tool is executed against the caller's own scope, which the planner never
    saw and could not have named. The answer is composed by a formatter in code,
    so no figure here was written by a model — and the reply names the data it
    used, so a wrong tool choice is visible rather than silent.
    """

    from app.services.insights.analyst.registry import call_tool
    from app.services.insights.tool_chat import CHAT_TOOLS, TOOL_FORMATTERS

    comparison = _resolve_comparison(params)
    tool = params.tool or ""

    if tool not in CHAT_TOOLS:
        # Belt and braces: the planner already checks this, and a plan reaching
        # here with anything else is a bug rather than a question to answer.
        return SkillResult(
            skill="tool_answer",
            answer=UNANSWERABLE_FALLBACK,
            fact_pack=_pack(comparison),
            unsupported=True,
        )

    result = call_tool(db, scope, tool, params.tool_args or {})
    if not result.ok:
        return SkillResult(
            skill="tool_answer",
            answer=blocks(
                "I could not look that up.",
                result.detail or "The lookup did not return anything usable.",
            ),
            fact_pack=_pack(comparison),
            unsupported=True,
        )

    answer = TOOL_FORMATTERS[tool](result.data)
    if not answer:
        # A formatter that cannot describe what it got says nothing rather than
        # something vague, and the refusal path takes over.
        return SkillResult(
            skill="tool_answer",
            answer=UNANSWERABLE_FALLBACK,
            fact_pack=_pack(comparison),
            unsupported=True,
        )

    # Two lookups have something the owner can act on rather than only read.
    # Note the answer text itself is left alone here: on the tool path the
    # narrator rewrites it from the facts, so shortening this template changed
    # nothing that reached the screen. Only the skills that answer with their
    # own wording - recommendations, item_promotion_advice - were trimmed.
    cards: list[dict[str, Any]] = []
    if tool == "get_combos":
        cards = combo_cards(db, scope)
    elif tool == "get_offer_catalogue":
        cards = offer_cards_from_catalogue(db, scope)

    return SkillResult(
        skill="tool_answer",
        answer=answer,
        fact_pack=_pack(comparison, findings=[{"tool": tool, "numbers": result.data}]),
        data={"tool": tool, "args": result.args},
        suggestions=cards,
    )


def briefing_recall(db: Session, scope: InsightsScope, params: SkillParams) -> SkillResult:
    """The most recent generated briefing, repeated back."""

    comparison = _resolve_comparison(params)
    briefing = get_latest_briefing(db, scope=scope)

    if briefing is None:
        # Rather than silently answering a different question, fall through to a
        # live diagnosis so the owner still gets a summary.
        result = revenue_diagnosis(db, scope, params)
        return SkillResult(
            skill="briefing_recall",
            answer=(
                "No briefing has been generated yet, so here is the current picture. "
                + result.answer
            ),
            fact_pack=result.fact_pack,
            data=result.data,
        )

    return SkillResult(
        skill="briefing_recall",
        answer=blocks(bold(briefing.headline), briefing.narrative),
        fact_pack=FactPack(
            period_label=briefing.facts.get("period", comparison.current.label()),
            previous_period_label=briefing.facts.get(
                "previous_period", comparison.previous.label()
            ),
            timezone=briefing.facts.get("timezone", comparison.timezone_name),
            headline=briefing.facts.get("headline", {}),
            insights=briefing.facts.get("findings", []),
            notes=briefing.facts.get("caveats", []),
        ),
        data={"briefing_id": str(briefing.id)},
    )


# What to say back to a person, rather than to a question about data. Keyed by
# the sub-intent the router detected, because "hello" and "what can you do" want
# very different replies and giving both the same capability list is what made
# the assistant feel like a machine with one response in it.
SMALL_TALK_REPLIES: dict[str, tuple[str, ...]] = {
    "greeting": (
        "Hello. What would you like to know about the restaurant?",
        "Hi there. Ask me anything about how the restaurant is doing.",
        "Hello. Ready when you are — what shall we look at?",
    ),
    "how_are_you": (
        "Doing well, thanks for asking. More to the point, the restaurant's "
        "numbers are here whenever you want them.",
        "All good here. Shall we take a look at how trading is going?",
    ),
    "thanks": (
        "Any time.",
        "You are welcome. Ask me anything else whenever you need it.",
    ),
    "goodbye": (
        "Speak soon.",
        "Goodbye — I will be here when you need the numbers.",
    ),
}

# Offered after a greeting so the owner has somewhere to start, and kept to
# three: the full capability list belongs in the answer to "what can you do",
# not in a reply to "hello".
SMALL_TALK_PROMPTS = (
    "How did last week go?",
    "Which dishes are selling best?",
    "What should I focus on?",
)


def small_talk(db: Session, scope: InsightsScope, params: SkillParams) -> SkillResult:
    """Reply to a person, not to a question about data.

    A greeting answered with "I could not work out which part of your data that
    question is about" is not a refusal — it is a bug. Nothing was asked about
    the data, so there is nothing to refuse.

    Deliberately deterministic and instant: there is no data behind a greeting,
    so there is nothing for the model to ground an answer in, and nobody wants
    to wait a minute to be greeted back. The reply varies with the wording so
    the same phrase always gets the same answer while different phrases do not
    all sound identical.
    """

    intent = params.topic or "greeting"

    if intent == "capabilities":
        return SkillResult(
            skill="small_talk",
            answer=blocks(
                "I am your restaurant's data assistant. I read this "
                "restaurant's own records and answer questions about them.",
                "Things I can cover:",
                bullets(
                    [
                        "Revenue, orders and average order value",
                        "Which dishes and categories are selling, and which are slipping",
                        "Busy times and quiet days",
                        "New and returning customers",
                        "Offers, cancellations and order timings",
                        "What to focus on next, based on the figures",
                    ]
                ),
                "Ask in your own words — you can ask for several things at once.",
            ),
            fact_pack=_pack(_resolve_comparison(params)),
        )

    options = SMALL_TALK_REPLIES.get(intent, SMALL_TALK_REPLIES["greeting"])
    # Chosen from the wording, not at random, so the reply is reproducible.
    reply = options[sum(ord(char) for char in (params.subject or "")) % len(options)]

    if intent == "greeting":
        reply = blocks(reply, "For example:", bullets(list(SMALL_TALK_PROMPTS)))

    return SkillResult(
        skill="small_talk",
        answer=reply,
        fact_pack=_pack(_resolve_comparison(params)),
    )


def unsupported(db: Session, scope: InsightsScope, params: SkillParams) -> SkillResult:
    """An honest refusal for questions the platform holds no data for.

    Answering these from adjacent numbers would be the most damaging thing the
    assistant could do: it would sound authoritative and be wrong.
    """

    comparison = _resolve_comparison(params)
    capability = (
        "I can help with revenue, orders, dishes, categories, busy times, "
        "customer retention, offer performance, cancellations, order timings, "
        "and recommendations."
    )

    # An entity the platform does not model gets its own sentence naming the
    # nearest thing that does exist. A generic refusal here sends the owner away
    # without telling them what to ask instead.
    if params.entity:
        reply = UNANSWERABLE_ENTITY_REPLIES.get(params.entity)
        if reply:
            return SkillResult(
                skill="unsupported",
                answer=reply,
                fact_pack=_pack(comparison),
                unsupported=True,
            )

    topic = UNSUPPORTED_TOPICS.get(params.topic or "", "")
    if not topic:
        # Reached when a topic was claimed that does not describe the question.
        # Naming a subject the owner never raised reads as a broken system, so
        # the refusal stays general rather than inventing one.
        return SkillResult(
            skill="unsupported",
            answer=blocks(
                "I could not work out which part of your data that question is "
                "about, so I would rather say so than answer something else.",
                capability,
            ),
            fact_pack=_pack(comparison),
            unsupported=True,
        )

    return SkillResult(
        skill="unsupported",
        answer=blocks(
            f"I do not have data on {topic}, so I cannot answer that.",
            capability,
        ),
        fact_pack=_pack(comparison),
        unsupported=True,
    )



def cancellation_reasons(
    db: Session, scope: InsightsScope, params: SkillParams
) -> SkillResult:
    """Why orders were cancelled, from the recorded reason on each one."""

    from app.services.insights.root_cause import (
        CANCELLATION_REASON_LABELS,
        cancellations_by_reason,
    )

    comparison = _resolve_comparison(params)
    breakdown = cancellations_by_reason(db, scope, comparison.current)

    if not breakdown:
        return SkillResult(
            skill="cancellation_reasons",
            answer=f"No orders were cancelled in {comparison.current.label()}.",
            fact_pack=_pack(comparison),
        )

    total = sum(row.orders for row in breakdown)
    lead = (
        f"{bold(total)} order{'s' if total != 1 else ''} were cancelled in "
        f"{comparison.current.label()}."
    )
    sentences = []
    findings = []
    for row in breakdown:
        label = CANCELLATION_REASON_LABELS.get(row.reason, "no reason was recorded")
        sentences.append(
            f"{row.orders} because {label}, worth {bold(money(row.value))}"
        )
        findings.append(
            {
                "reason": row.reason.value,
                "numbers": {"orders": row.orders, "value": round(row.value, 2)},
            }
        )

    return SkillResult(
        skill="cancellation_reasons",
        answer=blocks(lead, bullets(sentences)),
        fact_pack=_pack(comparison, findings=findings),
        data={"cancellations": findings},
    )


def order_operations(db: Session, scope: InsightsScope, params: SkillParams) -> SkillResult:
    """How quickly orders are accepted and prepared."""

    from app.services.insights.root_cause import acceptance_latency, preparation_time

    comparison = _resolve_comparison(params)
    latency = acceptance_latency(db, scope, comparison.current)
    previous = acceptance_latency(db, scope, comparison.previous)
    prep = preparation_time(db, scope, comparison.current)

    if latency.median_minutes is None and prep.median_minutes is None:
        # Timings come from events recorded from Phase 6A onward, so an older
        # window genuinely has nothing rather than nothing having happened.
        return SkillResult(
            skill="order_operations",
            answer=(
                f"No order timings were recorded for {comparison.current.label()}. "
                "Timings are captured from the point order history started being "
                "tracked, so older periods have none."
            ),
            fact_pack=_pack(comparison),
        )

    sentences = []
    findings = []
    if latency.median_minutes is not None:
        accepted = (
            f"a median of {bold(str(latency.median_minutes) + ' minutes')} across "
            f"{latency.sample_size} order{'s' if latency.sample_size != 1 else ''}"
        )
        findings.append(
            {
                "measure": "acceptance_minutes",
                "numbers": {
                    "median": latency.median_minutes,
                    "orders": latency.sample_size,
                    "previous_median": previous.median_minutes,
                },
            }
        )
        if previous.median_minutes is not None:
            direction = (
                "slower" if latency.median_minutes > previous.median_minutes else "faster"
            )
            accepted += (
                f", {direction} than the {previous.median_minutes} minutes "
                "the period before"
            )
        sentences.append(labelled("Time to accept", accepted))
    if prep.median_minutes is not None:
        sentences.append(
            labelled(
                "Time to prepare",
                f"a median of {bold(str(prep.median_minutes) + ' minutes')} across "
                f"{prep.sample_size} order{'s' if prep.sample_size != 1 else ''}",
            )
        )

        findings.append(
            {
                "measure": "preparation_minutes",
                "numbers": {"median": prep.median_minutes, "orders": prep.sample_size},
            }
        )

    # Named rather than omitted. A question about preparation answered with
    # acceptance times only, and no mention of the gap, is a partial answer
    # wearing the shape of a complete one.
    missing = [
        name
        for name, stats in (("accept", latency), ("prepare", prep))
        if stats.median_minutes is None
    ]

    gap = (
        f"No timings for how long orders took to {' or '.join(missing)} were "
        "recorded in this period, so that part is not covered above."
        if missing
        else ""
    )

    return SkillResult(
        skill="order_operations",
        answer=blocks(
            f"Order timings for {comparison.current.label()}:",
            bullets(sentences),
            gap,
        ),
        fact_pack=_pack(comparison, findings=findings),
        data={"operations": findings},
    )


def action_outcomes(db: Session, scope: InsightsScope, params: SkillParams) -> SkillResult:
    """Did the actions the owner approved actually do anything?"""

    from app.services.insights.outcomes import list_outcomes

    comparison = _resolve_comparison(params)
    rows = list_outcomes(db, scope=scope, limit=5)

    if not rows:
        return SkillResult(
            skill="action_outcomes",
            answer=(
                "No approved actions have been measured yet. Results appear once an "
                "offer has been running long enough for the numbers to mean anything."
            ),
            fact_pack=_pack(comparison),
        )

    sentences = []
    findings = []
    for row in rows:
        sentences.append(row.summary)
        findings.append(
            {
                "verdict": row.verdict.value,
                "numbers": {
                    "orders": row.attributed_orders,
                    "revenue": float(row.attributed_revenue),
                    "discount_cost": float(row.discount_cost),
                },
            }
        )

    return SkillResult(
        skill="action_outcomes",
        answer=blocks(
            "Here is what happened after the actions you approved:"
            if len(sentences) > 1
            else "",
            bullets(sentences) if len(sentences) > 1 else paragraph(*sentences),
        ),
        fact_pack=_pack(comparison, findings=findings),
        data={"outcomes": findings},
    )



def item_promotion_advice(
    db: Session, scope: InsightsScope, params: SkillParams
) -> SkillResult:
    """Which dishes are slipping, and which of them is worth promoting.

    Answers the compound question — "what's declining and what should I do about
    it" — which routing to a single analysis always got half wrong: item
    performance names the dishes but suggests nothing, and recommendations
    suggest actions without naming the decline that motivated them.

    Strictly read-only. It reports existing proposals and never creates,
    approves, or activates an offer.
    """

    from app.models.enums import OwnerActionType

    snapshot, comparison = _snapshot(db, scope, params)
    breakdown = _breakdown(snapshot, "item")
    decliners = (
        [row for row in breakdown.contributions if row.absolute_change < 0]
        if breakdown is not None
        else []
    )
    decliners.sort(key=lambda row: row.absolute_change)

    if not decliners:
        return SkillResult(
            skill="item_promotion_advice",
            answer=(
                f"No dish sales fell in {comparison.current.label()}, so there is "
                "nothing that needs promoting on those grounds."
            ),
            fact_pack=_pack(comparison, notes=_volume_note(snapshot)),
        )

    lead = (
        f"{len(decliners)} dish{'es' if len(decliners) != 1 else ''} sold less in "
        f"{comparison.current.label()}:"
    )
    declines: list[str] = []
    findings = []
    for row in decliners[:5]:
        declines.append(
            labelled(
                row.label,
                f"down {bold(money(row.absolute_change))} to {money(row.current)} "
                f"from {money(row.previous)}",
            )
        )
        findings.append(
            {
                "subject": row.label,
                "numbers": {
                    "current": round(row.current, 2),
                    "previous": round(row.previous, 2),
                    "change": round(row.absolute_change, 2),
                    "orders": row.current_orders,
                },
            }
        )

    # The biggest decline is the one worth acting on, but only if the money
    # clears the same materiality bar the insight rules use.
    worst = decliners[0]
    if is_material_change(worst.absolute_change, worst.percent_change):
        verdict = (
            f"{bold('Promote ' + worst.label + ' first.')} It accounts for the "
            f"largest fall, at {money(worst.absolute_change)}."
        )
    else:
        verdict = (
            f"{bold('Hold off on discounting.')} None of these fell by enough to "
            "justify it on its own — the amounts involved are small enough that a "
            "promotion would likely cost more than it recovers."
        )

    # Any existing proposal for these dishes, reported not created.
    proposals = [
        proposal
        for proposal in list_proposals(
            db, scope=scope, statuses=[OwnerActionStatus.PROPOSED], limit=10
        )
        if proposal.action_type
        in {OwnerActionType.PROMOTE_ITEM, OwnerActionType.PROMOTE_CATEGORY}
    ]
    pending = ""
    promotion_cards = offer_cards_from_proposals(db, proposals)
    if proposals:
        count = (
            f"There {'is' if len(proposals) == 1 else 'are'} already "
            f"{len(proposals)} pending recommendation"
            f"{'s' if len(proposals) != 1 else ''} covering this"
        )
        if promotion_cards:
            # Each proposal now has a card below carrying its name, discount and
            # rationale, so listing the titles here says it twice.
            pending = f"{count}. Nothing runs until you approve it."
        else:
            pending = blocks(
                f"{count}:",
                bullets(proposal.title for proposal in proposals[:3]),
                "Nothing runs until you approve it.",
            )
        findings.extend(
            {
                "recommendation": proposal.title,
                "numbers": {
                    "expected_impact": (
                        round(float(proposal.expected_impact_amount), 2)
                        if proposal.expected_impact_amount is not None
                        else None
                    )
                },
            }
            for proposal in proposals[:3]
        )
    else:
        sentences.append(
            "No promotion has been proposed for these yet. Recommendations are "
            "generated by the nightly analysis, and nothing is ever created "
            "without your approval."
        )

    return SkillResult(
        skill="item_promotion_advice",
        answer=blocks(lead, bullets(declines), verdict, pending),
        fact_pack=_pack(comparison, findings=findings, notes=_volume_note(snapshot)),
        data={"declining_items": findings},
        suggestions=promotion_cards,
    )


SkillHandler = Callable[[Session, InsightsScope, SkillParams], SkillResult]

def multi_part(db: Session, scope: InsightsScope, params: SkillParams) -> SkillResult:
    """Answer every part of a multi-part question, and say so when one cannot be.

    Each part runs as its own skill, under the caller's own scope, through the
    same validation as any single answer. Nothing new reads the database here —
    this composes existing skills rather than adding a path around them.

    The one rule that matters: a part that cannot be answered is *named*, not
    dropped. Silently omitting it would leave the owner reading a confident
    reply to three of their four questions with no way to tell which one went
    missing.
    """

    from app.services.insights.multipart import PARTS_BY_KEY

    comparison = _resolve_comparison(params)
    parts = [PARTS_BY_KEY[key] for key in params.parts if key in PARTS_BY_KEY]

    if len(parts) < 2:
        # Not actually multi-part. Falling through to the diagnosis beats
        # answering with an empty composition.
        return revenue_diagnosis(db, scope, params)

    sections: list[str] = []
    missing: list[str] = []
    headline: dict[str, Any] = {}
    findings: list[dict[str, Any]] = []
    notes: list[str] = []
    data: dict[str, Any] = {}

    for part in parts:
        part_params = replace(
            params,
            metric=part.metric,
            rank_by=part.rank_by or params.rank_by,
            direction=part.direction or params.direction,
            parts=(),
        )
        result = run_skill(db, scope=scope, skill=part.skill, params=part_params)

        if result.unsupported:
            # Named, with the reason the skill itself gave, so the owner learns
            # what is missing rather than that something is.
            missing.append(part.label)
            notes.append(f"{part.label}: not available. {_first_line(result.answer)}")
            continue

        sections.append(result.answer)
        headline.update(result.fact_pack.headline)
        for finding in result.fact_pack.insights:
            findings.append({"part": part.key, **finding})
        notes.extend(result.fact_pack.notes)
        data[part.key] = result.data

    if not sections:
        return SkillResult(
            skill="multi_part",
            answer=blocks(
                "I could not answer any part of that from your data.",
                *notes,
            ),
            fact_pack=_pack(comparison, notes=notes),
            unsupported=True,
        )

    if missing:
        sections.append(
            "I could not cover "
            + _join_labels(missing)
            + " from your data, so "
            + ("that part is" if len(missing) == 1 else "those parts are")
            + " missing from the above."
        )

    return SkillResult(
        skill="multi_part",
        answer=blocks(*sections),
        fact_pack=_pack(
            comparison,
            headline=headline,
            findings=findings,
            # Deduplicated because every part carries the same window caveats,
            # and four copies of "only 4 of 7 days had orders" reads as noise.
            notes=list(dict.fromkeys(notes)),
        ),
        data={"parts": data, "unavailable": missing},
    )


def _first_line(answer: str) -> str:
    for line in answer.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _join_labels(labels: list[str]) -> str:
    if len(labels) == 1:
        return labels[0].lower()
    return ", ".join(label.lower() for label in labels[:-1]) + f" or {labels[-1].lower()}"


SKILLS: dict[str, SkillHandler] = {
    "revenue_diagnosis": revenue_diagnosis,
    "metric_lookup": metric_lookup,
    "item_performance": item_performance,
    "time_patterns": time_patterns,
    "customer_retention": customer_retention,
    "offer_performance": offer_performance,
    "recommendations": recommendations,
    "briefing_recall": briefing_recall,
    "cancellation_reasons": cancellation_reasons,
    "order_operations": order_operations,
    "action_outcomes": action_outcomes,
    "item_promotion_advice": item_promotion_advice,
    "branch_comparison": branch_comparison,
    "tool_answer": tool_answer,
    "multi_part": multi_part,
    "small_talk": small_talk,
    "unsupported": unsupported,
}

SKILL_NAMES = tuple(SKILLS)


def run_skill(
    db: Session,
    *,
    scope: InsightsScope,
    skill: str,
    params: SkillParams,
) -> SkillResult:
    """Execute a named skill.

    An unknown name falls back to the diagnosis rather than raising: the router
    can be wrong, and a broadly useful answer beats an error.
    """

    handler = SKILLS.get(skill, revenue_diagnosis)
    return handler(db, scope, params)


__all__ = [
    "SKILLS",
    "SKILL_NAMES",
    "SkillParams",
    "SkillResult",
    "UNSUPPORTED_TOPICS",
    "run_skill",
]

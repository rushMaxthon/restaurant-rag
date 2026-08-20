"""The tool implementations themselves: read-only, scoped, and dependency-light.

Every function here takes the verified `InsightsScope` positionally and a
validated argument model. None of them accepts an identifier for a restaurant,
a branch, or a user, so no argument can move a call outside the scope it was
given. Where a caller needs to name a branch it does so by *name*, and the name
is resolved against the current scope — a branch belonging to someone else
simply does not resolve.

This module deliberately imports no write helper. It does not import the offer
service, `actions`, or `generation`, and it never calls `Session.add`,
`commit`, `flush`, or `delete`. Reads of stored insights and proposals are done
with local selects for exactly that reason: pulling them from their owning
modules would drag an execution path into a read-only layer.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import OwnerActionStatus, OwnerInsightStatus
from app.models.menu_item import MenuItem
from app.models.owner_action import OwnerActionProposal
from app.models.generated_combo import GeneratedCombo
from app.models.location_fulfillment_slot import LocationFulfillmentSlot
from app.models.owner_insight import OwnerBriefing, OwnerInsight
from app.models.personalized_offer import GeneratedOffer, PersonalizedOffer
from app.models.push_notification_campaign import PushNotificationCampaign
from app.models.restaurant_location import RestaurantLocation
from app.services.insights import metrics as metrics_layer
from app.services.insights import root_cause
from app.services.insights.analyst.schemas import (
    ALLOWED_WINDOW_DAYS,
    BranchArgs,
    BranchPairArgs,
    BreakdownArgs,
    LimitArgs,
    NoArgs,
    WindowArgs,
)
from app.services.insights.diagnostics import build_delta
from app.services.insights.offer_performance import fetch_offer_performance
from app.services.insights.periods import (
    AnalysisPeriod,
    PeriodComparison,
    resolve_period_comparison,
)
from app.services.insights.scope import InsightsScope
from app.services.insights.service import build_diagnostics_snapshot

settings = get_settings()


class ToolArgumentError(ValueError):
    """A tool argument that passed schema validation but is still not usable."""

    def __init__(self, error: str, detail: str) -> None:
        super().__init__(detail)
        self.error = error
        self.detail = detail


# --- shared helpers --------------------------------------------------------


def _jsonable(value: Any) -> Any:
    """Render a value in a form that survives JSON serialisation.

    Applied at the boundary so every tool returns the same primitive vocabulary,
    which is what lets a later phase hash, ledger, and replay results.
    """

    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if is_dataclass(value):
        return _jsonable(asdict(value))
    return str(value)


def _resolve_window(window_days: int) -> PeriodComparison:
    if window_days not in ALLOWED_WINDOW_DAYS:
        raise ToolArgumentError(
            "window_not_allowed",
            f"window_days must be one of {list(ALLOWED_WINDOW_DAYS)}",
        )
    return resolve_period_comparison(window_days=window_days)


def _period_payload(period: AnalysisPeriod) -> dict[str, Any]:
    return {
        "start_date": period.start_date.isoformat(),
        "end_date": period.end_date.isoformat(),
        "day_count": period.day_count,
        "label": period.label(),
    }


def _resolve_branch(
    db: Session, scope: InsightsScope, branch_name: str
) -> RestaurantLocation:
    """Find a branch by name within the current scope, or fail loudly.

    Two refusals rather than one silent widening: a name that belongs to another
    restaurant does not resolve at all, and a name that resolves to a different
    branch than the one the scope is pinned to is rejected instead of answered.
    """

    candidates = list(
        db.scalars(
            select(RestaurantLocation).where(
                RestaurantLocation.restaurant_id == scope.restaurant_id
            )
        )
    )
    wanted = branch_name.strip().casefold()
    matches = [row for row in candidates if row.branch_name.strip().casefold() == wanted]
    if not matches:
        # Partial match, so "Ellisbridge" finds "Bangkok Bowl Ellisbridge".
        matches = [row for row in candidates if wanted in row.branch_name.casefold()]

    if not matches:
        raise ToolArgumentError(
            "branch_not_found",
            "No branch of this restaurant matches that name. Known branches: "
            + ", ".join(sorted(row.branch_name for row in candidates)),
        )
    if len(matches) > 1:
        raise ToolArgumentError(
            "branch_ambiguous",
            "That name matches more than one branch: "
            + ", ".join(sorted(row.branch_name for row in matches)),
        )

    branch = matches[0]
    if (
        scope.restaurant_location_id is not None
        and branch.id != scope.restaurant_location_id
    ):
        raise ToolArgumentError(
            "outside_current_scope",
            "This analysis is pinned to a single branch, so another branch "
            "cannot be read from here.",
        )
    return branch


def _branch_scope(scope: InsightsScope, branch: RestaurantLocation) -> InsightsScope:
    """A scope narrowed to one branch of the same, already-verified restaurant.

    The restaurant id is carried over rather than re-derived, so narrowing can
    only ever shrink what a call may read.
    """

    return InsightsScope(
        restaurant_id=scope.restaurant_id,
        restaurant_location_id=branch.id,
    )


def _totals_payload(totals: metrics_layer.TotalsMetrics) -> dict[str, Any]:
    return {
        "orders": totals.orders,
        "gross_revenue": round(totals.gross_revenue, 2),
        "item_revenue": round(totals.item_revenue, 2),
        "items_sold": totals.items_sold,
        "customers": totals.customers,
        "discount_total": round(totals.discount_total, 2),
        "average_order_value": round(totals.average_order_value, 2),
    }


def _delta_payload(metric: str, current: float, previous: float) -> dict[str, Any]:
    return _jsonable(asdict(build_delta(metric, current, previous)))


# --- tools -----------------------------------------------------------------


def get_data_coverage(db: Session, scope: InsightsScope, args: WindowArgs) -> dict[str, Any]:
    comparison = _resolve_window(args.window_days)
    current = metrics_layer.fetch_coverage(db, scope, comparison.current)
    previous = metrics_layer.fetch_coverage(db, scope, comparison.previous)
    return {
        "period": _period_payload(comparison.current),
        "previous_period": _period_payload(comparison.previous),
        "current": _jsonable(asdict(current)),
        "previous": _jsonable(asdict(previous)),
        "counted_order_statuses": [
            status.value for status in metrics_layer.counted_order_statuses()
        ],
        "minimum_orders_for_reliable_percentages": settings.insights_min_orders_for_delta,
    }


def get_period_metrics(db: Session, scope: InsightsScope, args: WindowArgs) -> dict[str, Any]:
    comparison = _resolve_window(args.window_days)
    current = metrics_layer.fetch_totals(db, scope, comparison.current)
    previous = metrics_layer.fetch_totals(db, scope, comparison.previous)
    current_cancelled = metrics_layer.fetch_cancellations(db, scope, comparison.current)
    previous_cancelled = metrics_layer.fetch_cancellations(db, scope, comparison.previous)
    return {
        "period": _period_payload(comparison.current),
        "previous_period": _period_payload(comparison.previous),
        "current": _totals_payload(current),
        "previous": _totals_payload(previous),
        "cancelled": {
            "current": _jsonable(asdict(current_cancelled)),
            "previous": _jsonable(asdict(previous_cancelled)),
        },
    }


def get_metric_deltas(db: Session, scope: InsightsScope, args: WindowArgs) -> dict[str, Any]:
    comparison = _resolve_window(args.window_days)
    snapshot = build_diagnostics_snapshot(db, scope=scope, comparison=comparison)
    return {
        "period": _period_payload(comparison.current),
        "previous_period": _period_payload(comparison.previous),
        "headline": [row.model_dump(mode="json") for row in snapshot.headline],
        "data_quality": snapshot.data_quality.model_dump(mode="json"),
    }


def get_breakdown(db: Session, scope: InsightsScope, args: BreakdownArgs) -> dict[str, Any]:
    comparison = _resolve_window(args.window_days)
    snapshot = build_diagnostics_snapshot(db, scope=scope, comparison=comparison)
    for breakdown in snapshot.breakdowns:
        if breakdown.dimension == args.dimension:
            return {
                "period": _period_payload(comparison.current),
                "breakdown": breakdown.model_dump(mode="json"),
            }

    if args.dimension == "location" and scope.restaurant_location_id is not None:
        raise ToolArgumentError(
            "dimension_unavailable",
            "This analysis is pinned to one branch, so there is nothing to "
            "attribute across branches.",
        )
    raise ToolArgumentError(
        "dimension_unavailable",
        f"No {args.dimension} breakdown was produced for this window.",
    )


def get_daily_series(db: Session, scope: InsightsScope, args: WindowArgs) -> dict[str, Any]:
    comparison = _resolve_window(args.window_days)
    points = metrics_layer.fetch_daily_series(db, scope, comparison.current)
    return {
        "period": _period_payload(comparison.current),
        # Days with no trade are absent rather than zero-filled: a gap is a fact
        # about the business, and flattening it to 0.0 hides closures.
        "days_with_orders": [_jsonable(asdict(point)) for point in points],
        "days_in_window": comparison.current.day_count,
    }


def get_location_performance(
    db: Session, scope: InsightsScope, args: WindowArgs
) -> dict[str, Any]:
    comparison = _resolve_window(args.window_days)
    current = metrics_layer.fetch_location_metrics(db, scope, comparison.current)
    previous = metrics_layer.fetch_location_metrics(db, scope, comparison.previous)
    previous_by_id = {row.restaurant_location_id: row for row in previous}

    branches = []
    for row in sorted(current, key=lambda item: item.revenue, reverse=True):
        was = previous_by_id.pop(row.restaurant_location_id, None)
        branches.append(
            {
                "branch_name": row.branch_name,
                "current": {
                    "orders": row.orders,
                    "revenue": round(row.revenue, 2),
                    "customers": row.customers,
                },
                "previous": {
                    "orders": was.orders if was else 0,
                    "revenue": round(was.revenue, 2) if was else 0.0,
                    "customers": was.customers if was else 0,
                },
                "revenue_change": _delta_payload(
                    "gross_revenue", row.revenue, was.revenue if was else 0.0
                ),
            }
        )

    # Branches that traded before and not at all now never appear in the current
    # rows, and they are the single most important case this tool exists for.
    for row in sorted(previous_by_id.values(), key=lambda item: item.revenue, reverse=True):
        branches.append(
            {
                "branch_name": row.branch_name,
                "current": {"orders": 0, "revenue": 0.0, "customers": 0},
                "previous": {
                    "orders": row.orders,
                    "revenue": round(row.revenue, 2),
                    "customers": row.customers,
                },
                "revenue_change": _delta_payload("gross_revenue", 0.0, row.revenue),
                "stopped_trading": True,
            }
        )

    return {
        "period": _period_payload(comparison.current),
        "previous_period": _period_payload(comparison.previous),
        "branches": branches,
    }


def compare_locations(
    db: Session, scope: InsightsScope, args: BranchPairArgs
) -> dict[str, Any]:
    comparison = _resolve_window(args.window_days)
    branches = []
    for name in (args.branch_a, args.branch_b):
        branch = _resolve_branch(db, scope, name)
        branch_scope = _branch_scope(scope, branch)
        current = metrics_layer.fetch_totals(db, branch_scope, comparison.current)
        previous = metrics_layer.fetch_totals(db, branch_scope, comparison.previous)
        coverage = metrics_layer.fetch_coverage(db, branch_scope, comparison.current)
        branches.append(
            {
                "branch_name": branch.branch_name,
                "is_open": branch.is_open,
                "current": _totals_payload(current),
                "previous": _totals_payload(previous),
                "trading_days": coverage.trading_days,
                "revenue_change": _delta_payload(
                    "gross_revenue", current.gross_revenue, previous.gross_revenue
                ),
            }
        )

    return {
        "period": _period_payload(comparison.current),
        "previous_period": _period_payload(comparison.previous),
        "branches": branches,
    }


def get_branch_status(db: Session, scope: InsightsScope, args: NoArgs) -> dict[str, Any]:
    """Current configuration of every branch: open, accepting, and how.

    Present state rather than history. A branch switched off is invisible to
    every order-based metric — there are simply no rows — so without this a
    closure can only ever be inferred.
    """

    conditions = [RestaurantLocation.restaurant_id == scope.restaurant_id]
    if scope.restaurant_location_id is not None:
        conditions.append(RestaurantLocation.id == scope.restaurant_location_id)

    rows = db.scalars(
        select(RestaurantLocation).where(*conditions).order_by(RestaurantLocation.branch_name)
    ).all()

    return {
        "branches": [
            {
                "branch_name": row.branch_name,
                "city": row.city,
                "is_open": row.is_open,
                "is_active": row.is_active,
                "temporary_closed_reason": row.temporary_closed_reason,
                "opening_time": _jsonable(row.opening_time),
                "closing_time": _jsonable(row.closing_time),
                "delivery_enabled": row.delivery_enabled,
                "pickup_enabled": row.pickup_enabled,
                "minimum_order_amount": _jsonable(row.minimum_order_amount),
                "delivery_fee": _jsonable(row.delivery_fee),
                "preparation_time_minutes": row.preparation_time_minutes,
            }
            for row in rows
        ]
    }


def get_menu_health(db: Session, scope: InsightsScope, args: NoArgs) -> dict[str, Any]:
    """What is on the menu right now, per branch, and what is switched off.

    Gaps are reported explicitly — a category carried by one branch and not
    another is a fact no sales query can show, because a dish that is not on the
    menu produces no rows to be missing from.
    """

    conditions = [MenuItem.restaurant_id == scope.restaurant_id]
    if scope.restaurant_location_id is not None:
        conditions.append(MenuItem.restaurant_location_id == scope.restaurant_location_id)

    rows = db.execute(
        select(MenuItem, RestaurantLocation.branch_name)
        .join(RestaurantLocation, RestaurantLocation.id == MenuItem.restaurant_location_id)
        .where(*conditions)
        .order_by(RestaurantLocation.branch_name, MenuItem.name)
    ).all()

    items = [
        {
            "branch_name": branch_name,
            "name": item.name,
            "category": item.category,
            "price": _jsonable(item.price),
            "is_available": item.is_available,
            # Recorded on every menu row and never surfaced: an owner asking
            # "how much of my menu is vegetarian" had no way to find out.
            "is_veg": item.is_veg,
            "is_bestseller": item.is_bestseller,
            "is_new_launch": item.is_new_launch,
        }
        for item, branch_name in rows
    ]

    by_branch: dict[str, set[str]] = {}
    for entry in items:
        by_branch.setdefault(entry["branch_name"], set()).add(entry["category"])
    all_categories = {category for categories in by_branch.values() for category in categories}
    gaps = [
        {"branch_name": branch, "missing_categories": sorted(all_categories - categories)}
        for branch, categories in sorted(by_branch.items())
        if all_categories - categories
    ]

    return {
        "items": items,
        "unavailable_count": sum(1 for entry in items if not entry["is_available"]),
        "veg_count": sum(1 for entry in items if entry["is_veg"]),
        "bestseller_count": sum(1 for entry in items if entry["is_bestseller"]),
        "new_launch_count": sum(1 for entry in items if entry["is_new_launch"]),
        "category_gaps_by_branch": gaps,
    }


def get_stockouts(db: Session, scope: InsightsScope, args: WindowArgs) -> dict[str, Any]:
    comparison = _resolve_window(args.window_days)
    windows = root_cause.stockouts_in_period(db, scope, comparison.current)
    return {
        "period": _period_payload(comparison.current),
        "items": sorted(
            (_jsonable(asdict(window)) for window in windows.values()),
            key=lambda row: row["hours_unavailable"],
            reverse=True,
        ),
    }


def get_cancellations(db: Session, scope: InsightsScope, args: WindowArgs) -> dict[str, Any]:
    comparison = _resolve_window(args.window_days)
    current = metrics_layer.fetch_cancellations(db, scope, comparison.current)
    previous = metrics_layer.fetch_cancellations(db, scope, comparison.previous)
    breakdown = root_cause.cancellations_by_reason(db, scope, comparison.current)
    return {
        "period": _period_payload(comparison.current),
        "current": _jsonable(asdict(current)),
        "previous": _jsonable(asdict(previous)),
        "by_reason": [
            {
                "reason": row.reason.value,
                "orders": row.orders,
                "value": round(row.value, 2),
            }
            for row in breakdown
        ],
    }


def get_payment_failures(
    db: Session, scope: InsightsScope, args: WindowArgs
) -> dict[str, Any]:
    comparison = _resolve_window(args.window_days)
    current = metrics_layer.fetch_payment_failures(db, scope, comparison.current)
    previous = metrics_layer.fetch_payment_failures(db, scope, comparison.previous)
    counted = metrics_layer.fetch_totals(db, scope, comparison.current)
    lost_value = sum(row.value for row in current)
    return {
        "period": _period_payload(comparison.current),
        "current": [_jsonable(asdict(row)) for row in current],
        "previous": [_jsonable(asdict(row)) for row in previous],
        "lost_orders": sum(row.orders for row in current),
        "lost_value": round(lost_value, 2),
        # Stated as a share of counted revenue so the size of the leak is
        # readable without a second call.
        "lost_value_share_of_revenue_percent": (
            round(lost_value / counted.gross_revenue * 100, 1)
            if counted.gross_revenue
            else None
        ),
    }


def get_order_operations(
    db: Session, scope: InsightsScope, args: WindowArgs
) -> dict[str, Any]:
    comparison = _resolve_window(args.window_days)
    return {
        "period": _period_payload(comparison.current),
        "acceptance_latency": _jsonable(
            asdict(root_cause.acceptance_latency(db, scope, comparison.current))
        ),
        "preparation_time": _jsonable(
            asdict(root_cause.preparation_time(db, scope, comparison.current))
        ),
    }


def get_offer_performance(
    db: Session, scope: InsightsScope, args: WindowArgs
) -> dict[str, Any]:
    comparison = _resolve_window(args.window_days)
    rows = fetch_offer_performance(db, scope, comparison.current)
    return {
        "period": _period_payload(comparison.current),
        "offers": [_jsonable(asdict(row)) for row in rows],
        "caveat": (
            "Offer figures are observational. Orders placed with an offer are "
            "not evidence the offer caused them."
        ),
    }


def get_customer_cohorts(
    db: Session, scope: InsightsScope, args: WindowArgs
) -> dict[str, Any]:
    comparison = _resolve_window(args.window_days)
    current = metrics_layer.fetch_customer_cohorts(db, scope, comparison.current)
    previous = metrics_layer.fetch_customer_cohorts(db, scope, comparison.previous)
    return {
        "period": _period_payload(comparison.current),
        "current": [_jsonable(asdict(row)) for row in current],
        "previous": [_jsonable(asdict(row)) for row in previous],
    }


def get_anomalies(db: Session, scope: InsightsScope, args: WindowArgs) -> dict[str, Any]:
    comparison = _resolve_window(args.window_days)
    snapshot = build_diagnostics_snapshot(db, scope=scope, comparison=comparison)
    return {
        "period": _period_payload(comparison.current),
        "anomalies": snapshot.anomalies.model_dump(mode="json"),
    }


def get_recent_briefing(db: Session, scope: InsightsScope, args: NoArgs) -> dict[str, Any]:
    conditions = [OwnerBriefing.restaurant_id == scope.restaurant_id]
    if scope.restaurant_location_id is not None:
        conditions.append(
            OwnerBriefing.restaurant_location_id == scope.restaurant_location_id
        )
    briefing = db.scalars(
        select(OwnerBriefing)
        .where(*conditions)
        .order_by(OwnerBriefing.generated_at.desc())
        .limit(1)
    ).first()

    if briefing is None:
        return {"briefing": None}
    return {
        "briefing": {
            "headline": briefing.headline,
            "narrative": briefing.narrative,
            "period_start": briefing.period_start.isoformat(),
            "period_end": briefing.period_end.isoformat(),
            "narration_source": briefing.narration_source.value,
            "insight_count": briefing.insight_count,
        }
    }


def get_insight_history(
    db: Session, scope: InsightsScope, args: LimitArgs
) -> dict[str, Any]:
    """Findings already shown to this owner, so an analysis can avoid repeating them."""

    conditions = [
        OwnerInsight.restaurant_id == scope.restaurant_id,
        OwnerInsight.status != OwnerInsightStatus.DISMISSED,
    ]
    if scope.restaurant_location_id is not None:
        conditions.append(
            OwnerInsight.restaurant_location_id == scope.restaurant_location_id
        )
    rows = db.scalars(
        select(OwnerInsight)
        .where(*conditions)
        .order_by(OwnerInsight.generated_at.desc())
        .limit(args.limit)
    ).all()

    return {
        "insights": [
            {
                "insight_type": row.insight_type.value,
                "severity": row.severity.value,
                "status": row.status.value,
                "title": row.title,
                "body": row.body,
                "period_start": row.period_start.isoformat(),
                "period_end": row.period_end.isoformat(),
            }
            for row in rows
        ]
    }


def get_open_recommendations(
    db: Session, scope: InsightsScope, args: LimitArgs
) -> dict[str, Any]:
    conditions = [
        OwnerActionProposal.restaurant_id == scope.restaurant_id,
        OwnerActionProposal.status == OwnerActionStatus.PROPOSED,
    ]
    if scope.restaurant_location_id is not None:
        conditions.append(
            OwnerActionProposal.restaurant_location_id == scope.restaurant_location_id
        )
    rows = db.scalars(
        select(OwnerActionProposal)
        .where(*conditions)
        .order_by(OwnerActionProposal.priority.desc())
        .limit(args.limit)
    ).all()

    return {
        "recommendations": [
            {
                "action_type": row.action_type.value,
                "title": row.title,
                "rationale": row.rationale,
                "is_executable": row.is_executable,
                "expected_impact_amount": _jsonable(row.expected_impact_amount),
            }
            for row in rows
        ]
    }


def get_fulfillment_mix(db: Session, scope: InsightsScope, args: WindowArgs) -> dict[str, Any]:
    """Delivery against pickup, and ASAP against scheduled."""

    comparison = _resolve_window(args.window_days)
    rows = db.execute(
        metrics_layer.fulfillment_mix_query(scope, comparison.current)
    ).all()
    total = sum(int(row.orders or 0) for row in rows)
    return {
        "period": _period_payload(comparison.current),
        "total_orders": total,
        "splits": [
            {
                "fulfillment_type": str(row.fulfillment_type.value if hasattr(row.fulfillment_type, "value") else row.fulfillment_type),
                "schedule_type": str(row.schedule_type.value if hasattr(row.schedule_type, "value") else row.schedule_type),
                "orders": int(row.orders or 0),
                "revenue": round(_jsonable(row.revenue) or 0.0, 2),
                "share_percent": round(int(row.orders or 0) / total * 100, 1) if total else None,
            }
            for row in rows
        ],
    }


def get_payment_mix(db: Session, scope: InsightsScope, args: WindowArgs) -> dict[str, Any]:
    """How customers paid, by order count and revenue."""

    comparison = _resolve_window(args.window_days)
    rows = db.execute(metrics_layer.payment_mix_query(scope, comparison.current)).all()
    total = sum(int(row.orders or 0) for row in rows)
    return {
        "period": _period_payload(comparison.current),
        "total_orders": total,
        "methods": [
            {
                "payment_method": str(row.payment_method.value if hasattr(row.payment_method, "value") else row.payment_method),
                "orders": int(row.orders or 0),
                "revenue": round(_jsonable(row.revenue) or 0.0, 2),
                "share_percent": round(int(row.orders or 0) / total * 100, 1) if total else None,
            }
            for row in rows
        ],
    }


def get_order_economics(db: Session, scope: InsightsScope, args: WindowArgs) -> dict[str, Any]:
    """What sits between the subtotal and what the customer paid.

    Fees, tax and discounts are recorded on every order and have never been
    reported anywhere, so an owner asking what they pay away in delivery fees
    had no way to find out.
    """

    comparison = _resolve_window(args.window_days)
    row = db.execute(
        metrics_layer.order_economics_query(scope, comparison.current)
    ).one_or_none()
    if row is None or not int(row.orders or 0):
        return {"period": _period_payload(comparison.current), "orders": 0}

    return {
        "period": _period_payload(comparison.current),
        "orders": int(row.orders or 0),
        "subtotal": round(_jsonable(row.subtotal) or 0.0, 2),
        "delivery_fee": round(_jsonable(row.delivery_fee) or 0.0, 2),
        "tax_amount": round(_jsonable(row.tax_amount) or 0.0, 2),
        "discount_amount": round(_jsonable(row.discount_amount) or 0.0, 2),
        "total_amount": round(_jsonable(row.total_amount) or 0.0, 2),
        # Said plainly, because "total minus subtotal" invites being read as
        # margin: nothing here knows what the food cost.
        "note": (
            "These are the amounts recorded on the orders. Food and operating "
            "costs are not held anywhere, so none of this is profit."
        ),
    }


def get_payment_health(db: Session, scope: InsightsScope, args: WindowArgs) -> dict[str, Any]:
    """Provider-level payment outcomes, including declines and their reasons."""

    comparison = _resolve_window(args.window_days)
    rows = db.execute(
        metrics_layer.payment_health_query(scope, comparison.current)
    ).all()
    return {
        "period": _period_payload(comparison.current),
        "transactions": [
            {
                "provider": row.provider,
                "status": str(row.status.value if hasattr(row.status, "value") else row.status),
                "failure_code": row.failure_code,
                "count": int(row.transactions or 0),
                "amount": round(_jsonable(row.amount) or 0.0, 2),
            }
            for row in rows
        ],
    }


def get_offer_catalogue(db: Session, scope: InsightsScope, args: NoArgs) -> dict[str, Any]:
    """Every offer this restaurant has, with its state and expiry.

    Reads both tables. `personalized_offers` holds the templates an owner or the
    action system created; `generated_offers` holds the per-customer offers the
    AI generator produced. A restaurant can easily have none of the first and a
    dozen of the second, so reporting one alone would answer "you have no
    offers" to a restaurant that has twelve live.
    """

    template_conditions = [PersonalizedOffer.restaurant_id == scope.restaurant_id]
    generated_conditions = [GeneratedOffer.restaurant_id == scope.restaurant_id]
    if scope.restaurant_location_id is not None:
        template_conditions.append(
            PersonalizedOffer.restaurant_location_id == scope.restaurant_location_id
        )
        generated_conditions.append(
            GeneratedOffer.restaurant_location_id == scope.restaurant_location_id
        )

    # Liveness is decided by the expiry date, not by the state column. This
    # restaurant has ten offers marked ACTIVE of which nine expired in June:
    # answering "what is live" from the state alone would report ten live offers
    # when there are none.
    now = datetime.now(UTC)

    def live(state: Any, expires_at: Any) -> bool:
        if getattr(state, "value", state) != "ACTIVE":
            return False
        return expires_at is None or expires_at > now

    offers: list[dict[str, Any]] = []
    for row in db.scalars(select(PersonalizedOffer).where(*template_conditions)):
        offers.append(
            {
                "source": "template",
                "name": row.name,
                "state": row.state.value,
                "discount_type": row.discount_type.value,
                "discount_value": _jsonable(row.discount_value),
                "minimum_order_amount": _jsonable(row.minimum_order_amount),
                "starts_at": _jsonable(row.starts_at),
                "expires_at": _jsonable(row.expires_at),
                "is_live": live(row.state, row.expires_at),
            }
        )
    for row in db.scalars(select(GeneratedOffer).where(*generated_conditions)):
        offers.append(
            {
                "source": "generated",
                "name": row.generated_title,
                "state": row.state.value,
                "discount_type": row.discount_type.value,
                "discount_value": _jsonable(row.discount_value),
                "minimum_order_amount": _jsonable(row.minimum_order_amount),
                "starts_at": _jsonable(row.starts_at),
                "expires_at": _jsonable(row.expires_at),
                "is_live": live(row.state, row.expires_at),
                "views": row.view_count,
                "clicks": row.click_count,
                "conversions": row.conversion_count,
            }
        )

    by_state: dict[str, int] = {}
    for offer in offers:
        by_state[offer["state"]] = by_state.get(offer["state"], 0) + 1

    live_count = sum(1 for offer in offers if offer["is_live"])
    stale = sum(
        1
        for offer in offers
        if offer["state"] == "ACTIVE" and not offer["is_live"]
    )
    return {
        "offers": offers,
        "total": len(offers),
        "by_state": by_state,
        "live_now": live_count,
        # Marked active but past their expiry date. Worth naming: it is the
        # difference between what the records say and what a customer can use.
        "active_but_expired": stale,
    }


def get_combos(db: Session, scope: InsightsScope, args: NoArgs) -> dict[str, Any]:
    """Item pairings the combo builder found in real baskets."""

    conditions = [GeneratedCombo.restaurant_id == scope.restaurant_id]
    if scope.restaurant_location_id is not None:
        conditions.append(
            GeneratedCombo.restaurant_location_id == scope.restaurant_location_id
        )

    rows = db.scalars(
        select(GeneratedCombo)
        .where(*conditions)
        .order_by(GeneratedCombo.order_count.desc())
        .limit(10)
    ).all()

    return {
        "combos": [
            {
                "combo_name": row.combo_name,
                "orders_seen": row.order_count,
                "customers_seen": row.unique_user_count,
                "original_total_price": _jsonable(row.original_total_price),
                "suggested_combo_price": _jsonable(row.suggested_combo_price),
                "status": row.status,
                "is_active": row.is_active,
                "customer_visible": row.is_customer_visible,
            }
            for row in rows
        ]
    }


def get_schedule(db: Session, scope: InsightsScope, args: NoArgs) -> dict[str, Any]:
    """Opening hours and the fulfilment slots each branch takes orders in."""

    location_conditions = [RestaurantLocation.restaurant_id == scope.restaurant_id]
    if scope.restaurant_location_id is not None:
        location_conditions.append(RestaurantLocation.id == scope.restaurant_location_id)

    locations = db.scalars(
        select(RestaurantLocation)
        .where(*location_conditions)
        .order_by(RestaurantLocation.branch_name)
    ).all()
    ids = [row.id for row in locations]

    slots = (
        db.scalars(
            select(LocationFulfillmentSlot)
            .where(LocationFulfillmentSlot.location_id.in_(ids))
            .order_by(LocationFulfillmentSlot.start_time)
        ).all()
        if ids
        else []
    )

    by_location: dict[Any, list[dict[str, Any]]] = {}
    for slot in slots:
        by_location.setdefault(slot.location_id, []).append(
            {
                "day": slot.day_of_week.value
                if hasattr(slot.day_of_week, "value")
                else str(slot.day_of_week),
                "fulfillment_type": slot.fulfillment_type.value
                if hasattr(slot.fulfillment_type, "value")
                else str(slot.fulfillment_type),
                "start_time": _jsonable(slot.start_time),
                "end_time": _jsonable(slot.end_time),
                "is_active": slot.is_active,
            }
        )

    return {
        "branches": [
            {
                "branch_name": row.branch_name,
                "opening_time": _jsonable(row.opening_time),
                "closing_time": _jsonable(row.closing_time),
                "is_open": row.is_open,
                "future_order_enabled": row.future_order_enabled,
                "max_future_days": row.max_future_days,
                "slot_interval_minutes": row.slot_interval_minutes,
                "slots": by_location.get(row.id, []),
            }
            for row in locations
        ]
    }


def get_notification_campaigns(
    db: Session, scope: InsightsScope, args: LimitArgs
) -> dict[str, Any]:
    """Push campaigns this restaurant sent, and what happened to them.

    Sent, delivered, opened and failed counts are recorded per campaign and had
    no way to reach an owner. This is the one place the platform holds anything
    resembling marketing activity — so the domain gate that refuses "marketing"
    explanations stays correct for *spend*, while this answers what was actually
    sent.
    """

    rows = db.scalars(
        select(PushNotificationCampaign)
        .where(PushNotificationCampaign.restaurant_id == scope.restaurant_id)
        .order_by(PushNotificationCampaign.created_at.desc())
        .limit(args.limit)
    ).all()

    return {
        "campaigns": [
            {
                "title": row.title,
                "status": row.status.value,
                "audience": row.audience.value,
                "scheduled_for": _jsonable(row.scheduled_for),
                "dispatched_at": _jsonable(row.dispatched_at),
                "sent": row.sent_count,
                "delivered": row.delivered_count,
                "opened": row.opened_count,
                "failed": row.failed_count,
            }
            for row in rows
        ],
        "total": len(rows),
    }


def get_branch_metrics(db: Session, scope: InsightsScope, args: BranchArgs) -> dict[str, Any]:
    """One named branch in isolation, for following up on a whole-branch move."""

    comparison = _resolve_window(args.window_days)
    branch = _resolve_branch(db, scope, args.branch_name)
    branch_scope = _branch_scope(scope, branch)
    current = metrics_layer.fetch_totals(db, branch_scope, comparison.current)
    previous = metrics_layer.fetch_totals(db, branch_scope, comparison.previous)
    coverage = metrics_layer.fetch_coverage(db, branch_scope, comparison.current)
    return {
        "branch_name": branch.branch_name,
        "is_open": branch.is_open,
        "temporary_closed_reason": branch.temporary_closed_reason,
        "period": _period_payload(comparison.current),
        "previous_period": _period_payload(comparison.previous),
        "current": _totals_payload(current),
        "previous": _totals_payload(previous),
        "coverage": _jsonable(asdict(coverage)),
    }


__all__ = [
    "ToolArgumentError",
    "compare_locations",
    "get_anomalies",
    "get_branch_metrics",
    "get_branch_status",
    "get_breakdown",
    "get_cancellations",
    "get_customer_cohorts",
    "get_daily_series",
    "get_data_coverage",
    "get_insight_history",
    "get_location_performance",
    "get_menu_health",
    "get_metric_deltas",
    "get_offer_performance",
    "get_open_recommendations",
    "get_order_operations",
    "get_payment_failures",
    "get_period_metrics",
    "get_recent_briefing",
    "get_combos",
    "get_notification_campaigns",
    "get_fulfillment_mix",
    "get_offer_catalogue",
    "get_order_economics",
    "get_payment_health",
    "get_payment_mix",
    "get_schedule",
    "get_stockouts",
]

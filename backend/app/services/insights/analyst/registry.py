"""The fixed catalogue of analyst tools, and the only way to call one.

Every access goes through `call_tool`, which does three things in order: look
the name up in a closed registry, validate the arguments against that tool's
model, and invoke the handler with a scope the *caller* supplied. There is no
path that takes a tool name and an arbitrary callable, and no path that takes a
restaurant id from the arguments.

The forbidden-argument check runs at import time rather than in a test alone, so
a tool that would let its caller name a tenant cannot even be loaded.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.services.insights.analyst import tools as tool_impl
from app.services.insights.analyst.schemas import (
    BranchArgs,
    BranchPairArgs,
    BreakdownArgs,
    LimitArgs,
    NoArgs,
    ToolArgs,
    ToolResult,
    ToolSpec,
    WindowArgs,
)
from app.services.insights.scope import InsightsScope

logger = logging.getLogger(__name__)

# Argument names that would let a caller choose whose data it reads. Scope is
# injected by the caller, so none of these may ever appear in a tool's schema.
FORBIDDEN_ARGUMENT_NAMES = frozenset(
    {
        "restaurant_id",
        "restaurant_location_id",
        "location_id",
        "branch_id",
        "owner_id",
        "user_id",
        "customer_id",
        "tenant_id",
        "scope",
        "db",
        "session",
        "sql",
        "query",
    }
)


class ToolNotFound(KeyError):
    """A tool name that is not in the registry."""


def _spec(
    name: str,
    description: str,
    args_model: type[ToolArgs],
    handler: Any,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        args_model=args_model,
        handler=handler,
    )


TOOL_LIST: tuple[ToolSpec, ...] = (
    _spec(
        "get_data_coverage",
        "How much trade the window actually contains: trading days, orders, "
        "customers, and the threshold below which percentages are unreliable. "
        "Call this first; every other number means less without it.",
        WindowArgs,
        tool_impl.get_data_coverage,
    ),
    _spec(
        "get_period_metrics",
        "Totals for the window and the one before it: orders, revenue, items, "
        "customers, discounts, average order value, and cancellations.",
        WindowArgs,
        tool_impl.get_period_metrics,
    ),
    _spec(
        "get_metric_deltas",
        "Headline metrics with their changes, directions, and the data-quality "
        "caveats that apply to the comparison.",
        WindowArgs,
        tool_impl.get_metric_deltas,
    ),
    _spec(
        "get_breakdown",
        "Attribute the revenue change to one dimension: item, category, "
        "hour_of_day, daypart, weekday, customer_cohort, or location. "
        "Contributions are signed shares of the parent change.",
        BreakdownArgs,
        tool_impl.get_breakdown,
    ),
    _spec(
        "get_daily_series",
        "Orders and revenue per trading day. Days with no orders are omitted, "
        "so gaps are visible rather than flattened to zero.",
        WindowArgs,
        tool_impl.get_daily_series,
    ),
    _spec(
        "get_location_performance",
        "Every branch's orders, revenue, and customers this window against the "
        "last, including branches that traded before and have now stopped.",
        WindowArgs,
        tool_impl.get_location_performance,
    ),
    _spec(
        "get_branch_metrics",
        "One named branch on its own, with its open state and trading days.",
        BranchArgs,
        tool_impl.get_branch_metrics,
    ),
    _spec(
        "compare_locations",
        "Two named branches side by side over the same window.",
        BranchPairArgs,
        tool_impl.compare_locations,
    ),
    _spec(
        "get_branch_status",
        "Current configuration of every branch: open, active, closure reason, "
        "hours, fulfilment options, and minimum order. A closed branch produces "
        "no orders at all, so this is the only place a closure is visible.",
        NoArgs,
        tool_impl.get_branch_status,
    ),
    _spec(
        "get_menu_health",
        "The live menu per branch with prices and availability, plus categories "
        "one branch carries and another does not.",
        NoArgs,
        tool_impl.get_menu_health,
    ),
    _spec(
        "get_stockouts",
        "How long each dish spent switched off during the window, and how often.",
        WindowArgs,
        tool_impl.get_stockouts,
    ),
    _spec(
        "get_cancellations",
        "Cancelled orders and their value, grouped by recorded reason.",
        WindowArgs,
        tool_impl.get_cancellations,
    ),
    _spec(
        "get_payment_failures",
        "Orders lost at the payment step: never completed, abandoned, declined, "
        "or still pending. Recoverable money rather than lost demand.",
        WindowArgs,
        tool_impl.get_payment_failures,
    ),
    _spec(
        "get_order_operations",
        "Median minutes to accept an order and to prepare it, with sample sizes.",
        WindowArgs,
        tool_impl.get_order_operations,
    ),
    _spec(
        "get_offer_performance",
        "Revenue, discount cost, and engagement per offer. Observational only.",
        WindowArgs,
        tool_impl.get_offer_performance,
    ),
    _spec(
        "get_customer_cohorts",
        "New and returning customers, their orders, and their spend.",
        WindowArgs,
        tool_impl.get_customer_cohorts,
    ),
    _spec(
        "get_anomalies",
        "Days whose revenue departs from the recent baseline, with the baseline "
        "size and any reason detection was not run.",
        WindowArgs,
        tool_impl.get_anomalies,
    ),
    _spec(
        "get_fulfillment_mix",
        "Delivery against pickup, and ASAP against scheduled, by order count "
        "and revenue.",
        WindowArgs,
        tool_impl.get_fulfillment_mix,
    ),
    _spec(
        "get_payment_mix",
        "How customers paid: cash on delivery, card, or a wallet.",
        WindowArgs,
        tool_impl.get_payment_mix,
    ),
    _spec(
        "get_order_economics",
        "Delivery fees, tax and discounts recorded on orders, and how they sit "
        "between the subtotal and what the customer paid. Not profit: food and "
        "operating costs are not recorded anywhere.",
        WindowArgs,
        tool_impl.get_order_economics,
    ),
    _spec(
        "get_payment_health",
        "Payment provider outcomes: which succeeded, which were cancelled or "
        "declined, and the failure codes recorded against them.",
        WindowArgs,
        tool_impl.get_payment_health,
    ),
    _spec(
        "get_offer_catalogue",
        "Every offer this restaurant has, template and AI-generated alike, with "
        "its state and expiry date.",
        NoArgs,
        tool_impl.get_offer_catalogue,
    ),
    _spec(
        "get_combos",
        "Item pairings found in real baskets, with how often they were ordered "
        "together and the suggested bundle price.",
        NoArgs,
        tool_impl.get_combos,
    ),
    _spec(
        "get_schedule",
        "Opening hours, future-order settings, and the fulfilment slots each "
        "branch takes orders in.",
        NoArgs,
        tool_impl.get_schedule,
    ),
    _spec(
        "get_notification_campaigns",
        "Push campaigns this restaurant sent, with sent, delivered, opened and "
        "failed counts.",
        LimitArgs,
        tool_impl.get_notification_campaigns,
    ),
    _spec(
        "get_recent_briefing",
        "The most recent generated briefing for this restaurant.",
        NoArgs,
        tool_impl.get_recent_briefing,
    ),
    _spec(
        "get_insight_history",
        "Findings already shown to this owner and not dismissed.",
        LimitArgs,
        tool_impl.get_insight_history,
    ),
    _spec(
        "get_open_recommendations",
        "Recommendations currently awaiting the owner's decision.",
        LimitArgs,
        tool_impl.get_open_recommendations,
    ),
)


def _validate_registry(specs: tuple[ToolSpec, ...]) -> dict[str, ToolSpec]:
    registry: dict[str, ToolSpec] = {}
    for spec in specs:
        if spec.name in registry:
            raise RuntimeError(f"Duplicate analyst tool name: {spec.name}")
        offending = sorted(
            set(spec.args_model.model_fields) & FORBIDDEN_ARGUMENT_NAMES
        )
        if offending:
            # Loud at import: a tool that lets its caller name a tenant is not a
            # bug to be found in review later.
            raise RuntimeError(
                f"Analyst tool {spec.name} exposes scope-bearing arguments: {offending}"
            )
        registry[spec.name] = spec
    return registry


TOOLS: dict[str, ToolSpec] = _validate_registry(TOOL_LIST)


def tool_names() -> tuple[str, ...]:
    return tuple(TOOLS)


def describe_tools() -> list[dict[str, Any]]:
    """The catalogue, in the shape a later phase will render into a prompt."""

    return [
        {
            "name": spec.name,
            "description": spec.description,
            "arguments": spec.args_model.model_json_schema(),
        }
        for spec in TOOL_LIST
    ]


def call_tool(
    db: Session,
    scope: InsightsScope,
    name: str,
    args: dict[str, Any] | None = None,
) -> ToolResult:
    """Run one registered tool under a caller-supplied scope.

    Failures are returned, not raised: an unknown tool, a bad argument, or a
    branch that does not exist are all things a caller should be able to see and
    correct. An unexpected exception is logged and returned as a failed result
    so one broken tool cannot abort a whole analysis.
    """

    raw_args = dict(args or {})
    spec = TOOLS.get(name)
    if spec is None:
        return ToolResult(
            tool=name,
            args=raw_args,
            ok=False,
            error="unknown_tool",
            detail=f"No such tool. Available: {', '.join(tool_names())}",
        )

    try:
        parsed = spec.args_model.model_validate(raw_args)
    except ValidationError as error:
        return ToolResult(
            tool=name,
            args=raw_args,
            ok=False,
            error="invalid_arguments",
            detail=error.json(),
        )

    try:
        data = spec.handler(db, scope, parsed)
    except tool_impl.ToolArgumentError as error:
        return ToolResult(
            tool=name,
            args=parsed.model_dump(mode="json"),
            ok=False,
            error=error.error,
            detail=error.detail,
        )
    except Exception as error:  # noqa: BLE001 - one bad tool must not end the analysis
        logger.exception("Analyst tool failed name=%s restaurant_id=%s", name, scope.restaurant_id)
        return ToolResult(
            tool=name,
            args=parsed.model_dump(mode="json"),
            ok=False,
            error="tool_failed",
            detail=str(error),
        )

    return ToolResult(
        tool=name,
        args=parsed.model_dump(mode="json"),
        ok=True,
        data=data,
    )


__all__ = [
    "FORBIDDEN_ARGUMENT_NAMES",
    "TOOLS",
    "TOOL_LIST",
    "ToolNotFound",
    "call_tool",
    "describe_tools",
    "tool_names",
]

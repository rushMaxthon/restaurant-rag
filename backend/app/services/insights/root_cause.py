"""Why a finding happened, using the operational history from Phase 6A.

Everything before this could say *what* moved and *when*. This says *why*, but
only where the recorded events actually support an answer:

* a dish that declined while it was switched off is lost supply, not lost demand
* orders that fell while acceptance latency tripled point at the kitchen, not
  the menu
* cancellations now carry a recorded reason instead of being a mystery

The honest default is silence. Events only exist from the 0042 migration
onward, so older windows have no history, and plenty of declines have no
recorded cause at all. Returning `None` is the common case and the correct one —
inventing a cause would be worse than admitting there isn't one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from sqlalchemy import Float, cast, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import OrderCancellationReason, OrderStatus
from app.models.menu_availability_event import MenuItemAvailabilityEvent
from app.models.order import Order
from app.models.order_status_event import OrderStatusEvent
from app.services.insights.periods import AnalysisPeriod
from app.services.insights.rules import money, percent
from app.services.insights.scope import InsightsScope

settings = get_settings()
logger = logging.getLogger(__name__)

# A dish switched off for less than this is normal operational noise, not an
# explanation for a sales decline.
MIN_STOCKOUT_HOURS = 2.0

CANCELLATION_REASON_LABELS = {
    OrderCancellationReason.PAYMENT_NOT_COMPLETED: "the payment was never completed",
    OrderCancellationReason.PAYMENT_ABANDONED: "the customer left the payment screen",
    OrderCancellationReason.PAYMENT_FAILED: "the payment was declined",
    OrderCancellationReason.UNKNOWN: "no reason was recorded",
}


@dataclass(frozen=True, slots=True)
class StockoutWindow:
    dish_key: str
    item_name: str
    hours_unavailable: float
    switch_offs: int


@dataclass(frozen=True, slots=True)
class LatencyStats:
    median_minutes: float | None
    sample_size: int


@dataclass(frozen=True, slots=True)
class CancellationBreakdown:
    reason: OrderCancellationReason
    orders: int
    value: float


def _scope_conditions(scope: InsightsScope, model) -> list:
    """Scope any 6A event table.

    Both tables carry a denormalised `restaurant_id`, so no join back to orders
    or menu items is needed and no cross-tenant reach is possible.
    """

    conditions = [model.restaurant_id == scope.restaurant_id]
    if scope.restaurant_location_id is not None:
        conditions.append(model.restaurant_location_id == scope.restaurant_location_id)
    return conditions


def stockouts_in_period(
    db: Session,
    scope: InsightsScope,
    period: AnalysisPeriod,
) -> dict[str, StockoutWindow]:
    """How long each dish spent switched off during the window.

    Availability is a series of transitions, so unavailable time is measured by
    pairing each switch-off with the next switch-on. A dish still off at the end
    of the window is counted up to the window's end rather than dropped.
    """

    events = db.scalars(
        select(MenuItemAvailabilityEvent)
        .where(
            *_scope_conditions(scope, MenuItemAvailabilityEvent),
            MenuItemAvailabilityEvent.occurred_at < period.end_at,
        )
        .order_by(
            MenuItemAvailabilityEvent.menu_item_id,
            MenuItemAvailabilityEvent.occurred_at,
        )
    ).all()

    by_item: dict[str, list[MenuItemAvailabilityEvent]] = {}
    for event in events:
        by_item.setdefault(str(event.menu_item_id), []).append(event)

    results: dict[str, StockoutWindow] = {}
    for rows in by_item.values():
        off_since = None
        seconds_off = 0.0
        switch_offs = 0
        name = rows[-1].item_name_snapshot

        for event in rows:
            if not event.is_available and off_since is None:
                off_since = event.occurred_at
            elif event.is_available and off_since is not None:
                # Only the part of the outage inside the window counts.
                start = max(off_since, period.start_at)
                end = min(event.occurred_at, period.end_at)
                if end > start:
                    seconds_off += (end - start).total_seconds()
                    switch_offs += 1
                off_since = None

        if off_since is not None:
            start = max(off_since, period.start_at)
            if period.end_at > start:
                seconds_off += (period.end_at - start).total_seconds()
                switch_offs += 1

        hours = seconds_off / 3600.0
        if hours < MIN_STOCKOUT_HOURS:
            continue

        dish_key = name.strip().lower()
        existing = results.get(dish_key)
        if existing is not None:
            # Branch copies of one dish are collapsed, matching how the item
            # metrics group them.
            hours += existing.hours_unavailable
            switch_offs += existing.switch_offs
        results[dish_key] = StockoutWindow(
            dish_key=dish_key,
            item_name=name,
            hours_unavailable=round(hours, 1),
            switch_offs=switch_offs,
        )

    return results


def acceptance_latency(
    db: Session,
    scope: InsightsScope,
    period: AnalysisPeriod,
) -> LatencyStats:
    """Median minutes from an order being placed to being accepted."""

    placed = (
        select(
            OrderStatusEvent.order_id.label("order_id"),
            func.min(OrderStatusEvent.occurred_at).label("at"),
        )
        .where(
            *_scope_conditions(scope, OrderStatusEvent),
            OrderStatusEvent.to_status == OrderStatus.PLACED,
            OrderStatusEvent.occurred_at >= period.start_at,
            OrderStatusEvent.occurred_at < period.end_at,
        )
        .group_by(OrderStatusEvent.order_id)
        .subquery()
    )
    accepted = (
        select(
            OrderStatusEvent.order_id.label("order_id"),
            func.min(OrderStatusEvent.occurred_at).label("at"),
        )
        .where(
            *_scope_conditions(scope, OrderStatusEvent),
            OrderStatusEvent.to_status == OrderStatus.ACCEPTED,
        )
        .group_by(OrderStatusEvent.order_id)
        .subquery()
    )

    minutes = cast(
        func.extract("epoch", accepted.c.at - placed.c.at) / 60.0, Float
    )
    row = db.execute(
        select(
            func.percentile_cont(0.5).within_group(minutes).label("median"),
            func.count().label("sample"),
        )
        .select_from(placed)
        .join(accepted, accepted.c.order_id == placed.c.order_id)
        .where(accepted.c.at > placed.c.at)
    ).one_or_none()

    if row is None or row.sample == 0:
        return LatencyStats(median_minutes=None, sample_size=0)
    return LatencyStats(
        median_minutes=round(float(row.median), 1) if row.median is not None else None,
        sample_size=int(row.sample or 0),
    )


def preparation_time(
    db: Session,
    scope: InsightsScope,
    period: AnalysisPeriod,
) -> LatencyStats:
    """Median minutes from acceptance to leaving the kitchen."""

    accepted = (
        select(
            OrderStatusEvent.order_id.label("order_id"),
            func.min(OrderStatusEvent.occurred_at).label("at"),
        )
        .where(
            *_scope_conditions(scope, OrderStatusEvent),
            OrderStatusEvent.to_status == OrderStatus.ACCEPTED,
            OrderStatusEvent.occurred_at >= period.start_at,
            OrderStatusEvent.occurred_at < period.end_at,
        )
        .group_by(OrderStatusEvent.order_id)
        .subquery()
    )
    dispatched = (
        select(
            OrderStatusEvent.order_id.label("order_id"),
            func.min(OrderStatusEvent.occurred_at).label("at"),
        )
        .where(
            *_scope_conditions(scope, OrderStatusEvent),
            OrderStatusEvent.to_status == OrderStatus.OUT_FOR_DELIVERY,
        )
        .group_by(OrderStatusEvent.order_id)
        .subquery()
    )

    minutes = cast(
        func.extract("epoch", dispatched.c.at - accepted.c.at) / 60.0, Float
    )
    row = db.execute(
        select(
            func.percentile_cont(0.5).within_group(minutes).label("median"),
            func.count().label("sample"),
        )
        .select_from(accepted)
        .join(dispatched, dispatched.c.order_id == accepted.c.order_id)
        .where(dispatched.c.at > accepted.c.at)
    ).one_or_none()

    if row is None or row.sample == 0:
        return LatencyStats(median_minutes=None, sample_size=0)
    return LatencyStats(
        median_minutes=round(float(row.median), 1) if row.median is not None else None,
        sample_size=int(row.sample or 0),
    )


def cancellations_by_reason(
    db: Session,
    scope: InsightsScope,
    period: AnalysisPeriod,
) -> list[CancellationBreakdown]:
    """Cancelled orders grouped by their recorded reason, largest first."""

    conditions = [Order.restaurant_id == scope.restaurant_id]
    if scope.restaurant_location_id is not None:
        conditions.append(Order.restaurant_location_id == scope.restaurant_location_id)

    rows = db.execute(
        select(
            func.coalesce(
                Order.cancellation_reason, OrderCancellationReason.UNKNOWN
            ).label("reason"),
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.total_amount), 0).label("value"),
        )
        .where(
            *conditions,
            Order.status == OrderStatus.CANCELLED,
            Order.placed_at >= period.start_at,
            Order.placed_at < period.end_at,
        )
        .group_by("reason")
        .order_by(func.count(Order.id).desc())
    ).all()

    return [
        CancellationBreakdown(
            reason=OrderCancellationReason(row.reason),
            orders=int(row.orders or 0),
            value=float(row.value or 0.0),
        )
        for row in rows
    ]


# --- explanations ----------------------------------------------------------


def explain_item_decline(
    *,
    subject: str | None,
    stockouts: dict[str, StockoutWindow],
) -> str | None:
    """Was a dish's decline explained by it being switched off?"""

    if not subject:
        return None
    window = stockouts.get(subject.strip().lower())
    if window is None:
        return None

    spells = (
        f" across {window.switch_offs} separate spells" if window.switch_offs > 1 else ""
    )
    return (
        f"{window.item_name} was unavailable for about {window.hours_unavailable} "
        f"hours{spells} in this period, so some of the drop is lost supply rather "
        "than lost demand."
    )


def explain_cancellations(breakdown: list[CancellationBreakdown]) -> str | None:
    """What actually caused the cancellations."""

    if not breakdown:
        return None
    top = breakdown[0]
    label = CANCELLATION_REASON_LABELS.get(top.reason, "no reason was recorded")
    total = sum(row.orders for row in breakdown)
    share = (top.orders / total * 100.0) if total else 0.0

    if top.reason == OrderCancellationReason.UNKNOWN:
        return (
            f"{top.orders} of {total} cancellations predate reason tracking, so "
            "their cause is not recorded."
        )
    return (
        f"{top.orders} of {total} cancellations ({percent(share)}) happened because "
        f"{label}, worth {money(top.value)}."
    )


def explain_latency(
    current: LatencyStats,
    previous: LatencyStats,
) -> str | None:
    """Did orders start taking noticeably longer to be accepted?"""

    if current.median_minutes is None or previous.median_minutes is None:
        return None
    if current.sample_size < 5 or previous.sample_size < 5:
        # Too few orders for a median to mean anything.
        return None
    if previous.median_minutes <= 0:
        return None

    change = (current.median_minutes - previous.median_minutes) / previous.median_minutes
    if change < 0.25:
        return None

    return (
        f"Orders took a median of {current.median_minutes} minutes to be accepted, "
        f"up from {previous.median_minutes} minutes in the period before."
    )


__all__ = [
    "CANCELLATION_REASON_LABELS",
    "CancellationBreakdown",
    "LatencyStats",
    "MIN_STOCKOUT_HOURS",
    "StockoutWindow",
    "acceptance_latency",
    "cancellations_by_reason",
    "explain_cancellations",
    "explain_item_decline",
    "explain_latency",
    "preparation_time",
    "stockouts_in_period",
]

"""Deterministic SQL aggregates for the AI Restaurant Manager.

Every function here pushes aggregation into Postgres (`GROUP BY`) rather than
loading orders into Python, because a diagnosis needs two windows per question
and `get_reports_snapshot`'s load-everything-then-loop approach does not survive
that at scale.

Three conventions hold throughout:

* Scope is mandatory. Builders take an `InsightsScope` that has already passed
  the permission check, never a raw client-supplied id.
* Day, hour, and weekday buckets are computed in the restaurant's business
  timezone via `timezone(<tz>, placed_at)`, never in UTC.
* Only `insights_counted_order_statuses` count toward revenue. Cancellations are
  reported separately by `fetch_cancellation_metrics`.

Revenue bases differ by dimension, and callers must not mix them:

* `gross_revenue` (`orders.total_amount`) partitions cleanly by order, so
  hour/weekday/customer contributions sum back to the gross delta.
* `item_revenue` (`SUM(order_items.total_price)`) is the only basis on which
  item and category contributions add up, since fees, tax, and discounts sit on
  the order rather than on any line.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Select, Text, case, cast, distinct, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import OrderCancellationReason, OrderStatus
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.payment import PaymentTransaction
from app.models.restaurant_location import RestaurantLocation
from app.services.insights.periods import AnalysisPeriod
from app.services.insights.scope import InsightsScope

settings = get_settings()

# Cancellation reasons that mean the customer wanted the food but the payment
# step lost the order. Recoverable, unlike a kitchen or supply cancellation.
PAYMENT_FAILURE_REASONS: tuple[OrderCancellationReason, ...] = (
    OrderCancellationReason.PAYMENT_NOT_COMPLETED,
    OrderCancellationReason.PAYMENT_ABANDONED,
    OrderCancellationReason.PAYMENT_FAILED,
)

# Weekday names indexed by Postgres ISODOW (1 = Monday .. 7 = Sunday).
ISO_WEEKDAY_NAMES = {
    1: "Monday",
    2: "Tuesday",
    3: "Wednesday",
    4: "Thursday",
    5: "Friday",
    6: "Saturday",
    7: "Sunday",
}

# Local-hour ranges, half-open on the right.
DAYPARTS: tuple[tuple[str, int, int], ...] = (
    ("Late night", 0, 6),
    ("Breakfast", 6, 11),
    ("Lunch", 11, 15),
    ("Afternoon", 15, 18),
    ("Dinner", 18, 23),
    ("Late night", 23, 24),
)


@dataclass(frozen=True, slots=True)
class TotalsMetrics:
    orders: int = 0
    gross_revenue: float = 0.0
    item_revenue: float = 0.0
    items_sold: int = 0
    customers: int = 0
    discount_total: float = 0.0

    @property
    def average_order_value(self) -> float:
        return self.gross_revenue / self.orders if self.orders else 0.0


@dataclass(frozen=True, slots=True)
class CancellationMetrics:
    cancelled_orders: int = 0
    cancelled_value: float = 0.0


@dataclass(frozen=True, slots=True)
class DailyPoint:
    day: date
    orders: int
    revenue: float


@dataclass(frozen=True, slots=True)
class ItemMetrics:
    dish_key: str
    name: str
    category: str | None
    menu_item_id: uuid.UUID | None
    quantity: int
    revenue: float
    orders: int


@dataclass(frozen=True, slots=True)
class CategoryMetrics:
    category: str
    quantity: int
    revenue: float
    orders: int


@dataclass(frozen=True, slots=True)
class HourMetrics:
    hour: int
    orders: int
    revenue: float


@dataclass(frozen=True, slots=True)
class WeekdayMetrics:
    iso_weekday: int
    weekday_name: str
    orders: int
    revenue: float


@dataclass(frozen=True, slots=True)
class DaypartMetrics:
    daypart: str
    orders: int
    revenue: float


@dataclass(frozen=True, slots=True)
class CustomerCohortMetrics:
    cohort: str
    customers: int
    orders: int
    revenue: float


@dataclass(frozen=True, slots=True)
class LocationMetrics:
    """One branch's trade within a window.

    A whole-branch change is the largest movement this platform can produce —
    opening or closing one moves every dish, daypart, and cohort at once. Without
    this dimension a closure is attributed to whichever dish happened to sell
    there, which is exactly how a shut branch reads as "the salad is declining".
    """

    restaurant_location_id: uuid.UUID
    branch_name: str
    orders: int
    revenue: float
    customers: int


@dataclass(frozen=True, slots=True)
class CoverageMetrics:
    """How much trade a window actually contains.

    Separate from `has_sufficient_volume`, which answers a yes/no question about
    percentage reliability. This answers "how thin is it, and where", so a
    caller can say four trading days out of thirty rather than implying the
    window was busy throughout.
    """

    days_in_window: int = 0
    trading_days: int = 0
    orders: int = 0
    customers: int = 0
    first_order_day: date | None = None
    last_order_day: date | None = None

    @property
    def trading_day_share(self) -> float:
        if not self.days_in_window:
            return 0.0
        return self.trading_days / self.days_in_window


@dataclass(frozen=True, slots=True)
class PaymentFailureMetrics:
    """Orders lost at the payment step, by recorded reason.

    These never appear in revenue (cancelled) or in the counted statuses
    (payment-pending), so nothing else in this module can see them. They are
    recoverable money rather than lost demand, which makes them worth separating
    from ordinary cancellations.
    """

    reason: str
    orders: int
    value: float


def counted_order_statuses() -> tuple[OrderStatus, ...]:
    """Statuses that count as real business, per configuration.

    Unknown or non-revenue statuses in the setting are dropped rather than
    trusted, so a typo cannot silently pull cancelled orders into revenue.
    """

    allowed = {
        OrderStatus.ACCEPTED,
        OrderStatus.PREPARING,
        OrderStatus.OUT_FOR_DELIVERY,
        OrderStatus.DELIVERED,
        OrderStatus.PLACED,
    }
    configured: list[OrderStatus] = []
    for raw_value in settings.insights_counted_order_statuses_list:
        try:
            parsed = OrderStatus(raw_value)
        except ValueError:
            continue
        if parsed in allowed:
            configured.append(parsed)
    if configured:
        return tuple(dict.fromkeys(configured))
    return (
        OrderStatus.ACCEPTED,
        OrderStatus.PREPARING,
        OrderStatus.OUT_FOR_DELIVERY,
        OrderStatus.DELIVERED,
    )


def _safe_float(value: Decimal | float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)


def _scope_conditions(scope: InsightsScope) -> list:
    conditions = [Order.restaurant_id == scope.restaurant_id]
    if scope.restaurant_location_id is not None:
        conditions.append(Order.restaurant_location_id == scope.restaurant_location_id)
    return conditions


def _period_conditions(period: AnalysisPeriod) -> list:
    return [Order.placed_at >= period.start_at, Order.placed_at < period.end_at]


def _counted_conditions() -> list:
    return [Order.status.in_(counted_order_statuses())]


def _base_conditions(scope: InsightsScope, period: AnalysisPeriod) -> list:
    return [*_scope_conditions(scope), *_period_conditions(period), *_counted_conditions()]


def _local_placed_at(period: AnalysisPeriod):
    """`placed_at` rendered in the business timezone.

    The timezone name is bound as a parameter, so it cannot be injected.
    """

    return func.timezone(period.timezone_name, Order.placed_at)


# --- query builders --------------------------------------------------------
#
# Split out from the fetchers so tests can compile the SQL and assert that the
# tenancy predicate and timezone conversion are present without needing a
# database.


def totals_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    item_revenue = (
        select(func.coalesce(func.sum(OrderItem.total_price), 0))
        .join(Order, Order.id == OrderItem.order_id)
        .where(*_base_conditions(scope, period))
        .scalar_subquery()
    )
    items_sold = (
        select(func.coalesce(func.sum(OrderItem.quantity), 0))
        .join(Order, Order.id == OrderItem.order_id)
        .where(*_base_conditions(scope, period))
        .scalar_subquery()
    )
    return select(
        func.count(Order.id).label("orders"),
        func.coalesce(func.sum(Order.total_amount), 0).label("gross_revenue"),
        item_revenue.label("item_revenue"),
        items_sold.label("items_sold"),
        func.count(distinct(Order.customer_id)).label("customers"),
        func.coalesce(func.sum(Order.discount_amount), 0).label("discount_total"),
    ).where(*_base_conditions(scope, period))


def cancellations_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    return select(
        func.count(Order.id).label("cancelled_orders"),
        func.coalesce(func.sum(Order.total_amount), 0).label("cancelled_value"),
    ).where(
        *_scope_conditions(scope),
        *_period_conditions(period),
        Order.status == OrderStatus.CANCELLED,
    )


def daily_series_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    local_day = cast(_local_placed_at(period), Date).label("day")
    return (
        select(
            local_day,
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
        )
        .where(*_base_conditions(scope, period))
        .group_by(local_day)
        .order_by(local_day)
    )


def item_metrics_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    """Item revenue grouped by dish name, not by menu item id.

    Each branch stores its own row for the same dish, so grouping by id would
    split "Margherita Pizza" across locations and dilute every contribution
    ranking. The RAG retrieval layer collapses branch duplicates by dish key for
    the same reason.
    """

    dish_key = func.lower(func.trim(OrderItem.item_name_snapshot)).label("dish_key")
    return (
        select(
            dish_key,
            func.min(OrderItem.item_name_snapshot).label("name"),
            func.min(MenuItem.category).label("category"),
            # Postgres has no min()/max() aggregate for uuid, so a representative
            # id for the dish group is picked in text form and parsed back.
            func.min(cast(OrderItem.menu_item_id, Text)).label("menu_item_id"),
            func.coalesce(func.sum(OrderItem.quantity), 0).label("quantity"),
            func.coalesce(func.sum(OrderItem.total_price), 0).label("revenue"),
            func.count(distinct(Order.id)).label("orders"),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(MenuItem, MenuItem.id == OrderItem.menu_item_id, isouter=True)
        .where(*_base_conditions(scope, period))
        .group_by(dish_key)
    )


def category_metrics_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    category = func.coalesce(MenuItem.category, "Uncategorized").label("category")
    return (
        select(
            category,
            func.coalesce(func.sum(OrderItem.quantity), 0).label("quantity"),
            func.coalesce(func.sum(OrderItem.total_price), 0).label("revenue"),
            func.count(distinct(Order.id)).label("orders"),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(MenuItem, MenuItem.id == OrderItem.menu_item_id, isouter=True)
        .where(*_base_conditions(scope, period))
        .group_by(category)
    )


def hour_metrics_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    local_hour = func.extract("hour", _local_placed_at(period)).label("hour")
    return (
        select(
            local_hour,
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
        )
        .where(*_base_conditions(scope, period))
        .group_by(local_hour)
        .order_by(local_hour)
    )


def weekday_metrics_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    local_weekday = func.extract("isodow", _local_placed_at(period)).label("iso_weekday")
    return (
        select(
            local_weekday,
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
        )
        .where(*_base_conditions(scope, period))
        .group_by(local_weekday)
        .order_by(local_weekday)
    )


def customer_cohort_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    """Split in-period orders into first-time and returning customers.

    "New" means new to this scope: the customer's earliest counted order within
    the same restaurant (and branch, when one is selected) falls inside the
    window. Scoping the lookback the same way as the metric keeps the split
    internally consistent when a branch filter is applied.
    """

    first_order = (
        select(
            Order.customer_id.label("customer_id"),
            func.min(Order.placed_at).label("first_placed_at"),
        )
        .where(*_scope_conditions(scope), *_counted_conditions())
        .group_by(Order.customer_id)
        .subquery()
    )

    cohort = case(
        (first_order.c.first_placed_at >= period.start_at, "new"),
        else_="returning",
    ).label("cohort")

    return (
        select(
            cohort,
            func.count(distinct(Order.customer_id)).label("customers"),
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
        )
        .select_from(Order)
        .join(first_order, first_order.c.customer_id == Order.customer_id)
        .where(*_base_conditions(scope, period))
        .group_by(cohort)
    )


def location_metrics_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    """Counted trade grouped by branch.

    Joined to `restaurant_locations` for the branch name only; the tenancy
    predicate still sits on `orders`, so the join cannot widen the scope.
    """

    return (
        select(
            Order.restaurant_location_id.label("restaurant_location_id"),
            func.min(RestaurantLocation.branch_name).label("branch_name"),
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
            func.count(distinct(Order.customer_id)).label("customers"),
        )
        .select_from(Order)
        .join(RestaurantLocation, RestaurantLocation.id == Order.restaurant_location_id)
        .where(*_base_conditions(scope, period))
        .group_by(Order.restaurant_location_id)
    )


def coverage_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    local_day = cast(_local_placed_at(period), Date)
    return select(
        func.count(distinct(local_day)).label("trading_days"),
        func.count(Order.id).label("orders"),
        func.count(distinct(Order.customer_id)).label("customers"),
        func.min(local_day).label("first_order_day"),
        func.max(local_day).label("last_order_day"),
    ).where(*_base_conditions(scope, period))


def payment_failure_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    """Cancelled-at-payment and still-pending orders, grouped by reason.

    `PAYMENT_PENDING` rows carry no cancellation reason yet — the reaper has not
    reached them — so they are reported under their status instead of being
    folded into an unrelated reason bucket.
    """

    reason = case(
        (
            Order.status == OrderStatus.PAYMENT_PENDING,
            OrderStatus.PAYMENT_PENDING.value,
        ),
        else_=func.coalesce(
            cast(Order.cancellation_reason, Text),
            OrderCancellationReason.UNKNOWN.value,
        ),
    ).label("reason")

    return (
        select(
            reason,
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.total_amount), 0).label("value"),
        )
        .where(
            *_scope_conditions(scope),
            *_period_conditions(period),
            Order.status.in_((OrderStatus.CANCELLED, OrderStatus.PAYMENT_PENDING)),
            # A cancellation with no payment reason is an operational
            # cancellation, and belongs to `cancellations_by_reason` instead.
            (Order.status == OrderStatus.PAYMENT_PENDING)
            | Order.cancellation_reason.in_(PAYMENT_FAILURE_REASONS),
        )
        .group_by(reason)
        .order_by(func.count(Order.id).desc())
    )


def daily_series_range_query(
    scope: InsightsScope,
    start_period: AnalysisPeriod,
    end_period: AnalysisPeriod,
) -> Select:
    """A single daily series spanning two adjacent periods.

    Used by anomaly detection, which needs the baseline and the window under
    investigation as one continuous series.
    """

    local_day = cast(
        func.timezone(start_period.timezone_name, Order.placed_at), Date
    ).label("day")
    return (
        select(
            local_day,
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
        )
        .where(
            *_scope_conditions(scope),
            *_counted_conditions(),
            Order.placed_at >= start_period.start_at,
            Order.placed_at < end_period.end_at,
        )
        .group_by(local_day)
        .order_by(local_day)
    )


# --- fetchers --------------------------------------------------------------


def fetch_totals(db: Session, scope: InsightsScope, period: AnalysisPeriod) -> TotalsMetrics:
    row = db.execute(totals_query(scope, period)).one_or_none()
    if row is None:
        return TotalsMetrics()
    return TotalsMetrics(
        orders=int(row.orders or 0),
        gross_revenue=_safe_float(row.gross_revenue),
        item_revenue=_safe_float(row.item_revenue),
        items_sold=int(row.items_sold or 0),
        customers=int(row.customers or 0),
        discount_total=_safe_float(row.discount_total),
    )


def fetch_cancellations(
    db: Session, scope: InsightsScope, period: AnalysisPeriod
) -> CancellationMetrics:
    row = db.execute(cancellations_query(scope, period)).one_or_none()
    if row is None:
        return CancellationMetrics()
    return CancellationMetrics(
        cancelled_orders=int(row.cancelled_orders or 0),
        cancelled_value=_safe_float(row.cancelled_value),
    )


def fetch_daily_series(
    db: Session, scope: InsightsScope, period: AnalysisPeriod
) -> list[DailyPoint]:
    rows = db.execute(daily_series_query(scope, period)).all()
    return [
        DailyPoint(day=row.day, orders=int(row.orders or 0), revenue=_safe_float(row.revenue))
        for row in rows
    ]


def fetch_daily_series_range(
    db: Session,
    scope: InsightsScope,
    start_period: AnalysisPeriod,
    end_period: AnalysisPeriod,
) -> list[DailyPoint]:
    rows = db.execute(daily_series_range_query(scope, start_period, end_period)).all()
    return [
        DailyPoint(day=row.day, orders=int(row.orders or 0), revenue=_safe_float(row.revenue))
        for row in rows
    ]


def _coerce_uuid(value: object) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def fetch_item_metrics(
    db: Session, scope: InsightsScope, period: AnalysisPeriod
) -> list[ItemMetrics]:
    rows = db.execute(item_metrics_query(scope, period)).all()
    return [
        ItemMetrics(
            dish_key=row.dish_key,
            name=row.name,
            category=row.category,
            menu_item_id=_coerce_uuid(row.menu_item_id),
            quantity=int(row.quantity or 0),
            revenue=_safe_float(row.revenue),
            orders=int(row.orders or 0),
        )
        for row in rows
    ]


def fetch_category_metrics(
    db: Session, scope: InsightsScope, period: AnalysisPeriod
) -> list[CategoryMetrics]:
    rows = db.execute(category_metrics_query(scope, period)).all()
    return [
        CategoryMetrics(
            category=row.category,
            quantity=int(row.quantity or 0),
            revenue=_safe_float(row.revenue),
            orders=int(row.orders or 0),
        )
        for row in rows
    ]


def fetch_hour_metrics(
    db: Session, scope: InsightsScope, period: AnalysisPeriod
) -> list[HourMetrics]:
    rows = db.execute(hour_metrics_query(scope, period)).all()
    return [
        HourMetrics(
            hour=int(row.hour or 0),
            orders=int(row.orders or 0),
            revenue=_safe_float(row.revenue),
        )
        for row in rows
    ]


def fetch_weekday_metrics(
    db: Session, scope: InsightsScope, period: AnalysisPeriod
) -> list[WeekdayMetrics]:
    rows = db.execute(weekday_metrics_query(scope, period)).all()
    return [
        WeekdayMetrics(
            iso_weekday=int(row.iso_weekday or 0),
            weekday_name=ISO_WEEKDAY_NAMES.get(int(row.iso_weekday or 0), "Unknown"),
            orders=int(row.orders or 0),
            revenue=_safe_float(row.revenue),
        )
        for row in rows
    ]


def fetch_customer_cohorts(
    db: Session, scope: InsightsScope, period: AnalysisPeriod
) -> list[CustomerCohortMetrics]:
    rows = db.execute(customer_cohort_query(scope, period)).all()
    return [
        CustomerCohortMetrics(
            cohort=row.cohort,
            customers=int(row.customers or 0),
            orders=int(row.orders or 0),
            revenue=_safe_float(row.revenue),
        )
        for row in rows
    ]


def fetch_location_metrics(
    db: Session, scope: InsightsScope, period: AnalysisPeriod
) -> list[LocationMetrics]:
    rows = db.execute(location_metrics_query(scope, period)).all()
    return [
        LocationMetrics(
            restaurant_location_id=row.restaurant_location_id,
            branch_name=row.branch_name,
            orders=int(row.orders or 0),
            revenue=_safe_float(row.revenue),
            customers=int(row.customers or 0),
        )
        for row in rows
    ]


def fetch_coverage(
    db: Session, scope: InsightsScope, period: AnalysisPeriod
) -> CoverageMetrics:
    row = db.execute(coverage_query(scope, period)).one_or_none()
    if row is None:
        return CoverageMetrics(days_in_window=period.day_count)
    return CoverageMetrics(
        days_in_window=period.day_count,
        trading_days=int(row.trading_days or 0),
        orders=int(row.orders or 0),
        customers=int(row.customers or 0),
        first_order_day=row.first_order_day,
        last_order_day=row.last_order_day,
    )


def fetch_payment_failures(
    db: Session, scope: InsightsScope, period: AnalysisPeriod
) -> list[PaymentFailureMetrics]:
    rows = db.execute(payment_failure_query(scope, period)).all()
    return [
        PaymentFailureMetrics(
            reason=str(row.reason),
            orders=int(row.orders or 0),
            value=_safe_float(row.value),
        )
        for row in rows
    ]


def fulfillment_mix_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    """Counted trade split by how the order was collected and when it was for."""

    return (
        select(
            Order.fulfillment_type.label("fulfillment_type"),
            Order.schedule_type.label("schedule_type"),
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
        )
        .where(*_base_conditions(scope, period))
        .group_by(Order.fulfillment_type, Order.schedule_type)
        .order_by(func.count(Order.id).desc())
    )


def payment_mix_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    """Counted trade split by how the customer paid."""

    return (
        select(
            Order.payment_method.label("payment_method"),
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
        )
        .where(*_base_conditions(scope, period))
        .group_by(Order.payment_method)
        .order_by(func.count(Order.id).desc())
    )


def order_economics_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    """What sits between the subtotal and the total.

    Delivery fees, tax and discounts are recorded per order and have never been
    reported anywhere: an owner asking what they pay away in delivery fees had
    no way to find out.
    """

    return select(
        func.count(Order.id).label("orders"),
        func.coalesce(func.sum(Order.subtotal), 0).label("subtotal"),
        func.coalesce(func.sum(Order.delivery_fee), 0).label("delivery_fee"),
        func.coalesce(func.sum(Order.tax_amount), 0).label("tax_amount"),
        func.coalesce(func.sum(Order.discount_amount), 0).label("discount_amount"),
        func.coalesce(func.sum(Order.total_amount), 0).label("total_amount"),
    ).where(*_base_conditions(scope, period))


def payment_health_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    """Provider-level payment outcomes, scoped through the order they belong to.

    `payment_transactions` carries no restaurant id of its own, so the tenancy
    predicate rides on the joined order — the same rule every other query here
    follows, applied one join further out.
    """

    return (
        select(
            PaymentTransaction.provider.label("provider"),
            PaymentTransaction.status.label("status"),
            PaymentTransaction.failure_code.label("failure_code"),
            func.count(PaymentTransaction.id).label("transactions"),
            func.coalesce(func.sum(PaymentTransaction.amount), 0).label("amount"),
        )
        .select_from(PaymentTransaction)
        .join(Order, Order.id == PaymentTransaction.order_id)
        .where(*_scope_conditions(scope), *_period_conditions(period))
        .group_by(
            PaymentTransaction.provider,
            PaymentTransaction.status,
            PaymentTransaction.failure_code,
        )
        .order_by(func.count(PaymentTransaction.id).desc())
    )


def rollup_dayparts(hours: list[HourMetrics]) -> list[DaypartMetrics]:
    """Fold 24 hour buckets into named dayparts.

    Derived in Python from the hour rows the database already returned, since a
    second grouped query over the same partition would buy nothing.
    """

    totals: dict[str, dict[str, float]] = {}
    for name, start_hour, end_hour in DAYPARTS:
        bucket = totals.setdefault(name, {"orders": 0.0, "revenue": 0.0})
        for row in hours:
            if start_hour <= row.hour < end_hour:
                bucket["orders"] += row.orders
                bucket["revenue"] += row.revenue

    ordered_names: list[str] = []
    for name, _start, _end in DAYPARTS:
        if name not in ordered_names:
            ordered_names.append(name)

    return [
        DaypartMetrics(
            daypart=name,
            orders=int(totals[name]["orders"]),
            revenue=totals[name]["revenue"],
        )
        for name in ordered_names
    ]


__all__ = [
    "CancellationMetrics",
    "CategoryMetrics",
    "CoverageMetrics",
    "CustomerCohortMetrics",
    "DAYPARTS",
    "DailyPoint",
    "DaypartMetrics",
    "HourMetrics",
    "ISO_WEEKDAY_NAMES",
    "ItemMetrics",
    "LocationMetrics",
    "PAYMENT_FAILURE_REASONS",
    "PaymentFailureMetrics",
    "TotalsMetrics",
    "WeekdayMetrics",
    "cancellations_query",
    "category_metrics_query",
    "counted_order_statuses",
    "coverage_query",
    "customer_cohort_query",
    "daily_series_query",
    "daily_series_range_query",
    "fetch_cancellations",
    "fetch_category_metrics",
    "fetch_coverage",
    "fetch_customer_cohorts",
    "fetch_daily_series",
    "fetch_daily_series_range",
    "fetch_hour_metrics",
    "fetch_item_metrics",
    "fetch_location_metrics",
    "fetch_payment_failures",
    "fetch_totals",
    "fetch_weekday_metrics",
    "fulfillment_mix_query",
    "hour_metrics_query",
    "item_metrics_query",
    "location_metrics_query",
    "payment_failure_query",
    "payment_health_query",
    "payment_mix_query",
    "rollup_dayparts",
    "totals_query",
    "weekday_metrics_query",
]

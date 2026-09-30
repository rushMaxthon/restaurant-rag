"""Turning a segment key into actual customers.

Every segment here is recency/frequency/monetary shaped — "who should hear from
us". That is a different axis from `services/ai_offer_segments.py`, which
groups by item, category and cuisine affinity to answer "what should this offer
be about". The two are not interchangeable and neither subsumes the other; this
module borrows that one's SQL habits and none of its taxonomy.

Three rules hold for every segment:

1. **Tenancy.** Membership is computed from orders at one restaurant, and from
   users belonging to that restaurant's own app client. A customer is scoped by
   `app_client_id` (see `docs/per-app-identity.md`), so the same human in the
   Marketplace app is a different account that a single-restaurant campaign
   must never reach.
2. **Counted orders only.** `counted_order_statuses()` from the insights layer,
   so a cancelled order never makes someone a regular. Reusing it means
   segments and the owner's revenue reports can never disagree about what an
   order is.
3. **Consent is not membership.** A customer who opted out is still in their
   segment; they are removed at the reach step, where the owner is shown why.
   See `consent.audience_base_conditions`.

Thresholds live in `SEGMENT_RULES` as named constants rather than inline
numbers, because the owner-facing one-liner and the SQL have to stay honest
about each other — "ordered 3 or more times" in the UI and `>= 3` in the query
are the same fact written twice, and they drift the moment one is a literal.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, and_, distinct, func, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.app_client import AppClient
from app.models.enums import AppClientStatus, AppMode, MarketingSegmentKey
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.user import User
from app.services.insights.metrics import counted_order_statuses
from app.services.marketing.consent import audience_base_conditions

logger = logging.getLogger(__name__)
settings = get_settings()


# --- thresholds ------------------------------------------------------------
#
# Each of these appears twice: once here, once in the owner-facing `definition`
# string below. Keeping them named makes the pair inspectable.

LAPSED_MIN_ORDERS = 3
LAPSED_INACTIVE_DAYS = 30
FIRST_TIME_WINDOW_DAYS = 60
VIP_WINDOW_DAYS = 90
VIP_TOP_PERCENTILE = 0.90
WEEKEND_MIN_ORDERS = 2
WEEKEND_CONCENTRATION = 0.6
DISH_FAN_MIN_ORDERS = 2

# Postgres `extract(dow ...)`: 0 = Sunday .. 6 = Saturday.
WEEKEND_DOW = (0, 5, 6)


@dataclass(frozen=True, slots=True)
class SegmentDefinition:
    key: MarketingSegmentKey
    name: str
    #: One line in the owner's terms. Never rule syntax — the owner is choosing
    #: an audience, not writing a query.
    definition: str


SEGMENT_RULES: tuple[SegmentDefinition, ...] = (
    SegmentDefinition(
        key=MarketingSegmentKey.LAPSED_REGULARS,
        name="Lapsed regulars",
        definition=(
            f"Ordered {LAPSED_MIN_ORDERS} or more times, "
            f"but nothing in the last {LAPSED_INACTIVE_DAYS} days"
        ),
    ),
    SegmentDefinition(
        key=MarketingSegmentKey.FIRST_TIME_BUYERS,
        name="First-time buyers",
        definition=f"Exactly one order, placed in the last {FIRST_TIME_WINDOW_DAYS} days",
    ),
    SegmentDefinition(
        key=MarketingSegmentKey.VIPS,
        name="VIPs",
        definition=f"Top 10% by spend over the last {VIP_WINDOW_DAYS} days",
    ),
    SegmentDefinition(
        key=MarketingSegmentKey.BIG_SPENDERS,
        name="Big spenders",
        definition="Average order value above your restaurant median",
    ),
    SegmentDefinition(
        key=MarketingSegmentKey.WEEKEND_DINERS,
        name="Weekend-only diners",
        definition="Orders concentrated on Friday, Saturday and Sunday",
    ),
    SegmentDefinition(
        key=MarketingSegmentKey.DISH_FANS,
        name="Fans of your most re-ordered dish",
        definition="Repeat orders containing your most re-ordered dish",
    ),
    SegmentDefinition(
        key=MarketingSegmentKey.BRANCH_CUSTOMERS,
        name="All branch customers",
        definition="Anyone who has ordered from the selected branches",
    ),
    SegmentDefinition(
        key=MarketingSegmentKey.NEVER_ORDERED,
        name="Registered, never ordered",
        definition="Has an account but has never placed an order",
    ),
)

SEGMENTS_BY_KEY = {rule.key: rule for rule in SEGMENT_RULES}


class SegmentUnavailable(RuntimeError):
    """A segment cannot be computed for this restaurant at all.

    Distinct from a segment that computes to zero members. "This restaurant has
    no app of its own, so nobody can be reached" is a different thing to tell an
    owner than "nobody matches", and only one of them is fixable by widening
    the audience.
    """


# --- tenancy ---------------------------------------------------------------


def resolve_marketing_app_client_id(db: Session, restaurant_id: uuid.UUID) -> uuid.UUID:
    """The app client whose customers a campaign for this restaurant may reach.

    A restaurant's own single-restaurant app. Deliberately *not* the
    marketplace client: a marketplace customer's account belongs to the
    platform's app, and pushing a single restaurant's promotion through it is
    the platform's decision to make, not one tenant's.

    Raises rather than returning None so a restaurant without its own app
    surfaces as an explicit, explained block instead of an audience that is
    silently always zero.
    """

    app_client_id = db.scalar(
        select(AppClient.id).where(
            AppClient.restaurant_id == restaurant_id,
            AppClient.app_mode == AppMode.SINGLE_RESTAURANT,
            AppClient.status == AppClientStatus.ACTIVE,
        )
    )
    if app_client_id is None:
        raise SegmentUnavailable(
            "This restaurant does not have its own app yet, so there is nobody to send to."
        )
    return app_client_id


def _counted_order_conditions(
    restaurant_id: uuid.UUID,
    branch_ids: list[uuid.UUID] | None,
) -> list:
    conditions = [
        Order.restaurant_id == restaurant_id,
        Order.status.in_(counted_order_statuses()),
    ]
    if branch_ids:
        conditions.append(Order.restaurant_location_id.in_(branch_ids))
    return conditions


def _customer_totals(
    restaurant_id: uuid.UUID,
    branch_ids: list[uuid.UUID] | None,
    *,
    since: datetime | None = None,
):
    """Per-customer order aggregates, as a subquery.

    The building block for most segments: order count, spend, and the first and
    last time they ordered. Computed once per request rather than per segment.
    """

    conditions = _counted_order_conditions(restaurant_id, branch_ids)
    if since is not None:
        conditions.append(Order.placed_at >= since)

    return (
        select(
            Order.customer_id.label("customer_id"),
            func.count(Order.id).label("orders"),
            func.coalesce(func.sum(Order.total_amount), 0).label("revenue"),
            func.min(Order.placed_at).label("first_order_at"),
            func.max(Order.placed_at).label("last_order_at"),
        )
        .where(*conditions)
        .group_by(Order.customer_id)
        .subquery()
    )


def _base_user_conditions(app_client_id: uuid.UUID) -> list:
    return [User.app_client_id == app_client_id, *audience_base_conditions()]


# --- per-segment member queries --------------------------------------------


def _lapsed_regulars(app_client_id, restaurant_id, branch_ids, now) -> Select:
    totals = _customer_totals(restaurant_id, branch_ids)
    cutoff = now - timedelta(days=LAPSED_INACTIVE_DAYS)
    return (
        select(User.id)
        .join(totals, totals.c.customer_id == User.id)
        .where(
            *_base_user_conditions(app_client_id),
            totals.c.orders >= LAPSED_MIN_ORDERS,
            totals.c.last_order_at < cutoff,
        )
    )


def _first_time_buyers(app_client_id, restaurant_id, branch_ids, now) -> Select:
    totals = _customer_totals(restaurant_id, branch_ids)
    cutoff = now - timedelta(days=FIRST_TIME_WINDOW_DAYS)
    return (
        select(User.id)
        .join(totals, totals.c.customer_id == User.id)
        .where(
            *_base_user_conditions(app_client_id),
            totals.c.orders == 1,
            totals.c.last_order_at >= cutoff,
        )
    )


def _vips(app_client_id, restaurant_id, branch_ids, now) -> Select:
    """Top 10% by spend in the window.

    The threshold is a percentile of this restaurant's own customers, not an
    absolute amount — a VIP at a dhaba and a VIP at a fine-dining room do not
    spend the same, and an owner should not have to know their own distribution
    to use the segment.

    `>=` against the 90th percentile means a restaurant whose customers all
    spend identically returns everyone rather than nobody. That is the right
    failure: the minimum-audience check downstream is what stops a campaign
    that would go to the whole base, and it says so in those words.
    """

    since = now - timedelta(days=VIP_WINDOW_DAYS)
    totals = _customer_totals(restaurant_id, branch_ids, since=since)

    threshold = select(
        func.percentile_cont(VIP_TOP_PERCENTILE)
        .within_group(totals.c.revenue)
        .label("threshold")
    ).scalar_subquery()

    return (
        select(User.id)
        .join(totals, totals.c.customer_id == User.id)
        .where(
            *_base_user_conditions(app_client_id),
            totals.c.revenue >= threshold,
        )
    )


def _big_spenders(app_client_id, restaurant_id, branch_ids, now) -> Select:
    """Average order value above the restaurant's median average order value.

    The median is taken over per-customer averages, not over raw orders. Those
    are different numbers: a handful of customers ordering very often would
    otherwise drag the median toward their habits rather than toward the
    typical customer, which is who the owner means by "median".
    """

    conditions = _counted_order_conditions(restaurant_id, branch_ids)
    averages = (
        select(
            Order.customer_id.label("customer_id"),
            func.avg(Order.total_amount).label("aov"),
        )
        .where(*conditions)
        .group_by(Order.customer_id)
        .subquery()
    )

    median = select(
        func.percentile_cont(0.5).within_group(averages.c.aov).label("median")
    ).scalar_subquery()

    return (
        select(User.id)
        .join(averages, averages.c.customer_id == User.id)
        .where(
            *_base_user_conditions(app_client_id),
            averages.c.aov > median,
        )
    )


def _weekend_diners(app_client_id, restaurant_id, branch_ids, now) -> Select:
    """Customers whose ordering is concentrated on Friday, Saturday and Sunday.

    "Concentrated" is a share of their own orders, not a raw weekend count.
    Someone who orders every single day would otherwise qualify as a weekend
    diner purely by volume, and a Tuesday-lunch promotion aimed at this segment
    would be aimed at the wrong people.

    The weekday is taken in the business timezone. A 00:30 Saturday order is a
    Friday night order to the restaurant that cooked it, and in UTC it may not
    even be the same day.
    """

    conditions = _counted_order_conditions(restaurant_id, branch_ids)
    local_dow = func.extract(
        "dow", func.timezone(settings.business_timezone, Order.placed_at)
    )
    weekend_orders = func.count(Order.id).filter(local_dow.in_(WEEKEND_DOW))
    total_orders = func.count(Order.id)

    concentration = (
        select(
            Order.customer_id.label("customer_id"),
            total_orders.label("orders"),
            weekend_orders.label("weekend_orders"),
        )
        .where(*conditions)
        .group_by(Order.customer_id)
        .having(total_orders >= WEEKEND_MIN_ORDERS)
        .having(weekend_orders >= WEEKEND_CONCENTRATION * total_orders)
        .subquery()
    )

    return (
        select(User.id)
        .join(concentration, concentration.c.customer_id == User.id)
        .where(*_base_user_conditions(app_client_id))
    )


def most_reordered_item_id(
    db: Session,
    restaurant_id: uuid.UUID,
    branch_ids: list[uuid.UUID] | None,
) -> uuid.UUID | None:
    """The dish the most different people order more than once.

    Ranked by distinct repeat customers rather than by units sold, so a single
    bulk order cannot crown a dish nobody re-orders. Returns None when no dish
    has any repeat customer at all, which is the honest answer for a young
    restaurant.
    """

    conditions = _counted_order_conditions(restaurant_id, branch_ids)
    per_customer_item = (
        select(
            OrderItem.menu_item_id.label("menu_item_id"),
            Order.customer_id.label("customer_id"),
            func.count(distinct(Order.id)).label("orders"),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .where(*conditions)
        .group_by(OrderItem.menu_item_id, Order.customer_id)
        .subquery()
    )

    return db.scalar(
        select(per_customer_item.c.menu_item_id)
        .where(per_customer_item.c.orders >= DISH_FAN_MIN_ORDERS)
        .group_by(per_customer_item.c.menu_item_id)
        .order_by(func.count(distinct(per_customer_item.c.customer_id)).desc())
        .limit(1)
    )


def _dish_fans(app_client_id, restaurant_id, branch_ids, now, *, menu_item_id) -> Select:
    conditions = _counted_order_conditions(restaurant_id, branch_ids)
    fans = (
        select(
            Order.customer_id.label("customer_id"),
            func.count(distinct(Order.id)).label("orders"),
        )
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .where(*conditions, OrderItem.menu_item_id == menu_item_id)
        .group_by(Order.customer_id)
        .having(func.count(distinct(Order.id)) >= DISH_FAN_MIN_ORDERS)
        .subquery()
    )

    return (
        select(User.id)
        .join(fans, fans.c.customer_id == User.id)
        .where(*_base_user_conditions(app_client_id))
    )


def _branch_customers(app_client_id, restaurant_id, branch_ids, now) -> Select:
    totals = _customer_totals(restaurant_id, branch_ids)
    return (
        select(User.id)
        .join(totals, totals.c.customer_id == User.id)
        .where(*_base_user_conditions(app_client_id))
    )


def _never_ordered(app_client_id, restaurant_id, branch_ids, now) -> Select:
    """Registered in this app, never placed a counted order at this restaurant.

    Branch filtering is deliberately ignored here — and this is the one segment
    where it must be. "Never ordered from the Koramangala branch" would include
    every loyal Indiranagar regular, which is the opposite of who the owner
    means. Never ordered means never ordered.
    """

    ordered = (
        select(Order.customer_id)
        .where(*_counted_order_conditions(restaurant_id, None))
        .distinct()
        .scalar_subquery()
    )
    return select(User.id).where(
        *_base_user_conditions(app_client_id),
        User.id.not_in(ordered),
    )


# --- public API ------------------------------------------------------------


def segment_member_query(
    db: Session,
    *,
    key: MarketingSegmentKey,
    restaurant_id: uuid.UUID,
    app_client_id: uuid.UUID,
    branch_ids: list[uuid.UUID] | None = None,
    now: datetime | None = None,
) -> Select:
    """A `SELECT users.id` for one segment.

    Returned as a query rather than a list so callers can count it, intersect
    it with device tokens, or materialise it — counting an audience of four
    hundred should not mean loading four hundred user rows.
    """

    now = now or datetime.now(UTC)
    branch_ids = branch_ids or None

    if key == MarketingSegmentKey.DISH_FANS:
        menu_item_id = most_reordered_item_id(db, restaurant_id, branch_ids)
        if menu_item_id is None:
            # No dish has a repeat customer yet. An empty query is the truthful
            # answer and reads the same downstream as any other empty segment.
            return select(User.id).where(User.id.is_(None))
        return _dish_fans(
            app_client_id, restaurant_id, branch_ids, now, menu_item_id=menu_item_id
        )

    builders = {
        MarketingSegmentKey.LAPSED_REGULARS: _lapsed_regulars,
        MarketingSegmentKey.FIRST_TIME_BUYERS: _first_time_buyers,
        MarketingSegmentKey.VIPS: _vips,
        MarketingSegmentKey.BIG_SPENDERS: _big_spenders,
        MarketingSegmentKey.WEEKEND_DINERS: _weekend_diners,
        MarketingSegmentKey.BRANCH_CUSTOMERS: _branch_customers,
        MarketingSegmentKey.NEVER_ORDERED: _never_ordered,
    }
    builder = builders[key]
    return builder(app_client_id, restaurant_id, branch_ids, now)


def count_segment_members(
    db: Session,
    *,
    key: MarketingSegmentKey,
    restaurant_id: uuid.UUID,
    app_client_id: uuid.UUID,
    branch_ids: list[uuid.UUID] | None = None,
    now: datetime | None = None,
) -> int:
    query = segment_member_query(
        db,
        key=key,
        restaurant_id=restaurant_id,
        app_client_id=app_client_id,
        branch_ids=branch_ids,
        now=now,
    )
    return db.scalar(select(func.count()).select_from(query.subquery())) or 0


def list_segment_member_ids(
    db: Session,
    *,
    key: MarketingSegmentKey,
    restaurant_id: uuid.UUID,
    app_client_id: uuid.UUID,
    branch_ids: list[uuid.UUID] | None = None,
    now: datetime | None = None,
) -> list[uuid.UUID]:
    query = segment_member_query(
        db,
        key=key,
        restaurant_id=restaurant_id,
        app_client_id=app_client_id,
        branch_ids=branch_ids,
        now=now,
    )
    return list(db.scalars(query).all())

"""Did a promotion pay for itself?

The revenue side comes from orders attributed to an offer, the cost side from
the discount those orders gave away. Both are read from real foreign keys rather
than inferred, so a figure here can always be traced to specific orders.

Two deliberate choices:

* Only counted order statuses contribute revenue, matching the rest of the
  insights layer. A cancelled order that used an offer cost nothing and earned
  nothing.
* "Net revenue" is revenue after the discount, not profit. Food and delivery
  costs are not in the data, so calling it profit would overstate what is known.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.enums import PersonalizedOfferEventType
from app.models.order import Order
from app.models.personalized_offer import (
    GeneratedOffer,
    PersonalizedOffer,
    PersonalizedOfferEvent,
)
from app.services.insights.metrics import counted_order_statuses
from app.services.insights.periods import AnalysisPeriod
from app.services.insights.scope import InsightsScope


@dataclass(frozen=True, slots=True)
class OfferPerformance:
    offer_id: uuid.UUID
    offer_name: str
    # "TEMPLATE" for a manually created offer, "GENERATED" for an AI-generated one.
    offer_kind: str
    orders: int
    customers: int
    gross_revenue: float
    discount_cost: float
    views: int
    clicks: int
    conversions: int

    @property
    def net_revenue(self) -> float:
        """Revenue after the discount. Not profit — food cost is not recorded."""

        return self.gross_revenue - self.discount_cost

    @property
    def average_order_value(self) -> float:
        return self.gross_revenue / self.orders if self.orders else 0.0

    @property
    def return_per_unit_discount(self) -> float | None:
        """Gross revenue earned per unit of discount given away.

        None when nothing was discounted, since dividing by zero would invent a
        ratio for an offer that never actually cost anything.
        """

        if self.discount_cost <= 0:
            return None
        return self.gross_revenue / self.discount_cost

    @property
    def click_through_rate(self) -> float | None:
        if self.views <= 0:
            return None
        return (self.clicks / self.views) * 100.0

    @property
    def conversion_rate(self) -> float | None:
        if self.views <= 0:
            return None
        return (self.conversions / self.views) * 100.0


def _safe_float(value: Decimal | float | int | None) -> float:
    return float(value) if value is not None else 0.0


def _order_conditions(scope: InsightsScope, period: AnalysisPeriod) -> list:
    conditions = [
        Order.restaurant_id == scope.restaurant_id,
        Order.placed_at >= period.start_at,
        Order.placed_at < period.end_at,
        Order.status.in_(counted_order_statuses()),
    ]
    if scope.restaurant_location_id is not None:
        conditions.append(Order.restaurant_location_id == scope.restaurant_location_id)
    return conditions


def template_offer_revenue_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    return (
        select(
            Order.applied_offer_id.label("offer_id"),
            func.count(Order.id).label("orders"),
            func.count(func.distinct(Order.customer_id)).label("customers"),
            func.coalesce(func.sum(Order.total_amount), 0).label("gross_revenue"),
            func.coalesce(func.sum(Order.discount_amount), 0).label("discount_cost"),
        )
        .where(*_order_conditions(scope, period), Order.applied_offer_id.is_not(None))
        .group_by(Order.applied_offer_id)
    )


def generated_offer_revenue_query(scope: InsightsScope, period: AnalysisPeriod) -> Select:
    return (
        select(
            Order.applied_generated_offer_id.label("offer_id"),
            func.count(Order.id).label("orders"),
            func.count(func.distinct(Order.customer_id)).label("customers"),
            func.coalesce(func.sum(Order.total_amount), 0).label("gross_revenue"),
            func.coalesce(func.sum(Order.discount_amount), 0).label("discount_cost"),
        )
        .where(
            *_order_conditions(scope, period),
            Order.applied_generated_offer_id.is_not(None),
        )
        .group_by(Order.applied_generated_offer_id)
    )


def _engagement_counts(
    db: Session,
    *,
    scope: InsightsScope,
    period: AnalysisPeriod,
    generated: bool,
) -> dict[uuid.UUID, dict[str, int]]:
    """View, click, and conversion counts per offer, scoped to this restaurant.

    Events carry no restaurant column, so they are joined through the offer they
    belong to — otherwise another tenant's engagement would be counted here.
    """

    if generated:
        key_column = PersonalizedOfferEvent.generated_offer_id
        scope_join = GeneratedOffer
        join_condition = GeneratedOffer.id == PersonalizedOfferEvent.generated_offer_id
        restaurant_column = GeneratedOffer.restaurant_id
    else:
        key_column = PersonalizedOfferEvent.offer_id
        scope_join = PersonalizedOffer
        join_condition = PersonalizedOffer.id == PersonalizedOfferEvent.offer_id
        restaurant_column = PersonalizedOffer.restaurant_id

    query = (
        select(
            key_column.label("offer_id"),
            PersonalizedOfferEvent.event_type,
            func.count(PersonalizedOfferEvent.id).label("total"),
        )
        .join(scope_join, join_condition)
        .where(
            key_column.is_not(None),
            restaurant_column == scope.restaurant_id,
            PersonalizedOfferEvent.created_at >= period.start_at,
            PersonalizedOfferEvent.created_at < period.end_at,
        )
        .group_by(key_column, PersonalizedOfferEvent.event_type)
    )

    counts: dict[uuid.UUID, dict[str, int]] = {}
    for row in db.execute(query).all():
        bucket = counts.setdefault(
            row.offer_id, {"views": 0, "clicks": 0, "conversions": 0}
        )
        if row.event_type == PersonalizedOfferEventType.VIEWED:
            bucket["views"] += int(row.total or 0)
        elif row.event_type == PersonalizedOfferEventType.CLICKED:
            bucket["clicks"] += int(row.total or 0)
        elif row.event_type == PersonalizedOfferEventType.CONVERTED:
            bucket["conversions"] += int(row.total or 0)
    return counts


def fetch_offer_performance(
    db: Session,
    scope: InsightsScope,
    period: AnalysisPeriod,
) -> list[OfferPerformance]:
    """Revenue, cost, and engagement per offer for one restaurant and window."""

    results: list[OfferPerformance] = []

    for generated in (False, True):
        query = (
            generated_offer_revenue_query(scope, period)
            if generated
            else template_offer_revenue_query(scope, period)
        )
        rows = db.execute(query).all()
        if not rows:
            continue

        offer_ids = [row.offer_id for row in rows]
        model = GeneratedOffer if generated else PersonalizedOffer
        name_column = (
            GeneratedOffer.generated_title if generated else PersonalizedOffer.name
        )
        names = {
            offer_id: name
            for offer_id, name in db.execute(
                select(model.id, name_column).where(
                    model.id.in_(offer_ids),
                    # Belt and braces: the orders were already restaurant-scoped,
                    # but an offer that does not belong here must never be named.
                    model.restaurant_id == scope.restaurant_id,
                )
            ).all()
        }
        engagement = _engagement_counts(
            db, scope=scope, period=period, generated=generated
        )

        for row in rows:
            if row.offer_id not in names:
                continue
            counts = engagement.get(row.offer_id, {})
            results.append(
                OfferPerformance(
                    offer_id=row.offer_id,
                    offer_name=names[row.offer_id],
                    offer_kind="GENERATED" if generated else "TEMPLATE",
                    orders=int(row.orders or 0),
                    customers=int(row.customers or 0),
                    gross_revenue=_safe_float(row.gross_revenue),
                    discount_cost=_safe_float(row.discount_cost),
                    views=counts.get("views", 0),
                    clicks=counts.get("clicks", 0),
                    conversions=counts.get("conversions", 0),
                )
            )

    results.sort(key=lambda row: (-row.gross_revenue, row.offer_name.lower()))
    return results


__all__ = [
    "OfferPerformance",
    "fetch_offer_performance",
    "generated_offer_revenue_query",
    "template_offer_revenue_query",
]

"""Segment-based AI offer generation for one restaurant.

The per-customer generator in `ai_offer_generation` writes one offer per
eligible customer. For a restaurant with three hundred regulars that is three
hundred near-identical offers, none of which tell the owner anything about their
business.

This module inverts it:

    restaurant data -> analysis -> segments -> a few offers -> eligible customers

The important design decision is that it does *not* invent an eligibility
system. `personalized_offers._score_generated_offer_for_user` already decides,
per customer, whether a shared offer applies - matching the offer's item,
category or cuisine against that customer's own repeat-order patterns, their
favourite restaurant, how recently they ordered, and their average spend. An
offer with `generated_for_user_id = None` is already evaluated that way for
every customer by the read path.

So a segment offer here is simply a normal `GeneratedOffer` with no owning
customer, shaped so the existing scorer selects the right people: a "Pizza"
segment becomes a FAVORITE_ITEM offer carrying `applicable_category="Pizza"`,
and the scorer then shows it to exactly the customers whose repeat patterns
contain Pizza. Eligibility is therefore data-driven by construction, and what
the owner is told is eligible is what customers actually get.

Copy generation and the discount guardrails are reused unchanged, so a segment
offer cannot exceed a cap the per-customer path enforces.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import (
    OrderStatus,
    PaymentStatus,
    PersonalizedOfferAudience,
    PersonalizedOfferDiscountType,
    PersonalizedOfferGenerationReason,
    PersonalizedOfferSource,
    PersonalizedOfferState,
    PersonalizedOfferType,
    UserRole,
)
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.personalized_offer import GeneratedOffer
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User

settings = get_settings()
logger = logging.getLogger(__name__)

# How many offers one run may produce. The brief is "a small set": past about
# five the owner is back to reading a list instead of a decision, and the
# segments below start describing the same customers twice.
MAX_SEGMENT_OFFERS = 5

# A pattern held by one or two customers is an anecdote, not a segment.
MIN_ITEM_CUSTOMERS = 2
MIN_GROUP_CUSTOMERS = 3
MIN_WINBACK_CUSTOMERS = 3

# Deliberately "paid, and not cancelled" rather than a narrower list of
# fulfilled statuses. Eligibility is decided later by the existing scorer, which
# reads a customer's repeat patterns from *every* paid order; counting a
# different set here would let this module build a segment the scorer then
# refuses to match anyone to.
EXCLUDED_STATUSES = (OrderStatus.CANCELLED, OrderStatus.PAYMENT_PENDING)


@dataclass(slots=True)
class ItemSignal:
    menu_item_id: uuid.UUID
    name: str
    category: str | None
    cuisine: str | None
    customers: int
    quantity: int
    revenue: Decimal


@dataclass(slots=True)
class GroupSignal:
    """A category or cuisine, with how many distinct customers order it."""

    name: str
    customers: int
    quantity: int


@dataclass(slots=True)
class RestaurantAnalysis:
    restaurant: Restaurant
    location: RestaurantLocation | None
    total_customers: int = 0
    active_customers: int = 0
    inactive_customers: int = 0
    average_order_value: Decimal = Decimal("0.00")
    top_items: list[ItemSignal] = field(default_factory=list)
    top_categories: list[GroupSignal] = field(default_factory=list)
    top_cuisines: list[GroupSignal] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        """The evidence, small enough to store on every offer it produced."""

        return {
            "total_customers": self.total_customers,
            "active_customers": self.active_customers,
            "inactive_customers": self.inactive_customers,
            "average_order_value": f"{self.average_order_value:.2f}",
            "top_items": [
                {"name": row.name, "customers": row.customers, "quantity": row.quantity}
                for row in self.top_items[:5]
            ],
            "top_categories": [
                {"name": row.name, "customers": row.customers} for row in self.top_categories[:5]
            ],
            "top_cuisines": [
                {"name": row.name, "customers": row.customers} for row in self.top_cuisines[:5]
            ],
        }


@dataclass(slots=True)
class OfferSegment:
    """One offer this run intends to create, and the data that justifies it."""

    key: str
    label: str
    offer_type: PersonalizedOfferType
    audience_type: PersonalizedOfferAudience
    generation_reason: PersonalizedOfferGenerationReason
    reach: int
    applicable_item_id: uuid.UUID | None = None
    applicable_item_name: str | None = None
    applicable_category: str | None = None
    applicable_cuisine: str | None = None
    discount_type: PersonalizedOfferDiscountType = PersonalizedOfferDiscountType.PERCENTAGE
    discount_value: Decimal = Decimal("10.00")
    minimum_order_amount: Decimal = Decimal("199.00")
    fallback_title: str = "An offer for you"
    fallback_subtitle: str = "Built from this restaurant's ordering patterns."
    fallback_cta: str = "Order Now"
    evidence: dict[str, Any] = field(default_factory=dict)


def _paid_orders(restaurant_id: uuid.UUID) -> Select:
    return select(Order.id).where(
        Order.restaurant_id == restaurant_id,
        Order.payment_status == PaymentStatus.PAID,
        Order.status.not_in(EXCLUDED_STATUSES),
    )


def analyze_restaurant(db: Session, restaurant_id: uuid.UUID) -> RestaurantAnalysis | None:
    """Aggregate one restaurant's demand into the facts segments are built from.

    Everything here is one pass of grouped SQL over that restaurant's paid,
    fulfilled orders. Nothing is per-customer, which is the point: the segments
    come from what the restaurant sells, not from iterating its customer list.
    """

    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        return None

    location = db.scalar(
        select(RestaurantLocation)
        .where(
            RestaurantLocation.restaurant_id == restaurant_id,
            RestaurantLocation.is_active.is_(True),
        )
        .order_by(RestaurantLocation.created_at.asc())
    )

    analysis = RestaurantAnalysis(restaurant=restaurant, location=location)

    order_scope = [
        Order.restaurant_id == restaurant_id,
        Order.payment_status == PaymentStatus.PAID,
        Order.status.not_in(EXCLUDED_STATUSES),
    ]

    analysis.average_order_value = Decimal(
        str(db.scalar(select(func.avg(Order.total_amount)).where(*order_scope)) or "0")
    ).quantize(Decimal("0.01"))

    # Customer counts, split by how recently they last ordered here.
    cutoff = datetime.now(UTC) - timedelta(days=settings.personalized_offer_inactivity_days)
    last_seen = (
        select(
            Order.customer_id.label("customer_id"),
            func.max(Order.placed_at).label("last_order_at"),
        )
        .where(*order_scope)
        .group_by(Order.customer_id)
        .subquery()
    )
    rows = db.execute(
        select(last_seen.c.customer_id, last_seen.c.last_order_at)
        .join(User, User.id == last_seen.c.customer_id)
        .where(User.role == UserRole.CUSTOMER, User.is_active.is_(True))
    ).all()
    analysis.total_customers = len(rows)
    for _, last_order_at in rows:
        if last_order_at is not None and last_order_at >= cutoff:
            analysis.active_customers += 1
        else:
            analysis.inactive_customers += 1

    # Item demand: distinct customers first, because an offer's worth is how
    # many people it reaches, not how many units one enthusiast bought.
    item_rows = db.execute(
        select(
            MenuItem.id,
            MenuItem.name,
            MenuItem.category,
            func.coalesce(MenuItem.cuisine_type, Restaurant.cuisine_type).label("cuisine"),
            func.count(func.distinct(Order.customer_id)).label("customers"),
            func.sum(OrderItem.quantity).label("quantity"),
            func.sum(OrderItem.total_price).label("revenue"),
        )
        .join(OrderItem, OrderItem.menu_item_id == MenuItem.id)
        .join(Order, OrderItem.order_id == Order.id)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .where(*order_scope, MenuItem.is_available.is_(True))
        .group_by(MenuItem.id, MenuItem.name, MenuItem.category, "cuisine")
        .order_by(
            func.count(func.distinct(Order.customer_id)).desc(),
            func.sum(OrderItem.quantity).desc(),
            MenuItem.name.asc(),
        )
        .limit(20)
    ).all()
    analysis.top_items = [
        ItemSignal(
            menu_item_id=row.id,
            name=str(row.name),
            category=str(row.category) if row.category else None,
            cuisine=str(row.cuisine) if row.cuisine else None,
            customers=int(row.customers or 0),
            quantity=int(row.quantity or 0),
            revenue=Decimal(str(row.revenue or "0")),
        )
        for row in item_rows
    ]

    def group_signals(column: Any) -> list[GroupSignal]:
        grouped = db.execute(
            select(
                column.label("name"),
                func.count(func.distinct(Order.customer_id)).label("customers"),
                func.sum(OrderItem.quantity).label("quantity"),
            )
            .join(OrderItem, OrderItem.menu_item_id == MenuItem.id)
            .join(Order, OrderItem.order_id == Order.id)
            .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
            .where(*order_scope, MenuItem.is_available.is_(True), column.is_not(None))
            .group_by(column)
            .order_by(func.count(func.distinct(Order.customer_id)).desc())
            .limit(10)
        ).all()
        return [
            GroupSignal(
                name=str(row.name),
                customers=int(row.customers or 0),
                quantity=int(row.quantity or 0),
            )
            for row in grouped
            if str(row.name).strip()
        ]

    analysis.top_categories = group_signals(MenuItem.category)
    analysis.top_cuisines = group_signals(
        func.coalesce(MenuItem.cuisine_type, Restaurant.cuisine_type)
    )
    return analysis


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _min_order(value: Decimal) -> Decimal:
    """Never below the configured floor, whatever the data suggests."""

    return _money(max(value, settings.ai_min_order_threshold))


def derive_segments(
    analysis: RestaurantAnalysis,
    *,
    limit: int = MAX_SEGMENT_OFFERS,
) -> list[OfferSegment]:
    """Turn the analysis into a small set of distinct, defensible offers.

    Duplication is avoided structurally rather than by comparing finished copy:
    a category segment is dropped when it is the top item's own category, and a
    cuisine segment only survives when the restaurant actually sells more than
    one cuisine. Otherwise all three would describe the same customers in
    slightly different words.
    """

    segments: list[OfferSegment] = []
    used_categories: set[str] = set()
    aov = analysis.average_order_value

    # 1. The dish the most different people order.
    top_item = next(
        (row for row in analysis.top_items if row.customers >= MIN_ITEM_CUSTOMERS), None
    )
    if top_item is not None:
        if top_item.category:
            used_categories.add(top_item.category.strip().lower())
        segments.append(
            OfferSegment(
                key=f"top_item:{top_item.menu_item_id}",
                label=f"Regulars of {top_item.name}",
                offer_type=PersonalizedOfferType.FAVORITE_ITEM,
                audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
                generation_reason=PersonalizedOfferGenerationReason.REPEATED_ORDER,
                reach=top_item.customers,
                applicable_item_id=top_item.menu_item_id,
                applicable_item_name=top_item.name,
                # Item only. The eligibility scorer treats item, category and
                # cuisine as alternatives, so also setting the category and
                # cuisine here would widen a dish offer into "anyone who has
                # ever ordered this restaurant's cuisine" - which, for a
                # single-cuisine restaurant, is every customer it has.
                applicable_category=None,
                applicable_cuisine=None,
                discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
                discount_value=Decimal("10.00"),
                minimum_order_amount=_min_order(aov * Decimal("0.8")),
                fallback_title=f"Save on {top_item.name}",
                fallback_subtitle=f"Your regular pick at {analysis.restaurant.name}.",
                fallback_cta="Order Again",
                evidence={
                    "item": top_item.name,
                    "customers_ordering": top_item.customers,
                    "units_sold": top_item.quantity,
                },
            )
        )

    # 2. The strongest category that is not already covered by the dish above.
    for group in analysis.top_categories:
        if group.customers < MIN_GROUP_CUSTOMERS:
            break
        if group.name.strip().lower() in used_categories:
            continue
        used_categories.add(group.name.strip().lower())
        segments.append(
            OfferSegment(
                key=f"category:{group.name.strip().lower()}",
                label=f"{group.name} buyers",
                offer_type=PersonalizedOfferType.FAVORITE_ITEM,
                audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
                generation_reason=PersonalizedOfferGenerationReason.REPEATED_ORDER,
                reach=group.customers,
                applicable_category=group.name,
                discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
                discount_value=Decimal("12.00"),
                minimum_order_amount=_min_order(aov * Decimal("0.9")),
                fallback_title=f"{group.name} deal for you",
                fallback_subtitle=f"Because {group.name.lower()} is what you keep coming back for.",
                fallback_cta="Browse Menu",
                evidence={"category": group.name, "customers_ordering": group.customers},
            )
        )
        break

    # 3. Cuisine, but only where there is more than one to distinguish between.
    if len(analysis.top_cuisines) > 1:
        cuisine = analysis.top_cuisines[0]
        if cuisine.customers >= MIN_GROUP_CUSTOMERS:
            segments.append(
                OfferSegment(
                    key=f"cuisine:{cuisine.name.strip().lower()}",
                    label=f"{cuisine.name} lovers",
                    offer_type=PersonalizedOfferType.CUISINE_AFFINITY,
                    audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
                    generation_reason=PersonalizedOfferGenerationReason.CUISINE_AFFINITY,
                    reach=cuisine.customers,
                    applicable_cuisine=cuisine.name,
                    discount_type=PersonalizedOfferDiscountType.FLAT,
                    discount_value=_money(min(Decimal("40.00"), settings.ai_max_flat_discount)),
                    minimum_order_amount=_min_order(aov * Decimal("1.1")),
                    fallback_title=f"More {cuisine.name} for you",
                    fallback_subtitle=f"Picked for {cuisine.name.lower()} regulars.",
                    fallback_cta="Explore Now",
                    evidence={"cuisine": cuisine.name, "customers_ordering": cuisine.customers},
                )
            )

    # 4. Customers who have stopped coming.
    if analysis.inactive_customers >= MIN_WINBACK_CUSTOMERS:
        segments.append(
            OfferSegment(
                key="winback",
                label="Customers who have stopped ordering",
                offer_type=PersonalizedOfferType.FAVORITE_RESTAURANT,
                audience_type=PersonalizedOfferAudience.INACTIVE_USERS,
                generation_reason=PersonalizedOfferGenerationReason.INACTIVE_USER,
                reach=analysis.inactive_customers,
                discount_type=PersonalizedOfferDiscountType.FREE_DELIVERY,
                discount_value=Decimal("0.00"),
                minimum_order_amount=_min_order(aov * Decimal("0.9")),
                fallback_title=f"{analysis.restaurant.name} misses you",
                fallback_subtitle="It has been a while - here is a reason to come back.",
                fallback_cta="Order Again",
                evidence={
                    "inactive_customers": analysis.inactive_customers,
                    "inactivity_days": settings.personalized_offer_inactivity_days,
                },
            )
        )

    # 5. Lifting basket size. The eligibility scorer rejects a BUDGET_BEHAVIOR
    #    offer whose minimum is more than 1.8x a customer's own average, so this
    #    reaches the people who already spend near the bar rather than everyone.
    if aov > 0 and analysis.total_customers >= MIN_GROUP_CUSTOMERS:
        segments.append(
            OfferSegment(
                key="basket_size",
                label="Customers who could spend a little more",
                offer_type=PersonalizedOfferType.BUDGET_BEHAVIOR,
                audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
                generation_reason=PersonalizedOfferGenerationReason.BUDGET_BEHAVIOR,
                reach=analysis.active_customers or analysis.total_customers,
                discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
                discount_value=Decimal("15.00"),
                minimum_order_amount=_min_order(aov * Decimal("1.25")),
                fallback_title="Save more on a bigger order",
                fallback_subtitle="Add a little to your usual basket and save.",
                fallback_cta="Order Now",
                evidence={"average_order_value": f"{aov:.2f}"},
            )
        )

    # Reach first: an offer nobody qualifies for is worth less than one that
    # covers half the customer base, whatever the segment is called.
    segments.sort(key=lambda row: row.reach, reverse=True)
    return segments[: max(limit, 1)]


def _segment_candidate(segment: OfferSegment, analysis: RestaurantAnalysis) -> Any:
    """Wrap a segment as an `AIOfferCandidate`.

    Not decoration: the candidate is what `_validate_or_fallback_payload` checks
    a model's copy against, so going through it is what keeps the discount caps,
    the minimum-order floor and the deterministic fallback identical to the
    per-customer path.
    """

    from app.services.ai_offer_generation import AIOfferCandidate

    location = analysis.location
    return AIOfferCandidate(
        offer_type=segment.offer_type,
        audience_type=segment.audience_type,
        generation_reason=segment.generation_reason,
        restaurant_id=analysis.restaurant.id,
        restaurant_name=analysis.restaurant.name,
        restaurant_slug=analysis.restaurant.slug,
        restaurant_location_id=location.id if location else None,
        restaurant_location_name=location.branch_name if location else None,
        applicable_item_id=segment.applicable_item_id,
        applicable_item_name=segment.applicable_item_name,
        applicable_category=segment.applicable_category,
        applicable_cuisine=segment.applicable_cuisine,
        score=Decimal(str(600 + min(segment.reach, 100))),
        target_type=(
            "ITEM"
            if segment.applicable_item_id
            else "CATEGORY"
            if segment.applicable_category
            else "CUISINE"
            if segment.applicable_cuisine
            else "RESTAURANT"
        ),
        target_id=str(
            segment.applicable_item_id
            or segment.applicable_category
            or segment.applicable_cuisine
            or (location.id if location else analysis.restaurant.id)
        ),
        fallback_title=segment.fallback_title,
        fallback_subtitle=segment.fallback_subtitle,
        fallback_cta=segment.fallback_cta,
        fallback_reason=f"Segment {segment.key} built from restaurant order history.",
        fallback_discount_type=segment.discount_type,
        fallback_discount_value=segment.discount_value,
        fallback_minimum_order_amount=segment.minimum_order_amount,
        fallback_max_discount_amount=(
            settings.ai_max_flat_discount
            if segment.discount_type == PersonalizedOfferDiscountType.PERCENTAGE
            else None
        ),
    )


def _build_segment_prompt(segment: OfferSegment, analysis: RestaurantAnalysis) -> str:
    """A prompt about a group, not a person.

    The per-customer prompt names one diner and their habits. Here the model is
    told what the segment is and how many people it covers, and is explicitly
    barred from second-person singular assumptions it cannot support.
    """

    target = (
        f"the dish {segment.applicable_item_name}"
        if segment.applicable_item_name
        else f"the {segment.applicable_category} category"
        if segment.applicable_category
        else f"{segment.applicable_cuisine} food"
        if segment.applicable_cuisine
        else f"the restaurant {analysis.restaurant.name}"
    )
    evidence = ", ".join(f"{key}={value}" for key, value in segment.evidence.items())

    return f"""You are writing ONE promotional offer for a group of customers at a restaurant.

Return STRICT JSON only with this exact shape:
{{
  "title": "string",
  "subtitle": "string",
  "discount_type": "flat|percentage|free_delivery",
  "discount_value": 0,
  "minimum_order": 0,
  "cta": "string",
  "reason": "string"
}}

Hard rules:
- do not include markdown
- keep title under 70 characters
- keep subtitle under 140 characters
- keep CTA under 24 characters
- discount_type must be exactly "{segment.discount_type.value.lower()}"
- discount_value must be exactly {segment.discount_value}
- minimum_order must be exactly {segment.minimum_order_amount}
- this offer is for MANY customers, so never claim to know one person's history
- never invent figures that are not given below

Restaurant: {analysis.restaurant.name}
Segment: {segment.label}
This offer is about: {target}
Customers in this segment: {segment.reach}
Evidence: {evidence or "restaurant order history"}
"""


def _generate_segment_copy(
    segment: OfferSegment, analysis: RestaurantAnalysis
) -> tuple[dict[str, Any], bool, str | None, Any]:
    """Ask the model for copy, then hold it to the same guardrails as ever."""

    import httpx

    from app.services.ai_offer_generation import (
        GENERATE_CLIENT,
        _extract_json_payload,
        _validate_or_fallback_payload,
    )
    from app.services.ollama_client import GENERATE_ENDPOINT, local_only_options

    candidate = _segment_candidate(segment, analysis)
    request = {
        "model": settings.qwen_offer_model_name,
        "prompt": _build_segment_prompt(segment, analysis),
        "stream": False,
        "format": "json",
        **local_only_options(),
    }
    try:
        response = GENERATE_CLIENT.post(GENERATE_ENDPOINT, json=request)
        response.raise_for_status()
        parsed = _extract_json_payload(str(response.json().get("response") or "").strip())
        payload, fallback_used, reason = _validate_or_fallback_payload(
            candidate, llm_payload=parsed
        )
    except (httpx.TimeoutException, httpx.HTTPError, ValueError) as error:
        payload, fallback_used, reason = _validate_or_fallback_payload(
            candidate, llm_payload=None, fallback_reason=str(error)
        )
    return payload, fallback_used, reason, candidate


def _live_segment_offers(db: Session, restaurant_id: uuid.UUID) -> dict[str, GeneratedOffer]:
    """Segment offers this restaurant already has running, by segment key."""

    rows = db.scalars(
        select(GeneratedOffer).where(
            GeneratedOffer.restaurant_id == restaurant_id,
            GeneratedOffer.source == PersonalizedOfferSource.AI_GENERATED,
            GeneratedOffer.state == PersonalizedOfferState.ACTIVE,
            # Shared offers only: the per-customer ones carry an owning user and
            # are none of this run's business.
            GeneratedOffer.generated_for_user_id.is_(None),
        )
    ).all()

    live: dict[str, GeneratedOffer] = {}
    for row in rows:
        key = (row.business_metadata or {}).get("segment_key")
        if isinstance(key, str):
            live[key] = row
    return live


def _persist_segment_offer(
    db: Session,
    *,
    segment: OfferSegment,
    analysis: RestaurantAnalysis,
    candidate: Any,
    payload: dict[str, Any],
    fallback_used: bool,
    fallback_reason: str | None,
) -> GeneratedOffer:
    """Write the offer with no owning customer.

    `generated_for_user_id=None` is the whole mechanism: the read path admits a
    shared offer for every customer and then asks the scorer, per customer,
    whether it applies. Setting an owner here would pin it to one person and
    reproduce exactly the behaviour this module replaces.
    """

    from app.services.ai_offer_generation import _discount_badge, _normalize_discount_type

    discount_type = _normalize_discount_type(str(payload["discount_type"]))
    discount_value = _money(Decimal(str(payload["discount_value"])))
    minimum_order_amount = _money(Decimal(str(payload["minimum_order"])))
    now = datetime.now(UTC)

    offer = GeneratedOffer(
        template_offer_id=None,
        generated_for_user_id=None,
        restaurant_id=analysis.restaurant.id,
        # Restaurant-wide, never pinned to a branch.
        #
        # `_matches_generated_offer_scope` rejects an offer at checkout whose
        # location does not equal the cart's, while the eligibility path that
        # puts it on the customer's home screen has no branch filter at all.
        # Carrying the restaurant's first branch here therefore produced an
        # offer that was visible to everyone and redeemable only at one branch.
        # A segment is derived from the whole restaurant's orders, so it applies
        # at the whole restaurant.
        restaurant_location_id=None,
        applicable_item_id=segment.applicable_item_id,
        generated_combo_id=None,
        source=PersonalizedOfferSource.AI_GENERATED,
        generation_reason=segment.generation_reason,
        state=PersonalizedOfferState.ACTIVE,
        offer_type=segment.offer_type,
        audience_type=segment.audience_type,
        applicable_category=segment.applicable_category,
        applicable_cuisine=segment.applicable_cuisine,
        generated_title=str(payload["title"]).strip() or segment.fallback_title,
        generated_subtitle=str(payload["subtitle"]).strip() or segment.fallback_subtitle,
        generated_badge=_discount_badge(discount_type, discount_value),
        generated_cta_label=str(payload["cta"]).strip() or segment.fallback_cta,
        discount_type=discount_type,
        discount_value=discount_value,
        max_discount_amount=(
            settings.ai_max_flat_discount
            if discount_type == PersonalizedOfferDiscountType.PERCENTAGE
            else None
        ),
        minimum_order_amount=minimum_order_amount,
        valid_for_days=settings.ai_offer_validity_days,
        score=_money(candidate.score),
        # Filled in once matching has run; a shared offer has no meaningful
        # count until the scorer has been asked about every customer.
        eligible_user_count=0,
        business_metadata={
            "strategy": "segment",
            "segment_key": segment.key,
            "segment_label": segment.label,
            "segment_reach_estimate": segment.reach,
            "segment_evidence": segment.evidence,
            "restaurant_analysis": analysis.to_metadata(),
            "source": "deterministic_fallback" if fallback_used else "llm",
            "model": settings.qwen_offer_model_name,
            "generated_at": now.isoformat(),
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "llm_reason": str(payload["reason"]).strip(),
        },
        starts_at=now,
        expires_at=now + timedelta(days=settings.ai_offer_validity_days),
    )
    db.add(offer)
    db.flush()
    return offer


def _restaurant_customers(db: Session, restaurant_id: uuid.UUID) -> list[User]:
    """Everyone who has actually paid this restaurant."""

    return list(
        db.scalars(
            select(User)
            .where(
                User.role == UserRole.CUSTOMER,
                User.is_active.is_(True),
                _paid_orders(restaurant_id)
                .where(Order.customer_id == User.id)
                .exists(),
            )
            .order_by(User.created_at.asc())
        ).all()
    )


def generate_segment_offers(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    force_refresh: bool = False,
    allow_disabled: bool = False,
) -> Any:
    """Analyse one restaurant, then create a few offers and match them.

    Returns the same summary type as the per-customer generator, so callers and
    the screen do not have to branch on which strategy ran.
    """

    from app.services.ai_offer_generation import (
        AIOfferGenerationSummary,
        _expire_ai_offers,
    )
    from app.services.personalized_offers import (
        _sync_generated_offer_matches_for_user,
        invalidate_all_personalized_offer_caches,
    )

    summary = AIOfferGenerationSummary()
    if not settings.enable_ai_offer_generation and not allow_disabled:
        logger.info("Segment offer generation skipped because ENABLE_AI_OFFER_GENERATION is disabled")
        return summary

    started = perf_counter()
    analysis = analyze_restaurant(db, restaurant_id)
    if analysis is None:
        return summary

    segments = derive_segments(analysis)
    summary.segments_considered = len(segments)
    if not segments:
        logger.info(
            "No offer segments met their thresholds restaurant_id=%s customers=%s",
            restaurant_id,
            analysis.total_customers,
        )
        summary.elapsed_ms = int((perf_counter() - started) * 1000)
        return summary

    live = _live_segment_offers(db, restaurant_id)
    created: list[GeneratedOffer] = []

    for segment in segments:
        existing = live.get(segment.key)
        if existing is not None and not force_refresh:
            # The same segment is already running. Creating a second offer for
            # it is the duplication this design exists to avoid.
            summary.segments_skipped += 1
            continue
        if existing is not None:
            summary.offers_replaced += _expire_ai_offers(
                db, [existing], reason="segment_regenerated"
            )

        payload, fallback_used, fallback_reason, candidate = _generate_segment_copy(
            segment, analysis
        )
        if fallback_used:
            summary.fallbacks_used += 1
            if fallback_reason:
                summary.llm_failures += 1

        created.append(
            _persist_segment_offer(
                db,
                segment=segment,
                analysis=analysis,
                candidate=candidate,
                payload=payload,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            )
        )
        summary.offers_generated += 1

    db.commit()

    # Eligibility, decided by the production scorer rather than by anything in
    # this module. Re-syncing each customer is what the read path does anyway,
    # so who the owner is told is eligible is exactly who will see the offer.
    created_ids = {offer.id for offer in created}
    customers = _restaurant_customers(db, restaurant_id)
    summary.users_scanned = len(customers)
    matched_customers = 0
    for customer in customers:
        matches = _sync_generated_offer_matches_for_user(db, user=customer)
        if any(match.generated_offer_id in created_ids and match.is_current for match in matches):
            matched_customers += 1
    summary.customers_matched = matched_customers

    invalidate_all_personalized_offer_caches()
    summary.elapsed_ms = int((perf_counter() - started) * 1000)
    logger.info(
        "Segment offer generation finished restaurant_id=%s segments=%s offers=%s "
        "replaced=%s skipped=%s customers=%s matched=%s elapsed_ms=%s",
        restaurant_id,
        summary.segments_considered,
        summary.offers_generated,
        summary.offers_replaced,
        summary.segments_skipped,
        summary.users_scanned,
        summary.customers_matched,
        summary.elapsed_ms,
    )
    return summary

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models.enums import (
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
from app.models.personalized_offer import GeneratedOffer, GeneratedOfferUserMatch
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.personalized_offers import (
    _generated_offer_is_live,
    _is_user_inactive,
    _load_order_insights,
    _load_repeated_order_patterns,
    _load_user_preferences,
    _normalize_text,
    _quantize,
    invalidate_all_personalized_offer_caches,
)

settings = get_settings()
logger = logging.getLogger(__name__)

from app.services.ollama_client import (
    GENERATE_ENDPOINT,
    HTTP_LIMITS,
    build_client,
    local_only_options,
)

GENERATE_TIMEOUT = httpx.Timeout(
    connect=5.0,
    read=settings.ollama_offer_timeout_seconds,
    write=10.0,
    pool=5.0,
)
GENERATE_CLIENT = build_client(GENERATE_TIMEOUT, limits=HTTP_LIMITS)


@dataclass(slots=True)
class AIOfferCandidate:
    offer_type: PersonalizedOfferType
    audience_type: PersonalizedOfferAudience
    generation_reason: PersonalizedOfferGenerationReason
    restaurant_id: uuid.UUID
    restaurant_name: str
    restaurant_slug: str
    restaurant_location_id: uuid.UUID | None
    restaurant_location_name: str | None
    applicable_item_id: uuid.UUID | None
    applicable_item_name: str | None
    applicable_category: str | None
    applicable_cuisine: str | None
    score: Decimal
    target_type: str
    target_id: str
    fallback_title: str
    fallback_subtitle: str
    fallback_cta: str
    fallback_reason: str
    fallback_discount_type: PersonalizedOfferDiscountType
    fallback_discount_value: Decimal
    fallback_minimum_order_amount: Decimal
    fallback_max_discount_amount: Decimal | None = None


@dataclass(slots=True)
class AIOfferGenerationSummary:
    users_scanned: int = 0
    offers_generated: int = 0
    offers_replaced: int = 0
    fallbacks_used: int = 0
    validation_failures: int = 0
    skipped_users: int = 0
    llm_failures: int = 0
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


class LLMOfferPayload(BaseModel):
    title: str
    subtitle: str
    discount_type: str
    discount_value: Decimal
    minimum_order: Decimal
    cta: str
    reason: str


def _offer_has_current_match(offer: GeneratedOffer, *, user_id: uuid.UUID) -> bool:
    return any(match.user_id == user_id and match.is_current for match in offer.user_matches)


def _refresh_reason_for_existing_offer(
    offer: GeneratedOffer,
    *,
    user_id: uuid.UUID,
    now: datetime,
    force_refresh: bool,
) -> str | None:
    if force_refresh:
        return "force_refresh_requested"
    if not _offer_has_current_match(offer, user_id=user_id):
        return "current_match_missing"
    if offer.conversion_count > 0:
        return "offer_already_converted"
    if not _generated_offer_is_live(offer, now):
        return "offer_not_live"
    if offer.expires_at is None:
        return "offer_missing_expiry"
    if offer.expires_at <= now + timedelta(hours=24):
        return "offer_near_expiry"
    return None


def _load_existing_ai_offers_for_user(db: Session, user_id: uuid.UUID) -> list[GeneratedOffer]:
    return db.scalars(
        select(GeneratedOffer)
        .options(selectinload(GeneratedOffer.user_matches))
        .where(
            GeneratedOffer.generated_for_user_id == user_id,
            GeneratedOffer.source == PersonalizedOfferSource.AI_GENERATED,
            GeneratedOffer.template_offer_id.is_(None),
            GeneratedOffer.state == PersonalizedOfferState.ACTIVE,
        )
        .order_by(GeneratedOffer.created_at.desc())
    ).all()


def _pick_default_restaurant(
    db: Session,
    *,
    preferred_cuisine: str | None = None,
    restaurant_id: uuid.UUID | None = None,
) -> tuple[Restaurant, RestaurantLocation | None] | None:
    """Pick a restaurant to build an offer for.

    `restaurant_id` pins the choice to one restaurant. It is what makes an
    owner-triggered run safe: without it every fallback branch below would
    happily choose somebody else's restaurant, and an owner pressing Generate
    would create offers across the whole platform.
    """

    restaurant_query = (
        select(Restaurant)
        .where(Restaurant.is_active.is_(True), Restaurant.is_approved.is_(True))
        .order_by(Restaurant.updated_at.desc(), Restaurant.created_at.desc())
    )
    if restaurant_id is not None:
        restaurant_query = restaurant_query.where(Restaurant.id == restaurant_id)
    if preferred_cuisine:
        preferred_restaurants = db.scalars(
            restaurant_query.where(func.lower(Restaurant.cuisine_type) == preferred_cuisine.lower())
        ).all()
        if preferred_restaurants:
            restaurant = preferred_restaurants[0]
            location = db.scalar(
                select(RestaurantLocation)
                .where(
                    RestaurantLocation.restaurant_id == restaurant.id,
                    RestaurantLocation.is_active.is_(True),
                )
                .order_by(RestaurantLocation.created_at.asc())
            )
            return restaurant, location

    restaurant = db.scalar(restaurant_query.limit(1))
    if restaurant is None:
        return None
    location = db.scalar(
        select(RestaurantLocation)
        .where(
            RestaurantLocation.restaurant_id == restaurant.id,
            RestaurantLocation.is_active.is_(True),
        )
        .order_by(RestaurantLocation.created_at.asc())
    )
    return restaurant, location


def _load_active_menu_item(
    db: Session,
    menu_item_id: uuid.UUID,
) -> MenuItem | None:
    return db.scalar(
        select(MenuItem)
        .options(selectinload(MenuItem.restaurant))
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .join(RestaurantLocation, MenuItem.restaurant_location_id == RestaurantLocation.id)
        .where(
            MenuItem.id == menu_item_id,
            MenuItem.is_available.is_(True),
            Restaurant.is_active.is_(True),
            Restaurant.is_approved.is_(True),
            RestaurantLocation.is_active.is_(True),
        )
    )


def _build_offer_candidate_for_user(
    db: Session,
    user: User,
    *,
    restaurant_id: uuid.UUID | None = None,
) -> AIOfferCandidate | None:
    """The best offer to build for this customer.

    When `restaurant_id` is set every branch is confined to that restaurant: an
    owner-triggered run must only ever produce offers for their own restaurant,
    however strong this customer's signals for somebody else's are.
    """

    preferences = _load_user_preferences(db, user.id)
    insights = _load_order_insights(db, user.id)
    if insights.latest_order_at is None:
        return None
    repeated_patterns = _load_repeated_order_patterns(db, user.id)
    now = datetime.now(UTC)
    is_inactive = _is_user_inactive(
        insights.latest_order_at,
        inactivity_days=settings.personalized_offer_inactivity_days,
        now=now,
    )

    if repeated_patterns:
        winner = repeated_patterns[0]
        menu_item = _load_active_menu_item(db, winner.menu_item_id)
        if (
            menu_item is not None
            and menu_item.restaurant is not None
            # Their strongest repeat item may be somebody else's dish. Under a
            # scope that is not a candidate, so fall through to the branches
            # below rather than building an offer for another restaurant.
            and (restaurant_id is None or menu_item.restaurant_id == restaurant_id)
        ):
            audience = (
                PersonalizedOfferAudience.INACTIVE_USERS
                if is_inactive
                else PersonalizedOfferAudience.ACTIVE_USERS
            )
            return AIOfferCandidate(
                offer_type=PersonalizedOfferType.FAVORITE_ITEM,
                audience_type=audience,
                generation_reason=(
                    PersonalizedOfferGenerationReason.INACTIVE_USER
                    if is_inactive
                    else PersonalizedOfferGenerationReason.REPEATED_ORDER
                ),
                restaurant_id=menu_item.restaurant_id,
                restaurant_name=menu_item.restaurant.name,
                restaurant_slug=menu_item.restaurant.slug,
                restaurant_location_id=menu_item.restaurant_location_id,
                restaurant_location_name=winner.restaurant_location_name,
                applicable_item_id=menu_item.id,
                applicable_item_name=menu_item.name,
                applicable_category=menu_item.category,
                applicable_cuisine=menu_item.cuisine_type or menu_item.restaurant.cuisine_type,
                score=Decimal("940.00") if is_inactive else Decimal("900.00"),
                target_type="ITEM",
                target_id=str(menu_item.id),
                fallback_title=(
                    f"Your favorite {menu_item.name} is waiting"
                    if is_inactive
                    else f"Save on {menu_item.name} today"
                ),
                fallback_subtitle=f"Built around your repeat orders from {menu_item.restaurant.name}.",
                fallback_cta="Order Again" if is_inactive else "Try Again",
                fallback_reason=f"Repeated item pattern detected for {menu_item.name}.",
                fallback_discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
                fallback_discount_value=Decimal("10.00"),
                fallback_minimum_order_amount=max(settings.ai_min_order_threshold, Decimal("99.00")),
                fallback_max_discount_amount=settings.ai_max_flat_discount,
            )

    if insights.favorite_restaurant_id is not None and (
        restaurant_id is None or insights.favorite_restaurant_id == restaurant_id
    ):
        restaurant = db.scalar(
            select(Restaurant).where(
                Restaurant.id == insights.favorite_restaurant_id,
                Restaurant.is_active.is_(True),
                Restaurant.is_approved.is_(True),
            )
        )
        if restaurant is not None:
            location = None
            if insights.favorite_location_id is not None:
                location = db.scalar(
                    select(RestaurantLocation).where(
                        RestaurantLocation.id == insights.favorite_location_id,
                        RestaurantLocation.restaurant_id == restaurant.id,
                        RestaurantLocation.is_active.is_(True),
                    )
                )
            if location is None:
                location = db.scalar(
                    select(RestaurantLocation)
                    .where(
                        RestaurantLocation.restaurant_id == restaurant.id,
                        RestaurantLocation.is_active.is_(True),
                    )
                    .order_by(RestaurantLocation.created_at.asc())
                )
            return AIOfferCandidate(
                offer_type=PersonalizedOfferType.FAVORITE_RESTAURANT,
                audience_type=(
                    PersonalizedOfferAudience.INACTIVE_USERS
                    if is_inactive
                    else PersonalizedOfferAudience.ACTIVE_USERS
                ),
                generation_reason=(
                    PersonalizedOfferGenerationReason.INACTIVE_USER
                    if is_inactive
                    else PersonalizedOfferGenerationReason.FAVORITE_RESTAURANT
                ),
                restaurant_id=restaurant.id,
                restaurant_name=restaurant.name,
                restaurant_slug=restaurant.slug,
                restaurant_location_id=location.id if location else None,
                restaurant_location_name=location.branch_name if location else None,
                applicable_item_id=None,
                applicable_item_name=None,
                applicable_category=None,
                applicable_cuisine=restaurant.cuisine_type,
                score=Decimal("880.00"),
                target_type="RESTAURANT",
                target_id=str(location.id if location else restaurant.id),
                fallback_title=(
                    f"{restaurant.name} misses you"
                    if is_inactive
                    else f"Recommended from {restaurant.name}"
                ),
                fallback_subtitle=f"Fresh picks from a restaurant you already trust.",
                fallback_cta="Explore Now",
                fallback_reason=f"Favorite restaurant signal detected for {restaurant.name}.",
                fallback_discount_type=PersonalizedOfferDiscountType.FREE_DELIVERY,
                fallback_discount_value=Decimal("0.00"),
                fallback_minimum_order_amount=max(settings.ai_min_order_threshold, Decimal("199.00")),
                fallback_max_discount_amount=None,
            )

    preferred_cuisine = None
    if preferences and preferences.favorite_cuisines:
        preferred_cuisine = preferences.favorite_cuisines[0]
    if preferred_cuisine is None:
        preferred_cuisine = insights.top_cuisine
    if preferred_cuisine:
        default_target = _pick_default_restaurant(
            db, preferred_cuisine=preferred_cuisine, restaurant_id=restaurant_id
        )
        if default_target is not None:
            restaurant, location = default_target
            return AIOfferCandidate(
                offer_type=PersonalizedOfferType.CUISINE_AFFINITY,
                audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
                generation_reason=PersonalizedOfferGenerationReason.CUISINE_AFFINITY,
                restaurant_id=restaurant.id,
                restaurant_name=restaurant.name,
                restaurant_slug=restaurant.slug,
                restaurant_location_id=location.id if location else None,
                restaurant_location_name=location.branch_name if location else None,
                applicable_item_id=None,
                applicable_item_name=None,
                applicable_category=None,
                applicable_cuisine=preferred_cuisine,
                score=Decimal("820.00"),
                target_type="RESTAURANT",
                target_id=str(location.id if location else restaurant.id),
                fallback_title=f"Fresh {preferred_cuisine} picks for you",
                fallback_subtitle=f"Built around your cuisine preferences and recent habits.",
                fallback_cta="Explore Now",
                fallback_reason=f"Cuisine affinity detected for {preferred_cuisine}.",
                fallback_discount_type=PersonalizedOfferDiscountType.FLAT,
                fallback_discount_value=Decimal("40.00"),
                fallback_minimum_order_amount=max(settings.ai_min_order_threshold, Decimal("249.00")),
                fallback_max_discount_amount=None,
            )

    default_target = _pick_default_restaurant(db, restaurant_id=restaurant_id)
    if default_target is None:
        return None
    restaurant, location = default_target
    return AIOfferCandidate(
        offer_type=PersonalizedOfferType.ORDER_HISTORY_MATCH,
        audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
        generation_reason=PersonalizedOfferGenerationReason.GLOBAL_FALLBACK,
        restaurant_id=restaurant.id,
        restaurant_name=restaurant.name,
        restaurant_slug=restaurant.slug,
        restaurant_location_id=location.id if location else None,
        restaurant_location_name=location.branch_name if location else None,
        applicable_item_id=None,
        applicable_item_name=None,
        applicable_category=None,
        applicable_cuisine=restaurant.cuisine_type,
        score=Decimal("760.00"),
        target_type="RESTAURANT",
        target_id=str(location.id if location else restaurant.id),
        fallback_title=f"Offer picks from {restaurant.name}",
        fallback_subtitle="A safe fallback offer generated from broad ordering signals.",
        fallback_cta="Explore Offers",
        fallback_reason="No strong repeat signal was available, so a safe fallback offer was used.",
        fallback_discount_type=PersonalizedOfferDiscountType.FLAT,
        fallback_discount_value=Decimal("25.00"),
        fallback_minimum_order_amount=max(settings.ai_min_order_threshold, Decimal("199.00")),
        fallback_max_discount_amount=None,
    )


def _build_llm_prompt(user: User, candidate: AIOfferCandidate) -> str:
    return f"""You are generating one personalized food-ordering offer.

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
- discount_type must be one of flat, percentage, free_delivery
- flat discount must be <= {settings.ai_max_flat_discount}
- percentage discount must be <= {settings.ai_max_percentage_discount}
- minimum_order must be >= {settings.ai_min_order_threshold}
- focus on the provided candidate scope only

User:
- email: {user.email}

Candidate scope:
- offer_type: {candidate.offer_type.value}
- audience_type: {candidate.audience_type.value}
- restaurant: {candidate.restaurant_name}
- branch: {candidate.restaurant_location_name or "any active branch"}
- item: {candidate.applicable_item_name or "none"}
- category: {candidate.applicable_category or "none"}
- cuisine: {candidate.applicable_cuisine or "none"}
- fallback_reason: {candidate.fallback_reason}

Return a premium, concise offer that fits this context.
"""


def _extract_json_payload(raw_reply: str) -> dict[str, Any]:
    raw_reply = raw_reply.strip()
    if not raw_reply:
        raise ValueError("Empty LLM response")
    try:
        payload = json.loads(raw_reply)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    start = raw_reply.find("{")
    end = raw_reply.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No JSON object found in LLM response")
    payload = json.loads(raw_reply[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM response JSON was not an object")
    return payload


def _normalize_discount_type(value: str) -> PersonalizedOfferDiscountType:
    normalized = _normalize_text(value).replace("-", "_")
    if normalized == "free_delivery":
        return PersonalizedOfferDiscountType.FREE_DELIVERY
    if normalized == "percentage":
        return PersonalizedOfferDiscountType.PERCENTAGE
    if normalized == "flat":
        return PersonalizedOfferDiscountType.FLAT
    raise ValueError(f"Unsupported discount type: {value}")


def _fallback_payload(candidate: AIOfferCandidate, *, fallback_reason: str) -> dict[str, Any]:
    return {
        "title": candidate.fallback_title,
        "subtitle": candidate.fallback_subtitle,
        "discount_type": candidate.fallback_discount_type.value,
        "discount_value": str(candidate.fallback_discount_value),
        "minimum_order": str(candidate.fallback_minimum_order_amount),
        "cta": candidate.fallback_cta,
        "reason": fallback_reason,
    }


def _validate_or_fallback_payload(
    candidate: AIOfferCandidate,
    *,
    llm_payload: dict[str, Any] | None,
    fallback_reason: str | None = None,
) -> tuple[dict[str, Any], bool, str | None]:
    if llm_payload is None:
        return _fallback_payload(candidate, fallback_reason=fallback_reason or candidate.fallback_reason), True, fallback_reason

    try:
        parsed = LLMOfferPayload.model_validate(llm_payload)
        discount_type = _normalize_discount_type(parsed.discount_type)
        discount_value = _quantize(parsed.discount_value)
        minimum_order = _quantize(parsed.minimum_order)
        if discount_type == PersonalizedOfferDiscountType.FLAT and discount_value > settings.ai_max_flat_discount:
            raise ValueError("Flat discount exceeded configured maximum")
        if discount_type == PersonalizedOfferDiscountType.PERCENTAGE and discount_value > settings.ai_max_percentage_discount:
            raise ValueError("Percentage discount exceeded configured maximum")
        if minimum_order < settings.ai_min_order_threshold:
            raise ValueError("Minimum order fell below configured threshold")
        if discount_type == PersonalizedOfferDiscountType.FREE_DELIVERY:
            discount_value = Decimal("0.00")
        return (
            {
                "title": parsed.title.strip(),
                "subtitle": parsed.subtitle.strip(),
                "discount_type": discount_type.value,
                "discount_value": str(discount_value),
                "minimum_order": str(minimum_order),
                "cta": parsed.cta.strip(),
                "reason": parsed.reason.strip(),
            },
            False,
            None,
        )
    except (ValidationError, ValueError) as error:
        return _fallback_payload(candidate, fallback_reason=str(error)), True, str(error)


def _generate_payload_with_llm(candidate: AIOfferCandidate, user: User) -> tuple[dict[str, Any], bool, str | None]:
    prompt = _build_llm_prompt(user, candidate)
    payload = {
        "model": settings.qwen_offer_model_name,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        **local_only_options(),
    }
    try:
        response = GENERATE_CLIENT.post(GENERATE_ENDPOINT, json=payload)
        response.raise_for_status()
        raw_reply = str(response.json().get("response") or "").strip()
        parsed = _extract_json_payload(raw_reply)
        return _validate_or_fallback_payload(candidate, llm_payload=parsed)
    except (httpx.TimeoutException, httpx.HTTPError, ValueError) as error:
        return _validate_or_fallback_payload(candidate, llm_payload=None, fallback_reason=str(error))


def _discount_badge(discount_type: PersonalizedOfferDiscountType, discount_value: Decimal) -> str:
    if discount_type == PersonalizedOfferDiscountType.FREE_DELIVERY:
        return "Free Delivery"
    if discount_type == PersonalizedOfferDiscountType.PERCENTAGE:
        return f"{int(discount_value)}% OFF"
    if discount_type == PersonalizedOfferDiscountType.FLAT:
        return f"Rs {discount_value:.0f} OFF"
    return "Offer"


def _expire_ai_offers(
    db: Session,
    offers: list[GeneratedOffer],
    *,
    reason: str,
) -> int:
    expired_count = 0
    now = datetime.now(UTC)
    for offer in offers:
        offer.state = PersonalizedOfferState.EXPIRED
        offer.expires_at = now
        metadata = dict(offer.business_metadata or {})
        metadata["refresh_reason"] = reason
        metadata["refreshed_at"] = now.isoformat()
        offer.business_metadata = metadata
        db.add(offer)
        expired_count += 1

    if offers:
        offer_ids = [offer.id for offer in offers]
        matches = db.scalars(
            select(GeneratedOfferUserMatch).where(
                GeneratedOfferUserMatch.generated_offer_id.in_(offer_ids),
                GeneratedOfferUserMatch.is_current.is_(True),
            )
        ).all()
        for match in matches:
            match.is_current = False
            db.add(match)
    return expired_count


def _persist_ai_offer_for_user(
    db: Session,
    *,
    user: User,
    candidate: AIOfferCandidate,
    payload: dict[str, Any],
    fallback_used: bool,
    fallback_reason: str | None,
) -> GeneratedOffer:
    discount_type = _normalize_discount_type(str(payload["discount_type"]))
    discount_value = _quantize(Decimal(str(payload["discount_value"])))
    minimum_order_amount = _quantize(Decimal(str(payload["minimum_order"])))
    now = datetime.now(UTC)

    offer = GeneratedOffer(
        template_offer_id=None,
        generated_for_user_id=user.id,
        restaurant_id=candidate.restaurant_id,
        restaurant_location_id=candidate.restaurant_location_id,
        applicable_item_id=candidate.applicable_item_id,
        generated_combo_id=None,
        source=PersonalizedOfferSource.AI_GENERATED,
        generation_reason=candidate.generation_reason,
        state=PersonalizedOfferState.ACTIVE,
        offer_type=candidate.offer_type,
        audience_type=candidate.audience_type,
        applicable_category=candidate.applicable_category,
        applicable_cuisine=candidate.applicable_cuisine,
        generated_title=str(payload["title"]).strip() or candidate.fallback_title,
        generated_subtitle=str(payload["subtitle"]).strip() or candidate.fallback_subtitle,
        generated_badge=_discount_badge(discount_type, discount_value),
        generated_cta_label=str(payload["cta"]).strip() or candidate.fallback_cta,
        discount_type=discount_type,
        discount_value=discount_value,
        max_discount_amount=(
            settings.ai_max_flat_discount
            if discount_type == PersonalizedOfferDiscountType.PERCENTAGE
            else None
        ),
        minimum_order_amount=minimum_order_amount,
        valid_for_days=settings.ai_offer_validity_days,
        score=_quantize(candidate.score),
        eligible_user_count=1,
        business_metadata={
            "source": "llm" if not fallback_used else "deterministic_fallback",
            "model": settings.qwen_offer_model_name,
            "generated_at": now.isoformat(),
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason,
            "llm_reason": str(payload["reason"]).strip(),
            "candidate_target_type": candidate.target_type,
            "candidate_target_id": candidate.target_id,
            "generated_for_user_id": str(user.id),
        },
        starts_at=now,
        expires_at=now + timedelta(days=settings.ai_offer_validity_days),
    )
    db.add(offer)
    db.flush()

    db.add(
        GeneratedOfferUserMatch(
            generated_offer_id=offer.id,
            user_id=user.id,
            matched_reason=candidate.generation_reason,
            score=_quantize(candidate.score),
            rank=1,
            is_current=True,
            target_type=candidate.target_type,
            target_id=candidate.target_id,
            match_metadata={
                "source": "llm" if not fallback_used else "deterministic_fallback",
                "reason": str(payload["reason"]).strip(),
            },
        )
    )
    return offer


def generate_ai_offers(
    db: Session,
    *,
    user_limit: int | None = None,
    batch_size: int | None = None,
    force_refresh: bool = False,
    allow_disabled: bool = False,
    restaurant_id: uuid.UUID | None = None,
) -> AIOfferGenerationSummary:
    """Generate personalized offers.

    `restaurant_id` confines a run to one restaurant, which is what an owner
    triggering this from their own Offers screen gets. It narrows the run at
    both ends: only customers who have actually paid that restaurant are
    scanned, and every candidate is pinned to it.
    """

    summary = AIOfferGenerationSummary()
    if not settings.enable_ai_offer_generation and not allow_disabled:
        logger.info("AI offer generation skipped because ENABLE_AI_OFFER_GENERATION is disabled")
        return summary

    started = perf_counter()
    effective_batch_size = max(batch_size or settings.ai_offer_batch_size, 1)
    limit = user_limit if user_limit is not None else settings.ai_offer_user_limit
    total_processed = 0
    offset = 0

    while True:
        remaining = limit - total_processed if limit and limit > 0 else effective_batch_size
        if limit and limit > 0 and remaining <= 0:
            break
        page_size = min(effective_batch_size, remaining) if limit and limit > 0 else effective_batch_size
        users = db.scalars(
            select(User)
            .where(
                User.role == UserRole.CUSTOMER,
                User.is_active.is_(True),
                # Scoped at the source: an owner's run scans the customers who
                # have actually paid *them*, not every customer on the platform.
                select(Order.id)
                .where(
                    Order.customer_id == User.id,
                    Order.payment_status == PaymentStatus.PAID,
                    *(
                        [Order.restaurant_id == restaurant_id]
                        if restaurant_id is not None
                        else []
                    ),
                )
                .exists(),
            )
            .order_by(User.created_at.asc())
            .offset(offset)
            .limit(page_size)
        ).all()
        if not users:
            break

        for user in users:
            summary.users_scanned += 1
            candidate = _build_offer_candidate_for_user(
                db, user, restaurant_id=restaurant_id
            )
            if candidate is None:
                summary.skipped_users += 1
                continue

            # Second gate, on the way out. The branches above are each scoped,
            # so this should never fire - which is exactly why it is here: a
            # future branch that forgets the scope must not be able to write an
            # offer against somebody else's restaurant.
            if restaurant_id is not None and candidate.restaurant_id != restaurant_id:
                logger.warning(
                    "Discarded out-of-scope AI offer candidate user_id=%s "
                    "candidate_restaurant_id=%s scope_restaurant_id=%s",
                    user.id,
                    candidate.restaurant_id,
                    restaurant_id,
                )
                summary.skipped_users += 1
                continue

            existing_offers = _load_existing_ai_offers_for_user(db, user.id)
            if existing_offers:
                now = datetime.now(UTC)
                refresh_reason = _refresh_reason_for_existing_offer(
                    existing_offers[0],
                    user_id=user.id,
                    now=now,
                    force_refresh=force_refresh,
                )
                if refresh_reason is None and len(existing_offers) == 1:
                    summary.skipped_users += 1
                    continue
                summary.offers_replaced += _expire_ai_offers(
                    db,
                    existing_offers,
                    reason=refresh_reason or "multiple_active_offers",
                )

            offer_payload, fallback_used, fallback_reason = _generate_payload_with_llm(candidate, user)
            if fallback_used:
                summary.fallbacks_used += 1
                if fallback_reason:
                    summary.llm_failures += 1

            _persist_ai_offer_for_user(
                db,
                user=user,
                candidate=candidate,
                payload=offer_payload,
                fallback_used=fallback_used,
                fallback_reason=fallback_reason,
            )
            summary.offers_generated += 1

        db.commit()
        total_processed += len(users)
        offset += len(users)

    summary.elapsed_ms = int((perf_counter() - started) * 1000)
    invalidate_all_personalized_offer_caches()
    logger.info(
        "AI offer generation finished users_scanned=%s offers_generated=%s fallbacks_used=%s llm_failures=%s elapsed_ms=%s",
        summary.users_scanned,
        summary.offers_generated,
        summary.fallbacks_used,
        summary.llm_failures,
        summary.elapsed_ms,
    )
    return summary

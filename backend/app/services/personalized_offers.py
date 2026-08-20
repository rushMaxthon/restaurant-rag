from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.models.enums import (
    GeneratedComboLifecycleStatus,
    OrderFulfillmentType,
    PaymentStatus,
    PersonalizedOfferAudience,
    PersonalizedOfferDiscountType,
    PersonalizedOfferEventType,
    PersonalizedOfferGenerationReason,
    PersonalizedOfferSource,
    PersonalizedOfferState,
    PersonalizedOfferType,
    UserRole,
)
from app.models.generated_combo import GeneratedCombo
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.personalized_offer import (
    GeneratedOffer,
    GeneratedOfferUserMatch,
    PersonalizedOffer,
    PersonalizedOfferEvent,
)
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.models.user_preferences import UserPreferences
from app.schemas.personalized_offer import (
    GeneratedOfferUpdateRequest,
    GeneratedOfferUserMatchResponse,
    PersonalizedOfferCardResponse,
    PersonalizedOfferContextRequest,
    PersonalizedOfferEventBatchRequest,
    PersonalizedOfferEventBatchResponse,
    PersonalizedOfferItemAvailabilityRequest,
    PersonalizedOfferItemAvailabilityResponse,
    PersonalizedOfferManagementResponse,
    PersonalizedOfferPreviewRequest,
    PersonalizedOfferPreviewResponse,
    PersonalizedOfferUpsertRequest,
)
from app.services.menu_item_customizations import (
    SelectedCustomizationOptionInput,
    fetch_menu_items_for_customized_order,
    resolve_menu_item_selection,
)
from app.services.cache import cache_delete_pattern, cache_get_json, cache_set_json
from app.services.recommendations import get_recommendations_for_user

settings = get_settings()
logger = logging.getLogger(__name__)

PERSONALIZED_OFFERS_CACHE_PREFIX = "personalized-offers"
TWO_PLACES = Decimal("0.01")
MANUAL_LIVE_OFFER_TYPES = {
    PersonalizedOfferType.WELCOME_FIRST_ORDER,
    PersonalizedOfferType.FAVORITE_ITEM,
    PersonalizedOfferType.FAVORITE_RESTAURANT,
    PersonalizedOfferType.PREFERENCE_MATCH,
    PersonalizedOfferType.ORDER_HISTORY_MATCH,
    PersonalizedOfferType.NEW_ITEM_MATCH,
    PersonalizedOfferType.TASTE_MATCH,
    PersonalizedOfferType.CUISINE_AFFINITY,
    PersonalizedOfferType.BUDGET_BEHAVIOR,
    PersonalizedOfferType.COMBO_AFFINITY,
    PersonalizedOfferType.CUSTOM,
}


@dataclass(slots=True)
class UserOrderInsights:
    latest_order_at: datetime | None
    average_order_value: Decimal
    favorite_restaurant_id: uuid.UUID | None
    favorite_restaurant_name: str | None
    favorite_restaurant_slug: str | None
    favorite_restaurant_cuisine: str | None
    favorite_location_id: uuid.UUID | None
    favorite_location_name: str | None
    favorite_item_id: uuid.UUID | None
    favorite_item_name: str | None
    favorite_item_category: str | None
    favorite_item_cuisine: str | None
    top_cuisine: str | None


@dataclass(slots=True)
class OfferSelection:
    score: float
    target_type: str
    target_id: str
    restaurant_id: uuid.UUID
    restaurant_name: str
    restaurant_slug: str
    restaurant_location_id: uuid.UUID | None
    restaurant_location_name: str | None
    menu_item_id: uuid.UUID | None
    menu_item_name: str | None
    generated_combo_id: uuid.UUID | None
    generated_combo_name: str | None
    cuisine_type: str | None
    badge: str
    title: str
    subtitle: str
    cta_label: str


@dataclass(slots=True)
class GeneratedOfferDescriptor:
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
    generated_combo_id: uuid.UUID | None
    generated_combo_name: str | None
    generated_title: str
    generated_subtitle: str
    generated_badge: str | None
    generated_cta_label: str | None
    score: Decimal
    metadata: dict[str, object]


@dataclass(slots=True)
class RepeatedOrderPattern:
    menu_item_id: uuid.UUID
    menu_item_name: str
    category: str | None
    cuisine_type: str | None
    restaurant_id: uuid.UUID
    restaurant_name: str
    restaurant_slug: str
    restaurant_location_id: uuid.UUID | None
    restaurant_location_name: str | None
    total_quantity: int
    order_count: int
    total_spend: Decimal
    latest_order_at: datetime | None


def _scope_offer_cards(
    cards: list[PersonalizedOfferCardResponse],
    restaurant_id: uuid.UUID | None,
) -> list[PersonalizedOfferCardResponse]:
    """Narrow offer cards to a single restaurant, if the app is scoped."""

    if restaurant_id is None:
        return cards
    return [card for card in cards if card.restaurant_id == restaurant_id]


def _cache_key(user_id: uuid.UUID, restaurant_id: uuid.UUID | None = None) -> str:
    """Cache key for one user in one app scope.

    The scope segment keeps a marketplace payload from being served to a
    single-restaurant app, and vice versa.
    """

    scope = str(restaurant_id) if restaurant_id else "all"
    return f"{PERSONALIZED_OFFERS_CACHE_PREFIX}:{user_id}:{scope}"


def invalidate_user_personalized_offers_cache(user_id: uuid.UUID) -> None:
    # Every scope for this user, not just the unscoped one.
    cache_delete_pattern(f"{PERSONALIZED_OFFERS_CACHE_PREFIX}:{user_id}:*")


def invalidate_all_personalized_offer_caches() -> None:
    cache_delete_pattern(f"{PERSONALIZED_OFFERS_CACHE_PREFIX}:*")


def _normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


def _meaningful_preferences(preferences: UserPreferences | None) -> bool:
    if preferences is None:
        return False
    return bool(
        preferences.favorite_cuisines
        or preferences.favorite_items
        or preferences.dietary_preferences
        or preferences.spice_level
        or preferences.average_budget
    )


def _quantize(value: Decimal | int | float | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _effective_state(offer: PersonalizedOffer, now: datetime | None = None) -> PersonalizedOfferState:
    current_time = now or datetime.now(UTC)
    if offer.expires_at is not None and offer.expires_at <= current_time:
        return PersonalizedOfferState.EXPIRED
    if offer.state == PersonalizedOfferState.EXPIRED:
        return PersonalizedOfferState.EXPIRED
    return offer.state


def _offer_is_live(offer: PersonalizedOffer, now: datetime | None = None) -> bool:
    current_time = now or datetime.now(UTC)
    if _effective_state(offer, current_time) != PersonalizedOfferState.ACTIVE:
        return False
    if offer.starts_at is not None and offer.starts_at > current_time:
        return False
    return True


def _offer_targets_user(offer: PersonalizedOffer, user: User) -> bool:
    rules = offer.business_rules or {}
    targeted_emails = rules.get("demo_target_emails")
    if isinstance(targeted_emails, list) and targeted_emails:
        normalized_targets = {
            str(value).strip().lower()
            for value in targeted_emails
            if str(value).strip()
        }
        return user.email.strip().lower() in normalized_targets
    return True


def _is_supported_manual_offer(offer: PersonalizedOffer) -> bool:
    return offer.offer_type in MANUAL_LIVE_OFFER_TYPES


def _discount_label(offer: PersonalizedOffer) -> str | None:
    if offer.discount_type == PersonalizedOfferDiscountType.NONE:
        return None
    if offer.discount_type == PersonalizedOfferDiscountType.FREE_DELIVERY:
        if offer.minimum_order_amount and offer.minimum_order_amount > 0:
            return f"Free delivery above Rs {offer.minimum_order_amount:.0f}"
        return "Free delivery"
    if offer.discount_type == PersonalizedOfferDiscountType.PERCENTAGE:
        value = int(offer.discount_value) if offer.discount_value == int(offer.discount_value) else offer.discount_value
        label = f"{value}% OFF"
        if offer.max_discount_amount and offer.max_discount_amount > 0:
            label = f"{label} up to Rs {offer.max_discount_amount:.0f}"
        return label
    if offer.discount_type == PersonalizedOfferDiscountType.FLAT:
        return f"Rs {offer.discount_value:.0f} OFF"
    return None


def _terms_label(offer: PersonalizedOffer) -> str:
    parts: list[str] = []
    if offer.inactivity_days > 0:
        parts.append(f"Inactive {offer.inactivity_days} days")
    if offer.minimum_order_amount > 0:
        parts.append(f"Min Rs {offer.minimum_order_amount:.0f}")
    if offer.valid_for_days > 0:
        parts.append(f"Valid {offer.valid_for_days} days")
    return " · ".join(parts) if parts else "Offer"


def _generated_offer_name(offer: GeneratedOffer) -> str:
    return offer.generated_title


def _generated_offer_discount_type(offer: GeneratedOffer) -> PersonalizedOfferDiscountType:
    return offer.discount_type


def _generated_offer_discount_value(offer: GeneratedOffer) -> Decimal:
    return _quantize(offer.discount_value)


def _generated_offer_max_discount_amount(offer: GeneratedOffer) -> Decimal | None:
    return _quantize(offer.max_discount_amount) if offer.max_discount_amount is not None else None


def _generated_offer_minimum_order_amount(offer: GeneratedOffer) -> Decimal:
    return _quantize(offer.minimum_order_amount)


def _generated_offer_valid_for_days(offer: GeneratedOffer) -> int:
    return int(offer.valid_for_days)


def _generated_offer_inactivity_days(offer: GeneratedOffer) -> int:
    value = offer.business_metadata.get("inactivity_days") if isinstance(offer.business_metadata, dict) else None
    return int(value) if value is not None else settings.personalized_offer_inactivity_days


def _generated_offer_cooldown_hours(offer: GeneratedOffer) -> int:
    value = offer.business_metadata.get("cooldown_hours") if isinstance(offer.business_metadata, dict) else None
    return int(value) if value is not None else settings.personalized_offer_cooldown_hours


def _generated_offer_manual_override(offer: GeneratedOffer) -> dict[str, object]:
    metadata = offer.business_metadata if isinstance(offer.business_metadata, dict) else {}
    override = metadata.get("manual_override")
    return override if isinstance(override, dict) else {}


def _generated_offer_template_business_rules(offer: GeneratedOffer) -> dict[str, object]:
    metadata = offer.business_metadata if isinstance(offer.business_metadata, dict) else {}
    rules = metadata.get("template_business_rules")
    if isinstance(rules, dict):
        return dict(rules)
    if offer.template_offer is not None and isinstance(offer.template_offer.business_rules, dict):
        return dict(offer.template_offer.business_rules)
    return {}


def _generated_offer_manually_edited(offer: GeneratedOffer) -> bool:
    metadata = offer.business_metadata if isinstance(offer.business_metadata, dict) else {}
    return bool(metadata.get("manually_edited"))


def _generated_offer_edited_by(offer: GeneratedOffer) -> str | None:
    metadata = offer.business_metadata if isinstance(offer.business_metadata, dict) else {}
    value = metadata.get("edited_by")
    return str(value).strip() if value else None


def _generated_offer_edited_at(offer: GeneratedOffer) -> datetime | None:
    metadata = offer.business_metadata if isinstance(offer.business_metadata, dict) else {}
    value = metadata.get("edited_at")
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _apply_generated_offer_manual_overrides(offer: GeneratedOffer) -> None:
    override = _generated_offer_manual_override(offer)
    if not override:
        return

    title = override.get("title")
    if isinstance(title, str) and title.strip():
        offer.generated_title = title.strip()

    subtitle = override.get("subtitle")
    if isinstance(subtitle, str) and subtitle.strip():
        offer.generated_subtitle = subtitle.strip()

    badge = override.get("badge")
    if isinstance(badge, str):
        offer.generated_badge = badge.strip() or None

    cta_label = override.get("cta_label")
    if isinstance(cta_label, str):
        offer.generated_cta_label = cta_label.strip() or None

    state_value = override.get("state")
    if isinstance(state_value, str) and state_value in PersonalizedOfferState.__members__:
        offer.state = PersonalizedOfferState[state_value]

    starts_at_value = override.get("starts_at")
    if isinstance(starts_at_value, str) and starts_at_value.strip():
        try:
            offer.starts_at = datetime.fromisoformat(starts_at_value)
        except ValueError:
            pass
    elif starts_at_value is None:
        offer.starts_at = None

    expires_at_value = override.get("expires_at")
    if isinstance(expires_at_value, str) and expires_at_value.strip():
        try:
            offer.expires_at = datetime.fromisoformat(expires_at_value)
        except ValueError:
            pass
    elif expires_at_value is None:
        offer.expires_at = None


def _generated_offer_targets_user(offer: GeneratedOffer, user: User) -> bool:
    rules = _generated_offer_template_business_rules(offer)
    targeted_emails = rules.get("demo_target_emails")
    if isinstance(targeted_emails, list) and targeted_emails:
        normalized_targets = {
            str(value).strip().lower()
            for value in targeted_emails
            if str(value).strip()
        }
        return user.email.strip().lower() in normalized_targets
    return True


def _is_legacy_custom_template_generated_offer(offer: GeneratedOffer) -> bool:
    if offer.generated_for_user_id is not None:
        return False
    if offer.template_offer is not None:
        return offer.template_offer.offer_type == PersonalizedOfferType.CUSTOM
    metadata = offer.business_metadata if isinstance(offer.business_metadata, dict) else {}
    provenance = metadata.get("template_provenance")
    if isinstance(provenance, dict):
        source_type = provenance.get("source_template_offer_type")
        if isinstance(source_type, str) and source_type.upper() == PersonalizedOfferType.CUSTOM.value:
            return True
    return offer.template_offer_id is not None and offer.offer_type == PersonalizedOfferType.CUSTOM


def _is_demo_seeded_offer(offer: PersonalizedOffer) -> bool:
    rules = offer.business_rules or {}
    seed_tag = str(rules.get("seed_tag") or "").strip().lower()
    return bool(seed_tag.startswith("personalized-offers") or isinstance(rules.get("demo_target_emails"), list))


def _serialize_cards(cards: list[PersonalizedOfferCardResponse]) -> list[dict[str, object]]:
    return [card.model_dump(mode="json") for card in cards]


def _deserialize_cards(payload: object) -> list[PersonalizedOfferCardResponse] | None:
    if not isinstance(payload, list):
        return None
    try:
        return [PersonalizedOfferCardResponse.model_validate(item) for item in payload]
    except Exception:
        return None


def _manual_offer_priority(offer: PersonalizedOffer) -> tuple[int, datetime]:
    if offer.offer_type == PersonalizedOfferType.WELCOME_FIRST_ORDER:
        return (4, offer.updated_at)
    if offer.discount_type == PersonalizedOfferDiscountType.FREE_DELIVERY:
        return (3, offer.updated_at)
    if offer.discount_type == PersonalizedOfferDiscountType.PERCENTAGE:
        return (2, offer.updated_at)
    if offer.discount_type == PersonalizedOfferDiscountType.FLAT:
        return (1, offer.updated_at)
    return (0, offer.updated_at)


def _manual_offer_subtitle(offer: PersonalizedOffer) -> str:
    if offer.notes:
        return offer.notes
    if offer.applicable_item is not None:
        return f"Available on {offer.applicable_item.name}"
    if offer.restaurant_location is not None:
        return f"{offer.restaurant_location.branch_name} branch offer"
    return f"Available at {offer.restaurant.name}"


def _manual_offer_cta(offer: PersonalizedOffer) -> str:
    return offer.cta_label or ("View item" if offer.applicable_item_id else "View offer")


def _serialize_manual_card(offer: PersonalizedOffer) -> PersonalizedOfferCardResponse | None:
    if not _is_supported_manual_offer(offer):
        return None
    restaurant = offer.restaurant
    if restaurant is None or not restaurant.is_active or not restaurant.is_approved:
        return None
    if offer.restaurant_location is not None and not offer.restaurant_location.is_active:
        return None
    if offer.applicable_item is not None and not offer.applicable_item.is_available:
        return None

    target_type = "ITEM" if offer.applicable_item_id is not None and offer.applicable_item is not None else "RESTAURANT"
    target_id = str(offer.applicable_item_id or offer.restaurant_location_id or offer.restaurant_id)
    restaurant_location_name = offer.restaurant_location.branch_name if offer.restaurant_location else None
    menu_item_id = offer.applicable_item_id if target_type == "ITEM" else None
    menu_item_name = offer.applicable_item.name if offer.applicable_item and target_type == "ITEM" else None

    return PersonalizedOfferCardResponse(
        id=f"{offer.id}:{target_type}:{target_id}",
        offer_id=offer.id,
        offer_name=offer.name,
        offer_type=offer.offer_type,
        audience_type=offer.audience_type,
        badge=_discount_label(offer) or "Offer",
        title=offer.name,
        subtitle=_manual_offer_subtitle(offer),
        cta_label=_manual_offer_cta(offer),
        target_type=target_type,
        restaurant_id=restaurant.id,
        restaurant_name=restaurant.name,
        restaurant_slug=restaurant.slug,
        restaurant_location_id=offer.restaurant_location_id,
        restaurant_location_name=restaurant_location_name,
        offer_restaurant_location_id=offer.restaurant_location_id,
        menu_item_id=menu_item_id,
        menu_item_name=menu_item_name,
        generated_combo_id=None,
        generated_combo_name=None,
        cuisine_type=restaurant.cuisine_type,
        discount_type=offer.discount_type,
        discount_value=offer.discount_value,
        discount_label=_discount_label(offer),
        max_discount_amount=offer.max_discount_amount,
        minimum_order_amount=offer.minimum_order_amount,
        terms_label=_terms_label(offer),
        valid_for_days=offer.valid_for_days,
        expires_at=offer.expires_at,
        created_at=offer.created_at,
    )


def _generated_offer_is_live(offer: GeneratedOffer, now: datetime | None = None) -> bool:
    current_time = now or datetime.now(UTC)
    if offer.expires_at is not None and offer.expires_at <= current_time:
        return False
    if offer.state != PersonalizedOfferState.ACTIVE:
        return False
    if offer.starts_at is not None and offer.starts_at > current_time:
        return False
    return True


def _matches_generated_offer_scope(offer: GeneratedOffer, *, restaurant_id: uuid.UUID, location_id: uuid.UUID | None) -> bool:
    if offer.restaurant_id != restaurant_id:
        return False
    if offer.restaurant_location_id is not None and offer.restaurant_location_id != location_id:
        return False
    return True


def _generated_discount_label(offer: GeneratedOffer) -> str | None:
    discount_type = _generated_offer_discount_type(offer)
    minimum_order_amount = _generated_offer_minimum_order_amount(offer)
    discount_value = _generated_offer_discount_value(offer)
    max_discount_amount = _generated_offer_max_discount_amount(offer)
    if discount_type == PersonalizedOfferDiscountType.NONE:
        return None
    if discount_type == PersonalizedOfferDiscountType.FREE_DELIVERY:
        if minimum_order_amount > 0:
            return f"Free delivery above Rs {minimum_order_amount:.0f}"
        return "Free delivery"
    if discount_type == PersonalizedOfferDiscountType.PERCENTAGE:
        value = int(discount_value) if discount_value == int(discount_value) else discount_value
        label = f"{value}% OFF"
        if max_discount_amount and max_discount_amount > 0:
            label = f"{label} up to Rs {max_discount_amount:.0f}"
        return label
    if discount_type == PersonalizedOfferDiscountType.FLAT:
        return f"Rs {discount_value:.0f} OFF"
    return None


def _generated_terms_label(offer: GeneratedOffer) -> str:
    parts: list[str] = []
    inactivity_days = _generated_offer_inactivity_days(offer)
    if inactivity_days > 0:
        parts.append(f"Inactive {inactivity_days} days")
    minimum_order_amount = _generated_offer_minimum_order_amount(offer)
    if minimum_order_amount > 0:
        parts.append(f"Min Rs {minimum_order_amount:.0f}")
    valid_for_days = _generated_offer_valid_for_days(offer)
    if valid_for_days > 0:
        parts.append(f"Valid {valid_for_days} days")
    return " · ".join(parts) if parts else "Offer"


def _refresh_generated_offer_eligible_counts(
    db: Session,
    *,
    offer_ids: Iterable[uuid.UUID],
) -> None:
    unique_offer_ids = list(dict.fromkeys(offer_ids))
    if not unique_offer_ids:
        return

    user_count_rows = db.execute(
        select(
            GeneratedOfferUserMatch.generated_offer_id,
            func.count(GeneratedOfferUserMatch.id).label("eligible_user_count"),
        )
        .where(
            GeneratedOfferUserMatch.generated_offer_id.in_(unique_offer_ids),
            GeneratedOfferUserMatch.is_current.is_(True),
        )
        .group_by(GeneratedOfferUserMatch.generated_offer_id)
    ).all()
    eligible_counts = {
        row.generated_offer_id: int(row.eligible_user_count or 0)
        for row in user_count_rows
    }
    offers_by_id = {
        offer.id: offer
        for offer in db.scalars(
            select(GeneratedOffer).where(GeneratedOffer.id.in_(unique_offer_ids))
        ).all()
    }
    for offer_id, offer in offers_by_id.items():
        offer.eligible_user_count = eligible_counts.get(offer_id, 0)
        db.add(offer)


def _pick_default_generated_offer_restaurant(
    db: Session,
) -> Restaurant | None:
    return db.scalar(
        select(Restaurant)
        .where(
            Restaurant.is_active.is_(True),
            Restaurant.is_approved.is_(True),
        )
        .order_by(Restaurant.updated_at.desc(), Restaurant.created_at.desc())
        .limit(1)
    )


def _welcome_offer_query():
    return (
        select(GeneratedOffer)
        .options(
            selectinload(GeneratedOffer.restaurant),
            selectinload(GeneratedOffer.restaurant_location),
        )
        .where(
            GeneratedOffer.template_offer_id.is_(None),
            GeneratedOffer.generated_for_user_id.is_(None),
            GeneratedOffer.offer_type == PersonalizedOfferType.WELCOME_FIRST_ORDER,
            GeneratedOffer.generation_reason == PersonalizedOfferGenerationReason.FIRST_ORDER,
        )
        .order_by(GeneratedOffer.updated_at.desc(), GeneratedOffer.created_at.desc())
    )


def _generated_offer_has_live_scope(offer: GeneratedOffer) -> bool:
    restaurant = offer.restaurant
    if restaurant is None or not restaurant.is_active or not restaurant.is_approved:
        return False
    location = offer.restaurant_location
    if location is not None and not location.is_active:
        return False
    return True


def _deactivate_generated_offer_matches(
    db: Session,
    *,
    matches: Iterable[GeneratedOfferUserMatch],
    reason: str,
) -> list[uuid.UUID]:
    current_time = datetime.now(UTC)
    touched_offer_ids: list[uuid.UUID] = []
    for match in matches:
        if not match.is_current:
            continue
        match.is_current = False
        metadata = dict(match.match_metadata or {})
        metadata["deactivated_reason"] = reason
        metadata["deactivated_at"] = current_time.isoformat()
        match.match_metadata = metadata
        db.add(match)
        touched_offer_ids.append(match.generated_offer_id)
    return touched_offer_ids


def _expire_generated_offers(
    db: Session,
    *,
    offers: Iterable[GeneratedOffer],
    reason: str,
) -> list[uuid.UUID]:
    current_time = datetime.now(UTC)
    touched_offer_ids: list[uuid.UUID] = []
    for offer in offers:
        offer.state = PersonalizedOfferState.EXPIRED
        offer.expires_at = current_time
        metadata = dict(offer.business_metadata or {})
        metadata["refresh_reason"] = reason
        metadata["refreshed_at"] = current_time.isoformat()
        offer.business_metadata = metadata
        db.add(offer)
        touched_offer_ids.append(offer.id)
    return touched_offer_ids


def ensure_global_welcome_offer(
    db: Session,
) -> GeneratedOffer | None:
    current_time = datetime.now(UTC)
    offers = db.scalars(_welcome_offer_query()).all()
    active_candidates: list[GeneratedOffer] = []
    offers_to_expire: list[GeneratedOffer] = []

    for offer in offers:
        if not _generated_offer_is_live(offer, current_time):
            continue
        if not _generated_offer_has_live_scope(offer):
            offers_to_expire.append(offer)
            continue
        active_candidates.append(offer)

    active_offer = active_candidates[0] if active_candidates else None
    if len(active_candidates) > 1:
        offers_to_expire.extend(active_candidates[1:])
    if offers_to_expire:
        _expire_generated_offers(
            db,
            offers=offers_to_expire,
            reason="replaced_by_global_welcome_offer",
        )

    if active_offer is not None:
        return active_offer

    restaurant = _pick_default_generated_offer_restaurant(db)
    if restaurant is None:
        return None

    minimum_order_amount = max(settings.ai_min_order_threshold, Decimal("149.00"))
    offer = GeneratedOffer(
        template_offer_id=None,
        generated_for_user_id=None,
        restaurant_id=restaurant.id,
        restaurant_location_id=None,
        applicable_item_id=None,
        generated_combo_id=None,
        source=PersonalizedOfferSource.AI_GENERATED,
        generation_reason=PersonalizedOfferGenerationReason.FIRST_ORDER,
        state=PersonalizedOfferState.ACTIVE,
        offer_type=PersonalizedOfferType.WELCOME_FIRST_ORDER,
        audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
        applicable_category=None,
        applicable_cuisine=restaurant.cuisine_type,
        generated_title=f"Welcome offer at {restaurant.name}",
        generated_subtitle="Start your first order with a safe introductory offer picked for you.",
        generated_badge="15% OFF",
        generated_cta_label="Start Here",
        discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
        discount_value=Decimal("15.00"),
        max_discount_amount=settings.ai_max_flat_discount,
        minimum_order_amount=minimum_order_amount,
        valid_for_days=0,
        score=Decimal("980.00"),
        eligible_user_count=0,
        business_metadata={
            "offer_strategy": "global_welcome",
            "copy_source": "deterministic_welcome",
            "llm_used": False,
            "reusable": True,
            "inactivity_days": 0,
            "cooldown_hours": 0,
            "generated_at": current_time.isoformat(),
        },
        starts_at=current_time,
        expires_at=None,
    )
    db.add(offer)
    db.flush()
    return offer


def sync_global_welcome_offer_for_user(
    db: Session,
    *,
    user: User,
) -> bool:
    if user.role != UserRole.CUSTOMER or not user.is_active:
        return False

    latest_order_at = _latest_paid_order_at(db, user.id)
    welcome_matches = db.scalars(
        select(GeneratedOfferUserMatch)
        .join(GeneratedOffer, GeneratedOfferUserMatch.generated_offer_id == GeneratedOffer.id)
        .where(
            GeneratedOfferUserMatch.user_id == user.id,
            GeneratedOffer.offer_type == PersonalizedOfferType.WELCOME_FIRST_ORDER,
        )
    ).all()
    touched_offer_ids = _deactivate_generated_offer_matches(
        db,
        matches=[
            match
            for match in welcome_matches
            if latest_order_at is not None or match.generated_offer.generated_for_user_id is not None
        ],
        reason=(
            "first_paid_order_completed"
            if latest_order_at is not None
            else "replaced_by_global_welcome_offer"
        ),
    )

    legacy_offers = db.scalars(
        select(GeneratedOffer)
        .where(
            GeneratedOffer.generated_for_user_id == user.id,
            GeneratedOffer.template_offer_id.is_(None),
            GeneratedOffer.offer_type == PersonalizedOfferType.WELCOME_FIRST_ORDER,
            GeneratedOffer.state == PersonalizedOfferState.ACTIVE,
        )
    ).all()
    if legacy_offers:
        touched_offer_ids.extend(
            _expire_generated_offers(
                db,
                offers=legacy_offers,
                reason=(
                    "first_paid_order_completed"
                    if latest_order_at is not None
                    else "replaced_by_global_welcome_offer"
                ),
            )
        )

    if latest_order_at is not None:
        _refresh_generated_offer_eligible_counts(db, offer_ids=touched_offer_ids)
        return False

    welcome_offer = ensure_global_welcome_offer(db)
    if welcome_offer is None:
        _refresh_generated_offer_eligible_counts(db, offer_ids=touched_offer_ids)
        return False

    match = db.scalar(
        select(GeneratedOfferUserMatch).where(
            GeneratedOfferUserMatch.generated_offer_id == welcome_offer.id,
            GeneratedOfferUserMatch.user_id == user.id,
        )
    )
    if match is None:
        match = GeneratedOfferUserMatch(
            generated_offer_id=welcome_offer.id,
            user_id=user.id,
        )
    match.matched_reason = PersonalizedOfferGenerationReason.FIRST_ORDER
    match.score = Decimal("500.00")
    match.rank = 1
    match.is_current = True
    match.target_type = "RESTAURANT"
    match.target_id = str(welcome_offer.restaurant_id)
    match.match_metadata = {
        "offer_strategy": "global_welcome",
        "copy_source": "deterministic_welcome",
        "llm_used": False,
        "reason": "First-order user with no paid order history yet.",
    }
    db.add(match)
    touched_offer_ids.append(welcome_offer.id)
    _refresh_generated_offer_eligible_counts(db, offer_ids=touched_offer_ids)
    return True


def _offer_base_query():
    return (
        select(PersonalizedOffer)
        .options(
            selectinload(PersonalizedOffer.restaurant),
            selectinload(PersonalizedOffer.restaurant_location),
            selectinload(PersonalizedOffer.applicable_item),
        )
        .order_by(PersonalizedOffer.updated_at.desc(), PersonalizedOffer.created_at.desc())
    )


def _ensure_generated_offers_bootstrapped(
    db: Session,
    *,
    restaurant_id: uuid.UUID | None = None,
) -> bool:
    if restaurant_id is not None:
        template_count = int(
            db.scalar(
                select(func.count(PersonalizedOffer.id)).where(
                    PersonalizedOffer.restaurant_id == restaurant_id,
                    PersonalizedOffer.offer_type != PersonalizedOfferType.CUSTOM,
                )
            )
            or 0
        )
        if template_count <= 0:
            return False

        generated_count = int(
            db.scalar(
                select(func.count(GeneratedOffer.id)).where(
                    GeneratedOffer.restaurant_id == restaurant_id,
                    GeneratedOffer.template_offer_id.is_not(None),
                )
            )
            or 0
        )
        if generated_count > 0:
            return False

        rebuild_generated_offers(db, restaurant_id=restaurant_id)
        db.commit()
        invalidate_all_personalized_offer_caches()
        return True

    template_restaurant_ids = set(
        db.scalars(
            select(PersonalizedOffer.restaurant_id)
            .where(PersonalizedOffer.offer_type != PersonalizedOfferType.CUSTOM)
            .distinct()
        ).all()
    )
    if not template_restaurant_ids:
        return False

    generated_restaurant_ids = set(
        db.scalars(
            select(GeneratedOffer.restaurant_id)
            .where(GeneratedOffer.template_offer_id.is_not(None))
            .distinct()
        ).all()
    )
    missing_restaurant_ids = template_restaurant_ids - generated_restaurant_ids
    if not missing_restaurant_ids:
        return False

    for missing_restaurant_id in missing_restaurant_ids:
        rebuild_generated_offers(db, restaurant_id=missing_restaurant_id)
    db.commit()
    invalidate_all_personalized_offer_caches()
    return True


def _load_user_preferences(db: Session, user_id: uuid.UUID) -> UserPreferences | None:
    return db.scalar(select(UserPreferences).where(UserPreferences.user_id == user_id))


def _latest_paid_order_at(db: Session, user_id: uuid.UUID) -> datetime | None:
    return db.scalar(
        select(func.max(Order.placed_at)).where(
            Order.customer_id == user_id,
            Order.payment_status == PaymentStatus.PAID,
        )
    )


def _is_user_inactive(latest_order_at: datetime | None, *, inactivity_days: int, now: datetime) -> bool:
    if latest_order_at is None:
        return True
    return latest_order_at <= now - timedelta(days=max(inactivity_days, 1))


def _matches_offer_audience(
    offer: PersonalizedOffer,
    *,
    latest_order_at: datetime | None,
    now: datetime,
) -> bool:
    is_inactive_for_offer = _is_user_inactive(
        latest_order_at,
        inactivity_days=offer.inactivity_days,
        now=now,
    )
    if offer.audience_type == PersonalizedOfferAudience.INACTIVE_USERS:
        return is_inactive_for_offer
    if offer.audience_type == PersonalizedOfferAudience.ACTIVE_USERS:
        return latest_order_at is not None and not is_inactive_for_offer
    return True


def _matches_offer_type_eligibility(
    offer: PersonalizedOffer,
    *,
    latest_order_at: datetime | None,
) -> bool:
    if offer.offer_type == PersonalizedOfferType.WELCOME_FIRST_ORDER:
        return latest_order_at is None
    return True


def _matches_generated_offer_audience(
    offer: GeneratedOffer,
    *,
    latest_order_at: datetime | None,
    now: datetime,
) -> bool:
    inactivity_days = _generated_offer_inactivity_days(offer)
    is_inactive_for_offer = _is_user_inactive(
        latest_order_at,
        inactivity_days=inactivity_days,
        now=now,
    )
    if offer.audience_type == PersonalizedOfferAudience.INACTIVE_USERS:
        return is_inactive_for_offer
    if offer.audience_type == PersonalizedOfferAudience.ACTIVE_USERS:
        return latest_order_at is not None and not is_inactive_for_offer
    return True


def _matches_generated_offer_type_eligibility(
    offer: GeneratedOffer,
    *,
    latest_order_at: datetime | None,
) -> bool:
    if offer.offer_type == PersonalizedOfferType.WELCOME_FIRST_ORDER:
        return latest_order_at is None
    return True


def _offer_priority_score(
    offer: PersonalizedOffer,
    *,
    is_globally_inactive: bool,
) -> int:
    if is_globally_inactive and offer.audience_type == PersonalizedOfferAudience.INACTIVE_USERS:
        return 5
    if offer.offer_type == PersonalizedOfferType.FAVORITE_ITEM:
        return 4
    if offer.offer_type in {PersonalizedOfferType.FAVORITE_RESTAURANT, PersonalizedOfferType.ORDER_HISTORY_MATCH}:
        return 3
    if offer.offer_type in {
        PersonalizedOfferType.PREFERENCE_MATCH,
        PersonalizedOfferType.TASTE_MATCH,
        PersonalizedOfferType.NEW_ITEM_MATCH,
        PersonalizedOfferType.CUISINE_AFFINITY,
        PersonalizedOfferType.BUDGET_BEHAVIOR,
        PersonalizedOfferType.COMBO_AFFINITY,
    }:
        return 2
    if offer.offer_type == PersonalizedOfferType.WELCOME_FIRST_ORDER:
        return 1
    return 0


def _load_order_insights(db: Session, user_id: uuid.UUID) -> UserOrderInsights:
    latest_order_at = db.scalar(
        select(func.max(Order.placed_at)).where(
            Order.customer_id == user_id,
            Order.payment_status == PaymentStatus.PAID,
        )
    )
    average_order_value = _quantize(
        db.scalar(
            select(func.avg(Order.total_amount)).where(
                Order.customer_id == user_id,
                Order.payment_status == PaymentStatus.PAID,
            )
        )
    )

    restaurant_rows = db.execute(
        select(
            Order.restaurant_id,
            Restaurant.name,
            Restaurant.slug,
            Restaurant.cuisine_type,
            Order.restaurant_location_id,
            RestaurantLocation.branch_name,
            func.count(Order.id).label("order_count"),
            func.max(Order.placed_at).label("latest_placed_at"),
        )
        .join(Restaurant, Order.restaurant_id == Restaurant.id)
        .join(RestaurantLocation, Order.restaurant_location_id == RestaurantLocation.id)
        .where(
            Order.customer_id == user_id,
            Order.payment_status == PaymentStatus.PAID,
        )
        .group_by(
            Order.restaurant_id,
            Restaurant.name,
            Restaurant.slug,
            Restaurant.cuisine_type,
            Order.restaurant_location_id,
            RestaurantLocation.branch_name,
        )
        .order_by(
            func.count(Order.id).desc(),
            func.max(Order.placed_at).desc(),
            Restaurant.name.asc(),
        )
    ).all()

    item_rows = db.execute(
        select(
            MenuItem.id,
            MenuItem.name,
            MenuItem.category,
            MenuItem.cuisine_type,
            MenuItem.restaurant_id,
            Restaurant.name.label("restaurant_name"),
            Restaurant.slug.label("restaurant_slug"),
            Restaurant.cuisine_type.label("restaurant_cuisine"),
            MenuItem.restaurant_location_id,
            RestaurantLocation.branch_name.label("branch_name"),
            func.sum(OrderItem.quantity).label("total_quantity"),
        )
        .join(OrderItem, OrderItem.menu_item_id == MenuItem.id)
        .join(Order, OrderItem.order_id == Order.id)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .join(RestaurantLocation, MenuItem.restaurant_location_id == RestaurantLocation.id)
        .where(
            Order.customer_id == user_id,
            Order.payment_status == PaymentStatus.PAID,
        )
        .group_by(
            MenuItem.id,
            MenuItem.name,
            MenuItem.category,
            MenuItem.cuisine_type,
            MenuItem.restaurant_id,
            Restaurant.name,
            Restaurant.slug,
            Restaurant.cuisine_type,
            MenuItem.restaurant_location_id,
            RestaurantLocation.branch_name,
        )
        .order_by(
            func.sum(OrderItem.quantity).desc(),
            MenuItem.name.asc(),
        )
    ).all()

    cuisine_rows = db.execute(
        select(
            func.coalesce(MenuItem.cuisine_type, Restaurant.cuisine_type).label("cuisine_label"),
            func.sum(OrderItem.quantity).label("total_quantity"),
        )
        .join(OrderItem, OrderItem.menu_item_id == MenuItem.id)
        .join(Order, OrderItem.order_id == Order.id)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .where(
            Order.customer_id == user_id,
            Order.payment_status == PaymentStatus.PAID,
        )
        .group_by(func.coalesce(MenuItem.cuisine_type, Restaurant.cuisine_type))
        .order_by(func.sum(OrderItem.quantity).desc())
    ).all()

    top_restaurant = restaurant_rows[0] if restaurant_rows else None
    top_item = item_rows[0] if item_rows else None
    top_cuisine = str(cuisine_rows[0].cuisine_label) if cuisine_rows and cuisine_rows[0].cuisine_label else None

    return UserOrderInsights(
        latest_order_at=latest_order_at,
        average_order_value=average_order_value,
        favorite_restaurant_id=top_restaurant.restaurant_id if top_restaurant else None,
        favorite_restaurant_name=str(top_restaurant.name) if top_restaurant else None,
        favorite_restaurant_slug=str(top_restaurant.slug) if top_restaurant else None,
        favorite_restaurant_cuisine=str(top_restaurant.cuisine_type) if top_restaurant else None,
        favorite_location_id=top_restaurant.restaurant_location_id if top_restaurant else None,
        favorite_location_name=str(top_restaurant.branch_name) if top_restaurant else None,
        favorite_item_id=top_item.id if top_item else None,
        favorite_item_name=str(top_item.name) if top_item else None,
        favorite_item_category=str(top_item.category) if top_item else None,
        favorite_item_cuisine=str(top_item.cuisine_type or top_item.restaurant_cuisine) if top_item else None,
        top_cuisine=top_cuisine,
    )


def _load_repeated_order_patterns(db: Session, user_id: uuid.UUID) -> list[RepeatedOrderPattern]:
    rows = db.execute(
        select(
            MenuItem.id,
            MenuItem.name,
            MenuItem.category,
            func.coalesce(MenuItem.cuisine_type, Restaurant.cuisine_type).label("cuisine_type"),
            MenuItem.restaurant_id,
            Restaurant.name.label("restaurant_name"),
            Restaurant.slug.label("restaurant_slug"),
            MenuItem.restaurant_location_id,
            RestaurantLocation.branch_name.label("branch_name"),
            func.sum(OrderItem.quantity).label("total_quantity"),
            func.count(func.distinct(Order.id)).label("order_count"),
            func.sum(OrderItem.total_price).label("total_spend"),
            func.max(Order.placed_at).label("latest_order_at"),
        )
        .join(OrderItem, OrderItem.menu_item_id == MenuItem.id)
        .join(Order, OrderItem.order_id == Order.id)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .join(RestaurantLocation, MenuItem.restaurant_location_id == RestaurantLocation.id)
        .where(
            Order.customer_id == user_id,
            Order.payment_status == PaymentStatus.PAID,
        )
        .group_by(
            MenuItem.id,
            MenuItem.name,
            MenuItem.category,
            func.coalesce(MenuItem.cuisine_type, Restaurant.cuisine_type),
            MenuItem.restaurant_id,
            Restaurant.name,
            Restaurant.slug,
            MenuItem.restaurant_location_id,
            RestaurantLocation.branch_name,
        )
        .order_by(
            func.sum(OrderItem.quantity).desc(),
            func.max(Order.placed_at).desc(),
            func.sum(OrderItem.total_price).desc(),
            MenuItem.name.asc(),
        )
    ).all()

    return [
        RepeatedOrderPattern(
            menu_item_id=row.id,
            menu_item_name=str(row.name),
            category=str(row.category) if row.category is not None else None,
            cuisine_type=str(row.cuisine_type) if row.cuisine_type is not None else None,
            restaurant_id=row.restaurant_id,
            restaurant_name=str(row.restaurant_name),
            restaurant_slug=str(row.restaurant_slug),
            restaurant_location_id=row.restaurant_location_id,
            restaurant_location_name=str(row.branch_name) if row.branch_name is not None else None,
            total_quantity=int(row.total_quantity or 0),
            order_count=int(row.order_count or 0),
            total_spend=_quantize(row.total_spend),
            latest_order_at=row.latest_order_at,
        )
        for row in rows
    ]


def _pick_generated_copy(choices: list[str], seed_value: str) -> str:
    if not choices:
        return ""
    index = abs(hash(seed_value)) % len(choices)
    return choices[index]


def _top_selling_menu_item_for_offer(db: Session, offer: PersonalizedOffer) -> MenuItem | None:
    quantity = func.sum(OrderItem.quantity)
    query = (
        select(MenuItem)
        .join(OrderItem, OrderItem.menu_item_id == MenuItem.id)
        .join(Order, OrderItem.order_id == Order.id)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .join(RestaurantLocation, MenuItem.restaurant_location_id == RestaurantLocation.id)
        .where(
            MenuItem.restaurant_id == offer.restaurant_id,
            MenuItem.is_available.is_(True),
            Restaurant.is_active.is_(True),
            Restaurant.is_approved.is_(True),
            RestaurantLocation.is_active.is_(True),
            Order.payment_status == PaymentStatus.PAID,
        )
        .group_by(MenuItem.id)
        .order_by(quantity.desc(), MenuItem.updated_at.desc(), MenuItem.name.asc())
    )
    if offer.restaurant_location_id is not None:
        query = query.where(MenuItem.restaurant_location_id == offer.restaurant_location_id)
    if offer.applicable_category:
        query = query.where(func.lower(MenuItem.category) == _normalize_text(offer.applicable_category))
    if offer.applicable_cuisine:
        query = query.where(
            or_(
                func.lower(MenuItem.cuisine_type) == _normalize_text(offer.applicable_cuisine),
                func.lower(Restaurant.cuisine_type) == _normalize_text(offer.applicable_cuisine),
            )
        )
    return db.scalar(query.limit(1))


def _top_generated_combo_for_offer(db: Session, offer: PersonalizedOffer) -> GeneratedCombo | None:
    query = (
        select(GeneratedCombo)
        .options(
            selectinload(GeneratedCombo.restaurant),
            selectinload(GeneratedCombo.restaurant_location),
        )
        .join(Restaurant, GeneratedCombo.restaurant_id == Restaurant.id)
        .join(RestaurantLocation, GeneratedCombo.restaurant_location_id == RestaurantLocation.id)
        .where(
            GeneratedCombo.restaurant_id == offer.restaurant_id,
            GeneratedCombo.is_active.is_(True),
            GeneratedCombo.status.in_(
                (
                    GeneratedComboLifecycleStatus.LIVE.value,
                    "PUBLISHED",
                )
            ),
            GeneratedCombo.is_customer_visible.is_(True),
            Restaurant.is_active.is_(True),
            Restaurant.is_approved.is_(True),
            RestaurantLocation.is_active.is_(True),
        )
        .order_by(
            GeneratedCombo.order_count.desc(),
            GeneratedCombo.confidence_score.desc(),
            GeneratedCombo.updated_at.desc(),
        )
    )
    if offer.restaurant_location_id is not None:
        query = query.where(GeneratedCombo.restaurant_location_id == offer.restaurant_location_id)
    return db.scalar(query.limit(1))


def _descriptor_for_offer(db: Session, offer: PersonalizedOffer) -> GeneratedOfferDescriptor | None:
    restaurant = offer.restaurant
    if restaurant is None or not restaurant.is_active or not restaurant.is_approved:
        return None
    location = offer.restaurant_location
    cuisine = offer.applicable_cuisine or restaurant.cuisine_type
    seed_key = f"{offer.id}:{offer.offer_type}:{offer.restaurant_location_id or 'all'}"
    badge = _discount_label(offer)
    cta_label = offer.cta_label or ("View combo" if offer.offer_type == PersonalizedOfferType.COMBO_AFFINITY else "Explore now")

    if offer.offer_type == PersonalizedOfferType.WELCOME_FIRST_ORDER:
        title = f"Welcome! Get your first order offer at {restaurant.name}"
        subtitle = "A warm start, powered by a live business-approved welcome template."
        return GeneratedOfferDescriptor(
            generation_reason=PersonalizedOfferGenerationReason.FIRST_ORDER,
            restaurant_id=restaurant.id,
            restaurant_name=restaurant.name,
            restaurant_slug=restaurant.slug,
            restaurant_location_id=location.id if location else None,
            restaurant_location_name=location.branch_name if location else None,
            applicable_item_id=None,
            applicable_item_name=None,
            applicable_category=None,
            applicable_cuisine=cuisine,
            generated_combo_id=None,
            generated_combo_name=None,
            generated_title=title,
            generated_subtitle=subtitle,
            generated_badge=badge or "Welcome offer",
            generated_cta_label=cta_label,
            score=Decimal("60.00"),
            metadata={"copy_style": "welcome"},
        )

    if offer.offer_type == PersonalizedOfferType.COMBO_AFFINITY:
        combo = _top_generated_combo_for_offer(db, offer)
        if combo is None:
            return None
        title = _pick_generated_copy(
            [
                "Combos built around your cravings",
                "A combo your regulars keep coming back for",
                "A proven combo worth another look",
            ],
            seed_key,
        )
        subtitle = f"{combo.combo_name} is one of the strongest combo patterns at {restaurant.name}."
        return GeneratedOfferDescriptor(
            generation_reason=PersonalizedOfferGenerationReason.COMBO_AFFINITY,
            restaurant_id=restaurant.id,
            restaurant_name=restaurant.name,
            restaurant_slug=restaurant.slug,
            restaurant_location_id=combo.restaurant_location_id,
            restaurant_location_name=combo.restaurant_location.branch_name,
            applicable_item_id=None,
            applicable_item_name=None,
            applicable_category=None,
            applicable_cuisine=restaurant.cuisine_type,
            generated_combo_id=combo.id,
            generated_combo_name=combo.combo_name,
            generated_title=title,
            generated_subtitle=subtitle,
            generated_badge=badge or "Combo pick",
            generated_cta_label=offer.cta_label or "View combo",
            score=Decimal("72.00"),
            metadata={"combo_order_count": combo.order_count},
        )

    if offer.offer_type == PersonalizedOfferType.FAVORITE_ITEM:
        menu_item = offer.applicable_item or _top_selling_menu_item_for_offer(db, offer)
        if menu_item is None:
            return None
        title = _pick_generated_copy(
            [
                f"Your favorite {menu_item.name} deserves a reward",
                f"Order {menu_item.name} with a little extra upside",
                f"{menu_item.name} nights just got tastier",
            ],
            seed_key + str(menu_item.id),
        )
        subtitle = f"Generated from repeat-order demand patterns around {menu_item.name} at {restaurant.name}."
        return GeneratedOfferDescriptor(
            generation_reason=PersonalizedOfferGenerationReason.REPEATED_ORDER,
            restaurant_id=restaurant.id,
            restaurant_name=restaurant.name,
            restaurant_slug=restaurant.slug,
            restaurant_location_id=menu_item.restaurant_location_id,
            restaurant_location_name=location.branch_name if location else None,
            applicable_item_id=menu_item.id,
            applicable_item_name=menu_item.name,
            applicable_category=menu_item.category,
            applicable_cuisine=menu_item.cuisine_type or cuisine,
            generated_combo_id=None,
            generated_combo_name=None,
            generated_title=title,
            generated_subtitle=subtitle,
            generated_badge=badge or "Repeat favorite",
            generated_cta_label=offer.cta_label or "Order again",
            score=Decimal("88.00"),
            metadata={"generated_from": "top_selling_item"},
        )

    if offer.offer_type in {
        PersonalizedOfferType.CUISINE_AFFINITY,
        PersonalizedOfferType.PREFERENCE_MATCH,
        PersonalizedOfferType.TASTE_MATCH,
        PersonalizedOfferType.NEW_ITEM_MATCH,
    }:
        cuisine_label = cuisine or "restaurant favorites"
        title = _pick_generated_copy(
            [
                f"Your {cuisine_label} favorites are waiting",
                f"Fresh {cuisine_label} picks for hungry regulars",
                f"A smart offer for your {cuisine_label} cravings",
            ],
            seed_key + cuisine_label,
        )
        subtitle = f"Generated from {cuisine_label.lower()}-leaning engagement rules at {restaurant.name}."
        return GeneratedOfferDescriptor(
            generation_reason=PersonalizedOfferGenerationReason.CUISINE_AFFINITY,
            restaurant_id=restaurant.id,
            restaurant_name=restaurant.name,
            restaurant_slug=restaurant.slug,
            restaurant_location_id=location.id if location else None,
            restaurant_location_name=location.branch_name if location else None,
            applicable_item_id=None,
            applicable_item_name=None,
            applicable_category=offer.applicable_category,
            applicable_cuisine=cuisine,
            generated_combo_id=None,
            generated_combo_name=None,
            generated_title=title,
            generated_subtitle=subtitle,
            generated_badge=badge or "Cuisine match",
            generated_cta_label=offer.cta_label or "Explore now",
            score=Decimal("74.00"),
            metadata={"generated_from": "cuisine_affinity"},
        )

    if offer.offer_type == PersonalizedOfferType.BUDGET_BEHAVIOR:
        title = "A smarter spend, still in your comfort zone"
        subtitle = f"Generated for value-conscious ordering behavior at {restaurant.name}."
        return GeneratedOfferDescriptor(
            generation_reason=PersonalizedOfferGenerationReason.BUDGET_BEHAVIOR,
            restaurant_id=restaurant.id,
            restaurant_name=restaurant.name,
            restaurant_slug=restaurant.slug,
            restaurant_location_id=location.id if location else None,
            restaurant_location_name=location.branch_name if location else None,
            applicable_item_id=None,
            applicable_item_name=None,
            applicable_category=offer.applicable_category,
            applicable_cuisine=cuisine,
            generated_combo_id=None,
            generated_combo_name=None,
            generated_title=title,
            generated_subtitle=subtitle,
            generated_badge=badge or "Value pick",
            generated_cta_label=offer.cta_label or "See value picks",
            score=Decimal("58.00"),
            metadata={"generated_from": "budget_behavior"},
        )

    reason = (
        PersonalizedOfferGenerationReason.INACTIVE_USER
        if offer.audience_type == PersonalizedOfferAudience.INACTIVE_USERS
        else PersonalizedOfferGenerationReason.FAVORITE_RESTAURANT
    )
    title = _pick_generated_copy(
        [
            f"{restaurant.name} misses you",
            f"Recommended from {restaurant.name}",
            f"An offer worth using at {restaurant.name}",
        ],
        seed_key,
    )
    subtitle = f"Generated from safe restaurant-level campaign rules for {restaurant.name}."
    return GeneratedOfferDescriptor(
        generation_reason=reason,
        restaurant_id=restaurant.id,
        restaurant_name=restaurant.name,
        restaurant_slug=restaurant.slug,
        restaurant_location_id=location.id if location else None,
        restaurant_location_name=location.branch_name if location else None,
        applicable_item_id=offer.applicable_item_id,
        applicable_item_name=offer.applicable_item.name if offer.applicable_item else None,
        applicable_category=offer.applicable_category,
        applicable_cuisine=cuisine,
        generated_combo_id=None,
        generated_combo_name=None,
        generated_title=title,
        generated_subtitle=subtitle,
        generated_badge=badge or ("Comeback offer" if reason == PersonalizedOfferGenerationReason.INACTIVE_USER else "Restaurant offer"),
        generated_cta_label=offer.cta_label or "Explore now",
        score=Decimal("68.00"),
        metadata={"generated_from": "restaurant_scope"},
    )


def rebuild_generated_offers(
    db: Session,
    *,
    restaurant_id: uuid.UUID | None = None,
) -> None:
    template_query = _offer_base_query()
    if restaurant_id is not None:
        template_query = template_query.where(PersonalizedOffer.restaurant_id == restaurant_id)
    templates = db.scalars(template_query).all()

    existing_query = (
        select(GeneratedOffer)
        .options(
            selectinload(GeneratedOffer.template_offer),
            selectinload(GeneratedOffer.restaurant),
            selectinload(GeneratedOffer.restaurant_location),
            selectinload(GeneratedOffer.applicable_item),
            selectinload(GeneratedOffer.generated_combo),
        )
        .where(GeneratedOffer.template_offer_id.is_not(None))
    )
    if restaurant_id is not None:
        existing_query = existing_query.where(GeneratedOffer.restaurant_id == restaurant_id)
    existing_offers = db.scalars(existing_query).all()
    by_template = {offer.template_offer_id: offer for offer in existing_offers}
    seen_template_ids: set[uuid.UUID] = set()

    for template in templates:
        if template.offer_type == PersonalizedOfferType.CUSTOM:
            continue
        descriptor = _descriptor_for_offer(db, template)
        current = by_template.get(template.id)
        if descriptor is None:
            if current is not None and current.state != PersonalizedOfferState.DISABLED:
                current.state = PersonalizedOfferState.DISABLED
                db.add(current)
            continue

        seen_template_ids.add(template.id)
        is_new_offer = current is None
        previous_metadata = dict(current.business_metadata or {}) if current is not None else {}
        generated_offer = current or GeneratedOffer(
            template_offer_id=template.id,
            restaurant_id=descriptor.restaurant_id,
            source=PersonalizedOfferSource.AI_GENERATED,
        )
        generated_offer.restaurant_id = descriptor.restaurant_id
        generated_offer.restaurant_location_id = descriptor.restaurant_location_id
        generated_offer.applicable_item_id = descriptor.applicable_item_id
        generated_offer.generated_combo_id = descriptor.generated_combo_id
        generated_offer.generation_reason = descriptor.generation_reason
        generated_offer.offer_type = template.offer_type
        generated_offer.audience_type = template.audience_type
        generated_offer.applicable_category = descriptor.applicable_category
        generated_offer.applicable_cuisine = descriptor.applicable_cuisine
        generated_offer.generated_title = descriptor.generated_title
        generated_offer.generated_subtitle = descriptor.generated_subtitle
        generated_offer.generated_badge = descriptor.generated_badge
        generated_offer.generated_cta_label = descriptor.generated_cta_label
        generated_offer.discount_type = template.discount_type
        generated_offer.discount_value = _quantize(template.discount_value)
        generated_offer.max_discount_amount = (
            _quantize(template.max_discount_amount) if template.max_discount_amount is not None else None
        )
        generated_offer.minimum_order_amount = _quantize(template.minimum_order_amount)
        generated_offer.valid_for_days = template.valid_for_days
        generated_offer.score = _quantize(descriptor.score)
        metadata = dict(descriptor.metadata)
        metadata["inactivity_days"] = template.inactivity_days
        metadata["cooldown_hours"] = template.cooldown_hours
        metadata["template_business_rules"] = dict(template.business_rules or {})
        metadata["template_provenance"] = {
            "source_template_offer_id": str(template.id),
            "source_template_offer_name": template.name,
            "source_template_offer_type": template.offer_type.value,
        }
        for key in (
            "manual_override",
            "manually_edited",
            "edited_by",
            "edited_by_user_id",
            "edited_at",
            "original_generated_offer_snapshot",
        ):
            if key in previous_metadata:
                metadata[key] = previous_metadata[key]
        generated_offer.business_metadata = metadata
        if is_new_offer:
            generated_offer.state = template.state
            generated_offer.starts_at = template.starts_at
            generated_offer.expires_at = template.expires_at
        _apply_generated_offer_manual_overrides(generated_offer)
        db.add(generated_offer)

    for existing in existing_offers:
        if existing.template_offer_id not in seen_template_ids:
            existing.state = PersonalizedOfferState.DISABLED
            db.add(existing)

    db.flush()


def _match_generated_offer_for_user(
    offer: GeneratedOffer,
    *,
    user: User,
    preferences: UserPreferences | None,
    insights: UserOrderInsights,
    repeated_patterns: list[RepeatedOrderPattern],
    now: datetime,
) -> tuple[Decimal, PersonalizedOfferGenerationReason, dict[str, object]] | None:
    if not _generated_offer_is_live(offer, now):
        return None

    if offer.generated_for_user_id is not None:
        if offer.generated_for_user_id != user.id:
            return None
        metadata = dict(offer.business_metadata or {})
        metadata.setdefault("runtime_source", "user_scoped_ai_offer")
        return _quantize(offer.score), offer.generation_reason, metadata

    if _is_legacy_custom_template_generated_offer(offer):
        return None

    if not _generated_offer_targets_user(offer, user):
        return None
    if not _matches_generated_offer_audience(offer, latest_order_at=insights.latest_order_at, now=now):
        return None
    if not _matches_generated_offer_type_eligibility(offer, latest_order_at=insights.latest_order_at):
        return None

    metadata: dict[str, object] = {}
    if offer.offer_type == PersonalizedOfferType.WELCOME_FIRST_ORDER:
        return Decimal("500.00"), PersonalizedOfferGenerationReason.FIRST_ORDER, metadata

    if offer.audience_type == PersonalizedOfferAudience.INACTIVE_USERS and insights.latest_order_at is not None:
        metadata["latest_order_at"] = insights.latest_order_at.isoformat()

    if offer.offer_type == PersonalizedOfferType.FAVORITE_ITEM:
        matching_patterns = []
        for pattern in repeated_patterns:
            if offer.applicable_item_id is not None and pattern.menu_item_id == offer.applicable_item_id:
                matching_patterns.append(pattern)
                continue
            if offer.applicable_category and _normalize_text(pattern.category) == _normalize_text(offer.applicable_category):
                matching_patterns.append(pattern)
                continue
            if offer.applicable_cuisine and _normalize_text(pattern.cuisine_type) == _normalize_text(offer.applicable_cuisine):
                matching_patterns.append(pattern)
        if not matching_patterns:
            return None
        winner = matching_patterns[0]
        priority = Decimal("400.00")
        score = priority + Decimal(str(winner.total_quantity)) + (winner.total_spend / Decimal("100"))
        metadata.update(
            {
                "winning_item_id": str(winner.menu_item_id),
                "winning_item_name": winner.menu_item_name,
                "winning_category": winner.category,
                "winning_cuisine": winner.cuisine_type,
                "winning_repeat_quantity": winner.total_quantity,
                "winning_order_count": winner.order_count,
                "winning_total_spend": f"{winner.total_spend:.2f}",
            }
        )
        return _quantize(score), PersonalizedOfferGenerationReason.REPEATED_ORDER, metadata

    if offer.offer_type in {PersonalizedOfferType.FAVORITE_RESTAURANT, PersonalizedOfferType.ORDER_HISTORY_MATCH}:
        if insights.favorite_restaurant_id != offer.restaurant_id:
            return None
        score = Decimal("300.00")
        if repeated_patterns:
            top_pattern = repeated_patterns[0]
            score += Decimal(str(top_pattern.total_quantity)) + (top_pattern.total_spend / Decimal("100"))
            metadata["winning_item_name"] = top_pattern.menu_item_name
            metadata["winning_repeat_quantity"] = top_pattern.total_quantity
        return _quantize(score), PersonalizedOfferGenerationReason.FAVORITE_RESTAURANT, metadata

    if offer.offer_type in {
        PersonalizedOfferType.CUISINE_AFFINITY,
        PersonalizedOfferType.PREFERENCE_MATCH,
        PersonalizedOfferType.TASTE_MATCH,
        PersonalizedOfferType.NEW_ITEM_MATCH,
    }:
        target_cuisine = _normalize_text(offer.applicable_cuisine)
        preferred_cuisines = {_normalize_text(value) for value in (preferences.favorite_cuisines if preferences else []) if value}
        top_cuisine = _normalize_text(insights.top_cuisine)
        if target_cuisine and target_cuisine not in preferred_cuisines and target_cuisine != top_cuisine:
            return None
        base = Decimal("220.00")
        if target_cuisine and target_cuisine == top_cuisine:
            base += Decimal("25.00")
        metadata["target_cuisine"] = offer.applicable_cuisine
        return _quantize(base), PersonalizedOfferGenerationReason.CUISINE_AFFINITY, metadata

    if offer.offer_type == PersonalizedOfferType.COMBO_AFFINITY:
        if insights.favorite_restaurant_id != offer.restaurant_id and not any(
            pattern.restaurant_id == offer.restaurant_id for pattern in repeated_patterns
        ):
            return None
        return Decimal("210.00"), PersonalizedOfferGenerationReason.COMBO_AFFINITY, metadata

    if offer.offer_type == PersonalizedOfferType.BUDGET_BEHAVIOR:
        average_value = insights.average_order_value
        if average_value > 0 and _generated_offer_minimum_order_amount(offer) > average_value * Decimal("1.8"):
            return None
        metadata["average_order_value"] = f"{average_value:.2f}"
        return Decimal("180.00"), PersonalizedOfferGenerationReason.BUDGET_BEHAVIOR, metadata

    return Decimal("120.00"), PersonalizedOfferGenerationReason.GLOBAL_FALLBACK, metadata


def _sync_generated_offer_matches_for_user(
    db: Session,
    *,
    user: User,
) -> list[GeneratedOfferUserMatch]:
    sync_global_welcome_offer_for_user(db, user=user)
    now = datetime.now(UTC)
    preferences = _load_user_preferences(db, user.id)
    insights = _load_order_insights(db, user.id)
    repeated_patterns = _load_repeated_order_patterns(db, user.id)
    generated_offers = db.scalars(
        select(GeneratedOffer)
        .options(
            selectinload(GeneratedOffer.template_offer).selectinload(PersonalizedOffer.restaurant),
            selectinload(GeneratedOffer.generated_for_user),
            selectinload(GeneratedOffer.restaurant),
            selectinload(GeneratedOffer.restaurant_location),
            selectinload(GeneratedOffer.applicable_item),
            selectinload(GeneratedOffer.generated_combo),
            selectinload(GeneratedOffer.user_matches),
        )
        .join(Restaurant, GeneratedOffer.restaurant_id == Restaurant.id)
        .outerjoin(RestaurantLocation, GeneratedOffer.restaurant_location_id == RestaurantLocation.id)
        .where(
            Restaurant.is_active.is_(True),
            Restaurant.is_approved.is_(True),
            or_(GeneratedOffer.restaurant_location_id.is_(None), RestaurantLocation.is_active.is_(True)),
            or_(GeneratedOffer.generated_for_user_id.is_(None), GeneratedOffer.generated_for_user_id == user.id),
        )
    ).all()

    scored: list[tuple[Decimal, GeneratedOffer, PersonalizedOfferGenerationReason, dict[str, object]]] = []
    for generated_offer in generated_offers:
        result = _match_generated_offer_for_user(
            generated_offer,
            user=user,
            preferences=preferences,
            insights=insights,
            repeated_patterns=repeated_patterns,
            now=now,
        )
        if result is None:
            continue
        score, matched_reason, metadata = result
        scored.append((score, generated_offer, matched_reason, metadata))

    scored.sort(
        key=lambda row: (
            row[0],
            row[1].created_at,
        ),
        reverse=True,
    )
    scored = scored[: max(settings.personalized_offer_max_cards, 1)]

    existing_matches = {
        match.generated_offer_id: match
        for match in db.scalars(
            select(GeneratedOfferUserMatch).where(GeneratedOfferUserMatch.user_id == user.id)
        ).all()
    }
    current_offer_ids = {generated_offer.id for _, generated_offer, _, _ in scored}
    for offer_id, match in existing_matches.items():
        if offer_id not in current_offer_ids and match.is_current:
            match.is_current = False
            db.add(match)

    refreshed_matches: list[GeneratedOfferUserMatch] = []
    for rank, (score, generated_offer, matched_reason, metadata) in enumerate(scored, start=1):
        match = existing_matches.get(generated_offer.id)
        if match is None:
            match = GeneratedOfferUserMatch(
                generated_offer_id=generated_offer.id,
                user_id=user.id,
            )
        match.matched_reason = matched_reason
        match.score = _quantize(score)
        match.rank = rank
        match.is_current = True
        match.target_type = (
            "ITEM"
            if generated_offer.applicable_item_id is not None
            else "COMBO"
            if generated_offer.generated_combo_id is not None
            else "RESTAURANT"
        )
        match.target_id = str(
            generated_offer.applicable_item_id
            or generated_offer.generated_combo_id
            or generated_offer.restaurant_location_id
            or generated_offer.restaurant_id
        )
        match.match_metadata = metadata
        db.add(match)
        refreshed_matches.append(match)

    db.flush()

    touched_offer_ids = current_offer_ids | set(existing_matches.keys())
    if touched_offer_ids:
        _refresh_generated_offer_eligible_counts(db, offer_ids=touched_offer_ids)

    db.commit()
    return db.scalars(
        select(GeneratedOfferUserMatch)
        .options(
            selectinload(GeneratedOfferUserMatch.generated_offer).selectinload(GeneratedOffer.template_offer),
            selectinload(GeneratedOfferUserMatch.generated_offer).selectinload(GeneratedOffer.restaurant),
            selectinload(GeneratedOfferUserMatch.generated_offer).selectinload(GeneratedOffer.restaurant_location),
        )
        .where(
            GeneratedOfferUserMatch.user_id == user.id,
            GeneratedOfferUserMatch.is_current.is_(True),
        )
        .order_by(GeneratedOfferUserMatch.rank.asc(), GeneratedOfferUserMatch.created_at.desc())
    ).all()


def _offer_matches_scope(offer: PersonalizedOffer, *, restaurant_id: uuid.UUID, location_id: uuid.UUID | None) -> bool:
    if offer.restaurant_id != restaurant_id:
        return False
    if offer.restaurant_location_id is not None and offer.restaurant_location_id != location_id:
        return False
    return True


def _recommendation_matches_offer(offer: PersonalizedOffer, recommendation) -> bool:
    if not _offer_matches_scope(
        offer,
        restaurant_id=recommendation.restaurant_id,
        location_id=recommendation.restaurant_location_id,
    ):
        return False
    if offer.applicable_item_id is not None and recommendation.id != offer.applicable_item_id:
        return False
    if offer.applicable_category and _normalize_text(recommendation.category) != _normalize_text(offer.applicable_category):
        return False
    offer_cuisine = _normalize_text(offer.applicable_cuisine)
    if offer_cuisine and _normalize_text(recommendation.cuisine_type or recommendation.restaurant.cuisine_type) != offer_cuisine:
        return False
    return True


def _choose_combo_for_offer(db: Session, offer: PersonalizedOffer, insights: UserOrderInsights) -> GeneratedCombo | None:
    query = (
        select(GeneratedCombo)
        .options(
            selectinload(GeneratedCombo.restaurant),
            selectinload(GeneratedCombo.restaurant_location),
        )
        .join(Restaurant, GeneratedCombo.restaurant_id == Restaurant.id)
        .join(RestaurantLocation, GeneratedCombo.restaurant_location_id == RestaurantLocation.id)
        .where(
            GeneratedCombo.is_active.is_(True),
            GeneratedCombo.status.in_(
                (
                    GeneratedComboLifecycleStatus.LIVE.value,
                    "PUBLISHED",
                )
            ),
            GeneratedCombo.is_customer_visible.is_(True),
            Restaurant.is_active.is_(True),
            Restaurant.is_approved.is_(True),
            RestaurantLocation.is_active.is_(True),
            GeneratedCombo.restaurant_id == offer.restaurant_id,
        )
        .order_by(
            GeneratedCombo.order_count.desc(),
            GeneratedCombo.confidence_score.desc(),
            GeneratedCombo.updated_at.desc(),
        )
    )
    if offer.restaurant_location_id is not None:
        query = query.where(GeneratedCombo.restaurant_location_id == offer.restaurant_location_id)
    elif insights.favorite_location_id is not None:
        query = query.order_by(
            (GeneratedCombo.restaurant_location_id == insights.favorite_location_id).desc(),
            GeneratedCombo.order_count.desc(),
            GeneratedCombo.confidence_score.desc(),
            GeneratedCombo.updated_at.desc(),
        )
    return db.scalar(query.limit(1))


def _build_selection_for_offer(
    db: Session,
    *,
    offer: PersonalizedOffer,
    recommendations: list,
    preferences: UserPreferences | None,
    insights: UserOrderInsights,
) -> OfferSelection | None:
    filtered_recommendations = [recommendation for recommendation in recommendations if _recommendation_matches_offer(offer, recommendation)]
    preferred_cuisine = _normalize_text(offer.applicable_cuisine or insights.top_cuisine or (preferences.favorite_cuisines[0] if preferences and preferences.favorite_cuisines else None))
    is_inactive_offer = offer.audience_type == PersonalizedOfferAudience.INACTIVE_USERS

    if offer.offer_type == PersonalizedOfferType.WELCOME_FIRST_ORDER:
        if insights.latest_order_at is not None:
            return None
        location = offer.restaurant_location
        return OfferSelection(
            score=0.62,
            target_type="RESTAURANT",
            target_id=str(offer.restaurant_id),
            restaurant_id=offer.restaurant_id,
            restaurant_name=offer.restaurant.name,
            restaurant_slug=offer.restaurant.slug,
            restaurant_location_id=location.id if location else None,
            restaurant_location_name=location.branch_name if location else None,
            menu_item_id=None,
            menu_item_name=None,
            generated_combo_id=None,
            generated_combo_name=None,
            cuisine_type=offer.restaurant.cuisine_type,
            badge="Welcome Offer",
            title=f"Welcome! Get your first order offer at {offer.restaurant.name}",
            subtitle="A first-order welcome pick is active for this restaurant if you want to start here.",
            cta_label=offer.cta_label or "Explore Now",
        )

    if offer.offer_type == PersonalizedOfferType.FAVORITE_ITEM:
        favorite_match = None
        if insights.favorite_item_name:
            normalized_name = _normalize_text(insights.favorite_item_name)
            favorite_match = next(
                (
                    recommendation
                    for recommendation in filtered_recommendations
                    if _normalize_text(recommendation.name) == normalized_name
                ),
                None,
            )
        recommendation = favorite_match or (
            filtered_recommendations[0]
            if (
                filtered_recommendations
                and (
                    offer.applicable_item_id is not None
                    or insights.favorite_restaurant_id == offer.restaurant_id
                )
            )
            else None
        )
        if recommendation is None and insights.favorite_item_id is not None and insights.favorite_restaurant_id == offer.restaurant_id:
            favorite_menu_item = db.scalar(
                select(MenuItem)
                .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
                .join(RestaurantLocation, MenuItem.restaurant_location_id == RestaurantLocation.id)
                .where(
                    MenuItem.id == insights.favorite_item_id,
                    MenuItem.restaurant_id == offer.restaurant_id,
                    MenuItem.is_available.is_(True),
                    Restaurant.is_active.is_(True),
                    Restaurant.is_approved.is_(True),
                    RestaurantLocation.is_active.is_(True),
                )
            )
            if favorite_menu_item is not None:
                return OfferSelection(
                    score=0.98,
                    target_type="ITEM",
                    target_id=str(favorite_menu_item.id),
                    restaurant_id=favorite_menu_item.restaurant_id,
                    restaurant_name=offer.restaurant.name,
                    restaurant_slug=offer.restaurant.slug,
                    restaurant_location_id=favorite_menu_item.restaurant_location_id,
                    restaurant_location_name=offer.restaurant_location.branch_name if offer.restaurant_location else insights.favorite_location_name,
                    menu_item_id=favorite_menu_item.id,
                    menu_item_name=favorite_menu_item.name,
                    generated_combo_id=None,
                    generated_combo_name=None,
                    cuisine_type=favorite_menu_item.cuisine_type or offer.restaurant.cuisine_type,
                    badge="Order Again" if is_inactive_offer else "Favorite Pick",
                    title=(
                        f"Your favorite {favorite_menu_item.name} is waiting"
                        if is_inactive_offer
                        else f"Your favorite {favorite_menu_item.name} is ready again"
                    ),
                    subtitle=(
                        f"Back at {offer.restaurant.name} and ready when you are."
                        if is_inactive_offer
                        else f"Revisit a favorite from {offer.restaurant.name}."
                    ),
                    cta_label=offer.cta_label or "Order Again",
                )
        if recommendation is None:
            return None
        return OfferSelection(
            score=0.98,
            target_type="ITEM",
            target_id=str(recommendation.id),
            restaurant_id=recommendation.restaurant_id,
            restaurant_name=recommendation.restaurant.name,
            restaurant_slug=recommendation.restaurant.slug,
            restaurant_location_id=recommendation.restaurant_location_id,
            restaurant_location_name=recommendation.restaurant_location.branch_name,
            menu_item_id=recommendation.id,
            menu_item_name=recommendation.name,
            generated_combo_id=None,
            generated_combo_name=None,
            cuisine_type=recommendation.cuisine_type or recommendation.restaurant.cuisine_type,
            badge="Order Again" if is_inactive_offer else "Favorite Pick",
            title=(
                f"Your favorite {recommendation.name} is waiting"
                if is_inactive_offer
                else f"Your favorite {recommendation.name} is ready again"
            ),
            subtitle=(
                f"Back at {recommendation.restaurant.name} and ready when you are."
                if is_inactive_offer
                else f"Revisit a favorite from {recommendation.restaurant.name}."
            ),
            cta_label=offer.cta_label or "Order Again",
        )

    if offer.offer_type == PersonalizedOfferType.FAVORITE_RESTAURANT:
        if insights.favorite_restaurant_id is None or insights.favorite_restaurant_id != offer.restaurant_id:
            return None
        restaurant_name = insights.favorite_restaurant_name or offer.restaurant.name
        return OfferSelection(
            score=0.9,
            target_type="RESTAURANT",
            target_id=str(offer.restaurant_id),
            restaurant_id=offer.restaurant_id,
            restaurant_name=restaurant_name,
            restaurant_slug=offer.restaurant.slug,
            restaurant_location_id=offer.restaurant_location_id or insights.favorite_location_id,
            restaurant_location_name=offer.restaurant_location.branch_name if offer.restaurant_location else insights.favorite_location_name,
            menu_item_id=None,
            menu_item_name=None,
            generated_combo_id=None,
            generated_combo_name=None,
            cuisine_type=offer.restaurant.cuisine_type,
            badge="We Miss You" if is_inactive_offer else "Favorite Restaurant",
            title=(
                f"{restaurant_name} misses you"
                if is_inactive_offer
                else f"Recommended from your favorite restaurant"
            ),
            subtitle=(
                f"Your go-to {offer.restaurant.cuisine_type.lower()} spot has fresh picks ready."
                if is_inactive_offer
                else f"Fresh picks from {restaurant_name}, a place you already love."
            ),
            cta_label=offer.cta_label or "Explore Now",
        )

    if offer.offer_type in {PersonalizedOfferType.TASTE_MATCH, PersonalizedOfferType.PREFERENCE_MATCH}:
        recommendation = next(
            (
                row
                for row in filtered_recommendations
                if row.recommendation_label == "Matches Your Taste"
            ),
            filtered_recommendations[0] if filtered_recommendations else None,
        )
        if recommendation is None:
            return None
        descriptor = "taste"
        if preferences and preferences.spice_level:
            descriptor = f"{preferences.spice_level.lower()}-craving"
        return OfferSelection(
            score=0.86,
            target_type="ITEM",
            target_id=str(recommendation.id),
            restaurant_id=recommendation.restaurant_id,
            restaurant_name=recommendation.restaurant.name,
            restaurant_slug=recommendation.restaurant.slug,
            restaurant_location_id=recommendation.restaurant_location_id,
            restaurant_location_name=recommendation.restaurant_location.branch_name,
            menu_item_id=recommendation.id,
            menu_item_name=recommendation.name,
            generated_combo_id=None,
            generated_combo_name=None,
            cuisine_type=recommendation.cuisine_type or recommendation.restaurant.cuisine_type,
            badge="Tailored Pick",
            title=f"Fresh {descriptor} picks for you",
            subtitle="Built around your saved taste, diet, and comfort cues.",
            cta_label=offer.cta_label or "Try Now",
        )

    if offer.offer_type == PersonalizedOfferType.ORDER_HISTORY_MATCH:
        recommendation = next(
            (
                row
                for row in filtered_recommendations
                if row.recommendation_label == "Based on Your Orders"
            ),
            filtered_recommendations[0] if filtered_recommendations else None,
        )
        if recommendation is None:
            return None
        return OfferSelection(
            score=0.89,
            target_type="ITEM",
            target_id=str(recommendation.id),
            restaurant_id=recommendation.restaurant_id,
            restaurant_name=recommendation.restaurant.name,
            restaurant_slug=recommendation.restaurant.slug,
            restaurant_location_id=recommendation.restaurant_location_id,
            restaurant_location_name=recommendation.restaurant_location.branch_name,
            menu_item_id=recommendation.id,
            menu_item_name=recommendation.name,
            generated_combo_id=None,
            generated_combo_name=None,
            cuisine_type=recommendation.cuisine_type or recommendation.restaurant.cuisine_type,
            badge="Order History",
            title="Picked from what you order most",
            subtitle=f"{recommendation.name} matches your recent cravings and repeat habits.",
            cta_label=offer.cta_label or "Order Again",
        )

    if offer.offer_type == PersonalizedOfferType.CUISINE_AFFINITY:
        cuisine_name = offer.applicable_cuisine or insights.top_cuisine or (preferences.favorite_cuisines[0] if preferences and preferences.favorite_cuisines else None)
        if not cuisine_name:
            return None
        recommendation = next(
            (
                row
                for row in filtered_recommendations
                if _normalize_text(row.cuisine_type or row.restaurant.cuisine_type) == _normalize_text(cuisine_name)
            ),
            filtered_recommendations[0] if filtered_recommendations else None,
        )
        if recommendation is None:
            return None
        return OfferSelection(
            score=0.82,
            target_type="RESTAURANT",
            target_id=str(recommendation.restaurant_id),
            restaurant_id=recommendation.restaurant_id,
            restaurant_name=recommendation.restaurant.name,
            restaurant_slug=recommendation.restaurant.slug,
            restaurant_location_id=recommendation.restaurant_location_id,
            restaurant_location_name=recommendation.restaurant_location.branch_name,
            menu_item_id=None,
            menu_item_name=None,
            generated_combo_id=None,
            generated_combo_name=None,
            cuisine_type=cuisine_name,
            badge="Cuisine Match",
            title=f"Your {cuisine_name} favorites are trending",
            subtitle=f"Jump back into {cuisine_name.lower()} comfort from a place you already like.",
            cta_label=offer.cta_label or "Explore Now",
        )

    if offer.offer_type == PersonalizedOfferType.BUDGET_BEHAVIOR:
        ceiling = insights.average_order_value if insights.average_order_value > 0 else Decimal("300.00")
        recommendation = next(
            (
                row
                for row in filtered_recommendations
                if _quantize(row.price) <= ceiling
            ),
            filtered_recommendations[0] if filtered_recommendations else None,
        )
        if recommendation is None:
            return None
        return OfferSelection(
            score=0.76,
            target_type="ITEM",
            target_id=str(recommendation.id),
            restaurant_id=recommendation.restaurant_id,
            restaurant_name=recommendation.restaurant.name,
            restaurant_slug=recommendation.restaurant.slug,
            restaurant_location_id=recommendation.restaurant_location_id,
            restaurant_location_name=recommendation.restaurant_location.branch_name,
            menu_item_id=recommendation.id,
            menu_item_name=recommendation.name,
            generated_combo_id=None,
            generated_combo_name=None,
            cuisine_type=recommendation.cuisine_type or recommendation.restaurant.cuisine_type,
            badge="Smart Value",
            title="Affordable comfort meals waiting for you",
            subtitle="Personalized picks that stay closer to your usual spend.",
            cta_label=offer.cta_label or "See Value Picks",
        )

    if offer.offer_type == PersonalizedOfferType.NEW_ITEM_MATCH:
        recommendation = next(
            (
                row
                for row in filtered_recommendations
                if row.is_new
            ),
            None,
        )
        if recommendation is None:
            recommendation = next(
                (
                    row
                    for row in filtered_recommendations
                    if row.recommendation_label in {"Trending Now", "Just Launched", "Matches Your Taste"}
                ),
                filtered_recommendations[0] if filtered_recommendations else None,
            )
        if recommendation is None:
            return None
        spicy_title = (
            preferences is not None
            and preferences.spice_level is not None
            and str(preferences.spice_level).strip().upper() == "HIGH"
        )
        return OfferSelection(
            score=0.84,
            target_type="ITEM",
            target_id=str(recommendation.id),
            restaurant_id=recommendation.restaurant_id,
            restaurant_name=recommendation.restaurant.name,
            restaurant_slug=recommendation.restaurant.slug,
            restaurant_location_id=recommendation.restaurant_location_id,
            restaurant_location_name=recommendation.restaurant_location.branch_name,
            menu_item_id=recommendation.id,
            menu_item_name=recommendation.name,
            generated_combo_id=None,
            generated_combo_name=None,
            cuisine_type=recommendation.cuisine_type or recommendation.restaurant.cuisine_type,
            badge="New Match",
            title="New spicy picks for you" if spicy_title else f"New dishes from {recommendation.restaurant.name}",
            subtitle=(
                "Fresh launches that line up with your bold spice preference."
                if spicy_title
                else f"Recently launched picks from {recommendation.restaurant.name} that match your profile."
            ),
            cta_label=offer.cta_label or "Try Now",
        )

    if offer.offer_type == PersonalizedOfferType.COMBO_AFFINITY:
        combo = _choose_combo_for_offer(db, offer, insights)
        if combo is None:
            return None
        return OfferSelection(
            score=0.8,
            target_type="COMBO",
            target_id=str(combo.id),
            restaurant_id=combo.restaurant_id,
            restaurant_name=combo.restaurant.name,
            restaurant_slug=combo.restaurant.slug,
            restaurant_location_id=combo.restaurant_location_id,
            restaurant_location_name=combo.restaurant_location.branch_name,
            menu_item_id=None,
            menu_item_name=None,
            generated_combo_id=combo.id,
            generated_combo_name=combo.combo_name,
            cuisine_type=combo.restaurant.cuisine_type,
            badge="Combo Pick",
            title="Combos picked based on your cravings",
            subtitle=f"{combo.combo_name} is ready again at {combo.restaurant.name}.",
            cta_label=offer.cta_label or "View Combo",
        )

    return None


def _serialize_card(offer: PersonalizedOffer, selection: OfferSelection) -> PersonalizedOfferCardResponse:
    return PersonalizedOfferCardResponse(
        id=f"{offer.id}:{selection.target_type}:{selection.target_id}",
        offer_id=offer.id,
        offer_name=offer.name,
        offer_type=offer.offer_type,
        audience_type=offer.audience_type,
        badge=selection.badge,
        title=selection.title,
        subtitle=selection.subtitle,
        cta_label=selection.cta_label,
        target_type=selection.target_type,
        restaurant_id=selection.restaurant_id,
        restaurant_name=selection.restaurant_name,
        restaurant_slug=selection.restaurant_slug,
        restaurant_location_id=selection.restaurant_location_id,
        restaurant_location_name=selection.restaurant_location_name,
        offer_restaurant_location_id=offer.restaurant_location_id,
        menu_item_id=selection.menu_item_id,
        menu_item_name=selection.menu_item_name,
        generated_combo_id=selection.generated_combo_id,
        generated_combo_name=selection.generated_combo_name,
        cuisine_type=selection.cuisine_type,
        discount_type=offer.discount_type,
        discount_value=offer.discount_value,
        discount_label=_discount_label(offer),
        max_discount_amount=offer.max_discount_amount,
        minimum_order_amount=offer.minimum_order_amount,
        terms_label=_terms_label(offer),
        valid_for_days=offer.valid_for_days,
        expires_at=offer.expires_at,
        created_at=offer.created_at,
    )


def _serialize_generated_match_card(match: GeneratedOfferUserMatch) -> PersonalizedOfferCardResponse | None:
    generated_offer = match.generated_offer
    if generated_offer is None:
        return None
    restaurant = generated_offer.restaurant
    if restaurant is None or not restaurant.is_active or not restaurant.is_approved:
        return None
    location = generated_offer.restaurant_location
    if location is not None and not location.is_active:
        return None
    menu_item = generated_offer.applicable_item
    if menu_item is not None and not menu_item.is_available:
        return None

    target_type = match.target_type or (
        "ITEM"
        if generated_offer.applicable_item_id is not None
        else "COMBO"
        if generated_offer.generated_combo_id is not None
        else "RESTAURANT"
    )
    target_id = match.target_id or str(
        generated_offer.applicable_item_id
        or generated_offer.generated_combo_id
        or generated_offer.restaurant_location_id
        or generated_offer.restaurant_id
    )
    combo_name = generated_offer.generated_combo.combo_name if generated_offer.generated_combo is not None else None
    combo_id = generated_offer.generated_combo_id

    return PersonalizedOfferCardResponse(
        id=f"{generated_offer.id}:{match.id}:{target_type}:{target_id}",
        generated_offer_id=generated_offer.id,
        generated_offer_user_match_id=match.id,
        offer_id=generated_offer.id,
        offer_name=_generated_offer_name(generated_offer),
        offer_type=generated_offer.offer_type,
        audience_type=generated_offer.audience_type,
        badge=generated_offer.generated_badge or _generated_discount_label(generated_offer) or "Offer",
        title=generated_offer.generated_title,
        subtitle=generated_offer.generated_subtitle,
        cta_label=generated_offer.generated_cta_label or "Explore now",
        target_type=target_type,
        restaurant_id=restaurant.id,
        restaurant_name=restaurant.name,
        restaurant_slug=restaurant.slug,
        restaurant_location_id=generated_offer.restaurant_location_id,
        restaurant_location_name=location.branch_name if location else None,
        offer_restaurant_location_id=generated_offer.restaurant_location_id,
        menu_item_id=generated_offer.applicable_item_id if target_type == "ITEM" else None,
        menu_item_name=menu_item.name if menu_item is not None and target_type == "ITEM" else None,
        generated_combo_id=combo_id,
        generated_combo_name=combo_name,
        cuisine_type=generated_offer.applicable_cuisine or restaurant.cuisine_type,
        discount_type=_generated_offer_discount_type(generated_offer),
        discount_value=_generated_offer_discount_value(generated_offer),
        discount_label=_generated_discount_label(generated_offer),
        max_discount_amount=_generated_offer_max_discount_amount(generated_offer),
        minimum_order_amount=_generated_offer_minimum_order_amount(generated_offer),
        terms_label=_generated_terms_label(generated_offer),
        valid_for_days=_generated_offer_valid_for_days(generated_offer),
        expires_at=generated_offer.expires_at,
        created_at=generated_offer.created_at,
    )


def _load_live_manual_offer_cards_for_user(
    db: Session,
    *,
    user: User,
) -> list[PersonalizedOfferCardResponse]:
    now = datetime.now(UTC)
    latest_order_at = _latest_paid_order_at(db, user.id)
    cards: list[tuple[tuple[int, datetime], PersonalizedOfferCardResponse]] = []
    for offer in _load_active_offers(db):
        if offer.offer_type != PersonalizedOfferType.CUSTOM:
            continue
        if not _offer_is_live(offer, now):
            continue
        if not _offer_targets_user(offer, user):
            continue
        if not _matches_offer_audience(offer, latest_order_at=latest_order_at, now=now):
            continue
        if not _matches_offer_type_eligibility(offer, latest_order_at=latest_order_at):
            continue
        card = _serialize_manual_card(offer)
        if card is None:
            continue
        cards.append((_manual_offer_priority(offer), card))
    cards.sort(key=lambda row: row[0], reverse=True)
    return [card for _, card in cards]


def list_restaurant_offers(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
) -> list[PersonalizedOfferManagementResponse]:
    _ensure_generated_offers_bootstrapped(db, restaurant_id=restaurant_id)
    offers = db.scalars(
        _offer_base_query().where(PersonalizedOffer.restaurant_id == restaurant_id)
    ).all()
    offer_ids = [offer.id for offer in offers]
    counts: dict[uuid.UUID, dict[PersonalizedOfferEventType, int]] = {}
    if offer_ids:
        rows = db.execute(
            select(
                PersonalizedOfferEvent.offer_id,
                PersonalizedOfferEvent.event_type,
                func.count(PersonalizedOfferEvent.id).label("event_count"),
            )
            .where(PersonalizedOfferEvent.offer_id.in_(offer_ids))
            .group_by(PersonalizedOfferEvent.offer_id, PersonalizedOfferEvent.event_type)
        ).all()
        for row in rows:
            counts.setdefault(row.offer_id, {})[row.event_type] = int(row.event_count or 0)

    generated_offers = db.scalars(
        select(GeneratedOffer)
        .options(
            selectinload(GeneratedOffer.template_offer),
            selectinload(GeneratedOffer.restaurant_location),
            selectinload(GeneratedOffer.applicable_item),
            selectinload(GeneratedOffer.generated_combo),
        )
        .where(GeneratedOffer.restaurant_id == restaurant_id)
        .order_by(GeneratedOffer.updated_at.desc(), GeneratedOffer.created_at.desc())
    ).all()
    generated_ids = [offer.id for offer in generated_offers]
    generated_counts: dict[uuid.UUID, tuple[int, int, int, int]] = {}
    if generated_ids:
        rows = db.execute(
            select(
                GeneratedOfferUserMatch.generated_offer_id,
                func.count(GeneratedOfferUserMatch.id).filter(GeneratedOfferUserMatch.is_current.is_(True)).label("eligible_count"),
                func.sum(GeneratedOfferUserMatch.view_count).label("view_count"),
                func.sum(GeneratedOfferUserMatch.click_count).label("click_count"),
                func.sum(GeneratedOfferUserMatch.conversion_count).label("conversion_count"),
            )
            .where(GeneratedOfferUserMatch.generated_offer_id.in_(generated_ids))
            .group_by(GeneratedOfferUserMatch.generated_offer_id)
        ).all()
        for row in rows:
            generated_counts[row.generated_offer_id] = (
                int(row.eligible_count or 0),
                int(row.view_count or 0),
                int(row.click_count or 0),
                int(row.conversion_count or 0),
            )

    now = datetime.now(UTC)
    template_rows = [
        PersonalizedOfferManagementResponse(
            id=offer.id,
            record_kind="TEMPLATE",
            source=PersonalizedOfferSource.MANUAL_TEMPLATE,
            template_offer_id=offer.id,
            template_offer_name=offer.name,
            restaurant_id=offer.restaurant_id,
            restaurant_location_id=offer.restaurant_location_id,
            restaurant_location_name=offer.restaurant_location.branch_name if offer.restaurant_location else None,
            applicable_item_id=offer.applicable_item_id,
            applicable_item_name=offer.applicable_item.name if offer.applicable_item else None,
            generated_combo_id=None,
            generated_combo_name=None,
            name=offer.name,
            offer_type=offer.offer_type,
            audience_type=offer.audience_type,
            state=offer.state,
            effective_state=_effective_state(offer, now),
            discount_type=offer.discount_type,
            discount_value=offer.discount_value,
            max_discount_amount=offer.max_discount_amount,
            minimum_order_amount=offer.minimum_order_amount,
            inactivity_days=offer.inactivity_days,
            cooldown_hours=offer.cooldown_hours,
            valid_for_days=offer.valid_for_days,
            applicable_category=offer.applicable_category,
            applicable_cuisine=offer.applicable_cuisine,
            cta_label=offer.cta_label,
            business_rules=offer.business_rules or {},
            notes=offer.notes,
            starts_at=offer.starts_at,
            expires_at=offer.expires_at,
            generation_reason=None,
            generated_title=None,
            generated_subtitle=None,
            generated_badge=None,
            generated_cta_label=None,
            manually_edited=False,
            edited_by=None,
            edited_at=None,
            eligible_user_count=0,
            view_count=counts.get(offer.id, {}).get(PersonalizedOfferEventType.VIEWED, 0),
            click_count=counts.get(offer.id, {}).get(PersonalizedOfferEventType.CLICKED, 0),
            conversion_count=counts.get(offer.id, {}).get(PersonalizedOfferEventType.CONVERTED, 0),
            editable=True,
            state_mutable=True,
            created_at=offer.created_at,
            updated_at=offer.updated_at,
        )
        for offer in offers
    ]

    generated_rows = [
        PersonalizedOfferManagementResponse(
            id=offer.id,
            record_kind="GENERATED",
            source=offer.source,
            template_offer_id=offer.template_offer_id,
            template_offer_name=offer.template_offer.name if offer.template_offer else None,
            restaurant_id=offer.restaurant_id,
            restaurant_location_id=offer.restaurant_location_id,
            restaurant_location_name=offer.restaurant_location.branch_name if offer.restaurant_location else None,
            applicable_item_id=offer.applicable_item_id,
            applicable_item_name=offer.applicable_item.name if offer.applicable_item else None,
            generated_combo_id=offer.generated_combo_id,
            generated_combo_name=offer.generated_combo.combo_name if offer.generated_combo else None,
            name=offer.generated_title,
            offer_type=offer.offer_type,
            audience_type=offer.audience_type,
            state=offer.state,
            effective_state=offer.state if offer.expires_at is None or offer.expires_at > now else PersonalizedOfferState.EXPIRED,
            discount_type=_generated_offer_discount_type(offer),
            discount_value=_generated_offer_discount_value(offer),
            max_discount_amount=_generated_offer_max_discount_amount(offer),
            minimum_order_amount=_generated_offer_minimum_order_amount(offer),
            inactivity_days=_generated_offer_inactivity_days(offer),
            cooldown_hours=_generated_offer_cooldown_hours(offer),
            valid_for_days=_generated_offer_valid_for_days(offer),
            applicable_category=offer.applicable_category,
            applicable_cuisine=offer.applicable_cuisine,
            cta_label=offer.generated_cta_label,
            business_rules=offer.business_metadata or {},
            notes=None,
            starts_at=offer.starts_at,
            expires_at=offer.expires_at,
            generation_reason=offer.generation_reason,
            generated_title=offer.generated_title,
            generated_subtitle=offer.generated_subtitle,
            generated_badge=offer.generated_badge,
            generated_cta_label=offer.generated_cta_label,
            manually_edited=_generated_offer_manually_edited(offer),
            edited_by=_generated_offer_edited_by(offer),
            edited_at=_generated_offer_edited_at(offer),
            eligible_user_count=generated_counts.get(offer.id, (0, 0, 0, 0))[0],
            view_count=generated_counts.get(offer.id, (0, 0, 0, 0))[1],
            click_count=generated_counts.get(offer.id, (0, 0, 0, 0))[2],
            conversion_count=generated_counts.get(offer.id, (0, 0, 0, 0))[3],
            editable=True,
            state_mutable=True,
            created_at=offer.created_at,
            updated_at=offer.updated_at,
        )
        for offer in generated_offers
        if not _is_legacy_custom_template_generated_offer(offer)
    ]

    return sorted(
        [*template_rows, *generated_rows],
        key=lambda row: (row.created_at, row.updated_at),
        reverse=True,
    )


def _upsert_offer_fields(
    offer: PersonalizedOffer,
    payload: PersonalizedOfferUpsertRequest,
) -> PersonalizedOffer:
    offer.name = payload.name.strip()
    offer.offer_type = payload.offer_type
    offer.audience_type = payload.audience_type
    offer.state = payload.state
    offer.restaurant_location_id = payload.restaurant_location_id
    offer.applicable_item_id = payload.applicable_item_id
    offer.applicable_category = payload.applicable_category.strip() if payload.applicable_category else None
    offer.applicable_cuisine = payload.applicable_cuisine.strip() if payload.applicable_cuisine else None
    offer.discount_type = payload.discount_type
    offer.discount_value = _quantize(payload.discount_value)
    offer.max_discount_amount = _quantize(payload.max_discount_amount) if payload.max_discount_amount is not None else None
    offer.minimum_order_amount = _quantize(payload.minimum_order_amount)
    offer.inactivity_days = payload.inactivity_days
    offer.cooldown_hours = payload.cooldown_hours
    offer.valid_for_days = payload.valid_for_days
    offer.cta_label = payload.cta_label.strip() if payload.cta_label else None
    offer.business_rules = dict(payload.business_rules)
    offer.notes = payload.notes
    offer.starts_at = payload.starts_at
    offer.expires_at = payload.expires_at
    return offer


def create_restaurant_offer(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    payload: PersonalizedOfferUpsertRequest,
) -> PersonalizedOffer:
    offer = PersonalizedOffer(restaurant_id=restaurant_id)
    _upsert_offer_fields(offer, payload)
    db.add(offer)
    db.commit()
    db.refresh(offer)
    rebuild_generated_offers(db, restaurant_id=restaurant_id)
    db.commit()
    invalidate_all_personalized_offer_caches()
    return offer


def update_restaurant_offer(
    db: Session,
    *,
    offer: PersonalizedOffer,
    payload: PersonalizedOfferUpsertRequest,
) -> PersonalizedOffer:
    _upsert_offer_fields(offer, payload)
    db.add(offer)
    db.commit()
    db.refresh(offer)
    rebuild_generated_offers(db, restaurant_id=offer.restaurant_id)
    db.commit()
    invalidate_all_personalized_offer_caches()
    return offer


def _detach_generated_offers_from_template(
    db: Session,
    *,
    offer: PersonalizedOffer,
    reason: str,
) -> None:
    linked_generated_offers = db.scalars(
        select(GeneratedOffer).where(GeneratedOffer.template_offer_id == offer.id)
    ).all()
    if not linked_generated_offers:
        return

    detached_at = datetime.now(UTC).isoformat()
    for generated_offer in linked_generated_offers:
        metadata = dict(generated_offer.business_metadata or {})
        provenance = metadata.get("template_provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        provenance.update(
            {
                "source_template_offer_id": provenance.get("source_template_offer_id") or str(offer.id),
                "source_template_offer_name": provenance.get("source_template_offer_name") or offer.name,
                "detached_at": detached_at,
                "detached_reason": reason,
            }
        )
        metadata["template_provenance"] = provenance
        metadata.setdefault("template_business_rules", dict(offer.business_rules or {}))
        generated_offer.business_metadata = metadata
        generated_offer.template_offer_id = None
        db.add(generated_offer)


def delete_restaurant_offer(
    db: Session,
    *,
    offer: PersonalizedOffer,
) -> None:
    restaurant_id = offer.restaurant_id
    _detach_generated_offers_from_template(
        db,
        offer=offer,
        reason="template_deleted_by_admin",
    )
    db.delete(offer)
    db.commit()
    rebuild_generated_offers(db, restaurant_id=restaurant_id)
    db.commit()
    invalidate_all_personalized_offer_caches()


def get_generated_offer_for_restaurant(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    generated_offer_id: uuid.UUID,
) -> GeneratedOffer | None:
    return db.scalar(
        select(GeneratedOffer).where(
            GeneratedOffer.id == generated_offer_id,
            GeneratedOffer.restaurant_id == restaurant_id,
        )
    )


def update_generated_offer(
    db: Session,
    *,
    generated_offer: GeneratedOffer,
    payload: GeneratedOfferUpdateRequest,
    edited_by_user: User,
) -> GeneratedOffer:
    if payload.state is not None and payload.state not in {
        PersonalizedOfferState.ACTIVE,
        PersonalizedOfferState.PAUSED,
        PersonalizedOfferState.DISABLED,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Generated offers can only be set to Active, Paused, or Disabled",
        )

    original_snapshot = {
        "title": generated_offer.generated_title,
        "subtitle": generated_offer.generated_subtitle,
        "badge": generated_offer.generated_badge,
        "cta_label": generated_offer.generated_cta_label,
        "starts_at": generated_offer.starts_at.isoformat() if generated_offer.starts_at else None,
        "expires_at": generated_offer.expires_at.isoformat() if generated_offer.expires_at else None,
        "state": generated_offer.state.value,
    }

    if payload.title is not None:
        generated_offer.generated_title = payload.title.strip()
    if payload.subtitle is not None:
        generated_offer.generated_subtitle = payload.subtitle.strip()
    if payload.badge is not None:
        generated_offer.generated_badge = payload.badge.strip() or None
    if payload.cta_label is not None:
        generated_offer.generated_cta_label = payload.cta_label.strip() or None
    if "starts_at" in payload.model_fields_set:
        generated_offer.starts_at = payload.starts_at
    if "expires_at" in payload.model_fields_set:
        generated_offer.expires_at = payload.expires_at
    if payload.state is not None:
        generated_offer.state = payload.state

    metadata = dict(generated_offer.business_metadata or {})
    metadata.setdefault("original_generated_offer_snapshot", original_snapshot)
    metadata["manual_override"] = {
        "title": generated_offer.generated_title,
        "subtitle": generated_offer.generated_subtitle,
        "badge": generated_offer.generated_badge,
        "cta_label": generated_offer.generated_cta_label,
        "starts_at": generated_offer.starts_at.isoformat() if generated_offer.starts_at else None,
        "expires_at": generated_offer.expires_at.isoformat() if generated_offer.expires_at else None,
        "state": generated_offer.state.value,
    }
    metadata["manually_edited"] = True
    metadata["edited_by"] = edited_by_user.email
    metadata["edited_by_user_id"] = str(edited_by_user.id)
    metadata["edited_at"] = datetime.now(UTC).isoformat()
    generated_offer.business_metadata = metadata
    db.add(generated_offer)
    db.commit()
    db.refresh(generated_offer)
    invalidate_all_personalized_offer_caches()
    return generated_offer


def delete_generated_offer(
    db: Session,
    *,
    generated_offer: GeneratedOffer,
) -> None:
    db.delete(generated_offer)
    db.commit()
    invalidate_all_personalized_offer_caches()


def list_generated_offer_user_matches(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    generated_offer_id: uuid.UUID,
) -> list[GeneratedOfferUserMatchResponse]:
    generated_offer = get_generated_offer_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        generated_offer_id=generated_offer_id,
    )
    if generated_offer is None:
        return []
    rows = db.scalars(
        select(GeneratedOfferUserMatch)
        .options(selectinload(GeneratedOfferUserMatch.user))
        .where(GeneratedOfferUserMatch.generated_offer_id == generated_offer_id)
        .order_by(
            GeneratedOfferUserMatch.is_current.desc(),
            GeneratedOfferUserMatch.rank.asc(),
            GeneratedOfferUserMatch.score.desc(),
            GeneratedOfferUserMatch.created_at.desc(),
        )
    ).all()
    return [
        GeneratedOfferUserMatchResponse(
            id=row.id,
            generated_offer_id=row.generated_offer_id,
            user_id=row.user_id,
            user_name=row.user.full_name,
            user_email=row.user.email,
            matched_reason=row.matched_reason,
            score=row.score,
            rank=row.rank,
            is_current=row.is_current,
            target_type=row.target_type,
            target_id=row.target_id,
            view_count=row.view_count,
            click_count=row.click_count,
            conversion_count=row.conversion_count,
            viewed_at=row.viewed_at,
            clicked_at=row.clicked_at,
            converted_at=row.converted_at,
            match_metadata=row.match_metadata or {},
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


def _load_active_offers(db: Session) -> list[PersonalizedOffer]:
    now = datetime.now(UTC)
    return db.scalars(
        _offer_base_query().join(Restaurant, PersonalizedOffer.restaurant_id == Restaurant.id)
        .outerjoin(RestaurantLocation, PersonalizedOffer.restaurant_location_id == RestaurantLocation.id)
        .where(
            PersonalizedOffer.state == PersonalizedOfferState.ACTIVE,
            or_(PersonalizedOffer.starts_at.is_(None), PersonalizedOffer.starts_at <= now),
            or_(PersonalizedOffer.expires_at.is_(None), PersonalizedOffer.expires_at > now),
            Restaurant.is_active.is_(True),
            Restaurant.is_approved.is_(True),
            or_(
                PersonalizedOffer.restaurant_location_id.is_(None),
                RestaurantLocation.is_active.is_(True),
            ),
        )
    ).all()


def _manual_offer_matches_menu_item_context(
    offer: PersonalizedOffer,
    *,
    menu_item: MenuItem,
    restaurant_id: uuid.UUID,
    restaurant_location_id: uuid.UUID | None,
) -> bool:
    if offer.offer_type != PersonalizedOfferType.CUSTOM:
        return False
    if not _offer_matches_scope(
        offer,
        restaurant_id=restaurant_id,
        location_id=restaurant_location_id,
    ):
        return False
    return _offer_matches_cart_targets(offer, [menu_item])


def get_personalized_offers_for_user(
    db: Session,
    user: User,
    *,
    limit: int | None = None,
    restaurant_id: uuid.UUID | None = None,
) -> list[PersonalizedOfferCardResponse]:
    cache_key = _cache_key(user.id, restaurant_id)
    cached_cards = _deserialize_cards(cache_get_json(cache_key))
    if cached_cards:
        logger.info(
            "Personalized offers cache hit user_id=%s offer_count=%d limit=%s",
            user.id,
            len(cached_cards),
            limit,
        )
        return cached_cards
    if cached_cards == []:
        _ensure_generated_offers_bootstrapped(db)

    effective_limit = max(limit or settings.personalized_offer_max_cards, 1)
    _ensure_generated_offers_bootstrapped(db)
    # Scoped before the limit is applied, so a scoped app still gets a full
    # page of its own offers rather than the leftovers of a mixed page.
    manual_cards = _scope_offer_cards(
        _load_live_manual_offer_cards_for_user(db, user=user),
        restaurant_id,
    )
    matches = _sync_generated_offer_matches_for_user(db, user=user)
    cards = manual_cards[:effective_limit]
    for match in matches:
        if len(cards) >= effective_limit:
            break
        card = _serialize_generated_match_card(match)
        if card is None:
            continue
        if restaurant_id is not None and card.restaurant_id != restaurant_id:
            continue
        cards.append(card)
    logger.info(
        "Personalized offers generated feed user_id=%s match_count=%d card_count=%d limit=%d",
        user.id,
        len(matches),
        len(cards),
        effective_limit,
    )
    cache_set_json(cache_key, _serialize_cards(cards), ttl_seconds=settings.personalized_offer_cache_ttl_seconds)
    return cards


def _generated_offer_matches_menu_item_context(
    match: GeneratedOfferUserMatch,
    *,
    menu_item: MenuItem,
    restaurant_id: uuid.UUID,
    restaurant_location_id: uuid.UUID | None,
) -> tuple[int, Decimal] | None:
    generated_offer = match.generated_offer
    if generated_offer is None:
        return None
    if not match.is_current or not _generated_offer_is_live(generated_offer):
        return None
    if not _matches_generated_offer_scope(
        generated_offer,
        restaurant_id=restaurant_id,
        location_id=restaurant_location_id,
    ):
        return None

    if generated_offer.applicable_item_id is not None:
        if generated_offer.applicable_item_id != menu_item.id:
            return None
        return (0, match.score)

    if generated_offer.applicable_category:
        if _normalize_text(menu_item.category) != _normalize_text(generated_offer.applicable_category):
            return None
        return (1, match.score)

    if generated_offer.applicable_cuisine:
        item_cuisine = _normalize_text(menu_item.cuisine_type)
        restaurant_cuisine = _normalize_text(menu_item.restaurant.cuisine_type)
        target_cuisine = _normalize_text(generated_offer.applicable_cuisine)
        if item_cuisine != target_cuisine and restaurant_cuisine != target_cuisine:
            return None
        return (2, match.score)

    if generated_offer.restaurant_location_id is not None:
        return (3, match.score)

    return (4, match.score)


def _rank_context_matches_for_menu_item(
    matches: list[GeneratedOfferUserMatch],
    *,
    menu_item: MenuItem,
    restaurant_id: uuid.UUID,
    restaurant_location_id: uuid.UUID | None,
) -> list[GeneratedOfferUserMatch]:
    ranked_matches: list[tuple[int, int, Decimal, GeneratedOfferUserMatch]] = []
    for match in matches:
        context_rank = _generated_offer_matches_menu_item_context(
            match,
            menu_item=menu_item,
            restaurant_id=restaurant_id,
            restaurant_location_id=restaurant_location_id,
        )
        if context_rank is None:
            continue
        priority, score = context_rank
        ranked_matches.append((priority, match.rank, score, match))
    ranked_matches.sort(key=lambda row: (row[0], row[1], -row[2]))
    return [match for _, _, _, match in ranked_matches]


def get_best_personalized_offer_for_context(
    db: Session,
    *,
    user: User,
    payload: PersonalizedOfferContextRequest,
) -> PersonalizedOfferCardResponse | None:
    cards = get_personalized_offers_for_context(db, user=user, payload=payload)
    return cards[0] if cards else None


def get_personalized_offers_for_context(
    db: Session,
    *,
    user: User,
    payload: PersonalizedOfferContextRequest,
    limit: int | None = None,
) -> list[PersonalizedOfferCardResponse]:
    menu_item = db.scalar(
        select(MenuItem)
        .options(selectinload(MenuItem.restaurant))
        .where(
            MenuItem.id == payload.menu_item_id,
            MenuItem.restaurant_id == payload.restaurant_id,
            MenuItem.is_available.is_(True),
        )
    )
    if menu_item is None:
        return []
    if (
        payload.restaurant_location_id is not None
        and menu_item.restaurant_location_id != payload.restaurant_location_id
    ):
        return []

    _ensure_generated_offers_bootstrapped(db, restaurant_id=payload.restaurant_id)
    matches = _sync_generated_offer_matches_for_user(db, user=user)
    effective_limit = max(limit or settings.personalized_offer_max_cards, 1)
    latest_order_at = _latest_paid_order_at(db, user.id)
    now = datetime.now(UTC)

    cards: list[PersonalizedOfferCardResponse] = []
    manual_candidates: list[tuple[tuple[int, datetime], PersonalizedOfferCardResponse]] = []
    for offer in _load_active_offers(db):
        if offer.offer_type != PersonalizedOfferType.CUSTOM:
            continue
        if not _offer_is_live(offer, now):
            continue
        if not _offer_targets_user(offer, user):
            continue
        if not _matches_offer_audience(offer, latest_order_at=latest_order_at, now=now):
            continue
        if not _matches_offer_type_eligibility(offer, latest_order_at=latest_order_at):
            continue
        if not _manual_offer_matches_menu_item_context(
            offer,
            menu_item=menu_item,
            restaurant_id=payload.restaurant_id,
            restaurant_location_id=payload.restaurant_location_id,
        ):
            continue
        card = _serialize_manual_card(offer)
        if card is None:
            continue
        manual_candidates.append((_manual_offer_priority(offer), card))
    manual_candidates.sort(key=lambda row: row[0], reverse=True)
    for _, card in manual_candidates:
        cards.append(card)
        if len(cards) >= effective_limit:
            return cards

    for match in _rank_context_matches_for_menu_item(
        matches,
        menu_item=menu_item,
        restaurant_id=payload.restaurant_id,
        restaurant_location_id=payload.restaurant_location_id,
    ):
        card = _serialize_generated_match_card(match)
        if card is not None:
            cards.append(card)
        if len(cards) >= effective_limit:
            break
    return cards


def get_personalized_offer_item_availability(
    db: Session,
    *,
    user: User,
    payload: PersonalizedOfferItemAvailabilityRequest,
) -> list[PersonalizedOfferItemAvailabilityResponse]:
    requested_ids = list(dict.fromkeys(payload.menu_item_ids))
    if not requested_ids:
        return []

    menu_items = list(
        db.scalars(
            select(MenuItem)
            .options(selectinload(MenuItem.restaurant))
            .where(
                MenuItem.id.in_(requested_ids),
                MenuItem.restaurant_id == payload.restaurant_id,
                MenuItem.is_available.is_(True),
            )
        )
    )
    if payload.restaurant_location_id is not None:
        menu_items = [
            item
            for item in menu_items
            if item.restaurant_location_id == payload.restaurant_location_id
        ]

    indexed_items = {item.id: item for item in menu_items}
    _ensure_generated_offers_bootstrapped(db, restaurant_id=payload.restaurant_id)
    matches = _sync_generated_offer_matches_for_user(db, user=user)
    latest_order_at = _latest_paid_order_at(db, user.id)
    now = datetime.now(UTC)
    manual_offers = [
        offer
        for offer in _load_active_offers(db)
        if offer.offer_type == PersonalizedOfferType.CUSTOM
        and _offer_is_live(offer, now)
        and _offer_targets_user(offer, user)
        and _matches_offer_audience(offer, latest_order_at=latest_order_at, now=now)
        and _matches_offer_type_eligibility(offer, latest_order_at=latest_order_at)
    ]

    responses: list[PersonalizedOfferItemAvailabilityResponse] = []
    for menu_item_id in requested_ids:
        menu_item = indexed_items.get(menu_item_id)
        if menu_item is None:
            responses.append(
                PersonalizedOfferItemAvailabilityResponse(
                    menu_item_id=menu_item_id,
                    has_offer=False,
                    offer_count=0,
                )
            )
            continue

        ranked_matches = _rank_context_matches_for_menu_item(
            matches,
            menu_item=menu_item,
            restaurant_id=payload.restaurant_id,
            restaurant_location_id=payload.restaurant_location_id,
        )
        offer_count = 0
        for offer in manual_offers:
            if _manual_offer_matches_menu_item_context(
                offer,
                menu_item=menu_item,
                restaurant_id=payload.restaurant_id,
                restaurant_location_id=payload.restaurant_location_id,
            ):
                offer_count += 1
                if offer_count >= settings.personalized_offer_max_cards:
                    break
        for match in ranked_matches:
            if offer_count >= settings.personalized_offer_max_cards:
                break
            if _serialize_generated_match_card(match) is not None:
                offer_count += 1

        responses.append(
            PersonalizedOfferItemAvailabilityResponse(
                menu_item_id=menu_item_id,
                has_offer=offer_count > 0,
                offer_count=offer_count,
            )
        )

    return responses


def record_personalized_offer_events(
    db: Session,
    *,
    user: User,
    payload: PersonalizedOfferEventBatchRequest,
    restaurant_id: uuid.UUID | None = None,
) -> PersonalizedOfferEventBatchResponse:
    offer_ids = [event.offer_id for event in payload.events]
    offers = {
        offer.id: offer
        for offer in db.scalars(
            select(PersonalizedOffer).where(PersonalizedOffer.id.in_(offer_ids))
        ).all()
    }

    recorded_count = 0
    for event in payload.events:
        offer = offers.get(event.offer_id)
        if offer is None:
            generated_offer = db.get(GeneratedOffer, event.generated_offer_id) if event.generated_offer_id else None
            if generated_offer is None:
                continue
        else:
            generated_offer = db.get(GeneratedOffer, event.generated_offer_id) if event.generated_offer_id else None

        # A scoped app never receives another restaurant's offers, so an event
        # naming one is dropped rather than polluting that restaurant's
        # analytics. Skipped instead of failing the batch, which would lose the
        # legitimate events sent alongside it.
        if restaurant_id is not None:
            event_restaurant_id = (
                offer.restaurant_id if offer is not None else generated_offer.restaurant_id
            )
            if event_restaurant_id != restaurant_id:
                logger.warning(
                    "Dropped out-of-scope offer event user_id=%s offer_id=%s event_restaurant_id=%s scope=%s",
                    user.id,
                    event.offer_id,
                    event_restaurant_id,
                    restaurant_id,
                )
                continue
        match = db.get(GeneratedOfferUserMatch, event.generated_offer_user_match_id) if event.generated_offer_user_match_id else None
        db.add(
            PersonalizedOfferEvent(
                offer_id=offer.id if offer is not None else None,
                user_id=user.id,
                event_type=event.event_type,
                target_type=event.target_type,
                target_id=event.target_id,
                event_metadata={},
                generated_offer_id=generated_offer.id if generated_offer is not None else None,
                generated_offer_user_match_id=match.id if match is not None else None,
            )
        )
        if generated_offer is not None:
            if event.event_type == PersonalizedOfferEventType.VIEWED:
                generated_offer.view_count += 1
            elif event.event_type == PersonalizedOfferEventType.CLICKED:
                generated_offer.click_count += 1
            elif event.event_type == PersonalizedOfferEventType.CONVERTED:
                generated_offer.conversion_count += 1
            db.add(generated_offer)
        if match is not None:
            if event.event_type == PersonalizedOfferEventType.VIEWED:
                match.view_count += 1
                match.viewed_at = datetime.now(UTC)
            elif event.event_type == PersonalizedOfferEventType.CLICKED:
                match.click_count += 1
                match.clicked_at = datetime.now(UTC)
            elif event.event_type == PersonalizedOfferEventType.CONVERTED:
                match.conversion_count += 1
                match.converted_at = datetime.now(UTC)
            db.add(match)
        recorded_count += 1

    db.commit()
    return PersonalizedOfferEventBatchResponse(recorded_count=recorded_count)


def _offer_matches_cart_targets(offer: PersonalizedOffer, menu_items: Iterable[MenuItem]) -> bool:
    items = list(menu_items)
    if offer.applicable_item_id is not None and not any(item.id == offer.applicable_item_id for item in items):
        return False
    if offer.applicable_category and not any(
        _normalize_text(item.category) == _normalize_text(offer.applicable_category)
        for item in items
    ):
        return False
    if offer.applicable_cuisine and not any(
        _normalize_text(item.cuisine_type) == _normalize_text(offer.applicable_cuisine)
        or _normalize_text(item.restaurant.cuisine_type) == _normalize_text(offer.applicable_cuisine)
        for item in items
    ):
        return False
    return True


def _generated_offer_matches_cart_targets(offer: GeneratedOffer, menu_items: Iterable[MenuItem]) -> bool:
    items = list(menu_items)
    if offer.applicable_item_id is not None and not any(item.id == offer.applicable_item_id for item in items):
        return False
    if offer.applicable_category and not any(
        _normalize_text(item.category) == _normalize_text(offer.applicable_category)
        for item in items
    ):
        return False
    if offer.applicable_cuisine and not any(
        _normalize_text(item.cuisine_type) == _normalize_text(offer.applicable_cuisine)
        or _normalize_text(item.restaurant.cuisine_type) == _normalize_text(offer.applicable_cuisine)
        for item in items
    ):
        return False
    return True


def _compute_discount_amount(
    offer: PersonalizedOffer,
    subtotal: Decimal,
    *,
    delivery_fee: Decimal = Decimal("0.00"),
) -> Decimal:
    if offer.discount_type == PersonalizedOfferDiscountType.NONE:
        return Decimal("0.00")
    if offer.discount_type == PersonalizedOfferDiscountType.FREE_DELIVERY:
        return _quantize(max(delivery_fee, Decimal("0.00")))
    if offer.discount_type == PersonalizedOfferDiscountType.FLAT:
        return min(_quantize(offer.discount_value), subtotal)

    discount = _quantize(subtotal * (offer.discount_value / Decimal("100")))
    if offer.max_discount_amount is not None and offer.max_discount_amount > 0:
        discount = min(discount, _quantize(offer.max_discount_amount))
    return min(discount, subtotal)


def _compute_generated_offer_discount_amount(
    offer: GeneratedOffer,
    subtotal: Decimal,
    *,
    delivery_fee: Decimal = Decimal("0.00"),
) -> Decimal:
    discount_type = _generated_offer_discount_type(offer)
    discount_value = _generated_offer_discount_value(offer)
    max_discount_amount = _generated_offer_max_discount_amount(offer)
    if discount_type == PersonalizedOfferDiscountType.NONE:
        return Decimal("0.00")
    if discount_type == PersonalizedOfferDiscountType.FREE_DELIVERY:
        return _quantize(max(delivery_fee, Decimal("0.00")))
    if discount_type == PersonalizedOfferDiscountType.FLAT:
        return min(_quantize(discount_value), subtotal)

    discount = _quantize(subtotal * (discount_value / Decimal("100")))
    if max_discount_amount is not None and max_discount_amount > 0:
        discount = min(discount, _quantize(max_discount_amount))
    return min(discount, subtotal)


def validate_offer_for_order(
    db: Session,
    *,
    user: User,
    offer_id: uuid.UUID,
    restaurant_id: uuid.UUID,
    restaurant_location_id: uuid.UUID,
    menu_items: Iterable[MenuItem],
    subtotal: Decimal,
    delivery_fee: Decimal = Decimal("0.00"),
) -> tuple[PersonalizedOffer, Decimal]:
    offer = db.scalar(
        _offer_base_query()
        .join(Restaurant, PersonalizedOffer.restaurant_id == Restaurant.id)
        .where(PersonalizedOffer.id == offer_id, Restaurant.is_active.is_(True), Restaurant.is_approved.is_(True))
    )
    if offer is None or not _offer_is_live(offer):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This offer is no longer available")
    if not _is_supported_manual_offer(offer):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This offer is not part of the live manual campaign flow")
    if not _offer_targets_user(offer, user):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This offer is not available")
    if not _offer_matches_scope(offer, restaurant_id=restaurant_id, location_id=restaurant_location_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This offer is not valid for the current restaurant")

    latest_order_at = _latest_paid_order_at(db, user.id)
    if offer.offer_type == PersonalizedOfferType.WELCOME_FIRST_ORDER and latest_order_at is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This welcome offer is only available on your first paid order")
    if offer.minimum_order_amount > 0 and subtotal < offer.minimum_order_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Minimum order amount for this offer is Rs {offer.minimum_order_amount:.0f}",
        )
    if not _offer_matches_cart_targets(offer, menu_items):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This offer does not apply to the current cart")

    return offer, _compute_discount_amount(offer, subtotal, delivery_fee=delivery_fee)


def validate_generated_offer_for_order(
    db: Session,
    *,
    user: User,
    generated_offer_id: uuid.UUID,
    restaurant_id: uuid.UUID,
    restaurant_location_id: uuid.UUID,
    menu_items: Iterable[MenuItem],
    subtotal: Decimal,
    delivery_fee: Decimal = Decimal("0.00"),
    generated_offer_user_match_id: uuid.UUID | None = None,
) -> tuple[GeneratedOffer, Decimal]:
    generated_offer = db.scalar(
        select(GeneratedOffer)
        .options(
            selectinload(GeneratedOffer.template_offer),
            selectinload(GeneratedOffer.restaurant),
            selectinload(GeneratedOffer.restaurant_location),
            selectinload(GeneratedOffer.applicable_item),
        )
        .join(Restaurant, GeneratedOffer.restaurant_id == Restaurant.id)
        .where(
            GeneratedOffer.id == generated_offer_id,
            Restaurant.is_active.is_(True),
            Restaurant.is_approved.is_(True),
        )
    )
    if generated_offer is None or not _generated_offer_is_live(generated_offer):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This offer is no longer available")
    if generated_offer.generated_for_user_id is not None and generated_offer.generated_for_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This offer is not available")
    if not _matches_generated_offer_scope(
        generated_offer,
        restaurant_id=restaurant_id,
        location_id=restaurant_location_id,
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This offer is not valid for the current restaurant")

    match: GeneratedOfferUserMatch | None = None
    if generated_offer_user_match_id is not None:
        match = db.get(GeneratedOfferUserMatch, generated_offer_user_match_id)
        if (
            match is None
            or match.generated_offer_id != generated_offer.id
            or match.user_id != user.id
            or not match.is_current
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This personalized offer match is no longer valid")
    elif generated_offer.generated_for_user_id is None:
        match = db.scalar(
            select(GeneratedOfferUserMatch).where(
                GeneratedOfferUserMatch.generated_offer_id == generated_offer.id,
                GeneratedOfferUserMatch.user_id == user.id,
                GeneratedOfferUserMatch.is_current.is_(True),
            )
        )
        if match is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This offer is not available")

    latest_order_at = _latest_paid_order_at(db, user.id)
    if not _matches_generated_offer_audience(generated_offer, latest_order_at=latest_order_at, now=datetime.now(UTC)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This offer is not available")
    if not _matches_generated_offer_type_eligibility(generated_offer, latest_order_at=latest_order_at):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This welcome offer is only available on your first paid order")

    minimum_order_amount = _generated_offer_minimum_order_amount(generated_offer)
    if minimum_order_amount > 0 and subtotal < minimum_order_amount:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Minimum order amount for this offer is Rs {minimum_order_amount:.0f}",
        )
    if not _generated_offer_matches_cart_targets(generated_offer, menu_items):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This offer does not apply to the current cart")

    return generated_offer, _compute_generated_offer_discount_amount(
        generated_offer,
        subtotal,
        delivery_fee=delivery_fee,
    )


def _load_cart_preview_menu_items(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    restaurant_location_id: uuid.UUID,
    cart_items: list,
) -> tuple[list[MenuItem], Decimal]:
    found = fetch_menu_items_for_customized_order(
        db,
        restaurant_id=restaurant_id,
        restaurant_location_id=restaurant_location_id,
        menu_item_ids=[item.menu_item_id for item in cart_items],
    )

    subtotal = Decimal("0.00")
    resolved_items: list[MenuItem] = []
    for cart_item in cart_items:
        menu_item = found[cart_item.menu_item_id]
        resolved_selection = resolve_menu_item_selection(
            menu_item,
            menu_item_size_id=getattr(cart_item, "menu_item_size_id", None),
            selected_options=[
                SelectedCustomizationOptionInput(
                    option_id=selected_option.option_id,
                    quantity=selected_option.quantity,
                )
                for selected_option in getattr(cart_item, "selected_options", [])
            ],
        )
        subtotal += _quantize(resolved_selection.unit_price * cart_item.quantity)
        resolved_items.append(menu_item)

    return resolved_items, _quantize(subtotal)


def preview_personalized_offer_for_user(
    db: Session,
    *,
    user: User,
    payload: PersonalizedOfferPreviewRequest,
) -> PersonalizedOfferPreviewResponse:
    if payload.generated_offer_id is not None:
        generated_offer = db.scalar(
            select(GeneratedOffer)
            .options(
                selectinload(GeneratedOffer.template_offer),
                selectinload(GeneratedOffer.restaurant),
                selectinload(GeneratedOffer.restaurant_location),
                selectinload(GeneratedOffer.applicable_item),
            )
            .join(Restaurant, GeneratedOffer.restaurant_id == Restaurant.id)
            .where(
                GeneratedOffer.id == payload.generated_offer_id,
                Restaurant.is_active.is_(True),
                Restaurant.is_approved.is_(True),
            )
        )
        if generated_offer is None:
            return PersonalizedOfferPreviewResponse(
                offer_id=payload.offer_id,
                eligible=False,
                message="This offer was not found",
            )

        preview = PersonalizedOfferPreviewResponse(
            offer_id=payload.offer_id,
            eligible=False,
            offer_name=_generated_offer_name(generated_offer),
            offer_title=generated_offer.generated_title,
            offer_restaurant_location_id=generated_offer.restaurant_location_id,
            discount_type=_generated_offer_discount_type(generated_offer),
            discount_value=_generated_offer_discount_value(generated_offer),
            discount_amount=Decimal("0.00"),
            discount_label=_generated_discount_label(generated_offer),
            max_discount_amount=_generated_offer_max_discount_amount(generated_offer),
            minimum_order_amount=_generated_offer_minimum_order_amount(generated_offer),
            subtotal=Decimal("0.00"),
            amount_to_unlock=Decimal("0.00"),
            message=None,
        )

        if payload.restaurant_location_id is None:
            preview.message = "Select a branch to validate this offer"
            return preview

        try:
            menu_items, subtotal = _load_cart_preview_menu_items(
                db,
                restaurant_id=payload.restaurant_id,
                restaurant_location_id=payload.restaurant_location_id,
                cart_items=payload.items,
            )
            preview.subtotal = subtotal
            location = db.scalar(
                select(RestaurantLocation).where(
                    RestaurantLocation.id == payload.restaurant_location_id,
                    RestaurantLocation.restaurant_id == payload.restaurant_id,
                )
            )
            delivery_fee = Decimal("0.00")
            if (
                payload.fulfillment_type == OrderFulfillmentType.DELIVERY
                and location is not None
            ):
                delivery_fee = _quantize(location.delivery_fee)
            minimum_order_amount = _generated_offer_minimum_order_amount(
                generated_offer
            )
            if minimum_order_amount > 0 and subtotal < minimum_order_amount:
                amount_to_unlock = _quantize(minimum_order_amount - subtotal)
                preview.amount_to_unlock = amount_to_unlock
                preview.message = (
                    f"Add Rs {amount_to_unlock:.0f} more to unlock this offer"
                )
                return preview
            _, discount_amount = validate_generated_offer_for_order(
                db,
                user=user,
                generated_offer_id=generated_offer.id,
                generated_offer_user_match_id=payload.generated_offer_user_match_id,
                restaurant_id=payload.restaurant_id,
                restaurant_location_id=payload.restaurant_location_id,
                menu_items=menu_items,
                subtotal=subtotal,
                delivery_fee=delivery_fee,
            )
            preview.eligible = True
            preview.discount_amount = _quantize(discount_amount)
            if preview.discount_amount > 0:
                preview.message = "Discount applied"
            elif _generated_offer_discount_type(
                generated_offer
            ) == PersonalizedOfferDiscountType.NONE:
                preview.message = "Offer active"
            else:
                preview.message = "Offer eligible"
            return preview
        except HTTPException as error:
            preview.message = str(error.detail)
            return preview

    offer = db.scalar(
        _offer_base_query().where(PersonalizedOffer.id == payload.offer_id)
    )
    if offer is None:
        return PersonalizedOfferPreviewResponse(
            offer_id=payload.offer_id,
            eligible=False,
            message="This offer was not found",
        )
    if not _is_supported_manual_offer(offer):
        return PersonalizedOfferPreviewResponse(
            offer_id=offer.id,
            eligible=False,
            offer_name=offer.name,
            offer_title=None,
            offer_restaurant_location_id=offer.restaurant_location_id,
            discount_type=offer.discount_type,
            discount_value=_quantize(offer.discount_value),
            discount_amount=Decimal("0.00"),
            discount_label=_discount_label(offer),
            max_discount_amount=_quantize(offer.max_discount_amount) if offer.max_discount_amount is not None else None,
            minimum_order_amount=_quantize(offer.minimum_order_amount),
            subtotal=Decimal("0.00"),
            amount_to_unlock=Decimal("0.00"),
            message="This legacy offer is not part of the live manual campaign flow",
        )

    preview = PersonalizedOfferPreviewResponse(
        offer_id=offer.id,
        eligible=False,
        offer_name=offer.name,
        offer_title=None,
        offer_restaurant_location_id=offer.restaurant_location_id,
        discount_type=offer.discount_type,
        discount_value=_quantize(offer.discount_value),
        discount_amount=Decimal("0.00"),
        discount_label=_discount_label(offer),
        max_discount_amount=_quantize(offer.max_discount_amount) if offer.max_discount_amount is not None else None,
        minimum_order_amount=_quantize(offer.minimum_order_amount),
        subtotal=Decimal("0.00"),
        amount_to_unlock=Decimal("0.00"),
        message=None,
    )

    if payload.restaurant_location_id is None:
        preview.message = "Select a branch to validate this offer"
        return preview

    try:
        menu_items, subtotal = _load_cart_preview_menu_items(
            db,
            restaurant_id=payload.restaurant_id,
            restaurant_location_id=payload.restaurant_location_id,
            cart_items=payload.items,
        )
        preview.subtotal = subtotal
        location = db.scalar(
            select(RestaurantLocation).where(
                RestaurantLocation.id == payload.restaurant_location_id,
                RestaurantLocation.restaurant_id == payload.restaurant_id,
            )
        )
        delivery_fee = Decimal("0.00")
        if payload.fulfillment_type == OrderFulfillmentType.DELIVERY and location is not None:
            delivery_fee = _quantize(location.delivery_fee)
        if offer.minimum_order_amount > 0 and subtotal < offer.minimum_order_amount:
            amount_to_unlock = _quantize(offer.minimum_order_amount - subtotal)
            preview.amount_to_unlock = amount_to_unlock
            preview.message = f"Add Rs {amount_to_unlock:.0f} more to unlock this offer"
            return preview
        _, discount_amount = validate_offer_for_order(
            db,
            user=user,
            offer_id=offer.id,
            restaurant_id=payload.restaurant_id,
            restaurant_location_id=payload.restaurant_location_id,
            menu_items=menu_items,
            subtotal=subtotal,
            delivery_fee=delivery_fee,
        )
        preview.eligible = True
        preview.discount_amount = _quantize(discount_amount)
        if preview.discount_amount > 0:
            preview.message = "Discount applied"
        elif offer.discount_type == PersonalizedOfferDiscountType.NONE:
            preview.message = "Offer active"
        else:
            preview.message = "Offer eligible"
        return preview
    except HTTPException as error:
        preview.message = str(error.detail)
        return preview


def record_offer_conversion(
    db: Session,
    *,
    user_id: uuid.UUID,
    offer: PersonalizedOffer | GeneratedOffer,
    order_id: uuid.UUID,
    generated_offer_id: uuid.UUID | None = None,
    generated_offer_user_match_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
) -> None:
    generated_offer = None
    manual_offer = offer if isinstance(offer, PersonalizedOffer) else None
    if isinstance(offer, GeneratedOffer):
        generated_offer = offer
    elif generated_offer_id:
        generated_offer = db.get(GeneratedOffer, generated_offer_id)
    match = db.get(GeneratedOfferUserMatch, generated_offer_user_match_id) if generated_offer_user_match_id else None
    db.add(
        PersonalizedOfferEvent(
            offer_id=manual_offer.id if manual_offer is not None else None,
            user_id=user_id,
            event_type=PersonalizedOfferEventType.CONVERTED,
            target_type=target_type,
            target_id=target_id,
            converted_at=datetime.now(UTC),
            order_id=order_id,
            # The metadata key predates the column and is still written, so
            # anything already reading it keeps working.
            event_metadata={"order_id": str(order_id)},
            generated_offer_id=generated_offer.id if generated_offer is not None else None,
            generated_offer_user_match_id=match.id if match is not None else None,
        )
    )
    if generated_offer is not None:
        generated_offer.conversion_count += 1
        db.add(generated_offer)
    if match is not None:
        match.conversion_count += 1
        match.converted_at = datetime.now(UTC)
        db.add(match)

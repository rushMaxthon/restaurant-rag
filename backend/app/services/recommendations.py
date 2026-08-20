from __future__ import annotations

import logging
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from math import asin, cos, radians, sin, sqrt
from typing import Iterable

from sqlalchemy import Select, select
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.models.menu_item import MenuItem
from app.models.enums import OrderStatus, PaymentStatus
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.models.user_preferences import UserPreferences
from app.schemas.preferences import (
    RecommendationLocationContext,
    UserPreferencesPayload,
    UserPreferencesResponse,
)
from app.schemas.recommendation import (
    RecommendationItemResponse,
    RecommendationLocationSummary,
    RecommendationLocationVariantSummary,
    RecommendationRestaurantSummary,
    RecommendationScoreBreakdown,
)
from app.services.bestsellers import (
    get_menu_item_featured_flag,
    hydrate_dynamic_bestseller_flags,
    is_menu_item_bestseller,
)
from app.services.cache import cache_delete_pattern, cache_get_json, cache_set_json, normalize_cache_query
from app.services.menu_item_metadata import (
    SIGNAL_KEYWORD_MAP,
    extract_menu_item_signals,
    get_new_item_reason,
    is_high_popularity_value,
    is_menu_item_new,
    is_menu_item_trending,
    resolve_menu_item_launch_timestamp,
)

MAX_RECOMMENDATIONS = 20
logger = logging.getLogger(__name__)
ORDER_HISTORY_ELIGIBLE_STATUSES = (
    OrderStatus.PLACED,
    OrderStatus.ACCEPTED,
    OrderStatus.PREPARING,
    OrderStatus.OUT_FOR_DELIVERY,
    OrderStatus.DELIVERED,
)

DIET_ALIASES = {
    "veg": "VEG",
    "vegetarian": "VEG",
    "non veg": "NON_VEG",
    "non vegetarian": "NON_VEG",
}
SPICE_LEVEL_ALIASES = {
    "low": "LOW",
    "medium": "MEDIUM",
    "high": "HIGH",
}
BUDGET_TIER_ALIASES = {
    "low": "LOW",
    "mid": "MID",
    "medium": "MID",
    "high": "HIGH",
}
ORDER_TERM_STOPWORDS = {
    "and",
    "with",
    "from",
    "fresh",
    "classic",
    "special",
    "style",
    "combo",
    "meal",
}


@dataclass
class CandidateScore:
    menu_item: MenuItem
    restaurant: Restaurant
    restaurant_location: RestaurantLocation
    total_score: float
    breakdown: RecommendationScoreBreakdown
    recommendation_label: str | None = None
    recommendation_reason: str | None = None
    new_item_reason: str | None = None


@dataclass
class PreferenceProfile:
    cuisines: set[str]
    disliked_cuisines: set[str]
    diet: str | None
    spice_level: str | None
    budget_tier: str | None
    favorite_items: set[str]
    cuisine_affinity_scores: dict[str, float]
    average_budget: float
    price_sensitivity: float

    @property
    def is_meaningful(self) -> bool:
        return bool(
            self.cuisines
            or self.disliked_cuisines
            or self.diet
            or self.spice_level
            or self.budget_tier
            or self.favorite_items
            or self.average_budget > 0
        )


@dataclass
class OrderHistoryProfile:
    item_scores: dict[str, float]
    item_term_scores: dict[str, float]
    category_scores: dict[str, float]
    cuisine_scores: dict[str, float]
    restaurant_scores: dict[str, float]
    eligible_order_count: int
    status_counts: dict[str, int]


@dataclass
class OrderHistoryScoreComponents:
    direct_item: float
    item_term: float
    category: float
    cuisine: float
    restaurant: float

    @property
    def total(self) -> float:
        return _clamp(
            (self.direct_item * 0.48)
            + (self.item_term * 0.22)
            + (self.category * 0.14)
            + (self.cuisine * 0.10)
            + (self.restaurant * 0.06)
        )


def _normalize_text(value: str | None) -> str:
    return normalize_cache_query(value or "")


def _normalize_choice_key(value: str | None) -> str:
    return " ".join(
        _normalize_text(value).replace("-", " ").replace("_", " ").split()
    )


def _clean_string_list(values: object | None) -> list[str]:
    if isinstance(values, str):
        iterable = [values]
    elif isinstance(values, Iterable):
        iterable = values
    else:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in iterable:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
    return normalized


def _dedupe_normalized(values: Iterable[str]) -> set[str]:
    return {_normalize_text(value) for value in values if _normalize_text(value)}


def _safe_decimal(value: Decimal | float | int | None) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def _normalize_counter(counter: Counter[str]) -> dict[str, float]:
    if not counter:
        return {}
    max_count = max(counter.values())
    if max_count <= 0:
        return {}
    return {key: count / max_count for key, count in counter.items()}


def _extract_search_terms(*values: str | None) -> set[str]:
    terms: set[str] = set()
    for value in values:
        normalized_value = _normalize_choice_key(value)
        if not normalized_value:
            continue
        terms.add(normalized_value)
        for token in normalized_value.split():
            if len(token) < 4 or token in ORDER_TERM_STOPWORDS:
                continue
            terms.add(token)
    return terms


def _build_candidate_query() -> Select[tuple[MenuItem, Restaurant, RestaurantLocation]]:
    return (
        select(MenuItem, Restaurant, RestaurantLocation)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .join(RestaurantLocation, MenuItem.restaurant_location_id == RestaurantLocation.id)
        .where(
            MenuItem.is_available.is_(True),
            Restaurant.is_active.is_(True),
            Restaurant.is_approved.is_(True),
            RestaurantLocation.is_active.is_(True),
        )
    )


def _budget_to_amount(budget_tier: str | None) -> float:
    mapping = {
        "LOW": 220.0,
        "MID": 420.0,
        "HIGH": 760.0,
    }
    return mapping.get((budget_tier or "").upper(), 0.0)


def _budget_to_sensitivity(budget_tier: str | None) -> float:
    mapping = {
        "LOW": 0.7,
        "MID": 1.0,
        "HIGH": 1.35,
    }
    return mapping.get((budget_tier or "").upper(), 1.0)


def _normalize_diet_value(values: object | None) -> str | None:
    for value in _clean_string_list(values):
        normalized = DIET_ALIASES.get(_normalize_choice_key(value))
        if normalized is not None:
            return normalized
    return None


def _normalize_spice_level(value: object | None) -> str | None:
    if not isinstance(value, str):
        return None
    return SPICE_LEVEL_ALIASES.get(_normalize_choice_key(value))


def _normalize_budget_tier(value: object | None) -> str | None:
    if not isinstance(value, str):
        return None
    return BUDGET_TIER_ALIASES.get(_normalize_choice_key(value))


def _payload_to_profile(payload: UserPreferencesPayload | None) -> PreferenceProfile | None:
    if payload is None:
        return None

    budget_amount = _budget_to_amount(payload.budget)
    return PreferenceProfile(
        cuisines=_dedupe_normalized(payload.cuisines),
        disliked_cuisines=set(),
        diet=payload.diet,
        spice_level=payload.spice_level,
        budget_tier=payload.budget,
        favorite_items=_dedupe_normalized(payload.favorite_items),
        cuisine_affinity_scores={},
        average_budget=budget_amount,
        price_sensitivity=_budget_to_sensitivity(payload.budget),
    )


def _model_to_profile(model: UserPreferences | None) -> PreferenceProfile | None:
    if model is None:
        return None

    diet = _normalize_diet_value(model.dietary_preferences)
    cuisine_affinity_scores = {
        _normalize_text(key): float(value)
        for key, value in (model.cuisine_affinity_scores or {}).items()
        if isinstance(value, (int, float))
    }

    average_budget = float(_safe_decimal(model.average_budget))
    budget_tier = _normalize_budget_tier(model.budget_tier)
    if not budget_tier and average_budget > 0:
        if average_budget <= 250:
            budget_tier = "LOW"
        elif average_budget <= 500:
            budget_tier = "MID"
        else:
            budget_tier = "HIGH"

    return PreferenceProfile(
        cuisines=_dedupe_normalized(_clean_string_list(model.favorite_cuisines)),
        disliked_cuisines=_dedupe_normalized(_clean_string_list(model.disliked_cuisines)),
        diet=diet,
        spice_level=_normalize_spice_level(model.spice_level),
        budget_tier=budget_tier,
        favorite_items=_dedupe_normalized(_clean_string_list(model.favorite_items)),
        cuisine_affinity_scores=cuisine_affinity_scores,
        average_budget=average_budget or _budget_to_amount(budget_tier),
        price_sensitivity=float(_safe_decimal(model.price_sensitivity)),
    )


def _merge_profiles(
    stored: PreferenceProfile | None,
    local: PreferenceProfile | None,
) -> PreferenceProfile | None:
    if stored is None:
        return local
    if local is None:
        return stored

    return PreferenceProfile(
        cuisines=set(local.cuisines),
        disliked_cuisines=stored.disliked_cuisines | local.disliked_cuisines,
        diet=local.diet,
        spice_level=local.spice_level,
        budget_tier=local.budget_tier,
        favorite_items=set(local.favorite_items),
        cuisine_affinity_scores={**stored.cuisine_affinity_scores, **local.cuisine_affinity_scores},
        average_budget=local.average_budget,
        price_sensitivity=local.price_sensitivity,
    )


def _text_blob(item: MenuItem, restaurant: Restaurant) -> str:
    return " ".join(
        [
            item.name,
            item.category,
            item.cuisine_type or "",
            item.description or "",
            restaurant.name,
            restaurant.cuisine_type,
        ]
    ).lower()


def _item_preference_match_score(
    item: MenuItem,
    preferences: PreferenceProfile | None,
) -> float:
    if preferences is None:
        return 0.0

    candidate_terms = preferences.favorite_items | preferences.cuisines
    if not candidate_terms:
        return 0.0

    item_name = _normalize_choice_key(item.name)
    item_category = _normalize_choice_key(item.category)
    item_description = _normalize_choice_key(item.description)
    best_score = 0.0

    for term in candidate_terms:
        normalized_term = _normalize_choice_key(term)
        if not normalized_term:
            continue

        if item_name == normalized_term or item_category == normalized_term:
            return 1.0
        if normalized_term in item_name:
            best_score = max(best_score, 0.98)
        elif normalized_term in item_category:
            best_score = max(best_score, 0.95)
        elif normalized_term in item_description:
            best_score = max(best_score, 0.7)

    return best_score


def _load_user_preferences(db: Session, user_id: uuid.UUID) -> UserPreferences | None:
    return db.scalar(select(UserPreferences).where(UserPreferences.user_id == user_id))


def _load_order_history(
    db: Session,
    user_id: uuid.UUID,
) -> OrderHistoryProfile:
    rows = db.execute(
        select(Order, OrderItem, MenuItem, Restaurant)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .join(MenuItem, OrderItem.menu_item_id == MenuItem.id)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .where(
            Order.customer_id == user_id,
            Order.payment_status == PaymentStatus.PAID,
            Order.status.in_(ORDER_HISTORY_ELIGIBLE_STATUSES),
        )
    ).all()

    item_counts: Counter[str] = Counter()
    item_term_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    cuisine_counts: Counter[str] = Counter()
    restaurant_counts: Counter[str] = Counter()
    eligible_order_ids: set[str] = set()
    status_counts: Counter[str] = Counter()
    now = datetime.now(UTC)

    for order, order_item, menu_item, restaurant in rows:
        quantity = max(order_item.quantity, 1)
        eligible_order_ids.add(str(order.id))
        status_counts[order.status.value] += 1
        placed_at = order.placed_at
        if placed_at.tzinfo is None:
            placed_at = placed_at.replace(tzinfo=UTC)
        age_days = max((now - placed_at).days, 0)
        recency_weight = 1 / (1 + (age_days / 30))
        status_weight = 1.0 if order.status == OrderStatus.DELIVERED else 0.94
        weighted_quantity = quantity * recency_weight * status_weight

        item_counts[str(menu_item.id)] += weighted_quantity
        for term in _extract_search_terms(order_item.item_name_snapshot, menu_item.name):
            item_term_counts[term] += weighted_quantity

        category_key = _normalize_text(menu_item.category)
        if category_key:
            category_counts[category_key] += weighted_quantity

        cuisine_key = _normalize_text(menu_item.cuisine_type or restaurant.cuisine_type)
        if cuisine_key:
            cuisine_counts[cuisine_key] += weighted_quantity
        restaurant_counts[str(restaurant.id)] += weighted_quantity

    history_profile = OrderHistoryProfile(
        item_scores=_normalize_counter(item_counts),
        item_term_scores=_normalize_counter(item_term_counts),
        category_scores=_normalize_counter(category_counts),
        cuisine_scores=_normalize_counter(cuisine_counts),
        restaurant_scores=_normalize_counter(restaurant_counts),
        eligible_order_count=len(eligible_order_ids),
        status_counts=dict(status_counts),
    )

    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Loaded order-history signals for user %s: eligible_statuses=%s orders=%s rows=%s status_counts=%s item_scores=%s category_scores=%s cuisine_scores=%s",
            user_id,
            [status.value for status in ORDER_HISTORY_ELIGIBLE_STATUSES],
            len(eligible_order_ids),
            len(rows),
            dict(status_counts),
            dict(sorted(history_profile.item_scores.items(), key=lambda entry: entry[1], reverse=True)[:8]),
            dict(sorted(history_profile.category_scores.items(), key=lambda entry: entry[1], reverse=True)[:6]),
            dict(sorted(history_profile.cuisine_scores.items(), key=lambda entry: entry[1], reverse=True)[:6]),
        )

    return history_profile


def _cuisine_preference_score(
    item: MenuItem,
    restaurant: Restaurant,
    preferences: PreferenceProfile | None,
    historical_cuisine_scores: dict[str, float],
) -> float:
    cuisine_key = _normalize_text(item.cuisine_type or restaurant.cuisine_type)
    if not cuisine_key:
        return 0.05 if preferences is not None and preferences.is_meaningful else 0.3

    if preferences is None or not preferences.is_meaningful:
        base_score = 0.35
    else:
        base_score = 0.05

    if preferences is not None:
        if cuisine_key in preferences.cuisines:
            base_score = 0.92
        elif cuisine_key in preferences.disliked_cuisines:
            return 0.0

        affinity_boost = preferences.cuisine_affinity_scores.get(cuisine_key, 0.0)
        if affinity_boost > 1:
            affinity_boost = affinity_boost / 100
        base_score += affinity_boost * 0.15

    history_boost = historical_cuisine_scores.get(cuisine_key, 0.0) * 0.18
    return _clamp(base_score + history_boost)


def _category_preference_score(
    item: MenuItem,
    preferences: PreferenceProfile | None,
    historical_category_scores: dict[str, float],
) -> float:
    category_key = _normalize_text(item.category)
    if not category_key:
        return 0.0

    if preferences is None or not preferences.is_meaningful:
        base_score = 0.35
    else:
        base_score = 0.05

    if preferences is not None:
        selected_terms = preferences.favorite_items | preferences.cuisines
        if category_key in selected_terms:
            base_score = 0.9

    history_boost = historical_category_scores.get(category_key, 0.0) * 0.2
    return _clamp(base_score + history_boost)


def _diet_match_score(item: MenuItem, preferences: PreferenceProfile | None) -> float:
    if preferences is None or preferences.diet is None:
        return 0.5
    if preferences.diet == "VEG":
        return 1.0 if item.is_veg else 0.05
    return 1.0 if not item.is_veg else 0.65


def _spice_match_score(
    item: MenuItem,
    restaurant: Restaurant,
    preferences: PreferenceProfile | None,
) -> float:
    if preferences is None or preferences.spice_level is None:
        return 0.5

    text_blob = _text_blob(item, restaurant)
    high_keywords = {
        "spicy",
        "hot",
        "fiery",
        "schezwan",
        "chilli",
        "chili",
        "kolhapuri",
        "chettinad",
        "peri peri",
        "tandoori",
    }
    low_keywords = {
        "mild",
        "butter",
        "cream",
        "creamy",
        "sweet",
        "vanilla",
        "classic",
        "plain",
    }

    if any(keyword in text_blob for keyword in high_keywords):
        estimated_level = "HIGH"
    elif any(keyword in text_blob for keyword in low_keywords):
        estimated_level = "LOW"
    else:
        estimated_level = "MEDIUM"

    if estimated_level == preferences.spice_level:
        return 1.0

    distance = abs(
        {"LOW": 0, "MEDIUM": 1, "HIGH": 2}[estimated_level]
        - {"LOW": 0, "MEDIUM": 1, "HIGH": 2}[preferences.spice_level]
    )
    return {0: 1.0, 1: 0.65, 2: 0.25}[distance]


def _preference_affinity_score(
    item: MenuItem,
    restaurant: Restaurant,
    preferences: PreferenceProfile | None,
    historical_cuisine_scores: dict[str, float],
) -> float:
    item_match_score = _item_preference_match_score(item, preferences)
    cuisine_score = _cuisine_preference_score(item, restaurant, preferences, historical_cuisine_scores)
    return _clamp(
        (item_match_score * 0.78)
        + (cuisine_score * 0.22)
    )


def _order_history_components(
    item: MenuItem,
    restaurant: Restaurant,
    history_profile: OrderHistoryProfile,
) -> OrderHistoryScoreComponents:
    direct_item_score = history_profile.item_scores.get(str(item.id), 0.0)
    text_blob_terms = _extract_search_terms(item.name, item.description)
    item_term_score = max(
        (history_profile.item_term_scores.get(term, 0.0) for term in text_blob_terms),
        default=0.0,
    )
    category_score = history_profile.category_scores.get(_normalize_text(item.category), 0.0)
    cuisine_key = _normalize_text(item.cuisine_type or restaurant.cuisine_type)
    cuisine_score = history_profile.cuisine_scores.get(cuisine_key, 0.0)
    restaurant_score = history_profile.restaurant_scores.get(str(restaurant.id), 0.0)
    return OrderHistoryScoreComponents(
        direct_item=direct_item_score,
        item_term=item_term_score,
        category=category_score,
        cuisine=cuisine_score,
        restaurant=restaurant_score,
    )


def _popularity_score(item: MenuItem, max_popularity: float) -> float:
    item_popularity = float(_safe_decimal(item.popularity_score))
    return _clamp(item_popularity / max_popularity) if max_popularity > 0 else 0.0


def _preference_signal_scores(
    preferences: PreferenceProfile | None,
) -> dict[str, float]:
    if preferences is None:
        return {}

    signal_scores: dict[str, float] = {}
    selected_terms = preferences.favorite_items | preferences.cuisines
    normalized_terms = {_normalize_choice_key(term) for term in selected_terms if _normalize_choice_key(term)}

    for signal, keywords in SIGNAL_KEYWORD_MAP.items():
        if any(keyword in normalized_terms or any(keyword in term for term in normalized_terms) for keyword in keywords):
            signal_scores[signal] = 1.0

    if preferences.diet == "VEG":
        signal_scores["veg"] = 1.0
    elif preferences.diet == "NON_VEG":
        signal_scores["non_veg"] = 1.0

    if preferences.spice_level == "HIGH":
        signal_scores["spicy"] = max(signal_scores.get("spicy", 0.0), 1.0)
    elif preferences.spice_level == "MEDIUM":
        signal_scores["spicy"] = max(signal_scores.get("spicy", 0.0), 0.55)

    return signal_scores


def _history_signal_scores(history_profile: OrderHistoryProfile) -> dict[str, float]:
    signal_scores: dict[str, float] = {}
    for signal, keywords in SIGNAL_KEYWORD_MAP.items():
        score = 0.0
        for keyword in keywords:
            normalized_keyword = _normalize_choice_key(keyword)
            if not normalized_keyword:
                continue
            score = max(
                score,
                history_profile.item_term_scores.get(normalized_keyword, 0.0),
                history_profile.category_scores.get(_normalize_text(keyword), 0.0),
                history_profile.cuisine_scores.get(_normalize_text(keyword), 0.0),
            )
        if score > 0:
            signal_scores[signal] = _clamp(score)
    return signal_scores


def _signal_overlap_score(
    item_signal_keys: set[str],
    signal_scores: dict[str, float],
) -> float:
    if not item_signal_keys or not signal_scores:
        return 0.0
    matching_scores = [signal_scores[key] for key in item_signal_keys if key in signal_scores]
    if not matching_scores:
        return 0.0
    return _clamp(sum(matching_scores) / len(matching_scores))


def _new_item_freshness_score(menu_item: MenuItem) -> float:
    settings = get_settings()
    window_days = max(settings.new_item_window_days, 0)
    if window_days <= 0 or not is_menu_item_new(menu_item):
        return 0.0

    launched_at = resolve_menu_item_launch_timestamp(menu_item)
    age_days = max((datetime.now(UTC) - launched_at).days, 0)
    return _clamp(1 - (age_days / max(window_days, 1)))


def _new_item_spice_affinity_score(
    menu_item: MenuItem,
    restaurant: Restaurant,
    preferences: PreferenceProfile | None,
) -> float:
    if preferences is None or preferences.spice_level is None:
        return 0.0

    menu_item_signals = extract_menu_item_signals(
        menu_item,
        restaurant_cuisine_type=restaurant.cuisine_type,
    )
    if "spicy" not in menu_item_signals.all_signals:
        return 0.0

    return {
        "HIGH": 1.0,
        "MEDIUM": 0.65,
        "LOW": 0.18,
    }.get(preferences.spice_level, 0.0)


def _new_item_taste_match_score(
    menu_item: MenuItem,
    restaurant: Restaurant,
    preferences: PreferenceProfile | None,
    *,
    preference_signal_scores: dict[str, float],
) -> float:
    if preferences is None:
        return 0.0

    menu_item_signals = extract_menu_item_signals(
        menu_item,
        restaurant_cuisine_type=restaurant.cuisine_type,
    )
    direct_match = _item_preference_match_score(menu_item, preferences)
    signal_match = _signal_overlap_score(menu_item_signals.all_signals, preference_signal_scores)
    cuisine_match = _signal_overlap_score(menu_item_signals.cuisine_signals, preference_signal_scores)
    diet_match = _signal_overlap_score(menu_item_signals.diet_signals, preference_signal_scores)
    return _clamp(
        (direct_match * 0.55)
        + (signal_match * 0.25)
        + (cuisine_match * 0.12)
        + (diet_match * 0.08)
    )


def _new_item_cuisine_affinity_score(
    menu_item: MenuItem,
    restaurant: Restaurant,
    preferences: PreferenceProfile | None,
    *,
    preference_signal_scores: dict[str, float],
    historical_cuisine_scores: dict[str, float],
) -> float:
    menu_item_signals = extract_menu_item_signals(
        menu_item,
        restaurant_cuisine_type=restaurant.cuisine_type,
    )
    signal_match = _signal_overlap_score(menu_item_signals.cuisine_signals, preference_signal_scores)
    cuisine_score = _cuisine_preference_score(menu_item, restaurant, preferences, historical_cuisine_scores)
    category_score = _category_preference_score(menu_item, preferences, {})
    return _clamp((signal_match * 0.45) + (cuisine_score * 0.4) + (category_score * 0.15))


def _new_item_order_affinity_score(
    menu_item: MenuItem,
    restaurant: Restaurant,
    history_profile: OrderHistoryProfile,
    *,
    history_signal_scores: dict[str, float],
    order_history_components: OrderHistoryScoreComponents,
) -> float:
    if history_profile.eligible_order_count <= 0:
        return 0.0

    menu_item_signals = extract_menu_item_signals(
        menu_item,
        restaurant_cuisine_type=restaurant.cuisine_type,
    )
    signal_match = _signal_overlap_score(menu_item_signals.all_signals, history_signal_scores)
    return _clamp(
        (order_history_components.total * 0.7)
        + (signal_match * 0.3)
    )


def _new_item_boost_score(
    menu_item: MenuItem,
    restaurant: Restaurant,
    *,
    preferences: PreferenceProfile | None,
    history_profile: OrderHistoryProfile | None,
    historical_cuisine_scores: dict[str, float],
    popularity: float,
    preference_signal_scores: dict[str, float],
    history_signal_scores: dict[str, float],
    order_history_components: OrderHistoryScoreComponents | None,
) -> tuple[float, dict[str, float]]:
    if not is_menu_item_new(menu_item):
        return 0.0, {
            "freshness": 0.0,
            "taste_match": 0.0,
            "order_affinity": 0.0,
            "cuisine_affinity": 0.0,
            "spice_match": 0.0,
        }

    freshness = _new_item_freshness_score(menu_item)
    taste_match = _new_item_taste_match_score(
        menu_item,
        restaurant,
        preferences,
        preference_signal_scores=preference_signal_scores,
    )
    cuisine_affinity = _new_item_cuisine_affinity_score(
        menu_item,
        restaurant,
        preferences,
        preference_signal_scores=preference_signal_scores,
        historical_cuisine_scores=historical_cuisine_scores,
    )
    spice_match = _new_item_spice_affinity_score(menu_item, restaurant, preferences)
    order_affinity = (
        _new_item_order_affinity_score(
            menu_item,
            restaurant,
            history_profile,
            history_signal_scores=history_signal_scores,
            order_history_components=order_history_components,
        )
        if history_profile is not None and order_history_components is not None
        else 0.0
    )

    has_personal_signals = bool(
        (preferences is not None and preferences.is_meaningful)
        or (history_profile is not None and history_profile.eligible_order_count > 0)
    )
    if has_personal_signals:
        boost = _clamp(
            freshness
            * (
                (taste_match * 0.40)
                + (order_affinity * 0.30)
                + (cuisine_affinity * 0.18)
                + (spice_match * 0.12)
            )
        )
    else:
        boost = _clamp((freshness * 0.7) + (popularity * 0.3))

    return boost, {
        "freshness": round(freshness, 4),
        "taste_match": round(taste_match, 4),
        "order_affinity": round(order_affinity, 4),
        "cuisine_affinity": round(cuisine_affinity, 4),
        "spice_match": round(spice_match, 4),
    }


def _build_recommendation_metadata(
    menu_item: MenuItem,
    restaurant: Restaurant,
    *,
    preferences: PreferenceProfile | None,
    history_profile: OrderHistoryProfile | None,
    preference_match: float,
    order_history: float,
    popularity: float,
    new_item_components: dict[str, float],
) -> tuple[str | None, str | None, str | None]:
    if (
        history_profile is not None
        and history_profile.eligible_order_count > 0
        and new_item_components.get("order_affinity", 0.0) >= 0.55
    ):
        return "Based on Your Orders", "Similar to dishes you order often.", get_new_item_reason(menu_item)

    menu_item_signals = extract_menu_item_signals(
        menu_item,
        restaurant_cuisine_type=restaurant.cuisine_type,
    )
    strong_taste_match = (
        new_item_components.get("spice_match", 0.0) >= 0.72
        or new_item_components.get("taste_match", 0.0) >= 0.45
        or new_item_components.get("cuisine_affinity", 0.0) >= 0.60
        or preference_match >= 0.62
    )
    if preferences is not None and preferences.is_meaningful and strong_taste_match:
        if (
            "spicy" in menu_item_signals.all_signals
            and new_item_components.get("spice_match", 0.0) >= 0.72
        ):
            reason = "Aligned with your spice and taste preferences."
        else:
            reason = "A strong match for your saved tastes and profile."
        return "Matches Your Taste", reason, get_new_item_reason(menu_item)

    raw_popularity = float(_safe_decimal(menu_item.popularity_score))
    if is_menu_item_trending(menu_item, popularity_score=raw_popularity):
        return "Trending Now", "A just-launched item gaining strong customer demand.", get_new_item_reason(menu_item)

    if is_menu_item_bestseller(menu_item):
        return "Best Seller", "One of the most-ordered items at this branch recently.", None

    if is_menu_item_new(menu_item):
        return "Just Launched", "Manually marked as a recent launch.", get_new_item_reason(menu_item)

    has_personal_match = (
        (preferences is not None and preferences.is_meaningful and preference_match >= 0.42)
        or (history_profile is not None and history_profile.eligible_order_count > 0 and order_history >= 0.38)
    )
    if has_personal_match:
        return "Recommended for You", "A general personalized match based on your profile and activity.", None

    return None, None, get_new_item_reason(menu_item)


def _budget_fit_score(item: MenuItem, preferences: PreferenceProfile | None) -> float:
    if preferences is None or preferences.average_budget <= 0:
        return 0.5

    average_budget = preferences.average_budget
    price_sensitivity = max(preferences.price_sensitivity or 1.0, 0.1)
    item_price = float(_safe_decimal(item.price))
    distance_ratio = abs(item_price - average_budget) / average_budget
    fit_score = 1 - (distance_ratio / price_sensitivity)
    return _clamp(fit_score)


def _novelty_score(
    item: MenuItem,
    restaurant: Restaurant,
    normalized_item_counts: dict[str, float],
    normalized_cuisine_counts: dict[str, float],
    normalized_restaurant_counts: dict[str, float],
) -> float:
    item_seen = normalized_item_counts.get(str(item.id), 0.0)
    cuisine_key = _normalize_text(item.cuisine_type or restaurant.cuisine_type)
    cuisine_seen = normalized_cuisine_counts.get(cuisine_key, 0.0)
    restaurant_seen = normalized_restaurant_counts.get(str(restaurant.id), 0.0)
    explored_score = (item_seen * 0.6) + (cuisine_seen * 0.25) + (restaurant_seen * 0.15)
    return _clamp(1 - explored_score)


def _serialize_recommendations(scored_candidates: list[CandidateScore]) -> list[RecommendationItemResponse]:
    return [
        RecommendationItemResponse(
            id=candidate.menu_item.id,
            restaurant_id=candidate.restaurant.id,
            restaurant_location_id=candidate.restaurant_location.id,
            restaurant_location_name=candidate.restaurant_location.branch_name,
            restaurant_location_city=candidate.restaurant_location.city,
            restaurant=RecommendationRestaurantSummary(
                id=candidate.restaurant.id,
                name=candidate.restaurant.name,
                slug=candidate.restaurant.slug,
                cuisine_type=candidate.restaurant.cuisine_type,
                city=candidate.restaurant.city,
                is_open=candidate.restaurant.is_open,
            ),
            restaurant_location=RecommendationLocationSummary(
                id=candidate.restaurant_location.id,
                branch_name=candidate.restaurant_location.branch_name,
                city=candidate.restaurant_location.city,
                latitude=candidate.restaurant_location.latitude,
                longitude=candidate.restaurant_location.longitude,
                is_open=candidate.restaurant_location.is_open,
                is_active=candidate.restaurant_location.is_active,
                delivery_fee=candidate.restaurant_location.delivery_fee,
                minimum_order_amount=candidate.restaurant_location.minimum_order_amount,
                estimated_delivery_time=candidate.restaurant_location.estimated_delivery_time,
            ),
            name=candidate.menu_item.name,
            category=candidate.menu_item.category,
            cuisine_type=candidate.menu_item.cuisine_type,
            description=candidate.menu_item.description,
            price=candidate.menu_item.price,
            is_available=candidate.menu_item.is_available,
            is_veg=candidate.menu_item.is_veg,
            is_bestseller=is_menu_item_bestseller(candidate.menu_item),
            is_featured=get_menu_item_featured_flag(candidate.menu_item),
            image_url=candidate.menu_item.image_url,
            popularity_score=candidate.menu_item.popularity_score,
            launched_at=resolve_menu_item_launch_timestamp(candidate.menu_item),
            created_at=candidate.menu_item.created_at,
            updated_at=candidate.menu_item.updated_at,
            is_new_launch=candidate.menu_item.is_new_launch,
            is_new=is_menu_item_new(candidate.menu_item),
            recommendation_label=candidate.recommendation_label,
            recommendation_reason=candidate.recommendation_reason,
            new_item_reason=candidate.new_item_reason,
            score=candidate.total_score,
            score_breakdown=candidate.breakdown,
        )
        for candidate in scored_candidates
    ]


def _sort_candidates(candidates: list[CandidateScore]) -> list[CandidateScore]:
    candidates.sort(
        key=lambda candidate: (
            candidate.total_score,
            float(_safe_decimal(candidate.menu_item.popularity_score)),
            1 if is_menu_item_bestseller(candidate.menu_item) else 0,
            1 if candidate.restaurant.is_open else 0,
        ),
        reverse=True,
    )
    return candidates


def _build_logged_in_recommendations(
    db: Session,
    user: User,
    preference_profile: PreferenceProfile | None,
) -> list[RecommendationItemResponse]:
    candidates = db.execute(_build_candidate_query()).all()
    if not candidates:
        return []
    hydrate_dynamic_bestseller_flags(db, [menu_item for menu_item, _, _ in candidates])

    history_profile = _load_order_history(db, user.id)
    preference_signal_scores = _preference_signal_scores(preference_profile)
    history_signal_scores = _history_signal_scores(history_profile)
    max_popularity = max(float(_safe_decimal(menu_item.popularity_score)) for menu_item, _, _ in candidates)
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Recommendation profile for user %s preferences=%s order_history=%s",
            user.id,
            {
                "cuisines": sorted(preference_profile.cuisines) if preference_profile else [],
                "diet": preference_profile.diet if preference_profile else None,
                "favorite_items": sorted(preference_profile.favorite_items) if preference_profile else [],
            },
            {
                "eligible_orders": history_profile.eligible_order_count,
                "status_counts": history_profile.status_counts,
                "item_terms": dict(sorted(history_profile.item_term_scores.items(), key=lambda entry: entry[1], reverse=True)[:8]),
                "categories": dict(sorted(history_profile.category_scores.items(), key=lambda entry: entry[1], reverse=True)[:6]),
                "cuisines": dict(sorted(history_profile.cuisine_scores.items(), key=lambda entry: entry[1], reverse=True)[:6]),
            },
        )

    scored_candidates: list[CandidateScore] = []
    for menu_item, restaurant, restaurant_location in candidates:
        preference_match = _preference_affinity_score(
            menu_item,
            restaurant,
            preference_profile,
            history_profile.cuisine_scores,
        )
        cuisine_category_match = _clamp(
            (_cuisine_preference_score(menu_item, restaurant, preference_profile, history_profile.cuisine_scores) * 0.55)
            + (_category_preference_score(menu_item, preference_profile, history_profile.category_scores) * 0.45)
        )
        diet_match = _diet_match_score(menu_item, preference_profile)
        order_history_components = _order_history_components(
            menu_item,
            restaurant,
            history_profile,
        )
        order_history = order_history_components.total
        popularity = _popularity_score(menu_item, max_popularity=max_popularity)
        new_item_boost, new_item_components = _new_item_boost_score(
            menu_item,
            restaurant,
            preferences=preference_profile,
            history_profile=history_profile,
            historical_cuisine_scores=history_profile.cuisine_scores,
            popularity=popularity,
            preference_signal_scores=preference_signal_scores,
            history_signal_scores=history_signal_scores,
            order_history_components=order_history_components,
        )

        base_score = (
            (preference_match * 0.45)
            + (order_history * 0.30)
            + (cuisine_category_match * 0.10)
            + (diet_match * 0.10)
            + (popularity * 0.05)
        )
        total_score = _clamp(base_score + (new_item_boost * 0.16))

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Recommendation score user=%s item=%s restaurant=%s preference_match=%.4f order_history=%.4f order_affinity={direct:%.4f term:%.4f category:%.4f cuisine:%.4f restaurant:%.4f} cuisine_category=%.4f diet=%.4f popularity=%.4f new_item=%s new_item_boost=%.4f new_item_components=%s total=%.4f",
                user.id,
                menu_item.name,
                restaurant.name,
                preference_match,
                order_history,
                order_history_components.direct_item,
                order_history_components.item_term,
                order_history_components.category,
                order_history_components.cuisine,
                order_history_components.restaurant,
                cuisine_category_match,
                diet_match,
                popularity,
                is_menu_item_new(menu_item),
                new_item_boost,
                new_item_components,
                total_score,
            )

        recommendation_label, recommendation_reason, new_item_reason = (
            _build_recommendation_metadata(
                menu_item,
                restaurant,
                preferences=preference_profile,
                history_profile=history_profile,
                preference_match=preference_match,
                order_history=order_history,
                popularity=popularity,
                new_item_components=new_item_components,
            )
        )

        scored_candidates.append(
            CandidateScore(
                menu_item=menu_item,
                restaurant=restaurant,
                restaurant_location=restaurant_location,
                total_score=round(total_score, 4),
                breakdown=RecommendationScoreBreakdown(
                    cuisine_match=round(cuisine_category_match, 4),
                    order_history=round(order_history, 4),
                    popularity=round(popularity, 4),
                    budget_fit=round(diet_match, 4),
                    novelty=0.0,
                ),
                recommendation_label=recommendation_label,
                recommendation_reason=recommendation_reason,
                new_item_reason=new_item_reason,
            )
        )

    ranked_candidates = _sort_candidates(scored_candidates)
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Final logged-in recommendation order for user %s: %s",
            user.id,
            [candidate.menu_item.name for candidate in ranked_candidates],
        )

    return _serialize_recommendations(ranked_candidates)


def _build_guest_preference_recommendations(
    db: Session,
    preference_profile: PreferenceProfile,
) -> list[RecommendationItemResponse]:
    candidates = db.execute(_build_candidate_query()).all()
    if not candidates:
        return []
    hydrate_dynamic_bestseller_flags(db, [menu_item for menu_item, _, _ in candidates])

    max_popularity = max(float(_safe_decimal(menu_item.popularity_score)) for menu_item, _, _ in candidates)
    preference_signal_scores = _preference_signal_scores(preference_profile)
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Guest recommendation preferences=%s",
            {
                "cuisines": sorted(preference_profile.cuisines),
                "diet": preference_profile.diet,
                "favorite_items": sorted(preference_profile.favorite_items),
            },
        )

    scored_candidates: list[CandidateScore] = []
    for menu_item, restaurant, restaurant_location in candidates:
        preference_match = _preference_affinity_score(menu_item, restaurant, preference_profile, {})
        cuisine_category_match = _clamp(
            (_cuisine_preference_score(menu_item, restaurant, preference_profile, {}) * 0.55)
            + (_category_preference_score(menu_item, preference_profile, {}) * 0.45)
        )
        diet_match = _diet_match_score(menu_item, preference_profile)
        popularity = _popularity_score(menu_item, max_popularity=max_popularity)
        new_item_boost, new_item_components = _new_item_boost_score(
            menu_item,
            restaurant,
            preferences=preference_profile,
            history_profile=None,
            historical_cuisine_scores={},
            popularity=popularity,
            preference_signal_scores=preference_signal_scores,
            history_signal_scores={},
            order_history_components=None,
        )
        base_score = (
            (preference_match * 0.68)
            + (cuisine_category_match * 0.17)
            + (diet_match * 0.10)
            + (popularity * 0.05)
        )
        total_score = _clamp(base_score + (new_item_boost * 0.16))

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Guest recommendation item=%s restaurant=%s preference_match=%.4f cuisine_category=%.4f diet=%.4f popularity=%.4f new_item=%s new_item_boost=%.4f new_item_components=%s total=%.4f",
                menu_item.name,
                restaurant.name,
                preference_match,
                cuisine_category_match,
                diet_match,
                popularity,
                is_menu_item_new(menu_item),
                new_item_boost,
                new_item_components,
                total_score,
            )

        recommendation_label, recommendation_reason, new_item_reason = (
            _build_recommendation_metadata(
                menu_item,
                restaurant,
                preferences=preference_profile,
                history_profile=None,
                preference_match=preference_match,
                order_history=0.0,
                popularity=popularity,
                new_item_components=new_item_components,
            )
        )

        scored_candidates.append(
            CandidateScore(
                menu_item=menu_item,
                restaurant=restaurant,
                restaurant_location=restaurant_location,
                total_score=round(total_score, 4),
                breakdown=RecommendationScoreBreakdown(
                    cuisine_match=round(cuisine_category_match, 4),
                    order_history=0.0,
                    popularity=round(popularity, 4),
                    budget_fit=round(diet_match, 4),
                    novelty=0.0,
                ),
                recommendation_label=recommendation_label,
                recommendation_reason=recommendation_reason,
                new_item_reason=new_item_reason,
            )
        )

    ranked_candidates = _sort_candidates(scored_candidates)
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Final guest recommendation order: %s",
            [candidate.menu_item.name for candidate in ranked_candidates],
        )

    return _serialize_recommendations(ranked_candidates)


def _build_fallback_recommendations(db: Session) -> list[RecommendationItemResponse]:
    candidates = db.execute(_build_candidate_query()).all()
    if not candidates:
        return []
    hydrate_dynamic_bestseller_flags(db, [menu_item for menu_item, _, _ in candidates])

    max_popularity = max(float(_safe_decimal(menu_item.popularity_score)) for menu_item, _, _ in candidates)
    scored_candidates: list[CandidateScore] = []
    for menu_item, restaurant, restaurant_location in candidates:
        popularity = _popularity_score(menu_item, max_popularity=max_popularity)
        open_boost = 0.1 if restaurant.is_open else 0.0
        new_item_boost, new_item_components = _new_item_boost_score(
            menu_item,
            restaurant,
            preferences=None,
            history_profile=None,
            historical_cuisine_scores={},
            popularity=popularity,
            preference_signal_scores={},
            history_signal_scores={},
            order_history_components=None,
        )
        total_score = _clamp((popularity * 0.82) + open_boost + (new_item_boost * 0.18))

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "Fallback recommendation item=%s restaurant=%s popularity=%.4f new_item=%s new_item_boost=%.4f new_item_components=%s total=%.4f",
                menu_item.name,
                restaurant.name,
                popularity,
                is_menu_item_new(menu_item),
                new_item_boost,
                new_item_components,
                total_score,
            )

        recommendation_label, recommendation_reason, new_item_reason = (
            _build_recommendation_metadata(
                menu_item,
                restaurant,
                preferences=None,
                history_profile=None,
                preference_match=0.0,
                order_history=0.0,
                popularity=popularity,
                new_item_components=new_item_components,
            )
        )

        scored_candidates.append(
            CandidateScore(
                menu_item=menu_item,
                restaurant=restaurant,
                restaurant_location=restaurant_location,
                total_score=round(total_score, 4),
                breakdown=RecommendationScoreBreakdown(
                    cuisine_match=0.0,
                    order_history=0.0,
                    popularity=round(popularity, 4),
                    budget_fit=0.0,
                    novelty=0.0,
                ),
                recommendation_label=recommendation_label,
                recommendation_reason=recommendation_reason,
                new_item_reason=new_item_reason,
            )
        )

    ranked_candidates = _sort_candidates(scored_candidates)
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug(
            "Final fallback recommendation order: %s",
            [candidate.menu_item.name for candidate in ranked_candidates],
        )

    return _serialize_recommendations(ranked_candidates)


def serialize_user_preferences(model: UserPreferences) -> UserPreferencesResponse:
    diet = _normalize_diet_value(model.dietary_preferences)

    budget = _normalize_budget_tier(model.budget_tier)
    if not budget:
        average_budget = float(_safe_decimal(model.average_budget))
        if average_budget > 0:
            if average_budget <= 250:
                budget = "LOW"
            elif average_budget <= 500:
                budget = "MID"
            else:
                budget = "HIGH"

    return UserPreferencesResponse(
        cuisines=_clean_string_list(model.favorite_cuisines),
        diet=diet,
        spice_level=_normalize_spice_level(model.spice_level),
        budget=budget,
        favorite_items=_clean_string_list(model.favorite_items),
        updated_at=model.updated_at,
    )


def _recommendation_cache_key(
    user_id: uuid.UUID,
    restaurant_id: uuid.UUID | None = None,
) -> str:
    """Cache key for one user in one app scope.

    The scope segment is essential: the same user can browse the marketplace on
    the web and a single-restaurant app on mobile, and the two must never share
    a cached payload.
    """

    scope = str(restaurant_id) if restaurant_id else "all"
    return f"recommendations:{user_id}:{scope}"


def invalidate_user_recommendation_cache(user_id: uuid.UUID) -> None:
    # Every scope for this user, not just the unscoped one.
    cache_delete_pattern(f"recommendations:{user_id}:*")


def invalidate_all_recommendation_caches() -> None:
    cache_delete_pattern("recommendations:*")


def _serialize_recommendation_cache_payload(
    items: list[RecommendationItemResponse],
) -> list[dict[str, object]]:
    return [item.model_dump(mode="json") for item in items]


def _deserialize_recommendation_cache_payload(
    payload: object,
) -> list[RecommendationItemResponse] | None:
    if not isinstance(payload, list):
        return None
    try:
        return [RecommendationItemResponse.model_validate(item) for item in payload]
    except Exception:
        logger.warning("Recommendation cache payload validation failed")
        return None


def _finalize_recommendations(
    items: list[RecommendationItemResponse],
    *,
    dedupe_multi_location: bool,
    location_context: RecommendationLocationContext | None,
) -> list[RecommendationItemResponse]:
    if dedupe_multi_location:
        return _dedupe_multi_location_recommendations(
            items,
            location_context=location_context,
            limit=MAX_RECOMMENDATIONS,
        )
    return items[:MAX_RECOMMENDATIONS]


def _recommendation_group_key(item: RecommendationItemResponse) -> tuple[str, str, str, str, bool]:
    return (
        str(item.restaurant_id),
        _normalize_choice_key(item.name),
        _normalize_choice_key(item.category),
        _normalize_choice_key(item.cuisine_type or item.restaurant.cuisine_type),
        item.is_veg,
    )


def _safe_float(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    return float(value)


def _distance_km(
    latitude_a: float | None,
    longitude_a: float | None,
    latitude_b: float | None,
    longitude_b: float | None,
) -> float | None:
    if None in {latitude_a, longitude_a, latitude_b, longitude_b}:
        return None

    lat1 = radians(latitude_a)
    lon1 = radians(longitude_a)
    lat2 = radians(latitude_b)
    lon2 = radians(longitude_b)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    haversine = (
        sin(delta_lat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(delta_lon / 2) ** 2
    )
    return 6371 * 2 * asin(sqrt(haversine))


def _select_preferred_recommendation_item(
    items: list[RecommendationItemResponse],
    *,
    location_context: RecommendationLocationContext | None,
) -> RecommendationItemResponse:
    normalized_city = _normalize_text(location_context.city) if location_context else ""
    context_latitude = location_context.latitude if location_context else None
    context_longitude = location_context.longitude if location_context else None

    def ranking_key(item: RecommendationItemResponse) -> tuple[float, ...]:
        city_match = (
            1.0
            if normalized_city
            and _normalize_text(item.restaurant_location.city) == normalized_city
            else 0.0
        )
        distance = _distance_km(
            context_latitude,
            context_longitude,
            _safe_float(getattr(item.restaurant_location, "latitude", None)),
            _safe_float(getattr(item.restaurant_location, "longitude", None)),
        )
        distance_score = 0.0 if distance is None else 1 / (1 + distance)
        return (
            city_match,
            distance_score,
            1.0 if item.restaurant_location.is_open else 0.0,
            1.0 if item.restaurant.is_open else 0.0,
            item.score,
            -float(_safe_decimal(item.price)),
        )

    return max(items, key=ranking_key)


def _dedupe_multi_location_recommendations(
    items: list[RecommendationItemResponse],
    *,
    location_context: RecommendationLocationContext | None,
    limit: int,
) -> list[RecommendationItemResponse]:
    if not items:
        return []

    grouped_items: dict[tuple[str, str, str, str, bool], list[RecommendationItemResponse]] = {}
    grouped_order: list[tuple[str, str, str, str, bool]] = []
    for item in items:
        key = _recommendation_group_key(item)
        if key not in grouped_items:
            grouped_items[key] = []
            grouped_order.append(key)
        grouped_items[key].append(item)

    deduped: list[RecommendationItemResponse] = []
    for key in grouped_order:
        variants = grouped_items[key]
        if len(variants) == 1:
            single = variants[0].model_copy(
                update={
                    "display_price": variants[0].price,
                    "price_label": None,
                    "available_locations_count": 1,
                    "preferred_menu_item_id": variants[0].id,
                    "preferred_location_id": variants[0].restaurant_location_id,
                    "preferred_location_name": variants[0].restaurant_location.branch_name,
                    "requires_location_selection": False,
                    "location_variants": [
                        RecommendationLocationVariantSummary(
                            menu_item_id=variants[0].id,
                            restaurant_location_id=variants[0].restaurant_location_id,
                            branch_name=variants[0].restaurant_location.branch_name,
                            city=variants[0].restaurant_location.city,
                            price=variants[0].price,
                            is_open=variants[0].restaurant_location.is_open,
                            is_active=variants[0].restaurant_location.is_active,
                        )
                    ],
                }
            )
            deduped.append(single)
            continue

        preferred = _select_preferred_recommendation_item(
            variants,
            location_context=location_context,
        )
        lowest_price = min((variant.price for variant in variants), key=_safe_decimal)
        location_variants = [
            RecommendationLocationVariantSummary(
                menu_item_id=variant.id,
                restaurant_location_id=variant.restaurant_location_id,
                branch_name=variant.restaurant_location.branch_name,
                city=variant.restaurant_location.city,
                price=variant.price,
                is_open=variant.restaurant_location.is_open,
                is_active=variant.restaurant_location.is_active,
            )
            for variant in sorted(
                variants,
                key=lambda variant: (
                    float(_safe_decimal(variant.price)),
                    0 if variant.restaurant_location.is_open else 1,
                    variant.restaurant_location.branch_name.lower(),
                ),
            )
        ]
        deduped.append(
            preferred.model_copy(
                update={
                    "display_price": lowest_price,
                    "price_label": f"From ₹{lowest_price:.2f}",
                    "available_locations_count": len(location_variants),
                    "preferred_menu_item_id": preferred.id,
                    "preferred_location_id": preferred.restaurant_location_id,
                    "preferred_location_name": preferred.restaurant_location.branch_name,
                    "requires_location_selection": location_context is None,
                    "location_variants": location_variants,
                }
            )
        )

    deduped.sort(
        key=lambda item: (
            item.score,
            float(_safe_decimal(item.popularity_score)),
            item.available_locations_count,
            1 if item.restaurant.is_open else 0,
        ),
        reverse=True,
    )
    return deduped[:limit]


def _scope_recommendations(
    items: list[RecommendationItemResponse],
    restaurant_id: uuid.UUID | None,
) -> list[RecommendationItemResponse]:
    """Narrow recommendations to a single restaurant, if the app is scoped."""

    if restaurant_id is None:
        return items
    return [item for item in items if item.restaurant_id == restaurant_id]


def get_deterministic_recommendations_for_user(
    db: Session,
    user: User,
    *,
    restaurant_id: uuid.UUID | None = None,
) -> list[RecommendationItemResponse]:
    cache_key = _recommendation_cache_key(user.id, restaurant_id)
    cached_payload = cache_get_json(cache_key)
    cached_items = _deserialize_recommendation_cache_payload(cached_payload)
    if cached_items is not None:
        return cached_items

    items = _scope_recommendations(
        _build_logged_in_recommendations(
            db,
            user,
            _model_to_profile(_load_user_preferences(db, user.id)),
        ),
        restaurant_id,
    )
    cache_set_json(cache_key, _serialize_recommendation_cache_payload(items))
    return items


def get_user_preferences_response(db: Session, user: User) -> UserPreferencesResponse | None:
    model = _load_user_preferences(db, user.id)
    if model is None:
        return None
    return serialize_user_preferences(model)


def upsert_user_preferences(
    db: Session,
    user: User,
    payload: UserPreferencesPayload,
) -> UserPreferencesResponse:
    model = _load_user_preferences(db, user.id)
    if model is None:
        model = UserPreferences(user_id=user.id)
        db.add(model)

    model.favorite_cuisines = _clean_string_list(payload.cuisines)
    model.disliked_cuisines = _clean_string_list(model.disliked_cuisines)
    model.dietary_preferences = [diet] if (diet := _normalize_diet_value([payload.diet])) else []
    model.preferred_meal_times = _clean_string_list(model.preferred_meal_times)
    model.cuisine_affinity_scores = (
        model.cuisine_affinity_scores
        if isinstance(model.cuisine_affinity_scores, dict)
        else {}
    )
    model.spice_level = _normalize_spice_level(payload.spice_level)
    model.budget_tier = _normalize_budget_tier(payload.budget)
    model.favorite_items = _clean_string_list(payload.favorite_items)
    model.average_budget = Decimal(str(_budget_to_amount(model.budget_tier)))
    model.price_sensitivity = Decimal(str(_budget_to_sensitivity(model.budget_tier)))

    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise

    db.refresh(model)
    invalidate_user_recommendation_cache(user.id)
    from app.services.personalized_offers import invalidate_user_personalized_offers_cache
    from app.services.rag import invalidate_user_chat_caches

    invalidate_user_personalized_offers_cache(user.id)
    invalidate_user_chat_caches(user.id)
    from app.services.ai_recommendations import queue_ai_recommendation_refresh

    queue_ai_recommendation_refresh(
        user_id=user.id,
        reason="preferences_updated",
        force_refresh=True,
    )
    return serialize_user_preferences(model)


def get_recommendations_for_request(
    db: Session,
    user: User | None,
    preference_payload: UserPreferencesPayload | None = None,
    *,
    dedupe_multi_location: bool = False,
    location_context: RecommendationLocationContext | None = None,
    restaurant_id: uuid.UUID | None = None,
) -> list[RecommendationItemResponse]:
    payload_profile = _payload_to_profile(preference_payload)

    if user is not None and preference_payload is None:
        return get_recommendations_for_user(
            db,
            user,
            dedupe_multi_location=dedupe_multi_location,
            location_context=location_context,
            restaurant_id=restaurant_id,
        )

    # Every remaining path is scoped before it is returned, so a scoped app
    # cannot receive another restaurant's dishes through the guest, merged
    # preference, or fallback branches.
    if user is not None:
        stored_profile = _model_to_profile(_load_user_preferences(db, user.id))
        merged_profile = _merge_profiles(stored_profile, payload_profile)
        return _finalize_recommendations(
            _scope_recommendations(
                _build_logged_in_recommendations(db, user, merged_profile),
                restaurant_id,
            ),
            dedupe_multi_location=dedupe_multi_location,
            location_context=location_context,
        )

    if payload_profile is not None and payload_profile.is_meaningful:
        return _finalize_recommendations(
            _scope_recommendations(
                _build_guest_preference_recommendations(db, payload_profile),
                restaurant_id,
            ),
            dedupe_multi_location=dedupe_multi_location,
            location_context=location_context,
        )

    return _finalize_recommendations(
        _scope_recommendations(_build_fallback_recommendations(db), restaurant_id),
        dedupe_multi_location=dedupe_multi_location,
        location_context=location_context,
    )


def get_recommendations_for_user(
    db: Session,
    user: User,
    *,
    dedupe_multi_location: bool = False,
    location_context: RecommendationLocationContext | None = None,
    restaurant_id: uuid.UUID | None = None,
) -> list[RecommendationItemResponse]:
    items = get_deterministic_recommendations_for_user(db, user, restaurant_id=restaurant_id)
    if dedupe_multi_location:
        from app.services.ai_recommendations import apply_cached_ai_recommendations

        # The AI layer may reorder or substitute, so re-apply the scope after it.
        return _scope_recommendations(
            apply_cached_ai_recommendations(
                db,
                user=user,
                items=items,
                location_context=location_context,
            ),
            restaurant_id,
        )

    return _finalize_recommendations(
        items,
        dedupe_multi_location=dedupe_multi_location,
        location_context=location_context,
    )

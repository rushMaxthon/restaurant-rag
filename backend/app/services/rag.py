from __future__ import annotations

import json
import hashlib
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
from time import perf_counter
from typing import Any, Iterator

import httpx
from fastapi import HTTPException, status
from sqlalchemy import Select, case, delete, desc, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.chat_history import ChatHistory
from app.models.enums import ChatMessageRole
from app.models.menu_embedding import MenuEmbedding
from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.models.user_preferences import UserPreferences
from app.schemas.chat import ChatHistoryItemResponse, ChatMessageResponse, ChatSuggestionItem
from app.schemas.generated_combo import GeneratedComboResponse
from app.schemas.personalized_offer import PersonalizedOfferCardResponse
from app.services.bestsellers import (
    get_menu_item_featured_flag,
    hydrate_dynamic_bestseller_flags,
    is_menu_item_bestseller,
)
from app.services.cache import cache_delete, cache_delete_pattern, cache_get_json, cache_set_json, normalize_cache_query
from app.services.favorites import apply_chat_suggestion_favorite_flags, get_user_favorite_ids
from app.services.generated_combos import find_generated_combos_for_query
from app.services.menu_item_metadata import (
    CUISINE_SIGNAL_KEYS,
    NORMALIZED_SPICY_KEYWORDS,
    extract_menu_item_signals,
    get_new_item_reason,
    is_high_popularity_value,
    is_menu_item_new,
    is_menu_item_trending,
    resolve_menu_item_launch_timestamp,
)
from app.services.personalized_offers import get_personalized_offers_for_user

settings = get_settings()
logger = logging.getLogger(__name__)

# Generation and embeddings are addressed separately, because they can live on
# different hosts: Ollama Cloud serves generation but no embedding route, so
# retrieval stays on a local Ollama while the reply may be written in the cloud.
# Both endpoints and both sets of auth headers come from the shared module.
from app.services.embeddings import EmbeddingError, get_embedding
from app.services.ollama_client import (
    think_option,
    EMBED_ENDPOINT,
    GENERATE_ENDPOINT,
    HTTP_LIMITS,
    build_client,
    local_only_options,
)

GENERATE_TIMEOUT = httpx.Timeout(
    connect=5.0,
    read=settings.ollama_chat_timeout_seconds,
    write=10.0,
    pool=5.0,
)

GENERATE_CLIENT = build_client(GENERATE_TIMEOUT, limits=HTTP_LIMITS)

TOP_K_RESULTS = settings.rag_top_k_results
HISTORY_MESSAGES = settings.rag_history_messages
SUGGESTION_LIMIT = settings.rag_suggestion_limit
MAX_CONTEXT_CANDIDATES = settings.rag_max_context_candidates
MAX_DESCRIPTION_CHARS = settings.rag_max_description_chars
SESSION_CACHE_PREFIX = "chat:session"
SESSION_STATE_CACHE_PREFIX = "chat:session-state"
EMBEDDING_CACHE_PREFIX = "rag:embedding"
RESPONSE_CACHE_PREFIX = "rag:response"
GREETING_RESPONSE_CACHE_PREFIX = "rag:response:greeting"

SYSTEM_PROMPT = """You are a premium food concierge for a restaurant ordering app.
Sound warm, polished, and genuinely helpful. Stay focused on food, restaurants, menus, offers, combos, and ordering.

Hard rules:
- use only the provided database-backed menu context
- never invent items, prices, restaurants, discounts, or availability
- never answer unrelated general-knowledge questions
- if an exact item is unavailable, say so naturally and suggest the closest grounded alternatives from context
- if the user asks for multiple foods, treat them as separate food intents

Style rules:
- 1 to 3 short sentences; lead with the best suggestion
- explain why a suggestion fits when the context supports it
- vary phrasing; never sound templated ("Here are some recommendations." is bad tone)
- a light food emoji occasionally is fine
- if the user is refining a previous request, continue the thread naturally
"""

INTENT_PROMPT = """You are an intent extraction system for a food ordering assistant.
Return JSON only.
Infer the user's current request and extract any grounded filters.
Use one of these intents only:
- greeting
- small_talk
- menu_question
- dish_recommendation
- restaurant_list
- recommendation
- offer_query
- order_history
- unsupported_domain
- invalid_input
- show_more
- other

Rules:
- show_more means the user wants continuation of the last recommendation flow.
- small_talk means the user is asking about your capabilities or chatting casually without asking for food yet.
- menu_question means the user asks about a specific item's price, cost, ingredients, contents, allergens, spice level, portion size, or whether it is veg. Set dish to the item name if the user names it; if they say "it"/"this"/"that", keep dish null.
- If the user asks for a specific dish or item, use dish_recommendation.
- If the user asks for restaurants, use restaurant_list.
- If the user asks generally for food ideas, use recommendation.
- If the user asks about offers, coupons, discounts, or deals, use offer_query.
- If the user asks about previous orders, reorders, or past food history, use order_history.
- If the user asks something outside food, restaurants, menus, dining, orders, or offers, use unsupported_domain.
- If the user input is gibberish, spammy, or impossible to parse, use invalid_input.
- If the user asks what is new, latest, or newly launched, keep the best-fit intent and set new_only to true.
- If a field is unknown, return null.
- Keep booleans as true/false and budget as a number or null.
Return exactly this shape:
{
  "intent": "dish_recommendation",
  "dish": null,
  "items": [],
  "cuisine": null,
  "category": null,
  "restaurant_query": null,
  "budget": null,
  "diet": null,
  "spicy": null,
  "mood": null,
  "show_more": false,
  "new_only": false
}
"""

SMALL_TALK_PROMPT = """You are a friendly restaurant food concierge.
The user is making casual small talk, not asking for food yet.
Reply warmly and briefly: 1 to 2 short sentences.
Respond to what they actually said in a light, human way, then gently invite them toward the menu, a craving, or a recommendation.
Do not mention specific menu items, prices, or restaurants. Never invent anything.

Good examples:
- "Going great over here — always better when someone's hungry 😄 What are you in the mood for?"
- "I'm doing well, thanks for asking! Ready to find you something delicious whenever you are."
"""

GREETING_PROMPT = """You are a premium restaurant food concierge.
The user is only greeting you.
Reply naturally, warmly, and briefly.
Invite them to share a craving, cuisine, budget, spice preference, or meal mood.
Do not mention specific menu items unless the user asks for food.
Keep the reply under 2 short sentences.

Good examples:
- "Hey 👋 What are you craving today?"
- "Good evening. Want something spicy, comforting, or budget-friendly tonight?"
"""

GENERIC_REPLY_MARKERS = (
    "don't have access",
    "do not have access",
    "i currently don't have access",
    "i currently do not have access",
    "sorry, this item is not available",
    "sorry, that item is not available",
    "menu is not available",
    "i can't access",
)

FOOD_DOMAIN_KEYWORDS = {
    "food",
    "foods",
    "dish",
    "dishes",
    "menu",
    "menus",
    "restaurant",
    "restaurants",
    "eat",
    "eating",
    "meal",
    "meals",
    "breakfast",
    "lunch",
    "dinner",
    "snack",
    "snacks",
    "dessert",
    "desserts",
    "drink",
    "drinks",
    "beverage",
    "beverages",
    "combo",
    "combos",
    "offer",
    "offers",
    "coupon",
    "coupons",
    "discount",
    "discounts",
    "deal",
    "deals",
    "order",
    "orders",
    "reorder",
    "healthy",
    "protein",
    "veg",
    "vegetarian",
    "vegan",
    "nonveg",
    "non",
    "spicy",
    "budget",
    "cheap",
    "affordable",
    "craving",
    "cravings",
    "pizza",
    "burger",
    "pasta",
    "biryani",
    "momo",
    "momos",
    "noodles",
    "paneer",
    "chicken",
    "thai",
    "indian",
    "italian",
    "chinese",
}

SMALL_TALK_MARKERS = (
    "how are you",
    "who are you",
    "what can you do",
    "help me",
    "can you help me",
    "how can you help",
    "what do you do",
    "how do you work",
    "how is your day",
    "hows your day",
    "how was your day",
    "how is it going",
    "hows it going",
    "how are things",
    "whats up",
    "how do you do",
)

ACKNOWLEDGEMENT_PHRASES = {
    "nice",
    "great",
    "thats great",
    "awesome",
    "cool",
    "perfect",
    "sounds good",
    "good",
    "ok",
    "okay",
    "love it",
    "got it",
}

MENU_QUESTION_PHRASES = (
    "what is in",
    "whats in",
    "how much",
    "made of",
    "what size",
    "how big",
    "how spicy",
    "price of",
    "cost of",
    "is it veg",
    "is this veg",
    "is that veg",
    "is it vegetarian",
    "is this vegetarian",
    "is it non veg",
    "is this non veg",
    "is it spicy",
    "is this spicy",
    "is that spicy",
    "does it contain",
    "does this contain",
    "does it have",
    "does this have",
)

MENU_QUESTION_TOKENS = {
    "price",
    "prices",
    "cost",
    "costs",
    "ingredient",
    "ingredients",
    "calorie",
    "calories",
    "allergen",
    "allergens",
    "allergy",
    "allergies",
    "portion",
    "portions",
    "size",
    "sizes",
}

MENU_QUESTION_PRONOUNS = {"it", "this", "that", "these", "those", "them", "one"}

ORDER_HISTORY_MARKERS = (
    "my last order",
    "last order",
    "recent order",
    "previous order",
    "past order",
    "ordered before",
    "order before",
    "reorder",
    "order again",
)

OFFER_QUERY_MARKERS = (
    "offer",
    "offers",
    "coupon",
    "coupons",
    "discount",
    "discounts",
    "deal",
    "deals",
    "promo",
    "promocode",
    "promo code",
)

UNSUPPORTED_QUERY_PATTERNS = (
    r"^(?:who|what|when|where|why|how)\s+(?:is|are|was|were)\b",
    r"^whats?\s+the\b",
    r"^do you know\b",
    r"^tell me about\b",
    r"^explain\b",
)

FOLLOW_UP_MESSAGE_MARKERS = (
    "give me more",
    "show me more",
    "show me some more",
    "more options",
    "any other options",
    "other options",
    "what else",
    "what else do you have",
    "any more",
    "more like this",
    "another one",
    "another option",
    "something else",
    "something different",
    "different ones",
    "show more",
    "anything else",
)

FOLLOW_UP_STOPWORDS = {
    "are",
    "there",
    "give",
    "show",
    "me",
    "more",
    "any",
    "another",
    "other",
    "what",
    "options",
    "option",
    "something",
    "else",
    "different",
    "different",
    "ones",
    "any",
    "other",
    "another",
    "please",
}

QUERY_STOPWORDS = {
    "a",
    "an",
    "and",
    "any",
    "can",
    "could",
    "do",
    "for",
    "get",
    "have",
    "i",
    "is",
    "me",
    "please",
    "recommend",
    "show",
    "some",
    "suggest",
    "tell",
    "the",
    "type",
    "types",
    "we",
    "what",
    "which",
    "available",
    "would",
    "you",
}

TOPIC_STOPWORDS = QUERY_STOPWORDS | {
    "about",
    "anything",
    "dish",
    "dishes",
    "food",
    "foods",
    "item",
    "items",
    "menu",
    "menus",
    "option",
    "options",
    "something",
    "whats",
}

PERSONALIZED_QUERY_MARKERS = (
    "my ",
    "me ",
    "mine",
    "again",
    "last order",
    "previous order",
    "for me",
    "my preferences",
    "my taste",
    "my usual",
    "based on my",
)

NEW_QUERY_MARKERS = (
    "what's new",
    "whats new",
    "what is new",
    "anything new",
    "any new",
    "new item",
    "new items",
    "new dish",
    "new dishes",
    "latest item",
    "latest items",
    "latest dish",
    "latest dishes",
    "recently launched",
    "just launched",
    "new on the menu",
)


@dataclass
class RetrievedMenuCandidate:
    menu_item: MenuItem
    restaurant: Restaurant
    distance: float
    source: str = "vector"


@dataclass
class RagStageTimings:
    cache_lookup_ms: float = 0.0
    session_state_ms: float = 0.0
    intent_ms: float = 0.0
    preferences_ms: float = 0.0
    history_ms: float = 0.0
    keyword_ms: float = 0.0
    db_filter_ms: float = 0.0
    embedding_ms: float = 0.0
    vector_ms: float = 0.0
    prompt_ms: float = 0.0
    llm_ms: float = 0.0
    db_commit_ms: float = 0.0
    total_ms: float = 0.0


@dataclass
class PreparedChatTurn:
    active_session_id: uuid.UUID
    message: str
    effective_message: str
    restaurant_id: uuid.UUID | None
    retrieval_source: str
    is_greeting: bool
    is_follow_up: bool
    uses_personal_context: bool
    should_bypass_llm: bool
    suggestion_limit: int
    vector_result_count: int
    extracted_intent: "ExtractedIntent"
    session_state: "SessionConversationState"
    final_candidates: list[RetrievedMenuCandidate]
    suggestions: list[ChatSuggestionItem]
    history_messages: list[ChatHistory]
    history_block: str
    context_block: str
    prompt: str
    timings: RagStageTimings
    combo_suggestions: list[GeneratedComboResponse] = field(default_factory=list)
    offer_suggestions: list[PersonalizedOfferCardResponse] = field(default_factory=list)
    fallback_reply: str | None = None


@dataclass
class ExtractedIntent:
    intent: str
    dish: str | None = None
    items: list[str] | None = None
    cuisine: str | None = None
    category: str | None = None
    restaurant_query: str | None = None
    budget: Decimal | None = None
    diet: str | None = None
    spicy: bool | None = None
    mood: str | None = None
    show_more: bool = False
    new_only: bool = False


@dataclass
class SessionConversationState:
    last_intent: str | None = None
    active_intent: str | None = None
    base_query: str | None = None
    active_topic: str | None = None
    dish: str | None = None
    items: list[str] | None = None
    cuisine: str | None = None
    category: str | None = None
    restaurant_query: str | None = None
    budget: Decimal | None = None
    diet: str | None = None
    spicy: bool | None = None
    mood: str | None = None
    new_only: bool = False
    last_successful_user_query: str | None = None
    last_recommendation_context: dict[str, Any] | None = None
    seen_item_ids: set[uuid.UUID] | None = None
    previous_restaurants: set[uuid.UUID] | None = None

    def __post_init__(self) -> None:
        if self.seen_item_ids is None:
            self.seen_item_ids = set()
        if self.previous_restaurants is None:
            self.previous_restaurants = set()
        if self.items is not None:
            self.items = [item for item in self.items if item]


@dataclass
class CacheQueryDescriptor:
    normalized_message: str
    cache_intent: str
    topic: str | None
    budget: Decimal | None
    diet: str | None
    spicy: bool | None
    new_only: bool = False


def _safe_decimal(value: Decimal | float | int | None) -> Decimal:
    if value is None:
      return Decimal("0")
    if isinstance(value, Decimal):
      return value
    return Decimal(str(value))


def _normalize_text(value: str) -> str:
    return normalize_cache_query(value)


def _normalize_match_text(value: str) -> str:
    """Punctuation-free normalization for exact-phrase matchers.

    `_normalize_text` keeps punctuation (it feeds cache keys), which made
    "thanks!" or "hi!" miss the greeting/acknowledgement sets and fall through
    to full retrieval.
    """
    # Apostrophes vanish (what's -> whats) so contractions still hit phrase
    # markers; every other symbol becomes a space.
    stripped = _normalize_text(value).replace("'", "").replace("’", "")
    stripped = re.sub(r"[^a-z0-9\s]", " ", stripped)
    return re.sub(r"\s+", " ", stripped).strip()


def _trim_text(value: str, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip())
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[: max_chars - 1].rstrip()}…"


def _current_meal_moment() -> str:
    hour = datetime.now().hour
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 16:
        return "midday"
    if 16 <= hour < 19:
        return "evening"
    return "night"


def _time_of_day_prompt_hint() -> str:
    moment = _current_meal_moment()
    if moment == "morning":
        return "It is morning. Lighter breakfast-friendly phrasing can feel natural when relevant."
    if moment == "midday":
        return "It is midday. Lunch-friendly phrasing can feel natural when relevant."
    if moment == "evening":
        return "It is evening. Dinner-friendly phrasing can feel natural when relevant."
    return "It is night. Late-evening or comfort-food phrasing can feel natural when relevant."


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _dedupe_topics(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(value)
    return deduped


def _singularize_token(token: str) -> str:
    if len(token) <= 3:
        return token
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith(("ches", "shes", "xes", "zes", "ses")) and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _query_tokens(message: str) -> list[str]:
    tokens = re.split(r"[^a-z0-9]+", _normalize_text(message))
    filtered: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if len(token) < 3 or token in seen or token in QUERY_STOPWORDS:
            continue
        seen.add(token)
        filtered.append(token)
    return filtered


def _canonicalize_topic(value: str | None) -> str | None:
    if value is None:
        return None
    tokens = [
        _singularize_token(token)
        for token in _query_tokens(value)
        if token not in TOPIC_STOPWORDS
    ]
    if not tokens:
        return None
    return " ".join(tokens[:3])


def _extract_bare_topic_hint(message: str) -> str | None:
    if _is_follow_up_recommendation_message(message):
        return None

    normalized = _normalize_text(message)
    if not normalized or _is_greeting_message(message) or _is_acknowledgement_message(message):
        return None
    if "restaurant" in normalized:
        return None

    candidate_tokens = [
        _singularize_token(token)
        for token in _query_tokens(message)
        if not token.isdigit()
        and token
        not in {
            "about",
            "anything",
            "food",
            "foods",
            "dish",
            "dishes",
            "item",
            "items",
            "menu",
            "menus",
            "restaurant",
            "restaurants",
            "something",
            "veg",
            "vegetarian",
            "non",
            "spicy",
            "starter",
            "whats",
        }
    ]
    if not candidate_tokens or len(candidate_tokens) > 3:
        return None

    if "non veg" in normalized or "non-veg" in normalized:
        return None
    if any(term in normalized for term in ("veg food", "vegetarian food", "spicy food", "restaurant list")):
        return None

    if not _has_food_domain_signal(message):
        return None

    return " ".join(candidate_tokens[:3])


def _extract_direct_item_hint(message: str) -> str | None:
    if _is_follow_up_recommendation_message(message):
        return None
    normalized = _normalize_text(message)
    patterns = (
        r"^(?:which|what)\s+(?:type|types|kind|kinds)\s+of\s+(.+?)(?:\s+(?:do\s+)?you\s+have)?[?.!]*$",
        r"^(?:which|what)\s+(.+?)\s+(?:do\s+)?you\s+have[?.!]*$",
        r"^(?:what|which)\s+(?:does|do)\s+(.+?)\s+(?:have|offer|serve)[?.!]*$",
        r"^(?:do you have|can i get|can you suggest|can you recommend|show me|suggest|recommend|any)\s+(.+?)[?.!]*$",
        r"^(?:i want|i need|looking for|i like|i love|i crave|craving|feel like)\s+(.+?)[?.!]*$",
    )
    for pattern in patterns:
        matched = re.match(pattern, normalized)
        if not matched:
            continue
        candidate = re.sub(r"\b(?:please|today|now)\b", "", matched.group(1)).strip(" ?!.,")
        canonical_candidate = _canonicalize_topic(candidate)
        if canonical_candidate:
            return canonical_candidate
        candidate_tokens = _query_tokens(candidate)
        if candidate_tokens:
            return " ".join(_singularize_token(token) for token in candidate_tokens)
    return _extract_bare_topic_hint(message)


def _extract_multi_item_hints(message: str) -> list[str]:
    if _is_follow_up_recommendation_message(message):
        return []

    normalized = _normalize_text(message)
    candidate: str | None = None
    patterns = (
        r"^(?:which|what)\s+(?:type|types|kind|kinds)\s+of\s+(.+?)(?:\s+(?:do\s+)?you\s+have)?[?.!]*$",
        r"^(?:which|what)\s+(.+?)\s+(?:do\s+)?you\s+have[?.!]*$",
        r"^(?:do you have|can i get|can you suggest|can you recommend|show me|suggest|recommend|any)\s+(.+?)[?.!]*$",
        r"^(?:i want|i need|looking for|i like|i love|i crave|craving|feel like)\s+(.+?)[?.!]*$",
    )
    for pattern in patterns:
        matched = re.match(pattern, normalized)
        if matched:
            candidate = matched.group(1)
            break

    if candidate is None and re.search(r"\b(?:and|or|with|plus)\b|,|/|&", normalized):
        candidate = normalized
    if not candidate:
        return []

    candidate = re.sub(
        r"\b(?:please|today|now|available|options|option|ideas|idea|something|want|looking|show|suggest|recommend)\b",
        " ",
        candidate,
    )
    parts = [
        part.strip(" ?!.,")
        for part in re.split(r"\b(?:and|or|with|plus)\b|,|/|&", candidate)
        if part.strip(" ?!.,")
    ]
    if len(parts) < 2:
        return []

    extracted: list[str] = []
    for part in parts:
        canonical = _canonicalize_topic(part)
        if canonical:
            extracted.append(canonical)
            continue
        candidate_tokens = _query_tokens(part)
        if candidate_tokens:
            extracted.append(" ".join(_singularize_token(token) for token in candidate_tokens))
    extracted = _dedupe_topics(extracted)
    return extracted if len(extracted) >= 2 else []


def _has_food_domain_signal(message: str) -> bool:
    normalized = _normalize_text(message)
    if not normalized:
        return False
    if any(marker in normalized for marker in OFFER_QUERY_MARKERS):
        return True
    if any(marker in normalized for marker in ORDER_HISTORY_MARKERS):
        return True
    if any(f" {cuisine_key} " in f" {normalized} " for cuisine_key in CUISINE_SIGNAL_KEYS):
        return True
    tokens = set(_query_tokens(message))
    return bool(tokens & FOOD_DOMAIN_KEYWORDS)


def _is_small_talk_message(message: str) -> bool:
    normalized = _normalize_match_text(message)
    if not normalized:
        return False
    return any(marker in normalized for marker in SMALL_TALK_MARKERS)


def _is_menu_question_message(message: str) -> bool:
    """Questions about a specific item's price, contents, or attributes."""
    normalized = _normalize_match_text(message)
    if not normalized:
        return False
    if any(phrase in normalized for phrase in MENU_QUESTION_PHRASES):
        return True
    return bool(set(_query_tokens(message)) & MENU_QUESTION_TOKENS)


def _extract_menu_question_dish(message: str) -> str | None:
    """The dish a menu question names, or None when it points at the
    conversation ("how much does it cost?")."""
    normalized = _normalize_match_text(message)
    patterns = (
        r"^(?:what|whats)\s+(?:is\s+)?in\s+(?:the\s+|a\s+|an\s+)?(.+?)$",
        r"^how\s+much\s+(?:is|are|does|do)\s+(?:the\s+|a\s+|an\s+)?(.+?)(?:\s+cost)?$",
        r"\b(?:price|prices|cost|ingredients|sizes?|calories)\s+(?:of|for|in)\s+(?:the\s+|a\s+|an\s+)?(.+?)$",
        r"^(?:is|are)\s+(?:the\s+|a\s+|an\s+)?(.+?)\s+(?:veg|vegetarian|non\s*veg|spicy)\b",
        r"^does\s+(?:the\s+|a\s+|an\s+)?(.+?)\s+(?:contain|have)\b",
    )
    for pattern in patterns:
        matched = re.search(pattern, normalized)
        if not matched:
            continue
        candidate = matched.group(1).strip()
        candidate_tokens = [token for token in candidate.split() if token]
        if not candidate_tokens or all(token in MENU_QUESTION_PRONOUNS for token in candidate_tokens):
            return None
        canonical = _canonicalize_topic(candidate)
        if canonical and not (set(canonical.split()) <= MENU_QUESTION_PRONOUNS):
            return canonical
        return None
    return None


def _is_contextual_menu_question(message: str) -> bool:
    """A menu question that relies on the session for which dish is meant."""
    return _is_menu_question_message(message) and _extract_menu_question_dish(message) is None


def _is_offer_query_message(message: str) -> bool:
    normalized = _normalize_text(message)
    if not normalized:
        return False
    return any(marker in normalized for marker in OFFER_QUERY_MARKERS)


def _is_order_history_message(message: str) -> bool:
    normalized = _normalize_text(message)
    if not normalized:
        return False
    return any(marker in normalized for marker in ORDER_HISTORY_MARKERS)


def _is_invalid_or_spam_message(message: str) -> bool:
    stripped = message.strip()
    if len(stripped) < 2:
        return True
    normalized = _normalize_text(message)
    if not normalized:
        return True
    if _is_small_talk_message(message) or _is_out_of_domain_message(message):
        return False
    if re.fullmatch(r"[\W_]+", stripped):
        return True
    if re.search(r"(.)\1{5,}", normalized):
        return True
    tokens = _query_tokens(message)
    if not tokens and not _is_greeting_message(message):
        return True
    return False


def _is_out_of_domain_message(message: str) -> bool:
    normalized = _normalize_text(message)
    if not normalized or _has_food_domain_signal(message):
        return False
    if _is_small_talk_message(message) or _is_greeting_message(message) or _is_acknowledgement_message(message):
        return False
    # A budget, follow-up, or menu-detail phrasing is an in-domain signal even
    # without a food keyword ("anything under 10 rupees?", "what is in it?").
    if _extract_budget_limit(message) is not None:
        return False
    if _is_follow_up_recommendation_message(message):
        return False
    if _is_menu_question_message(message):
        return False
    # Only explicit general-knowledge shapes are refused. The previous
    # any-question-mark heuristic rejected legitimate ordering questions like
    # "whats good here?" or "what does Luigi's have?".
    return any(re.match(pattern, normalized) for pattern in UNSUPPORTED_QUERY_PATTERNS)


def _message_requests_new_items(message: str) -> bool:
    normalized = _normalize_text(message)
    return any(marker in normalized for marker in NEW_QUERY_MARKERS)


def _extract_new_query_overrides(message: str) -> dict[str, Any]:
    normalized = _normalize_text(message)
    cleaned = re.sub(
        r"\b(?:what|what's|whats|is|any|show|me|for|latest|new|recent|recently|just|launched|launch|on|the|menu|item|items|dish|dishes|food|foods)\b",
        " ",
        normalized,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?!.,")

    cuisine: str | None = None
    for cuisine_key in sorted(CUISINE_SIGNAL_KEYS):
        if cuisine_key in normalized:
            cuisine = cuisine_key
            break

    diet: str | None = None
    if "vegetarian" in normalized or re.search(r"\bveg\b", normalized):
        diet = "veg"
    elif "non veg" in normalized or "non-veg" in normalized:
        diet = "non_veg"

    spicy = any(keyword in normalized for keyword in NORMALIZED_SPICY_KEYWORDS)

    dish: str | None = None
    if cleaned:
        topic = _canonicalize_topic(cleaned)
        if topic and topic not in CUISINE_SIGNAL_KEYS and topic not in {"spicy", "veg", "non veg"}:
            dish = topic

    return {
        "cuisine": cuisine,
        "diet": diet,
        "spicy": True if spicy else None,
        "dish": dish,
    }


def _is_combo_query(message: str, intent: ExtractedIntent | None = None) -> bool:
    if intent is not None and intent.category == "combo":
        return True
    normalized = _normalize_text(message)
    if not normalized:
        return False
    return bool(re.search(r"\bcombo(?:s)?\b", normalized)) or "ordered together" in normalized


def _extract_combo_topic(message: str) -> str | None:
    if not _is_combo_query(message):
        return None
    normalized = _normalize_text(message)
    cleaned = re.sub(r"\b(?:combo|combos|together|popular|ordered|frequently|suggest|show|have|what|do|you|any|available)\b", " ", normalized)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?!.,")
    return _canonicalize_topic(cleaned)


def _extract_offer_query_overrides(message: str) -> dict[str, Any]:
    normalized = _normalize_text(message)
    cleaned = re.sub(
        r"\b(?:offer|offers|coupon|coupons|discount|discounts|deal|deals|available|live|show|me|any|what|do|you|have|on|for|please|going|running|current|currently|active|right|now|today)\b",
        " ",
        normalized,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?!.,")

    cuisine: str | None = None
    for cuisine_key in sorted(CUISINE_SIGNAL_KEYS):
        if cuisine_key in normalized:
            cuisine = cuisine_key
            break

    restaurant_query: str | None = None
    if "restaurant" in normalized and cleaned:
        restaurant_query = _canonicalize_topic(cleaned)

    items: list[str] | None = None
    if cleaned:
        cleaned_parts = [
            part.strip(" ?!.,")
            for part in re.split(r"\b(?:and|or|with|plus)\b|,|/|&", cleaned)
            if part.strip(" ?!.,")
        ]
        if len(cleaned_parts) >= 2:
            extracted = [
                canonical
                for canonical in (_canonicalize_topic(part) for part in cleaned_parts)
                if canonical
            ]
            deduped = _dedupe_topics(extracted)
            if deduped:
                items = deduped
        if not items:
            direct_item_hint = _canonicalize_topic(cleaned)
            if direct_item_hint is not None:
                items = [direct_item_hint]

    if items:
        items = [
            item
            for item in items
            if item not in OFFER_QUERY_MARKERS and item not in {"promo", "promocode", "promo code"}
        ] or None

    return {
        "cuisine": cuisine,
        "restaurant_query": restaurant_query,
        "items": items or None,
        "wants_free_delivery": "free delivery" in normalized,
    }


def _is_greeting_message(message: str) -> bool:
    normalized = _normalize_match_text(message)
    if not normalized:
        return False

    greetings = {
        "hi",
        "hello",
        "hey",
        "good morning",
        "good afternoon",
        "good evening",
        "hi there",
        "hello there",
        "hey there",
    }
    if normalized in greetings:
        return True

    tokens = normalized.split()
    greeting_tokens = {"hi", "hello", "hey", "good", "morning", "afternoon", "evening", "there"}
    return len(tokens) <= 3 and all(token in greeting_tokens for token in tokens)


def _is_acknowledgement_message(message: str) -> bool:
    normalized = _normalize_match_text(message)
    acknowledgements = {
        "thanks",
        "thank you",
        "thanks a lot",
        "thankyou",
        "ok thanks",
        "great thanks",
        "cool thanks",
    }
    if normalized in acknowledgements or normalized in ACKNOWLEDGEMENT_PHRASES:
        return True
    tokens = normalized.split()
    return len(tokens) <= 3 and any(token in {"thanks", "thank", "thankyou"} for token in tokens)


def _is_follow_up_recommendation_message(message: str) -> bool:
    normalized = _normalize_match_text(message)
    if normalized in FOLLOW_UP_MESSAGE_MARKERS:
        return True
    if normalized.startswith("other "):
        return True

    tokens = _query_tokens(normalized)
    if not tokens:
        return False
    return all(token in FOLLOW_UP_STOPWORDS for token in tokens)


def _extract_structured_state_from_history(history_messages: list[ChatHistory]) -> SessionConversationState:
    state = SessionConversationState()

    for entry in history_messages:
        payload = entry.context_payload if isinstance(entry.context_payload, dict) else {}
        session_state_payload = payload.get("session_state")
        hydrated_state = _deserialize_session_state(session_state_payload)
        if hydrated_state is not None:
            state = hydrated_state

        if entry.role == ChatMessageRole.ASSISTANT:
            suggestions = payload.get("suggestions")
            if isinstance(suggestions, list):
                for suggestion in suggestions:
                    if not isinstance(suggestion, dict):
                        continue
                    suggestion_id = suggestion.get("id")
                    restaurant_id = suggestion.get("restaurant_id")
                    if isinstance(suggestion_id, str):
                        try:
                            state.seen_item_ids.add(uuid.UUID(suggestion_id))
                        except ValueError:
                            continue
                    if isinstance(restaurant_id, str):
                        try:
                            state.previous_restaurants.add(uuid.UUID(restaurant_id))
                        except ValueError:
                            continue

    for entry in reversed(history_messages):
        if entry.role != ChatMessageRole.USER:
            continue
        payload = entry.context_payload if isinstance(entry.context_payload, dict) else {}
        effective_message = payload.get("effective_message") if isinstance(payload.get("effective_message"), str) else None
        normalized_intent = payload.get("resolved_intent") if isinstance(payload.get("resolved_intent"), str) else None
        if effective_message and not _is_follow_up_recommendation_message(entry.message) and not _is_greeting_message(entry.message):
            state.base_query = effective_message
            if state.last_intent is None and normalized_intent:
                state.last_intent = normalized_intent
            break

    return state


def _recent_recommendation_contexts(history_messages: list[ChatHistory]) -> list[dict[str, Any]]:
    contexts: list[dict[str, Any]] = []
    for entry in history_messages:
        if entry.role != ChatMessageRole.ASSISTANT:
            continue
        payload = entry.context_payload if isinstance(entry.context_payload, dict) else {}
        session_state_payload = payload.get("session_state")
        if isinstance(session_state_payload, dict):
            context = session_state_payload.get("last_recommendation_context")
            if isinstance(context, dict):
                contexts.append(context)
    return contexts[-3:]


def _load_session_state(
    db: Session,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    history_messages: list[ChatHistory] | None = None,
) -> SessionConversationState:
    cached_state = _deserialize_session_state(cache_get_json(_session_state_cache_key(user_id, session_id)))
    if cached_state is not None:
        return cached_state

    entries = history_messages if history_messages is not None else _fetch_recent_history_messages(
        db,
        user_id=user_id,
        session_id=session_id,
    )
    state = _extract_structured_state_from_history(entries)
    cache_set_json(_session_state_cache_key(user_id, session_id), _serialize_session_state(state))
    return state


def _load_cached_session_state_only(
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
) -> SessionConversationState | None:
    return _deserialize_session_state(cache_get_json(_session_state_cache_key(user_id, session_id)))


def _build_intent_prompt(message: str, session_state: SessionConversationState) -> str:
    return (
        f"{INTENT_PROMPT}\n\n"
        f"SESSION STATE:\n{_session_state_prompt_summary(session_state)}\n\n"
        f"USER MESSAGE:\n{_trim_text(message, 220)}\n"
    )


def _parse_intent_payload(payload: dict[str, Any]) -> ExtractedIntent:
    budget_raw = payload.get("budget")
    budget: Decimal | None = None
    if budget_raw not in (None, ""):
        try:
            budget = Decimal(str(budget_raw))
        except (ValueError, ArithmeticError):
            budget = None

    spicy_raw = payload.get("spicy")
    spicy = spicy_raw if isinstance(spicy_raw, bool) else None
    show_more_raw = payload.get("show_more")
    raw_items = payload.get("items")
    items = _dedupe_topics(
        [item.strip() for item in raw_items if isinstance(item, str) and item.strip()]
    ) if isinstance(raw_items, list) else []

    return ExtractedIntent(
        intent=str(payload.get("intent") or "other").strip().lower(),
        dish=_optional_text(payload.get("dish")) if isinstance(payload.get("dish"), str) else None,
        items=items or None,
        cuisine=_optional_text(payload.get("cuisine")) if isinstance(payload.get("cuisine"), str) else None,
        category=_optional_text(payload.get("category")) if isinstance(payload.get("category"), str) else None,
        restaurant_query=_optional_text(payload.get("restaurant_query")) if isinstance(payload.get("restaurant_query"), str) else None,
        budget=budget,
        diet=_optional_text(payload.get("diet")) if isinstance(payload.get("diet"), str) else None,
        spicy=spicy,
        mood=_optional_text(payload.get("mood")) if isinstance(payload.get("mood"), str) else None,
        show_more=bool(show_more_raw) if isinstance(show_more_raw, bool) else False,
        new_only=bool(payload.get("new_only")) if isinstance(payload.get("new_only"), bool) else False,
    )


def _fallback_extract_intent(message: str, session_state: SessionConversationState) -> ExtractedIntent:
    multi_item_hints = _extract_multi_item_hints(message)
    if _message_requests_new_items(message):
        overrides = _extract_new_query_overrides(message)
        return ExtractedIntent(
            intent="recommendation",
            dish=overrides["dish"],
            items=multi_item_hints or None,
            cuisine=overrides["cuisine"],
            budget=_extract_budget_limit(message),
            diet=overrides["diet"],
            spicy=overrides["spicy"],
            new_only=True,
        )

    if _is_greeting_message(message):
        return ExtractedIntent(intent="greeting")

    if _is_small_talk_message(message):
        return ExtractedIntent(intent="small_talk")

    if _is_order_history_message(message):
        return ExtractedIntent(intent="order_history")

    if _is_offer_query_message(message):
        offer_overrides = _extract_offer_query_overrides(message)
        return ExtractedIntent(
            intent="offer_query",
            items=offer_overrides["items"],
            cuisine=offer_overrides["cuisine"],
            restaurant_query=offer_overrides["restaurant_query"],
        )

    if _is_menu_question_message(message):
        menu_question_dish = _extract_menu_question_dish(message)
        return ExtractedIntent(
            intent="menu_question",
            dish=menu_question_dish,
            items=[menu_question_dish] if menu_question_dish else None,
            budget=_extract_budget_limit(message),
        )

    if _is_invalid_or_spam_message(message):
        return ExtractedIntent(intent="invalid_input")

    if _is_combo_query(message):
        return ExtractedIntent(
            intent="recommendation",
            dish=_extract_combo_topic(message),
            items=multi_item_hints or None,
            category="combo",
            budget=_extract_budget_limit(message),
        )

    explicit_budget = _extract_budget_limit(message)
    normalized = _normalize_text(message)
    if explicit_budget is not None and any(term in normalized for term in ("dinner", "lunch", "breakfast", "meal", "snack")):
        return ExtractedIntent(
            intent="recommendation",
            items=multi_item_hints or None,
            budget=explicit_budget,
            mood=next((term for term in ("dinner", "lunch", "breakfast", "meal", "snack") if term in normalized), None),
        )

    if multi_item_hints:
        return ExtractedIntent(
            intent="dish_recommendation",
            dish=multi_item_hints[0],
            items=multi_item_hints,
            budget=explicit_budget,
        )

    direct_item_hint = _extract_direct_item_hint(message)
    if direct_item_hint is not None:
        return ExtractedIntent(
            intent="dish_recommendation",
            dish=direct_item_hint,
            items=[direct_item_hint],
            budget=explicit_budget,
        )

    if _is_out_of_domain_message(message):
        return ExtractedIntent(intent="unsupported_domain")

    fallback = ExtractedIntent(
        intent="show_more" if _is_follow_up_recommendation_message(message) else "recommendation",
        budget=explicit_budget,
        show_more=_is_follow_up_recommendation_message(message),
    )
    if "restaurant" in normalized:
        fallback.intent = "restaurant_list"
    if multi_item_hints:
        fallback.items = multi_item_hints
    return fallback


def _should_use_lightweight_intent_parser(message: str, session_state: SessionConversationState) -> bool:
    normalized = _normalize_text(message)
    tokens = _query_tokens(message)
    if _message_requests_new_items(message):
        return True
    if _is_greeting_message(message) or _is_acknowledgement_message(message):
        return True
    if _is_small_talk_message(message) or _is_invalid_or_spam_message(message):
        return True
    if _is_menu_question_message(message):
        return True
    if _is_offer_query_message(message) or _is_order_history_message(message):
        return True
    if _is_out_of_domain_message(message):
        return True
    if _is_follow_up_recommendation_message(message):
        return True
    if _extract_direct_item_hint(message) is not None:
        return True
    if _extract_budget_limit(message) is not None:
        return True
    if "restaurant" in normalized and len(tokens) <= 5:
        return True
    if any(term in normalized for term in ("veg", "vegetarian", "non veg", "non-veg", "spicy")) and len(tokens) <= 4:
        return True
    if len(tokens) <= 2 and not _message_requests_personal_context(message):
        return True
    if session_state.active_topic and len(tokens) <= 2:
        return True
    return False


def _extract_intent(
    message: str,
    session_state: SessionConversationState,
    *,
    force_lightweight: bool = False,
) -> ExtractedIntent:
    if force_lightweight or _should_use_lightweight_intent_parser(message, session_state):
        intent = _fallback_extract_intent(message, session_state)
        logger.info(
            "RAG intent fast-path parser intent=%s dish=%s items=%s cuisine=%s category=%s restaurant=%s budget=%s diet=%s spicy=%s mood=%s show_more=%s",
            intent.intent,
            intent.dish,
            intent.items,
            intent.cuisine,
            intent.category,
            intent.restaurant_query,
            intent.budget,
            intent.diet,
            intent.spicy,
            intent.mood,
            intent.show_more,
        )
        return intent

    prompt = _build_intent_prompt(message, session_state)
    payload = {
        "model": settings.ollama_chat_model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        # qwen3 defaults to thinking mode; hidden reasoning consumes the whole
        # num_predict budget and returns an empty response field.
        **think_option(),
        **local_only_options(),
        "options": {
            "num_predict": 120,
            "temperature": 0,
        },
    }

    try:
        response = GENERATE_CLIENT.post(GENERATE_ENDPOINT, json=payload)
        response.raise_for_status()
        raw_reply = response.json().get("response")
        parsed_payload = json.loads(raw_reply) if isinstance(raw_reply, str) else {}
        intent = _parse_intent_payload(parsed_payload)
    except (httpx.HTTPError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("RAG intent extraction failed, falling back to lightweight parser: %s", exc)
        intent = _fallback_extract_intent(message, session_state)

    if intent.intent not in {
        "greeting",
        "small_talk",
        "menu_question",
        "dish_recommendation",
        "restaurant_list",
        "recommendation",
        "offer_query",
        "order_history",
        "unsupported_domain",
        "invalid_input",
        "show_more",
        "other",
    }:
        intent.intent = "other"
    if intent.show_more:
        intent.intent = "show_more"
    if _message_requests_new_items(message):
        overrides = _extract_new_query_overrides(message)
        intent.new_only = True
        if intent.cuisine is None:
            intent.cuisine = overrides["cuisine"]
        if intent.diet is None:
            intent.diet = overrides["diet"]
        if intent.spicy is None:
            intent.spicy = overrides["spicy"]
        if intent.dish is None:
            intent.dish = overrides["dish"]
    if not intent.items:
        multi_item_hints = _extract_multi_item_hints(message)
        if multi_item_hints:
            intent.items = multi_item_hints
            if intent.dish is None:
                intent.dish = multi_item_hints[0]
    if intent.dish is None:
        direct_item_hint = _extract_direct_item_hint(message)
        if direct_item_hint is not None:
            intent.intent = "dish_recommendation"
            intent.dish = direct_item_hint
            intent.items = [direct_item_hint]

    logger.info(
        "RAG extracted intent intent=%s dish=%s items=%s cuisine=%s category=%s restaurant=%s budget=%s diet=%s spicy=%s mood=%s show_more=%s",
        intent.intent,
        intent.dish,
        intent.items,
        intent.cuisine,
        intent.category,
        intent.restaurant_query,
        intent.budget,
        intent.diet,
        intent.spicy,
        intent.mood,
        intent.show_more,
    )
    return intent


def _merge_intent_with_session(intent: ExtractedIntent, session_state: SessionConversationState) -> ExtractedIntent:
    if intent.intent == "menu_question" and not intent.dish and not intent.items:
        # "How much does it cost?" — resolve the pronoun against the dish the
        # conversation is currently about.
        inherited_dish = (
            session_state.dish
            or (session_state.items[0] if session_state.items else None)
            or session_state.active_topic
        )
        if inherited_dish:
            return ExtractedIntent(
                intent="menu_question",
                dish=inherited_dish,
                items=[inherited_dish],
                budget=intent.budget,
            )
        return intent

    if intent.intent == "show_more" or intent.show_more:
        selected_context = session_state.last_recommendation_context or {
            "intent": session_state.active_intent or session_state.last_intent,
            "topic": session_state.active_topic,
            "effective_query": session_state.last_successful_user_query or session_state.base_query,
        }
        logger.info(
            "RAG follow-up detected selected_active_context=%s seen_item_ids=%s",
            json.dumps(selected_context, default=str),
            [str(item_id) for item_id in sorted(session_state.seen_item_ids or set(), key=str)],
        )
        return ExtractedIntent(
            intent=session_state.active_intent or session_state.last_intent or "recommendation",
            dish=intent.dish or session_state.dish,
            items=intent.items or session_state.items,
            cuisine=intent.cuisine or session_state.cuisine,
            category=intent.category or session_state.category,
            restaurant_query=intent.restaurant_query or session_state.restaurant_query,
            budget=intent.budget if intent.budget is not None else session_state.budget,
            diet=intent.diet or session_state.diet,
            spicy=intent.spicy if intent.spicy is not None else session_state.spicy,
            mood=intent.mood or session_state.mood,
            show_more=True,
            new_only=intent.new_only or session_state.new_only,
        )

    should_inherit_soft_context = intent.intent == "other" and any(
        value is not None and value != ""
        for value in (
            intent.dish,
            intent.cuisine,
            intent.category,
            intent.restaurant_query,
            intent.budget,
            intent.diet,
            intent.mood,
        )
    )
    if intent.spicy is not None:
        should_inherit_soft_context = True
    return ExtractedIntent(
        intent=intent.intent,
        dish=intent.dish or (session_state.dish if should_inherit_soft_context else None),
        items=intent.items or (session_state.items if should_inherit_soft_context else None),
        cuisine=intent.cuisine or (session_state.cuisine if should_inherit_soft_context else None),
        category=intent.category or (session_state.category if should_inherit_soft_context else None),
        restaurant_query=intent.restaurant_query or (session_state.restaurant_query if should_inherit_soft_context else None),
        budget=intent.budget if intent.budget is not None else (session_state.budget if should_inherit_soft_context else None),
        diet=intent.diet or (session_state.diet if should_inherit_soft_context else None),
        spicy=intent.spicy if intent.spicy is not None else (session_state.spicy if should_inherit_soft_context else None),
        mood=intent.mood or (session_state.mood if should_inherit_soft_context else None),
        show_more=False,
        new_only=intent.new_only or (session_state.new_only if should_inherit_soft_context else False),
    )


def _build_effective_query_from_intent(message: str, intent: ExtractedIntent, session_state: SessionConversationState) -> str:
    parts: list[str] = []
    if intent.items:
        parts.extend(intent.items)
    elif intent.dish:
        parts.append(intent.dish)
    if intent.cuisine:
        parts.append(intent.cuisine)
    if intent.category:
        parts.append(intent.category)
    if intent.restaurant_query:
        parts.append(intent.restaurant_query)
    if intent.mood:
        parts.append(intent.mood)
    if intent.spicy is True:
        parts.append("spicy")
    if intent.diet == "veg":
        parts.append("veg")
    if intent.diet == "non_veg":
        parts.append("non veg")
    if intent.budget is not None:
        parts.append(f"under {intent.budget}")
    if parts:
        prefix = "new " if intent.new_only else ""
        return f"{prefix}{' '.join(parts)}".strip()
    if intent.show_more:
        return session_state.last_successful_user_query or session_state.base_query or message
    if intent.new_only:
        return "new menu items"
    return message


def _derive_active_topic(
    intent: ExtractedIntent,
    effective_query: str,
    prior_state: SessionConversationState,
    *,
    allow_prior_fallback: bool,
) -> str | None:
    return (
        _canonicalize_topic(" / ".join(intent.items[:2])) if intent.items else None
        or _canonicalize_topic(intent.dish)
        or _canonicalize_topic(intent.cuisine)
        or _canonicalize_topic(intent.category)
        or _canonicalize_topic(intent.restaurant_query)
        or _canonicalize_topic(effective_query)
        or (prior_state.active_topic if allow_prior_fallback else None)
    )


def _is_recommendation_like_intent(intent: ExtractedIntent) -> bool:
    return intent.intent in {"dish_recommendation", "restaurant_list", "recommendation"} or intent.show_more


def _recommendation_context_payload(
    *,
    intent: ExtractedIntent,
    effective_query: str,
    active_topic: str | None,
    retrieval_source: str,
    suggestions: list[ChatSuggestionItem],
) -> dict[str, Any]:
    return {
        "intent": intent.intent,
        "topic": active_topic,
        "effective_query": effective_query,
        "retrieval_source": retrieval_source,
        "dish": intent.dish,
        "items": intent.items,
        "cuisine": intent.cuisine,
        "category": intent.category,
        "restaurant_query": intent.restaurant_query,
        "budget": str(intent.budget) if intent.budget is not None else None,
        "diet": intent.diet,
        "spicy": intent.spicy,
        "mood": intent.mood,
        "new_only": intent.new_only,
        "suggested_item_ids": [str(item.id) for item in suggestions],
    }


def _infer_cache_query_descriptor(message: str) -> CacheQueryDescriptor:
    normalized_message = _normalize_text(message)
    lightweight_intent = _fallback_extract_intent(message, SessionConversationState())
    explicit_budget = _extract_budget_limit(message)
    query_tokens = _query_tokens(message)

    diet: str | None = None
    if "vegetarian" in normalized_message or re.search(r"\bveg\b", normalized_message):
        diet = "veg"
    elif "non veg" in normalized_message or "non-veg" in normalized_message:
        diet = "non_veg"

    spicy = True if ("spicy" in normalized_message or "chilli" in normalized_message) else None

    topic = (
        _canonicalize_topic(" / ".join(lightweight_intent.items[:2])) if lightweight_intent.items else None
        or _canonicalize_topic(lightweight_intent.dish)
        or _canonicalize_topic(lightweight_intent.cuisine)
        or _canonicalize_topic(lightweight_intent.category)
        or _canonicalize_topic(lightweight_intent.restaurant_query)
    )
    if _is_combo_query(message):
        topic = _extract_combo_topic(message) or topic
    if topic is None:
        topic = _canonicalize_topic(message)

    cache_intent_map = {
        "dish_recommendation": "dish_search",
        "menu_question": "menu_question",
        "restaurant_list": "restaurant_list",
        "recommendation": "recommendation",
        "offer_query": "offer_query",
        "order_history": "order_history",
        "small_talk": "small_talk",
        "unsupported_domain": "unsupported_domain",
        "invalid_input": "invalid_input",
        "other": "recommendation",
    }
    cache_intent = cache_intent_map.get(lightweight_intent.intent, lightweight_intent.intent)
    new_only = _message_requests_new_items(message) or lightweight_intent.new_only
    if _is_combo_query(message):
        cache_intent = "combo_search"
    elif new_only:
        cache_intent = "new_items"
    if cache_intent == "recommendation" and topic and len(query_tokens) <= 2:
        cache_intent = "dish_search"

    descriptor = CacheQueryDescriptor(
        normalized_message=normalized_message,
        cache_intent=cache_intent,
        topic=topic,
        budget=explicit_budget,
        diet=diet,
        spicy=spicy,
        new_only=new_only,
    )
    logger.info(
        "RAG cache descriptor raw_message=%s normalized_message=%s extracted_intent=%s extracted_topic=%s budget=%s diet=%s spicy=%s",
        message,
        normalized_message,
        descriptor.cache_intent,
        descriptor.topic,
        descriptor.budget,
        descriptor.diet,
        descriptor.spicy,
    )
    return descriptor


def _build_session_state_from_turn(
    prior_state: SessionConversationState,
    intent: ExtractedIntent,
    effective_query: str,
    suggestions: list[ChatSuggestionItem],
    retrieval_source: str,
) -> SessionConversationState:
    seen_item_ids = set(prior_state.seen_item_ids or set())
    previous_restaurants = set(prior_state.previous_restaurants or set())
    for suggestion in suggestions:
        seen_item_ids.add(suggestion.id)
        previous_restaurants.add(suggestion.restaurant_id)

    carry_forward_context = intent.show_more or (
        intent.intent == "other"
        and any(
            value is not None and value != ""
            for value in (
                intent.dish,
                intent.items,
                intent.cuisine,
                intent.category,
                intent.restaurant_query,
                intent.budget,
                intent.diet,
                intent.mood,
            )
        )
    ) or (intent.intent == "other" and intent.spicy is not None)
    active_topic = _derive_active_topic(
        intent,
        effective_query,
        prior_state,
        allow_prior_fallback=carry_forward_context,
    )
    recommendation_like = _is_recommendation_like_intent(intent)
    last_successful_user_query = prior_state.last_successful_user_query
    last_recommendation_context = prior_state.last_recommendation_context
    if recommendation_like:
        last_successful_user_query = effective_query
        last_recommendation_context = _recommendation_context_payload(
            intent=intent,
            effective_query=effective_query,
            active_topic=active_topic,
            retrieval_source=retrieval_source,
            suggestions=suggestions,
        )

    return SessionConversationState(
        last_intent=intent.intent,
        active_intent=intent.intent if recommendation_like else prior_state.active_intent,
        base_query=effective_query,
        active_topic=active_topic,
        dish=intent.dish if intent.dish is not None else (prior_state.dish if carry_forward_context else None),
        items=intent.items if intent.items is not None else (prior_state.items if carry_forward_context else None),
        cuisine=intent.cuisine if intent.cuisine is not None else (prior_state.cuisine if carry_forward_context else None),
        category=intent.category if intent.category is not None else (prior_state.category if carry_forward_context else None),
        restaurant_query=(
            intent.restaurant_query
            if intent.restaurant_query is not None
            else (prior_state.restaurant_query if carry_forward_context else None)
        ),
        budget=intent.budget if intent.budget is not None else (prior_state.budget if carry_forward_context else None),
        diet=intent.diet if intent.diet is not None else (prior_state.diet if carry_forward_context else None),
        spicy=intent.spicy if intent.spicy is not None else (prior_state.spicy if carry_forward_context else None),
        mood=intent.mood if intent.mood is not None else (prior_state.mood if carry_forward_context else None),
        new_only=intent.new_only or (prior_state.new_only if carry_forward_context else False),
        last_successful_user_query=last_successful_user_query,
        last_recommendation_context=last_recommendation_context,
        seen_item_ids=seen_item_ids,
        previous_restaurants=previous_restaurants,
    )


def _topic_hint_from_message(message: str) -> str:
    topic_tokens = [
        token
        for token in _query_tokens(message)
        if token not in FOLLOW_UP_STOPWORDS and not token.isdigit()
    ]
    if not topic_tokens:
        return "these"
    return " ".join(topic_tokens[:3])


def _intent_requested_topics(intent: ExtractedIntent | None) -> list[str]:
    if intent is None:
        return []
    if intent.items:
        return intent.items
    if intent.dish:
        return [intent.dish]
    return []


def _display_requested_topics(intent: ExtractedIntent | None) -> str:
    topics = _intent_requested_topics(intent)
    if not topics:
        return "that"
    if len(topics) == 1:
        return topics[0]
    if len(topics) == 2:
        return f"{topics[0]} and {topics[1]}"
    return f"{', '.join(topics[:-1])}, and {topics[-1]}"


def _extract_budget_limit(message: str) -> Decimal | None:
    normalized = _normalize_text(message).replace(",", "")
    patterns = (
        r"(?:under|below|less than|upto|up to|within)\s*(?:₹|rs\.?\s*)?(\d+(?:\.\d+)?)",
        r"(?:₹|rs\.?\s*)(\d+(?:\.\d+)?)\s*(?:or less|or below|budget|max|maximum)?",
    )
    for pattern in patterns:
        matched = re.search(pattern, normalized)
        if matched:
            return Decimal(matched.group(1))
    return None


def _resolve_budget_limit(
    message: str,
    preferences: UserPreferences | None,
) -> Decimal | None:
    explicit_budget = _extract_budget_limit(message)
    if explicit_budget is not None and explicit_budget > 0:
        return explicit_budget

    if preferences is None:
        return None

    preference_budget = _safe_decimal(getattr(preferences, "average_budget", None))
    if preference_budget > 0:
        return preference_budget

    return None


def _has_explicit_budget_limit(message: str) -> bool:
    budget_limit = _extract_budget_limit(message)
    return budget_limit is not None and budget_limit > 0


def _build_history_query(user_id: uuid.UUID, session_id: uuid.UUID) -> Select[tuple[ChatHistory]]:
    return (
        select(ChatHistory)
        .where(
            ChatHistory.user_id == user_id,
            ChatHistory.session_id == session_id,
        )
        .order_by(
            desc(ChatHistory.created_at),
            case(
                (ChatHistory.role == ChatMessageRole.ASSISTANT, 0),
                else_=1,
            ).asc(),
            desc(ChatHistory.id),
        )
        .limit(HISTORY_MESSAGES)
    )


def _session_cache_key(user_id: uuid.UUID, session_id: uuid.UUID) -> str:
    return f"{SESSION_CACHE_PREFIX}:{user_id}:{session_id}"


def _session_state_cache_key(user_id: uuid.UUID, session_id: uuid.UUID) -> str:
    return f"{SESSION_STATE_CACHE_PREFIX}:{user_id}:{session_id}"


def _embedding_cache_key(normalized_query: str) -> str:
    return f"{EMBEDDING_CACHE_PREFIX}:{normalized_query}"


def _response_cache_key(
    message: str,
    restaurant_id: uuid.UUID | None,
    *,
    descriptor: CacheQueryDescriptor | None = None,
) -> str:
    scope = str(restaurant_id) if restaurant_id is not None else "global"
    descriptor = descriptor or _infer_cache_query_descriptor(message)
    topic_slug = re.sub(r"[^a-z0-9]+", "-", descriptor.topic or "general").strip("-") or "general"
    key_parts = [RESPONSE_CACHE_PREFIX, scope, "v10", descriptor.cache_intent, topic_slug]
    if descriptor.budget is not None:
        key_parts.append(f"budget-{descriptor.budget.normalize()}")
    if descriptor.diet is not None:
        key_parts.append(descriptor.diet)
    if descriptor.spicy:
        key_parts.append("spicy")
    if descriptor.new_only:
        key_parts.append("new")
    return ":".join(str(part) for part in key_parts)


def _greeting_response_cache_key(message: str) -> str:
    normalized = _normalize_text(message)
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "greeting"
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
    return f"{GREETING_RESPONSE_CACHE_PREFIX}:v3:{slug}:{digest}"


def _serialize_session_state(state: SessionConversationState) -> dict[str, Any]:
    return {
        "last_intent": state.last_intent,
        "active_intent": state.active_intent,
        "base_query": state.base_query,
        "active_topic": state.active_topic,
        "dish": state.dish,
        "items": state.items,
        "cuisine": state.cuisine,
        "category": state.category,
        "restaurant_query": state.restaurant_query,
        "budget": str(state.budget) if state.budget is not None else None,
        "diet": state.diet,
        "spicy": state.spicy,
        "mood": state.mood,
        "new_only": state.new_only,
        "last_successful_user_query": state.last_successful_user_query,
        "last_recommendation_context": state.last_recommendation_context,
        "seen_item_ids": [str(item_id) for item_id in sorted(state.seen_item_ids or set(), key=str)],
        "previous_restaurants": [str(restaurant_id) for restaurant_id in sorted(state.previous_restaurants or set(), key=str)],
    }


def _deserialize_session_state(payload: object) -> SessionConversationState | None:
    if not isinstance(payload, dict):
        return None
    try:
        budget_raw = payload.get("budget")
        seen_item_ids = {
            uuid.UUID(item_id)
            for item_id in payload.get("seen_item_ids", [])
            if isinstance(item_id, str)
        }
        previous_restaurants = {
            uuid.UUID(restaurant_id)
            for restaurant_id in payload.get("previous_restaurants", [])
            if isinstance(restaurant_id, str)
        }
        return SessionConversationState(
            last_intent=payload.get("last_intent") if isinstance(payload.get("last_intent"), str) else None,
            active_intent=payload.get("active_intent") if isinstance(payload.get("active_intent"), str) else None,
            base_query=payload.get("base_query") if isinstance(payload.get("base_query"), str) else None,
            active_topic=payload.get("active_topic") if isinstance(payload.get("active_topic"), str) else None,
            dish=payload.get("dish") if isinstance(payload.get("dish"), str) else None,
            items=[item for item in payload.get("items", []) if isinstance(item, str) and item]
            if isinstance(payload.get("items"), list)
            else None,
            cuisine=payload.get("cuisine") if isinstance(payload.get("cuisine"), str) else None,
            category=payload.get("category") if isinstance(payload.get("category"), str) else None,
            restaurant_query=payload.get("restaurant_query") if isinstance(payload.get("restaurant_query"), str) else None,
            budget=Decimal(str(budget_raw)) if budget_raw not in (None, "") else None,
            diet=payload.get("diet") if isinstance(payload.get("diet"), str) else None,
            spicy=payload.get("spicy") if isinstance(payload.get("spicy"), bool) else None,
            mood=payload.get("mood") if isinstance(payload.get("mood"), str) else None,
            new_only=payload.get("new_only") if isinstance(payload.get("new_only"), bool) else False,
            last_successful_user_query=payload.get("last_successful_user_query") if isinstance(payload.get("last_successful_user_query"), str) else None,
            last_recommendation_context=payload.get("last_recommendation_context") if isinstance(payload.get("last_recommendation_context"), dict) else None,
            seen_item_ids=seen_item_ids,
            previous_restaurants=previous_restaurants,
        )
    except (TypeError, ValueError, ArithmeticError):
        logger.warning("RAG session state cache payload validation failed")
        return None


def _session_state_summary(state: SessionConversationState) -> str:
    summary = {
        "last_intent": state.last_intent,
        "active_intent": state.active_intent,
        "base_query": state.base_query,
        "active_topic": state.active_topic,
        "dish": state.dish,
        "items": state.items,
        "cuisine": state.cuisine,
        "category": state.category,
        "restaurant_query": state.restaurant_query,
        "budget": str(state.budget) if state.budget is not None else None,
        "diet": state.diet,
        "spicy": state.spicy,
        "mood": state.mood,
        "new_only": state.new_only,
        "last_successful_user_query": state.last_successful_user_query,
        "last_recommendation_context": state.last_recommendation_context,
        "seen_item_count": len(state.seen_item_ids or set()),
        "previous_restaurant_count": len(state.previous_restaurants or set()),
    }
    return json.dumps(summary, default=str)


def _session_state_prompt_summary(state: SessionConversationState) -> str:
    """Compact session context for LLM prompts.

    The full summary carries UUID lists and bookkeeping the model cannot use;
    on a CPU-only host every prompt token costs real latency, so prompts only
    get the fields that can influence phrasing, with nulls dropped.
    """
    summary = {
        "active_topic": state.active_topic,
        "dish": state.dish,
        "items": state.items,
        "cuisine": state.cuisine,
        "category": state.category,
        "restaurant_query": state.restaurant_query,
        "budget": str(state.budget) if state.budget is not None else None,
        "diet": state.diet,
        "spicy": state.spicy,
        "mood": state.mood,
        "new_only": state.new_only or None,
        "last_query": state.last_successful_user_query,
    }
    compact = {key: value for key, value in summary.items() if value not in (None, [], "")}
    if not compact:
        return "none"
    return json.dumps(compact, default=str, separators=(",", ":"))


def _serialize_history_entries(entries: list[ChatHistory]) -> list[dict[str, Any]]:
    return [
        {
            "id": str(entry.id),
            "user_id": str(entry.user_id),
            "restaurant_id": str(entry.restaurant_id) if entry.restaurant_id else None,
            "session_id": str(entry.session_id),
            "role": entry.role.value,
            "message": entry.message,
            "context_payload": entry.context_payload or {},
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
            "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
        }
        for entry in entries
    ]


def _deserialize_history_entries(payload: object) -> list[ChatHistory] | None:
    if not isinstance(payload, list):
        return None

    messages: list[ChatHistory] = []
    try:
        for item in payload:
            if not isinstance(item, dict):
                return None
            messages.append(
                ChatHistory(
                    id=uuid.UUID(item["id"]),
                    user_id=uuid.UUID(item["user_id"]),
                    restaurant_id=uuid.UUID(item["restaurant_id"]) if item.get("restaurant_id") else None,
                    session_id=uuid.UUID(item["session_id"]),
                    role=ChatMessageRole(item["role"]),
                    message=str(item["message"]),
                    context_payload=item.get("context_payload") or {},
                    created_at=datetime.fromisoformat(item["created_at"]) if item.get("created_at") else None,
                    updated_at=datetime.fromisoformat(item["updated_at"]) if item.get("updated_at") else None,
                )
            )
    except (KeyError, TypeError, ValueError):
        logger.warning("RAG session cache payload validation failed")
        return None

    return messages


def _fetch_recent_history_messages_from_db(
    db: Session,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
) -> list[ChatHistory]:
    rows = db.scalars(_build_history_query(user_id, session_id)).all()
    return list(reversed(rows))


def get_chat_history(
    db: Session,
    user: User,
    session_id: uuid.UUID | None = None,
    *,
    restaurant_id: uuid.UUID | None = None,
) -> list[ChatHistoryItemResponse]:
    if session_id is not None and restaurant_id is None:
        # The session cache is not scope-aware, so it is only safe to use for
        # unscoped callers.
        cached_payload = cache_get_json(_session_cache_key(user.id, session_id))
        cached_messages = _deserialize_history_entries(cached_payload)
        if cached_messages is not None:
            return [ChatHistoryItemResponse.model_validate(message) for message in cached_messages]

    query = select(ChatHistory).where(ChatHistory.user_id == user.id)
    if session_id is not None:
        query = query.where(ChatHistory.session_id == session_id)
    if restaurant_id is not None:
        # Marketplace turns (restaurant_id NULL) are excluded too: their
        # suggestion payloads can reference other restaurants' dishes.
        query = query.where(ChatHistory.restaurant_id == restaurant_id)

    messages = db.scalars(
        query.order_by(
            desc(ChatHistory.created_at),
            case(
                (ChatHistory.role == ChatMessageRole.ASSISTANT, 0),
                else_=1,
            ).asc(),
            desc(ChatHistory.id),
        ).limit(HISTORY_MESSAGES)
    ).all()
    messages = list(reversed(messages))
    if session_id is not None:
        cache_set_json(_session_cache_key(user.id, session_id), _serialize_history_entries(messages))
    return [ChatHistoryItemResponse.model_validate(message) for message in messages]


def clear_chat_history(
    db: Session,
    *,
    user: User,
    session_id: uuid.UUID | None = None,
    restaurant_id: uuid.UUID | None = None,
) -> int:
    query = delete(ChatHistory).where(ChatHistory.user_id == user.id)
    if session_id is not None:
        query = query.where(ChatHistory.session_id == session_id)
    if restaurant_id is not None:
        # A scoped app clears only its own conversations, never the user's
        # history with other restaurants.
        query = query.where(ChatHistory.restaurant_id == restaurant_id)

    result = db.execute(query)
    deleted_count = int(result.rowcount or 0)
    db.commit()

    if session_id is not None:
        cache_delete(
            _session_cache_key(user.id, session_id),
            _session_state_cache_key(user.id, session_id),
        )
    else:
        cache_delete_pattern(f"{SESSION_CACHE_PREFIX}:{user.id}:*")
        cache_delete_pattern(f"{SESSION_STATE_CACHE_PREFIX}:{user.id}:*")

    logger.info(
        "RAG chat history cleared user_id=%s session_id=%s deleted_count=%d",
        user.id,
        session_id,
        deleted_count,
    )
    return deleted_count


def invalidate_user_chat_caches(user_id: uuid.UUID) -> None:
    cache_delete_pattern(f"{SESSION_CACHE_PREFIX}:{user_id}:*")
    cache_delete_pattern(f"{SESSION_STATE_CACHE_PREFIX}:{user_id}:*")


def _fetch_recent_history_messages(
    db: Session,
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
) -> list[ChatHistory]:
    cached_payload = cache_get_json(_session_cache_key(user_id, session_id))
    cached_messages = _deserialize_history_entries(cached_payload)
    if cached_messages is not None:
        return cached_messages

    rows = _fetch_recent_history_messages_from_db(db, user_id=user_id, session_id=session_id)
    cache_set_json(_session_cache_key(user_id, session_id), _serialize_history_entries(rows))
    return rows


def _fetch_user_preferences(db: Session, user_id: uuid.UUID) -> UserPreferences | None:
    return db.scalar(select(UserPreferences).where(UserPreferences.user_id == user_id))


@lru_cache(maxsize=256)
def _embed_query_cached(normalized_message: str) -> tuple[float, ...]:
    # The customer's message is the QUERY side of the retrieval pair. Gemini
    # embeds a query differently from a stored document and retrieval is better
    # for the distinction; Ollama has no equivalent and ignores it.
    return tuple(get_embedding(normalized_message, task="query"))


def _embed_query(message: str) -> list[float] | None:
    """The query vector, or None when no provider could produce one.

    Returning None rather than raising is the point of this function's shape. It
    previously raised an HTTPException from inside retrieval, which unwound past
    the keyword, popular and emergency tiers all the way to the safe-fallback
    turn — so an embedding outage cost the customer every suggestion, even though
    keyword search was working perfectly and sitting right there in the cascade.

    None means "carry on without a vector": `_resolve_final_candidates` skips the
    vector tier and the tiers below it answer exactly as they always would.
    """

    normalized_message = _normalize_text(message)
    cache_before = _embed_query_cached.cache_info()
    logger.info("RAG user query: %s", message)
    redis_cache_key = _embedding_cache_key(normalized_message)

    cached_vector = cache_get_json(redis_cache_key)
    if isinstance(cached_vector, list) and len(cached_vector) == settings.embedding_dimensions:
        try:
            vector = [float(value) for value in cached_vector]
        except (TypeError, ValueError):
            vector = None
        if vector is not None:
            logger.info("RAG embedding loaded from Redis cache query=%s", normalized_message)
            return vector

    try:
        vector = list(_embed_query_cached(normalized_message))
    except EmbeddingError as exc:
        # Covers timeout, connection failure, HTTP error and 429 quota alike.
        # Every one of them means "no vector this turn", and none of them should
        # cost the customer their suggestions.
        logger.warning(
            "RAG embedding unavailable, continuing without vector retrieval: %s", exc
        )
        return None

    cache_after = _embed_query_cached.cache_info()
    logger.info(
        "RAG embedding generated: dimensions=%d cache_hit=%s preview=%s",
        len(vector),
        cache_after.hits > cache_before.hits,
        [round(value, 4) for value in vector[:8]],
    )
    cache_set_json(redis_cache_key, vector)
    return vector


def _retrieve_candidates(
    db: Session,
    query_embedding: list[float] | None,
    restaurant_id: uuid.UUID | None,
    restaurant_location_id: uuid.UUID | None,
    *,
    limit: int = TOP_K_RESULTS,
) -> list[RetrievedMenuCandidate]:
    distance = MenuEmbedding.embedding.cosine_distance(query_embedding)
    query = (
        select(MenuEmbedding, MenuItem, Restaurant, distance.label("distance"))
        .join(MenuItem, MenuEmbedding.menu_item_id == MenuItem.id)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .join(RestaurantLocation, MenuItem.restaurant_location_id == RestaurantLocation.id)
        .where(
            Restaurant.is_active.is_(True),
            Restaurant.is_approved.is_(True),
            RestaurantLocation.is_active.is_(True),
            MenuItem.is_available.is_(True),
        )
        .order_by(distance.asc())
        .limit(limit)
    )

    if restaurant_id is not None:
        query = query.where(Restaurant.id == restaurant_id)
    if restaurant_location_id is not None:
        query = query.where(RestaurantLocation.id == restaurant_location_id)

    rows = db.execute(query).all()
    hydrate_dynamic_bestseller_flags(db, [menu_item for _, menu_item, _, _ in rows])
    candidates = [
        RetrievedMenuCandidate(
            menu_item=menu_item,
            restaurant=restaurant,
            distance=float(distance_value),
            source="vector",
        )
        for _, menu_item, restaurant, distance_value in rows
    ]
    logger.info("RAG vector results count=%d names=%s", len(candidates), [candidate.menu_item.name for candidate in candidates[:5]])
    return candidates


def _fetch_keyword_candidates(
    db: Session,
    message: str,
    restaurant_id: uuid.UUID | None,
    restaurant_location_id: uuid.UUID | None,
    *,
    limit: int = TOP_K_RESULTS,
) -> list[RetrievedMenuCandidate]:
    tokens = _query_tokens(message)
    if not tokens:
        return []

    conditions: list[Any] = []
    for token in tokens:
        pattern = f"%{token}%"
        conditions.extend(
            [
                MenuItem.name.ilike(pattern),
                MenuItem.category.ilike(pattern),
                MenuItem.cuisine_type.ilike(pattern),
                MenuItem.description.ilike(pattern),
                Restaurant.cuisine_type.ilike(pattern),
                Restaurant.name.ilike(pattern),
            ]
        )

    query = (
        select(MenuItem, Restaurant)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .join(RestaurantLocation, MenuItem.restaurant_location_id == RestaurantLocation.id)
        .where(
            Restaurant.is_active.is_(True),
            Restaurant.is_approved.is_(True),
            RestaurantLocation.is_active.is_(True),
            MenuItem.is_available.is_(True),
            or_(*conditions),
        )
        .order_by(
            MenuItem.popularity_score.desc(),
            MenuItem.created_at.desc(),
        )
        .limit(limit * 4)
    )

    if restaurant_id is not None:
        query = query.where(Restaurant.id == restaurant_id)
    if restaurant_location_id is not None:
        query = query.where(RestaurantLocation.id == restaurant_location_id)

    rows = db.execute(query).all()
    candidates = [
        RetrievedMenuCandidate(
            menu_item=menu_item,
            restaurant=restaurant,
            distance=0.25,
            source="keyword",
        )
        for menu_item, restaurant in rows
    ]
    hydrate_dynamic_bestseller_flags(db, [candidate.menu_item for candidate in candidates])
    candidates.sort(
        key=lambda candidate: (
            1 if is_menu_item_bestseller(candidate.menu_item) else 0,
            float(_safe_decimal(candidate.menu_item.popularity_score)),
            candidate.menu_item.created_at.timestamp(),
        ),
        reverse=True,
    )
    logger.info("RAG keyword results count=%d names=%s", len(candidates), [candidate.menu_item.name for candidate in candidates[:5]])
    return candidates[:limit]


def _fetch_popular_candidates(
    db: Session,
    restaurant_id: uuid.UUID | None,
    restaurant_location_id: uuid.UUID | None,
    *,
    limit: int = TOP_K_RESULTS,
) -> list[RetrievedMenuCandidate]:
    query = (
        select(MenuItem, Restaurant)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .join(RestaurantLocation, MenuItem.restaurant_location_id == RestaurantLocation.id)
        .where(
            Restaurant.is_active.is_(True),
            Restaurant.is_approved.is_(True),
            RestaurantLocation.is_active.is_(True),
            MenuItem.is_available.is_(True),
        )
        .order_by(
            MenuItem.popularity_score.desc(),
            MenuItem.created_at.desc(),
        )
        .limit(limit * 4)
    )

    if restaurant_id is not None:
        query = query.where(Restaurant.id == restaurant_id)
    if restaurant_location_id is not None:
        query = query.where(RestaurantLocation.id == restaurant_location_id)

    rows = db.execute(query).all()
    candidates = [
        RetrievedMenuCandidate(
            menu_item=menu_item,
            restaurant=restaurant,
            distance=0.5,
            source="popular_fallback",
        )
        for menu_item, restaurant in rows
    ]
    hydrate_dynamic_bestseller_flags(db, [candidate.menu_item for candidate in candidates])
    candidates.sort(
        key=lambda candidate: (
            1 if is_menu_item_bestseller(candidate.menu_item) else 0,
            float(_safe_decimal(candidate.menu_item.popularity_score)),
            candidate.menu_item.created_at.timestamp(),
        ),
        reverse=True,
    )
    logger.info("RAG popular fallback results: %d", len(candidates))
    return candidates[:limit]


def _dedupe_candidates(*candidate_groups: list[RetrievedMenuCandidate]) -> list[RetrievedMenuCandidate]:
    deduped: list[RetrievedMenuCandidate] = []
    seen_menu_item_ids: set[uuid.UUID] = set()
    for candidates in candidate_groups:
        for candidate in candidates:
            if candidate.menu_item.id in seen_menu_item_ids:
                continue
            seen_menu_item_ids.add(candidate.menu_item.id)
            deduped.append(candidate)
    return deduped


def _menu_item_dish_key(restaurant_id: uuid.UUID, name: str | None) -> tuple[uuid.UUID, str]:
    return (restaurant_id, _normalize_match_text(name or ""))


def _dedupe_candidates_by_dish(candidates: list[RetrievedMenuCandidate]) -> list[RetrievedMenuCandidate]:
    """Collapse per-branch copies of the same dish to the best-ranked one.

    Every branch carries its own menu-item row, so without this the same dish
    can fill several suggestion slots at slightly different prices ("Kung Pao
    Chicken Rs.29.96" and "Kung Pao Chicken Rs.14.69" side by side).
    """
    deduped: list[RetrievedMenuCandidate] = []
    seen_dishes: set[tuple[uuid.UUID, str]] = set()
    for candidate in candidates:
        dish_key = _menu_item_dish_key(candidate.menu_item.restaurant_id, candidate.menu_item.name)
        if dish_key in seen_dishes:
            continue
        seen_dishes.add(dish_key)
        deduped.append(candidate)
    return deduped


def _fetch_dish_keys_for_item_ids(
    db: Session,
    item_ids: set[uuid.UUID],
) -> set[tuple[uuid.UUID, str]]:
    """Dish keys of already-suggested items, so a follow-up never re-offers
    the same dish from a different branch."""
    if not item_ids:
        return set()
    rows = db.execute(
        select(MenuItem.restaurant_id, MenuItem.name).where(MenuItem.id.in_(item_ids))
    ).all()
    return {_menu_item_dish_key(restaurant_id, name) for restaurant_id, name in rows}


def _candidate_matches_query_text(candidate: RetrievedMenuCandidate, query_text: str) -> bool:
    normalized_query = _normalize_text(query_text)
    if not normalized_query:
        return False

    searchable_fields = " ".join(
        [
            candidate.menu_item.name or "",
            candidate.menu_item.category or "",
            candidate.menu_item.cuisine_type or "",
            candidate.menu_item.description or "",
            candidate.restaurant.name or "",
            candidate.restaurant.cuisine_type or "",
        ]
    )
    normalized_fields = _normalize_text(searchable_fields)
    if normalized_query in normalized_fields:
        return True

    query_tokens = set(_query_tokens(query_text))
    field_tokens = set(_query_tokens(normalized_fields))
    return bool(query_tokens) and query_tokens.issubset(field_tokens)


def _normalized_preference_terms(preferences: UserPreferences | None) -> set[str]:
    if preferences is None:
        return set()
    values = list(getattr(preferences, "favorite_items", []) or []) + list(getattr(preferences, "favorite_cuisines", []) or [])
    return {_normalize_text(str(value)) for value in values if _normalize_text(str(value))}


def _normalized_preference_cuisines(preferences: UserPreferences | None) -> set[str]:
    if preferences is None:
        return set()
    return {
        _normalize_text(str(value))
        for value in getattr(preferences, "favorite_cuisines", []) or []
        if _normalize_text(str(value))
    }


def _normalized_preference_diet(preferences: UserPreferences | None) -> str | None:
    if preferences is None:
        return None
    values = [_normalize_text(str(value)) for value in getattr(preferences, "dietary_preferences", []) or []]
    if any(value in {"veg", "vegetarian"} for value in values):
        return "veg"
    if any(value in {"non veg", "nonveg", "non_veg"} for value in values):
        return "non_veg"
    return None


def _preference_spice_hint(preferences: UserPreferences | None) -> str | None:
    if preferences is None:
        return None
    value = _normalize_text(getattr(preferences, "spice_level", None))
    if value in {"high", "medium", "low"}:
        return value
    return None


def _new_item_sort_key(
    candidate: RetrievedMenuCandidate,
    *,
    intent: ExtractedIntent,
    preferences: UserPreferences | None,
) -> tuple[float, float, float, int, int]:
    searchable_fields = _normalize_text(
        " ".join(
            [
                candidate.menu_item.name or "",
                candidate.menu_item.category or "",
                candidate.menu_item.cuisine_type or "",
                candidate.menu_item.description or "",
                candidate.restaurant.cuisine_type or "",
            ]
        )
    )
    menu_item_signals = extract_menu_item_signals(
        candidate.menu_item,
        restaurant_cuisine_type=candidate.restaurant.cuisine_type,
    )

    score = 0.0
    requested_topics = _intent_requested_topics(intent)
    if requested_topics and any(_candidate_matches_query_text(candidate, topic) for topic in requested_topics):
        score += 2.4
    if intent.cuisine and _candidate_matches_query_text(candidate, intent.cuisine):
        score += 2.1
    if intent.spicy and "spicy" in menu_item_signals.all_signals:
        score += 2.0
    if intent.diet == "veg" and candidate.menu_item.is_veg:
        score += 1.0
    elif intent.diet == "non_veg" and not candidate.menu_item.is_veg:
        score += 1.0

    preference_terms = _normalized_preference_terms(preferences)
    if preference_terms and any(term in searchable_fields for term in preference_terms):
        score += 1.8

    preference_cuisines = _normalized_preference_cuisines(preferences)
    candidate_cuisine = _normalize_text(candidate.menu_item.cuisine_type or candidate.restaurant.cuisine_type)
    if candidate_cuisine and candidate_cuisine in preference_cuisines:
        score += 1.4

    preference_diet = _normalized_preference_diet(preferences)
    if preference_diet == "veg" and candidate.menu_item.is_veg:
        score += 0.7
    elif preference_diet == "non_veg" and not candidate.menu_item.is_veg:
        score += 0.7

    preference_spice = _preference_spice_hint(preferences)
    if preference_spice == "high" and "spicy" in menu_item_signals.all_signals:
        score += 1.1
    elif preference_spice == "medium" and "spicy" in menu_item_signals.all_signals:
        score += 0.7

    launch_timestamp = resolve_menu_item_launch_timestamp(candidate.menu_item).timestamp()
    popularity = float(_safe_decimal(candidate.menu_item.popularity_score))
    return (
        score,
        launch_timestamp,
        popularity,
        1 if is_menu_item_bestseller(candidate.menu_item) else 0,
        1 if candidate.restaurant.is_open else 0,
    )


def _sort_new_item_candidates(
    candidates: list[RetrievedMenuCandidate],
    *,
    intent: ExtractedIntent,
    preferences: UserPreferences | None,
) -> list[RetrievedMenuCandidate]:
    ranked = sorted(
        candidates,
        key=lambda candidate: _new_item_sort_key(candidate, intent=intent, preferences=preferences),
        reverse=True,
    )
    logger.info(
        "RAG new-item ranking intent=%s candidates=%s",
        {
            "dish": intent.dish,
            "cuisine": intent.cuisine,
            "diet": intent.diet,
            "spicy": intent.spicy,
            "new_only": intent.new_only,
        },
        [candidate.menu_item.name for candidate in ranked[:8]],
    )
    return ranked


def _filter_candidates(
    candidates: list[RetrievedMenuCandidate],
    budget_limit: Decimal | None,
    *,
    strict_budget: bool,
    intent: ExtractedIntent | None = None,
    exclude_item_ids: set[uuid.UUID] | None = None,
    exclude_dish_keys: set[tuple[uuid.UUID, str]] | None = None,
) -> list[RetrievedMenuCandidate]:
    excluded_ids = exclude_item_ids or set()
    excluded_dishes = exclude_dish_keys or set()
    available_candidates = [
        candidate
        for candidate in candidates
        if candidate.menu_item.is_available
        and candidate.menu_item.id not in excluded_ids
        and _menu_item_dish_key(candidate.menu_item.restaurant_id, candidate.menu_item.name)
        not in excluded_dishes
    ]
    available_candidates = _dedupe_candidates_by_dish(available_candidates)
    if not available_candidates:
        return []

    if intent is not None:
        if intent.new_only:
            available_candidates = [
                candidate for candidate in available_candidates if is_menu_item_new(candidate.menu_item)
            ]
            if not available_candidates:
                return []

        requested_topics = _intent_requested_topics(intent)
        if requested_topics:
            dish_matches = [
                candidate
                for candidate in available_candidates
                if any(_candidate_matches_query_text(candidate, topic) for topic in requested_topics)
            ]
            if dish_matches:
                if len(requested_topics) > 1:
                    dish_matches.sort(
                        key=lambda candidate: (
                            sum(1 for topic in requested_topics if _candidate_matches_query_text(candidate, topic)),
                            1 if is_menu_item_bestseller(candidate.menu_item) else 0,
                            float(_safe_decimal(candidate.menu_item.popularity_score)),
                            candidate.menu_item.created_at.timestamp(),
                        ),
                        reverse=True,
                    )
                available_candidates = dish_matches
            else:
                return []

        if intent.cuisine and not requested_topics:
            cuisine_matches = [
                candidate
                for candidate in available_candidates
                if _candidate_matches_query_text(candidate, intent.cuisine)
            ]
            if cuisine_matches:
                available_candidates = cuisine_matches

        if intent.category and not requested_topics:
            category_matches = [
                candidate
                for candidate in available_candidates
                if _candidate_matches_query_text(candidate, intent.category)
            ]
            if category_matches:
                available_candidates = category_matches

        if intent.restaurant_query:
            restaurant_matches = [
                candidate
                for candidate in available_candidates
                if _candidate_matches_query_text(candidate, intent.restaurant_query)
            ]
            if restaurant_matches:
                available_candidates = restaurant_matches

        if intent.diet == "veg":
            available_candidates = [candidate for candidate in available_candidates if candidate.menu_item.is_veg]
        elif intent.diet == "non_veg":
            available_candidates = [candidate for candidate in available_candidates if not candidate.menu_item.is_veg]

        if intent.spicy is True:
            spicy_candidates = [
                candidate
                for candidate in available_candidates
                if "spicy" in _normalize_text(candidate.menu_item.name)
                or "spicy" in _normalize_text(candidate.menu_item.description or "")
                or "chilli" in _normalize_text(candidate.menu_item.name)
                or "chilli" in _normalize_text(candidate.menu_item.description or "")
            ]
            if spicy_candidates:
                available_candidates = spicy_candidates

    if not available_candidates:
        return []

    if budget_limit is None or budget_limit <= 0:
        return available_candidates[:TOP_K_RESULTS]

    within_budget = [
        candidate
        for candidate in available_candidates
        if _safe_decimal(candidate.menu_item.price) <= budget_limit
    ]
    if strict_budget:
        return within_budget[:TOP_K_RESULTS]
    return (within_budget or available_candidates)[:TOP_K_RESULTS]


def _resolve_final_candidates(
    db: Session,
    *,
    message: str,
    restaurant_id: uuid.UUID | None,
    restaurant_location_id: uuid.UUID | None,
    budget_limit: Decimal | None,
    strict_budget: bool,
    intent: ExtractedIntent,
    query_embedding: list[float] | None,
    exclude_item_ids: set[uuid.UUID] | None = None,
    exclude_dish_keys: set[tuple[uuid.UUID, str]] | None = None,
    limit: int = TOP_K_RESULTS,
    allow_popular_fallback: bool = True,
) -> tuple[list[RetrievedMenuCandidate], str, int]:
    # No embedding means the provider was unavailable. The vector tier is
    # skipped and the cascade continues at keyword -> popular -> emergency,
    # which is the whole reason _embed_query returns None instead of raising.
    vector_candidates = (
        _retrieve_candidates(
            db,
            query_embedding,
            restaurant_id,
            restaurant_location_id,
            limit=limit,
        )
        if query_embedding is not None
        else []
    )
    filtered_vector = _filter_candidates(
        vector_candidates,
        budget_limit,
        strict_budget=strict_budget,
        intent=intent,
        exclude_item_ids=exclude_item_ids,
        exclude_dish_keys=exclude_dish_keys,
    )
    if filtered_vector:
        return filtered_vector[:TOP_K_RESULTS], "vector", len(vector_candidates)

    keyword_candidates = _fetch_keyword_candidates(
        db,
        message,
        restaurant_id,
        restaurant_location_id,
        limit=limit,
    )
    filtered_keyword = _filter_candidates(
        keyword_candidates,
        budget_limit,
        strict_budget=strict_budget,
        intent=intent,
        exclude_item_ids=exclude_item_ids,
        exclude_dish_keys=exclude_dish_keys,
    )
    if filtered_keyword:
        combined = _dedupe_candidates(filtered_keyword, filtered_vector)
        return combined[:TOP_K_RESULTS], "keyword", len(vector_candidates)

    if not allow_popular_fallback:
        return [], "follow_up_exhausted", len(vector_candidates)

    # No global re-query when scoped: a single-restaurant app with no popular
    # rows must never be handed another restaurant's dishes.
    popular_candidates = _fetch_popular_candidates(db, restaurant_id, restaurant_location_id, limit=limit)

    filtered_popular = _filter_candidates(
        popular_candidates,
        budget_limit,
        strict_budget=strict_budget,
        intent=intent,
        exclude_item_ids=exclude_item_ids,
        exclude_dish_keys=exclude_dish_keys,
    )
    if not filtered_popular and (_intent_requested_topics(intent) or intent.cuisine or intent.category or intent.restaurant_query):
        relaxed_intent = ExtractedIntent(
            intent=intent.intent,
            budget=intent.budget,
            diet=intent.diet,
            spicy=intent.spicy,
            mood=intent.mood,
            show_more=intent.show_more,
        )
        filtered_popular = _filter_candidates(
            popular_candidates,
            budget_limit,
            strict_budget=strict_budget,
            intent=relaxed_intent,
            exclude_item_ids=exclude_item_ids,
            exclude_dish_keys=exclude_dish_keys,
        )
        if filtered_popular:
            logger.info(
                "RAG fallback alternatives activated original_topic=%s relaxed_matches=%s",
                _display_requested_topics(intent) or intent.cuisine or intent.category or intent.restaurant_query,
                _candidate_name_summary(filtered_popular),
            )
    if filtered_popular:
        combined = _dedupe_candidates_by_dish(
            _dedupe_candidates(filtered_popular, filtered_keyword, filtered_vector)
        )
        return combined[:TOP_K_RESULTS], "popular_fallback", len(vector_candidates)

    emergency_candidates = _dedupe_candidates_by_dish(
        _dedupe_candidates(vector_candidates, keyword_candidates, popular_candidates)
    )
    return emergency_candidates[:TOP_K_RESULTS], "emergency_db_fallback", len(vector_candidates)


def _resolve_candidates_without_embedding(
    db: Session,
    *,
    message: str,
    restaurant_id: uuid.UUID | None,
    restaurant_location_id: uuid.UUID | None,
    budget_limit: Decimal | None,
    strict_budget: bool,
    intent: ExtractedIntent,
    filtered_keyword_candidates: list[RetrievedMenuCandidate],
    exclude_item_ids: set[uuid.UUID] | None = None,
    limit: int = TOP_K_RESULTS,
    allow_popular_fallback: bool = True,
    is_follow_up: bool = False,
) -> tuple[list[RetrievedMenuCandidate], str, int]:
    if filtered_keyword_candidates:
        retrieval_source = "keyword_follow_up" if is_follow_up else "keyword_intent"
        return filtered_keyword_candidates[:TOP_K_RESULTS], retrieval_source, 0

    if not allow_popular_fallback:
        return [], "follow_up_exhausted", 0

    popular_candidates = _fetch_popular_candidates(
        db,
        restaurant_id,
        restaurant_location_id,
        limit=limit,
    )
    if not popular_candidates and restaurant_id is not None:
        popular_candidates = _fetch_popular_candidates(db, None, None, limit=limit)

    filtered_popular = _filter_candidates(
        popular_candidates,
        budget_limit,
        strict_budget=strict_budget,
        intent=intent,
        exclude_item_ids=exclude_item_ids,
    )
    if not filtered_popular and (
        _intent_requested_topics(intent) or intent.cuisine or intent.category or intent.restaurant_query
    ):
        relaxed_intent = ExtractedIntent(
            intent=intent.intent,
            budget=intent.budget,
            diet=intent.diet,
            spicy=intent.spicy,
            mood=intent.mood,
            show_more=intent.show_more,
        )
        filtered_popular = _filter_candidates(
            popular_candidates,
            budget_limit,
            strict_budget=strict_budget,
            intent=relaxed_intent,
            exclude_item_ids=exclude_item_ids,
        )
        if filtered_popular:
            logger.info(
                "RAG embedding fallback alternatives activated original_topic=%s relaxed_matches=%s",
                _display_requested_topics(intent) or intent.cuisine or intent.category or intent.restaurant_query,
                _candidate_name_summary(filtered_popular),
            )
    if filtered_popular:
        combined = _dedupe_candidates(filtered_popular, filtered_keyword_candidates)
        return combined[:TOP_K_RESULTS], "popular_fallback", 0

    emergency_candidates = _dedupe_candidates(filtered_keyword_candidates, popular_candidates)
    return emergency_candidates[:TOP_K_RESULTS], "emergency_db_fallback", 0


def _resolve_new_item_candidates_fast(
    db: Session,
    *,
    message: str,
    restaurant_id: uuid.UUID | None,
    restaurant_location_id: uuid.UUID | None,
    budget_limit: Decimal | None,
    strict_budget: bool,
    intent: ExtractedIntent,
    preferences: UserPreferences | None,
    exclude_item_ids: set[uuid.UUID] | None = None,
    exclude_dish_keys: set[tuple[uuid.UUID, str]] | None = None,
    limit: int = TOP_K_RESULTS,
) -> tuple[list[RetrievedMenuCandidate], str]:
    keyword_candidates = _fetch_keyword_candidates(
        db,
        message,
        restaurant_id,
        restaurant_location_id,
        limit=limit,
    )
    # Scoped apps stay scoped even when the restaurant has no popular rows.
    popular_candidates = _fetch_popular_candidates(
        db,
        restaurant_id,
        restaurant_location_id,
        limit=limit,
    )

    combined_candidates = _dedupe_candidates(keyword_candidates, popular_candidates)
    filtered_candidates = _filter_candidates(
        combined_candidates,
        budget_limit,
        strict_budget=strict_budget,
        intent=intent,
        exclude_item_ids=exclude_item_ids,
        exclude_dish_keys=exclude_dish_keys,
    )
    if not filtered_candidates:
        return [], "new_item_no_match"

    ranked_candidates = _sort_new_item_candidates(
        filtered_candidates,
        intent=intent,
        preferences=preferences,
    )
    return ranked_candidates[:TOP_K_RESULTS], "new_item_fast_path"


def _format_context_line(candidate: RetrievedMenuCandidate) -> str:
    item = candidate.menu_item
    restaurant = candidate.restaurant
    description = _trim_text(item.description or "No description available", MAX_DESCRIPTION_CHARS)
    veg_label = "Veg" if item.is_veg else "Non-Veg"
    new_label = " | New item" if is_menu_item_new(item) else ""
    return (
        f"{item.name} | Rs. {_safe_decimal(item.price):.2f} | {veg_label} | "
        f"{item.category} | {restaurant.name}{new_label} | {description}"
    )


def _build_context_block(candidates: list[RetrievedMenuCandidate]) -> str:
    # The prompt should cover every suggestion card the user will see, so the
    # reply can reference any of them instead of only the first three.
    prompt_candidate_limit = max(2, min(MAX_CONTEXT_CANDIDATES, SUGGESTION_LIMIT))
    return "\n".join(
        _format_context_line(candidate)
        for candidate in candidates[:prompt_candidate_limit]
    )


def _build_combo_context_block(
    combos: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    for combo in combos[:3]:
        combo_name = str(combo.get("combo_name") or "Generated Combo")
        restaurant_name = str(combo.get("restaurant_name") or "Restaurant")
        combo_price = combo.get("suggested_combo_price")
        item_names = combo.get("item_names") or []
        items_block = ", ".join(str(item_name) for item_name in item_names[:4])
        lines.append(
            f"Combo: {combo_name}\nRestaurant: {restaurant_name}\nPrice: Rs. {combo_price}\nIncludes: {items_block}"
        )
    return "\n\n".join(lines)


def _build_history_block(history_messages: list[ChatHistory]) -> str:
    if not history_messages:
        return "No recent history."
    lines: list[str] = []
    for entry in history_messages[-3:]:
        role = "User" if entry.role == ChatMessageRole.USER else "Assistant"
        lines.append(f"{role}: {_trim_text(entry.message, 120)}")
    return "\n".join(lines)


def _build_prompt(
    *,
    message: str,
    context_block: str,
    history_block: str,
    intent: ExtractedIntent,
    session_state: SessionConversationState,
    availability_note: str | None = None,
) -> str:
    intent_fields = {
        "intent": intent.intent,
        "dish": intent.dish,
        "items": intent.items or None,
        "cuisine": intent.cuisine,
        "category": intent.category,
        "restaurant_query": intent.restaurant_query,
        "budget": str(intent.budget) if intent.budget is not None else None,
        "diet": intent.diet,
        "spicy": intent.spicy,
        "mood": intent.mood,
        "show_more": intent.show_more or None,
    }
    intent_block = json.dumps(
        {key: value for key, value in intent_fields.items() if value not in (None, [], "")},
        default=str,
        separators=(",", ":"),
    )
    # Static examples sit directly after the system prompt so warm requests
    # reuse the largest possible cached prompt prefix in Ollama.
    style_block = """RESPONSE STYLE EXAMPLES:
User: Suggest spicy food
Assistant: If you're in the mood for heat 🔥, the top spicy options from this menu are the strongest place to start.

User: Do you have sushi?
Assistant: There's no sushi on the menu right now — but if you're open to alternatives, these picks come closest.

User: Show me more
Assistant: Sure — here are a few more options in the same lane, without repeating the last set.
"""
    availability_block = f"AVAILABILITY:\n{availability_note}\n\n" if availability_note else ""
    return (
        f"{SYSTEM_PROMPT}\n\n"
        f"{style_block}\n"
        f"TIME CONTEXT:\n{_time_of_day_prompt_hint()}\n\n"
        f"STRUCTURED INTENT:\n{intent_block}\n\n"
        f"SESSION SUMMARY:\n{_session_state_prompt_summary(session_state)}\n\n"
        f"RECENT HISTORY:\n{history_block}\n\n"
        f"MENU CONTEXT:\n{context_block}\n\n"
        f"{availability_block}"
        f"USER QUESTION:\n{_trim_text(message, 220)}\n"
    )


def _build_greeting_prompt(message: str) -> str:
    return (
        f"{GREETING_PROMPT}\n\n"
        f"USER GREETING:\n{_trim_text(message, 120)}\n"
    )


def _build_acknowledgement_reply(message: str = "") -> str:
    variants = (
        "Anytime. Tell me what you're in the mood for, and I'll narrow it down.",
        "Glad that helps! Whenever you're ready, tell me a craving and I'll find a match.",
        "Happy to help 😊 Want me to line up another pick or check an offer?",
        "🙌 Say the word if you want more ideas — cuisine, budget, or spice level all work.",
    )
    digest = hashlib.sha1(_normalize_match_text(message).encode("utf-8")).hexdigest()
    return variants[int(digest, 16) % len(variants)]


def _greeting_moment_from_message(message: str) -> str | None:
    """The daypart the customer themselves named, if any.

    "Good morning!" must be answered as morning even when the server clock
    says evening — respect what the customer said over where the server runs.
    """
    normalized = _normalize_match_text(message)
    if "morning" in normalized:
        return "morning"
    if "afternoon" in normalized:
        return "midday"
    if "evening" in normalized:
        return "evening"
    if "night" in normalized:
        return "night"
    return None


def _build_greeting_reply(message: str = "") -> str:
    moment = _greeting_moment_from_message(message) or _current_meal_moment()
    if moment == "morning":
        return "Good morning 👋 What sounds good right now? I can help with breakfast picks, spice levels, budgets, or quick cravings."
    if moment == "midday":
        return "Good afternoon 👋 Looking for lunch ideas? I can help by cuisine, budget, spice level, or whatever you're craving."
    if moment == "evening":
        return "Good evening 👋 What are you craving tonight? I can help with spicy picks, comfort food, combos, or budget-friendly options."
    return "Hey 👋 Late-night cravings? I can help with dishes by cuisine, budget, spice level, offers, or meal mood."


def _build_small_talk_reply() -> str:
    return (
        "I'm your food concierge, so I'm best at helping with restaurants, menus, offers, combos, and meal ideas. "
        "Tell me a craving, cuisine, budget, or spice preference and I'll take it from there."
    )


def _build_offer_query_reply() -> str:
    return (
        "I can help you spot food offers and better-value picks. Try asking for things like dinner deals, combo offers, "
        "or budget-friendly meals under a price."
    )


def _build_order_history_reply() -> str:
    return (
        "I can help with food suggestions based on what you usually order. Try asking for something similar to your past "
        "orders, a repeat-worthy favorite, or a more budget-friendly reorder idea."
    )


def _build_invalid_input_reply() -> str:
    return (
        "I didn't quite catch that. Ask me about food, restaurants, menus, combos, offers, or something like dinner under a budget."
    )


def _build_unsupported_domain_reply() -> str:
    return (
        "That one's outside my kitchen 🍽️ I'm this app's restaurant assistant, so I can help with the menu, "
        "dishes, prices, offers, and orders. What are you craving?"
    )


def _build_restaurant_list_reply(
    db: Session,
    *,
    message: str,
    restaurant_id: uuid.UUID | None,
) -> str:
    """Grounded answer for "which restaurants do you have?".

    The restaurant_list intent previously fell through to dish retrieval and
    answered with menu items; the correct answer is the restaurants
    themselves, scoped to the app.
    """
    query = select(Restaurant).where(
        Restaurant.is_active.is_(True),
        Restaurant.is_approved.is_(True),
    )
    if restaurant_id is not None:
        query = query.where(Restaurant.id == restaurant_id)
    restaurants = db.scalars(query.order_by(Restaurant.name)).all()
    if not restaurants:
        return "I couldn't find any active restaurants right now — please try again in a bit."

    def _label(restaurant: Restaurant) -> str:
        cuisine = (restaurant.cuisine_type or "").strip()
        return f"{restaurant.name} ({cuisine})" if cuisine else restaurant.name

    if restaurant_id is not None:
        return (
            f"This app is all about {_label(restaurants[0])} — ask me for any dish on the menu, "
            "a budget-friendly pick, or something spicy, and I'll find it."
        )

    excluded_tokens = {"restaurant", "restaurants", "list", "there", "here"}
    tokens = [
        _singularize_token(token)
        for token in _query_tokens(message)
        if token not in TOPIC_STOPWORDS and token not in excluded_tokens
    ]
    matching = [
        restaurant
        for restaurant in restaurants
        if any(token in _normalize_text(f"{restaurant.name} {restaurant.cuisine_type or ''}") for token in tokens)
    ] if tokens else []
    listed = matching or restaurants
    names = ", ".join(_label(restaurant) for restaurant in listed[:8])
    if matching:
        return f"For that, you can order from {names}. Want me to pull up their best dishes?"
    return (
        f"Right now you can order from {names}. "
        "Tell me a craving or a cuisine and I'll narrow it down."
    )


def _instant_reply_for_intent(intent: ExtractedIntent, message: str = "") -> str | None:
    # small_talk is intentionally absent: casual conversation goes through the
    # LLM (with the canned reply kept only as its failure fallback).
    reply_map = {
        "greeting": _build_greeting_reply(message),
        "order_history": _build_order_history_reply(),
        "unsupported_domain": _build_unsupported_domain_reply(),
        "invalid_input": _build_invalid_input_reply(),
    }
    return reply_map.get(intent.intent)


def _generate_reply(prompt: str) -> str:
    payload = {
        "model": settings.ollama_chat_model,
        "prompt": prompt,
        "stream": False,
        **think_option(),
        **local_only_options(),
        "options": {
            "num_predict": settings.rag_max_reply_tokens,
            "temperature": 0.35,
        },
    }

    try:
        response = GENERATE_CLIENT.post(GENERATE_ENDPOINT, json=payload)
        response.raise_for_status()
    except httpx.ReadTimeout as exc:
        logger.warning("RAG Ollama generate timed out after %.1fs", settings.ollama_chat_timeout_seconds)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Chat model response timed out",
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("RAG Ollama generate transport error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate chat response from Ollama",
        ) from exc

    reply = response.json().get("response")
    if not isinstance(reply, str) or not reply.strip():
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Ollama returned an empty response",
        )
    return reply.strip()


def _stream_reply_events(prompt: str) -> Iterator[dict[str, Any]]:
    payload = {
        "model": settings.ollama_chat_model,
        "prompt": prompt,
        "stream": True,
        **think_option(),
        **local_only_options(),
        "options": {
            "num_predict": settings.rag_max_reply_tokens,
            "temperature": 0.35,
        },
    }

    try:
        with GENERATE_CLIENT.stream("POST", GENERATE_ENDPOINT, json=payload) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("RAG stream returned non-JSON line: %s", _trim_text(line, 160))
    except httpx.ReadTimeout as exc:
        logger.warning("RAG Ollama stream timed out after %.1fs", settings.ollama_chat_timeout_seconds)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Chat model response timed out",
        ) from exc
    except httpx.HTTPError as exc:
        logger.warning("RAG Ollama stream transport error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to generate chat response from Ollama",
        ) from exc


def _build_chat_new_item_metadata(
    candidate: RetrievedMenuCandidate,
    *,
    intent: ExtractedIntent | None,
    uses_personal_context: bool,
) -> tuple[str | None, str | None, str | None]:
    new_item_reason = get_new_item_reason(candidate.menu_item)
    if uses_personal_context and intent is not None and (
        intent.spicy is not None or intent.cuisine is not None or intent.diet is not None
    ):
        return "Matches Your Taste", "Aligned with your active taste request.", new_item_reason
    if is_menu_item_trending(candidate.menu_item):
        return "Trending Now", "A just-launched item gaining strong customer demand.", new_item_reason
    if is_menu_item_bestseller(candidate.menu_item):
        return "Best Seller", "One of the most-ordered items at this branch recently.", None
    if is_menu_item_new(candidate.menu_item):
        return "Just Launched", "Manually marked as a recent launch.", new_item_reason
    if uses_personal_context:
        return "Recommended for You", "A general personalized match for your request.", None
    return None, None, None


def _suggestion_items(
    candidates: list[RetrievedMenuCandidate],
    *,
    intent: ExtractedIntent | None = None,
    uses_personal_context: bool = False,
) -> list[ChatSuggestionItem]:
    suggestions: list[ChatSuggestionItem] = []
    for candidate in candidates[:SUGGESTION_LIMIT]:
        similarity_score = max(0.0, min(1.0, 1 - candidate.distance))
        is_new = is_menu_item_new(candidate.menu_item)
        recommendation_label, recommendation_reason, new_item_reason = _build_chat_new_item_metadata(
            candidate,
            intent=intent,
            uses_personal_context=uses_personal_context,
        )
        suggestions.append(
            ChatSuggestionItem(
                id=candidate.menu_item.id,
                restaurant_id=candidate.restaurant.id,
                restaurant_location_id=candidate.menu_item.restaurant_location_id,
                restaurant_name=candidate.restaurant.name,
                restaurant_location_name=(
                    candidate.menu_item.restaurant_location.branch_name
                    if candidate.menu_item.restaurant_location is not None
                    else candidate.restaurant.city
                ),
                name=candidate.menu_item.name,
                category=candidate.menu_item.category,
                cuisine_type=candidate.menu_item.cuisine_type,
                description=candidate.menu_item.description,
                price=candidate.menu_item.price,
                is_veg=candidate.menu_item.is_veg,
                is_available=candidate.menu_item.is_available,
                is_bestseller=is_menu_item_bestseller(candidate.menu_item),
                is_featured=get_menu_item_featured_flag(candidate.menu_item),
                image_url=candidate.menu_item.image_url,
                launched_at=resolve_menu_item_launch_timestamp(candidate.menu_item),
                is_new_launch=candidate.menu_item.is_new_launch,
                is_new=is_new,
                recommendation_label=recommendation_label,
                recommendation_reason=recommendation_reason,
                new_item_reason=new_item_reason,
                similarity_score=round(similarity_score, 4),
            )
        )
    return suggestions


def _attach_suggestion_favorites(
    db: Session,
    user: User,
    suggestions: list[ChatSuggestionItem],
) -> list[ChatSuggestionItem]:
    if not suggestions:
        return suggestions
    favorite_ids = get_user_favorite_ids(db, user, menu_item_ids=[item.id for item in suggestions])
    if not favorite_ids:
        return suggestions
    return apply_chat_suggestion_favorite_flags(suggestions, favorite_ids)


def _contains_generic_fallback(reply: str) -> bool:
    normalized_reply = _normalize_text(reply)
    return any(marker in normalized_reply for marker in GENERIC_REPLY_MARKERS)


def _intent_prefers_keyword_first(intent: ExtractedIntent, effective_query: str) -> bool:
    if intent.intent in {"dish_recommendation", "restaurant_list", "menu_question"}:
        return True
    if intent.show_more and (_intent_requested_topics(intent) or intent.cuisine or intent.category or intent.restaurant_query):
        return True
    return len(_query_tokens(effective_query)) <= 4


def _has_strong_keyword_signal(candidates: list[RetrievedMenuCandidate]) -> bool:
    return len(candidates) >= 2 or any(is_menu_item_bestseller(candidate.menu_item) for candidate in candidates)


def _should_bypass_llm(
    *,
    retrieval_source: str,
    candidates: list[RetrievedMenuCandidate],
    intent: ExtractedIntent,
    is_follow_up: bool,
) -> bool:
    """Template replies only cover empty or degenerate retrieval.

    Whenever grounded candidates exist, the LLM phrases the reply. The old
    keyword/popular bypass rules routed the most common intents (dish search,
    filtered recommendations) to canned templates, which is why the assistant
    read as robotic; with streaming and prompt-prefix caching the LLM path is
    fast enough to be the default.
    """
    if not candidates or retrieval_source == "no_more_matches":
        return True
    if retrieval_source == "emergency_db_fallback":
        return True
    return False


def _message_requests_personal_context(message: str) -> bool:
    normalized = _normalize_text(message)
    return any(marker in normalized for marker in PERSONALIZED_QUERY_MARKERS)


def _resolve_global_cacheability(
    *,
    message: str,
    restaurant_id: uuid.UUID | None,
    is_greeting: bool,
    uses_personal_context: bool,
    is_follow_up: bool,
) -> tuple[bool, str]:
    if restaurant_id is not None:
        return False, "restaurant_scope"
    if uses_personal_context:
        return False, "personal_context"
    if is_follow_up:
        return False, "follow_up"
    if _is_contextual_menu_question(message):
        # "how much does it cost?" answers depend on this session's dish;
        # caching one globally would serve another user the wrong answer.
        return False, "contextual_menu_question"
    if is_greeting:
        return True, "greeting"

    normalized = _normalize_text(message)
    if any(marker in normalized for marker in PERSONALIZED_QUERY_MARKERS):
        return False, "personalized_query"
    return True, "generic_query"


def _is_global_response_cacheable(
    *,
    message: str,
    restaurant_id: uuid.UUID | None,
    is_greeting: bool,
    uses_personal_context: bool,
    is_follow_up: bool,
) -> bool:
    cacheable, _ = _resolve_global_cacheability(
        message=message,
        restaurant_id=restaurant_id,
        is_greeting=is_greeting,
        uses_personal_context=uses_personal_context,
        is_follow_up=is_follow_up,
    )
    return cacheable


def _lookup_global_response_cache(
    *,
    message: str,
    restaurant_id: uuid.UUID | None,
    is_greeting: bool,
    uses_personal_context: bool,
    is_follow_up: bool,
) -> tuple[str, tuple[str, list[ChatSuggestionItem], str] | None, bool, str]:
    descriptor = _infer_cache_query_descriptor(message)
    normalized_query = descriptor.normalized_message
    cache_key = _response_cache_key(message, restaurant_id, descriptor=descriptor)
    cacheable, reason = _resolve_global_cacheability(
        message=message,
        restaurant_id=restaurant_id,
        is_greeting=is_greeting,
        uses_personal_context=uses_personal_context,
        is_follow_up=is_follow_up,
    )
    logger.info(
        "RAG response cache precheck raw_message=%s normalized_query=%s extracted_intent=%s extracted_topic=%s key=%s cacheable=%s reason=%s",
        message,
        normalized_query,
        descriptor.cache_intent,
        descriptor.topic,
        cache_key,
        cacheable,
        reason,
    )
    if not cacheable:
        logger.info("RAG response cache skipped key=%s reason=%s", cache_key, reason)
        return cache_key, None, False, reason

    payload = _deserialize_chat_response_cache_payload(cache_get_json(cache_key))
    if payload is None:
        logger.info("RAG response cache miss key=%s normalized_query=%s", cache_key, normalized_query)
    else:
        logger.info("RAG response cache hit key=%s normalized_query=%s", cache_key, normalized_query)
    return cache_key, payload, True, reason


def _serialize_chat_response_cache_payload(
    *,
    reply: str,
    suggestions: list[ChatSuggestionItem],
    combo_suggestions: list[GeneratedComboResponse],
    offer_suggestions: list[PersonalizedOfferCardResponse],
    retrieval_source: str,
) -> dict[str, Any]:
    return {
        "reply": reply,
        "suggestions": [item.model_dump(mode="json") for item in suggestions],
        "combo_suggestions": [item.model_dump(mode="json") for item in combo_suggestions],
        "offer_suggestions": [item.model_dump(mode="json") for item in offer_suggestions],
        "retrieval_source": retrieval_source,
    }


def _deserialize_chat_response_cache_payload(
    payload: object,
) -> tuple[str, list[ChatSuggestionItem], list[GeneratedComboResponse], list[PersonalizedOfferCardResponse], str] | None:
    if not isinstance(payload, dict):
        return None
    reply = payload.get("reply")
    suggestions_payload = payload.get("suggestions")
    combo_suggestions_payload = payload.get("combo_suggestions")
    offer_suggestions_payload = payload.get("offer_suggestions")
    retrieval_source = payload.get("retrieval_source")
    if not isinstance(reply, str) or not isinstance(retrieval_source, str) or not isinstance(suggestions_payload, list):
        return None
    if combo_suggestions_payload is None:
        combo_suggestions_payload = []
    if not isinstance(combo_suggestions_payload, list):
        return None
    if offer_suggestions_payload is None:
        offer_suggestions_payload = []
    if not isinstance(offer_suggestions_payload, list):
        return None
    try:
        suggestions = [ChatSuggestionItem.model_validate(item) for item in suggestions_payload]
        combo_suggestions = [
            GeneratedComboResponse.model_validate(item)
            for item in combo_suggestions_payload
        ]
        offer_suggestions = [
            PersonalizedOfferCardResponse.model_validate(item)
            for item in offer_suggestions_payload
        ]
    except Exception:
        logger.warning("RAG response cache payload validation failed")
        return None
    return reply, suggestions, combo_suggestions, offer_suggestions, retrieval_source


def _format_suggestion_names(suggestions: list[ChatSuggestionItem]) -> str:
    suggestion_names = [f"{item.name} (Rs. {item.price})" for item in suggestions[:3]]
    if not suggestion_names:
        return ""
    if len(suggestion_names) == 1:
        return suggestion_names[0]
    if len(suggestion_names) == 2:
        return f"{suggestion_names[0]} or {suggestion_names[1]}"
    return f"{', '.join(suggestion_names[:-1])}, or {suggestion_names[-1]}"


def _suggestion_reason_hint(suggestion: ChatSuggestionItem) -> str | None:
    if suggestion.recommendation_label == "Based on Your Orders":
        return f"{suggestion.name} stands out because it lines up nicely with what you've ordered before."
    if suggestion.recommendation_label == "Matches Your Taste":
        return f"{suggestion.name} looks like a strong fit for your current taste preferences."
    if suggestion.recommendation_label == "Recommended for You":
        return f"{suggestion.name} feels like one of the best all-round matches here."
    if suggestion.recommendation_label == "Just Launched":
        return f"{suggestion.name} is one of the fresher additions on the menu right now."
    if suggestion.recommendation_label == "Trending Now":
        return f"{suggestion.name} is getting strong attention right now."
    if suggestion.new_item_reason:
        return suggestion.new_item_reason
    return None


def _build_combo_reply_from_context(message: str, combo_count: int) -> str:
    topic = _extract_combo_topic(message)
    if topic:
        return (
            f"If you're leaning toward {topic}, I found {combo_count} combo pick"
            f"{'' if combo_count == 1 else 's'} worth a look 👇"
        )
    return (
        f"These combo picks look like the strongest fit right now 👇"
        if combo_count != 1
        else "I found one combo pick that looks especially promising 👇"
    )


def _offer_matches_requested_topics(
    offer: PersonalizedOfferCardResponse,
    *,
    items: list[str] | None,
    cuisine: str | None,
    restaurant_query: str | None,
    wants_free_delivery: bool,
) -> bool:
    if wants_free_delivery and offer.discount_type != "FREE_DELIVERY":
        return False

    if cuisine and cuisine not in _normalize_text(offer.cuisine_type):
        return False

    if restaurant_query:
        restaurant_fields = " ".join(
            part
            for part in [
                offer.restaurant_name,
                offer.restaurant_location_name or "",
                offer.title,
                offer.subtitle,
            ]
            if part
        )
        if restaurant_query not in _normalize_text(restaurant_fields):
            return False

    if items:
        haystack = " ".join(
            part
            for part in [
                offer.title,
                offer.subtitle,
                offer.offer_name,
                offer.menu_item_name or "",
                offer.generated_combo_name or "",
                offer.cuisine_type or "",
                offer.restaurant_name,
                offer.badge,
            ]
            if part
        )
        normalized_haystack = _normalize_text(haystack)
        return any(item in normalized_haystack for item in items)

    return True


def _filter_offer_cards_for_chat_query(
    cards: list[PersonalizedOfferCardResponse],
    *,
    restaurant_id: uuid.UUID | None,
    restaurant_location_id: uuid.UUID | None,
    intent: ExtractedIntent,
    message: str,
) -> list[PersonalizedOfferCardResponse]:
    offer_overrides = _extract_offer_query_overrides(message)
    requested_items = intent.items or offer_overrides["items"]
    requested_cuisine = intent.cuisine or offer_overrides["cuisine"]
    requested_restaurant = intent.restaurant_query or offer_overrides["restaurant_query"]
    wants_free_delivery = bool(offer_overrides["wants_free_delivery"])
    has_specific_scope = bool(
        requested_items
        or requested_cuisine
        or requested_restaurant
        or wants_free_delivery
    )

    exclusion_reasons = {
        "restaurant_scope": 0,
        "location_scope": 0,
        "query_scope": 0,
    }
    filtered: list[PersonalizedOfferCardResponse] = []
    for card in cards:
        if restaurant_id is not None and card.restaurant_id != restaurant_id:
            exclusion_reasons["restaurant_scope"] += 1
            continue
        if (
            restaurant_location_id is not None
            and card.restaurant_location_id is not None
            and card.restaurant_location_id != restaurant_location_id
        ):
            exclusion_reasons["location_scope"] += 1
            continue
        if not _offer_matches_requested_topics(
            card,
            items=requested_items,
            cuisine=requested_cuisine,
            restaurant_query=requested_restaurant,
            wants_free_delivery=wants_free_delivery,
        ):
            exclusion_reasons["query_scope"] += 1
            continue
        filtered.append(card)

    logger.info(
        "RAG offer filter total_cards=%d filtered_cards=%d restaurant_id=%s restaurant_location_id=%s requested_items=%s requested_cuisine=%s requested_restaurant=%s wants_free_delivery=%s exclusion_reasons=%s",
        len(cards),
        len(filtered),
        restaurant_id,
        restaurant_location_id,
        requested_items,
        requested_cuisine,
        requested_restaurant,
        wants_free_delivery,
        exclusion_reasons,
    )
    if filtered:
        return filtered[:4]
    if has_specific_scope:
        return []

    scoped = [
        card
        for card in cards
        if restaurant_id is None or card.restaurant_id == restaurant_id
    ]
    if restaurant_id is not None:
        # Never surface another restaurant's offers inside a scoped app, even
        # when the scoped restaurant has no live offers of its own.
        return scoped[:4]
    return scoped[:4] if scoped else cards[:4]


def _build_offer_context_block(offers: list[PersonalizedOfferCardResponse]) -> str:
    lines: list[str] = []
    for offer in offers[:4]:
        details: list[str] = [offer.title, offer.restaurant_name]
        if offer.discount_label:
            details.append(offer.discount_label)
        if offer.minimum_order_amount > 0:
            details.append(f"Min order Rs. {offer.minimum_order_amount}")
        if offer.expires_at:
            details.append(f"Expires {offer.expires_at:%d %b}")
        lines.append("\n".join(details))
    return "\n\n".join(lines)


def _build_offer_reply_from_cards(
    offers: list[PersonalizedOfferCardResponse],
    *,
    message: str,
) -> str:
    offer_overrides = _extract_offer_query_overrides(message)
    if offer_overrides["wants_free_delivery"]:
        return (
            "Here are some live free-delivery style offers you can use 👇"
            if len(offers) != 1
            else "I found one live free-delivery offer you can use 👇"
        )
    if offer_overrides["items"]:
        requested = ", ".join(offer_overrides["items"][:2])
        return (
            f"Here are the live offers closest to {requested} right now 👇"
            if len(offers) != 1
            else f"I found one live offer that fits {requested} 👇"
        )
    return (
        "Here are some live offers you can use 👇"
        if len(offers) != 1
        else "I found one live offer you can use right now 👇"
    )


def _build_offer_no_match_reply(
    *,
    intent: ExtractedIntent,
    message: str,
) -> str:
    offer_overrides = _extract_offer_query_overrides(message)
    requested_items = intent.items or offer_overrides["items"] or []
    requested_cuisine = intent.cuisine or offer_overrides["cuisine"]
    requested_restaurant = intent.restaurant_query or offer_overrides["restaurant_query"]
    wants_free_delivery = bool(offer_overrides["wants_free_delivery"])

    if wants_free_delivery:
        return "There are no live free-delivery offers right now, but I can still suggest budget-friendly picks."
    if requested_items:
        requested = ", ".join(requested_items[:2])
        return f"There are no live {requested} offers right now, but I can still suggest some budget-friendly options."
    if requested_cuisine:
        return f"There are no live {requested_cuisine.title()} offers right now, but I can still suggest some budget-friendly options."
    if requested_restaurant:
        return f"I couldn't find any live offers for {requested_restaurant.title()} right now, but I can still suggest some budget-friendly options."
    return "No live offers right now, but I can still suggest budget-friendly picks."


def _is_strong_item_name_match(requested_item: str, candidate_name: str) -> bool:
    normalized_requested = _normalize_text(requested_item)
    normalized_candidate = _normalize_text(candidate_name)
    if not normalized_requested or not normalized_candidate:
        return False
    if normalized_requested in normalized_candidate:
        return True
    requested_tokens = set(_query_tokens(requested_item))
    candidate_tokens = set(_query_tokens(candidate_name))
    return bool(requested_tokens) and requested_tokens.issubset(candidate_tokens)


def _matching_suggestions_for_dish(
    suggestions: list[ChatSuggestionItem],
    extracted_intent: ExtractedIntent | None,
) -> list[ChatSuggestionItem]:
    requested_topics = _intent_requested_topics(extracted_intent)
    if not requested_topics:
        return []
    # Match on the full searchable surface, not just the dish name: a request
    # like "spicy chinese" is satisfied by cuisine/description even though no
    # dish is literally named that, and claiming "no exact match" while
    # showing exact matches reads as contradictory.
    matched = []
    for suggestion in suggestions:
        searchable = " ".join(
            part
            for part in (
                suggestion.name,
                suggestion.category,
                suggestion.cuisine_type or "",
                suggestion.description or "",
            )
            if part
        )
        if any(_is_strong_item_name_match(topic, searchable) for topic in requested_topics):
            matched.append(suggestion)
    return matched


def _candidate_name_summary(candidates: list[RetrievedMenuCandidate]) -> list[str]:
    return [candidate.menu_item.name for candidate in candidates[:5]]


def _build_available_match_reply(
    suggestions: list[ChatSuggestionItem],
    extracted_intent: ExtractedIntent | None,
) -> str:
    matching_suggestions = _matching_suggestions_for_dish(suggestions, extracted_intent)
    if not matching_suggestions:
        matching_suggestions = suggestions[:3]
    if len(matching_suggestions) == 1:
        suggestion = matching_suggestions[0]
        reason_hint = _suggestion_reason_hint(suggestion)
        if reason_hint:
            return f"Yes — {reason_hint}"
        return f"Yes — {suggestion.name} from {suggestion.restaurant_name} looks like the clearest match."

    formatted_names = _format_suggestion_names(matching_suggestions)
    requested_item = _display_requested_topics(extracted_intent)
    return f"Yes — for {requested_item}, these grounded options look like the closest fit: {formatted_names}."


def _build_safe_reply(
    message: str,
    suggestions: list[ChatSuggestionItem],
    retrieval_source: str,
    *,
    extracted_intent: ExtractedIntent | None = None,
    is_follow_up: bool = False,
    follow_up_base_message: str | None = None,
) -> str:
    if retrieval_source == "greeting":
        return _build_greeting_reply(message)
    if extracted_intent is not None and extracted_intent.intent == "menu_question" and not suggestions:
        requested = _display_requested_topics(extracted_intent)
        if requested and requested != "that":
            return f"I couldn't find {requested} on the menu to check. Tell me the dish name as it appears and I'll pull up its details."
        return "Which dish would you like to know about? Give me its name and I'll pull up the price and details."
    if retrieval_source == "no_more_matches":
        topic_hint = _topic_hint_from_message(follow_up_base_message or message)
        return f"I've already shown the strongest remaining {topic_hint} options in this set. If you want, I can switch direction and find something lighter, cheaper, spicier, or vegetarian."
    if extracted_intent is not None and extracted_intent.new_only and not suggestions:
        topic = extracted_intent.cuisine or _display_requested_topics(extracted_intent) or ("spicy" if extracted_intent.spicy else None)
        if topic:
            return f"I don't see any newly launched {topic} items right now, but I can still help you find the closest alternatives."
        return "I don't see any newly launched items right now, but I can still help with the strongest current picks."
    if not suggestions:
        return "I couldn't pull together a strong menu match just yet. Try narrowing it by cuisine, budget, spice level, or whether you want veg or non-veg."

    formatted_names = _format_suggestion_names(suggestions)
    lead_reason = _suggestion_reason_hint(suggestions[0])
    if extracted_intent is not None and extracted_intent.new_only:
        if is_follow_up:
            return f"If you want a few more fresh launches, these are the next best options: {formatted_names}."
        if extracted_intent.spicy:
            return f"If you're after something new with a bit of heat 🔥, these are the best matches right now: {formatted_names}."
        if extracted_intent.cuisine:
            return f"Here are the freshest {extracted_intent.cuisine} picks available right now: {formatted_names}."
        return f"These are the freshest menu additions worth a look right now: {formatted_names}."
    if is_follow_up:
        return f"Sure — here are a few more options in the same lane: {formatted_names}."
    if _matching_suggestions_for_dish(suggestions, extracted_intent):
        return _build_available_match_reply(suggestions, extracted_intent)
    if _intent_requested_topics(extracted_intent):
        requested_item = _display_requested_topics(extracted_intent)
        return f"I couldn't find an exact {requested_item} right now, but these are the closest grounded alternatives: {formatted_names}."
    if retrieval_source == "popular_fallback":
        return f"I couldn't find an exact match for that, but these popular picks are probably the closest fit: {formatted_names}."
    if lead_reason:
        return f"{lead_reason} I'd start with {formatted_names}."
    return f"These look like the strongest options from the current menu: {formatted_names}."


def _ensure_useful_reply(
    *,
    message: str,
    raw_reply: str,
    suggestions: list[ChatSuggestionItem],
    retrieval_source: str,
    extracted_intent: ExtractedIntent | None = None,
    is_follow_up: bool = False,
    follow_up_base_message: str | None = None,
    fallback_reply_override: str | None = None,
) -> str:
    contradiction_markers = (
        "do not currently have",
        "do not have an exact match",
        "don't currently have",
        "not available",
    )
    contradictory_unavailable_reply = bool(_matching_suggestions_for_dish(suggestions, extracted_intent)) and any(
        marker in _normalize_text(raw_reply) for marker in contradiction_markers
    )

    if raw_reply.strip() and not _contains_generic_fallback(raw_reply) and not contradictory_unavailable_reply:
        return raw_reply.strip()

    safe_reply = fallback_reply_override or _build_safe_reply(
        message,
        suggestions,
        retrieval_source,
        extracted_intent=extracted_intent,
        is_follow_up=is_follow_up,
        follow_up_base_message=follow_up_base_message,
    )
    logger.warning("RAG generic reply intercepted. Replacing with safe DB-backed reply: %s", safe_reply)
    return safe_reply


def _save_message(
    db: Session,
    *,
    user_id: uuid.UUID,
    restaurant_id: uuid.UUID | None,
    session_id: uuid.UUID,
    role: ChatMessageRole,
    message: str,
    context_payload: dict[str, Any],
) -> ChatHistory:
    record = ChatHistory(
        user_id=user_id,
        restaurant_id=restaurant_id,
        session_id=session_id,
        role=role,
        message=message,
        context_payload=context_payload,
    )
    db.add(record)
    return record


def _prepare_cached_response_turn(
    db: Session,
    *,
    user: User,
    message: str,
    session_id: uuid.UUID | None,
    restaurant_id: uuid.UUID | None,
    suggestions: list[ChatSuggestionItem],
    combo_suggestions: list[GeneratedComboResponse] | None,
    offer_suggestions: list[PersonalizedOfferCardResponse] | None,
    retrieval_source: str,
) -> PreparedChatTurn:
    active_session_id = session_id or uuid.uuid4()
    timings = RagStageTimings()
    history_messages: list[ChatHistory] = []
    session_state = SessionConversationState()

    if session_id is not None:
        session_state_started_at = perf_counter()
        cached_state = _load_cached_session_state_only(user_id=user.id, session_id=active_session_id)
        timings.session_state_ms = round((perf_counter() - session_state_started_at) * 1000, 2)
        if cached_state is not None:
            session_state = cached_state

    extracted_intent = _merge_intent_with_session(
        _fallback_extract_intent(message, session_state),
        session_state,
    )
    effective_message = _build_effective_query_from_intent(
        message,
        extracted_intent,
        session_state,
    )
    history_block = _build_history_block(history_messages)

    return PreparedChatTurn(
        active_session_id=active_session_id,
        message=message,
        effective_message=effective_message,
        restaurant_id=restaurant_id,
        retrieval_source=retrieval_source,
        is_greeting=extracted_intent.intent == "greeting",
        is_follow_up=extracted_intent.show_more,
        uses_personal_context=False,
        should_bypass_llm=True,
        suggestion_limit=SUGGESTION_LIMIT,
        vector_result_count=0,
        extracted_intent=extracted_intent,
        session_state=session_state,
        final_candidates=[],
        suggestions=suggestions,
        history_messages=history_messages,
        history_block=history_block,
        context_block="",
        prompt="",
        timings=timings,
        combo_suggestions=combo_suggestions or [],
        offer_suggestions=offer_suggestions or [],
    )


def _prepare_instant_reply_turn(
    *,
    message: str,
    session_id: uuid.UUID | None,
    restaurant_id: uuid.UUID | None,
    retrieval_source: str,
    extracted_intent: ExtractedIntent,
) -> PreparedChatTurn:
    return PreparedChatTurn(
        active_session_id=session_id or uuid.uuid4(),
        message=message,
        effective_message=message,
        restaurant_id=restaurant_id,
        retrieval_source=retrieval_source,
        is_greeting=retrieval_source == "greeting",
        is_follow_up=False,
        uses_personal_context=False,
        should_bypass_llm=True,
        suggestion_limit=0,
        vector_result_count=0,
        extracted_intent=extracted_intent,
        session_state=SessionConversationState(),
        final_candidates=[],
        suggestions=[],
        history_messages=[],
        history_block="No recent history.",
        context_block="",
        prompt="",
        timings=RagStageTimings(),
    )


def _prepare_safe_fallback_turn(
    db: Session,
    *,
    user: User,
    message: str,
    session_id: uuid.UUID | None,
    restaurant_id: uuid.UUID | None,
    failure_reason: str,
) -> PreparedChatTurn:
    active_session_id = session_id or uuid.uuid4()
    timings = RagStageTimings()
    history_messages: list[ChatHistory] = []
    session_state = SessionConversationState()

    if session_id is not None:
        session_state_started_at = perf_counter()
        cached_state = _load_cached_session_state_only(
            user_id=user.id,
            session_id=active_session_id,
        )
        timings.session_state_ms = round((perf_counter() - session_state_started_at) * 1000, 2)
        if cached_state is not None:
            session_state = cached_state
        else:
            history_started_at = perf_counter()
            history_messages = _fetch_recent_history_messages(
                db,
                user_id=user.id,
                session_id=active_session_id,
            )
            timings.history_ms = round((perf_counter() - history_started_at) * 1000, 2)
            session_state = _load_session_state(
                db,
                user_id=user.id,
                session_id=active_session_id,
                history_messages=history_messages,
            )

    extracted_intent = _merge_intent_with_session(
        _fallback_extract_intent(message, session_state),
        session_state,
    )
    effective_message = _build_effective_query_from_intent(
        message,
        extracted_intent,
        session_state,
    )
    retrieval_source = "no_more_matches" if extracted_intent.show_more else "safe_fallback"
    fallback_reply = _build_safe_reply(
        message,
        [],
        retrieval_source,
        extracted_intent=extracted_intent,
        is_follow_up=extracted_intent.show_more,
        follow_up_base_message=effective_message,
    )
    history_block = (
        _build_history_block(history_messages)
        if history_messages
        else "Skipped while recovering chat context."
    )
    logger.warning(
        "RAG fallback execution reason=%s session_id=%s follow_up=%s effective_message=%s history_messages=%d",
        failure_reason,
        active_session_id,
        extracted_intent.show_more,
        effective_message,
        len(history_messages),
    )

    return PreparedChatTurn(
        active_session_id=active_session_id,
        message=message,
        effective_message=effective_message,
        restaurant_id=restaurant_id,
        retrieval_source=retrieval_source,
        is_greeting=False,
        is_follow_up=extracted_intent.show_more,
        uses_personal_context=_message_requests_personal_context(message) or extracted_intent.show_more,
        should_bypass_llm=True,
        suggestion_limit=0,
        vector_result_count=0,
        extracted_intent=extracted_intent,
        session_state=session_state,
        final_candidates=[],
        suggestions=[],
        history_messages=history_messages,
        history_block=history_block,
        context_block="",
        prompt="",
        timings=timings,
        fallback_reply=fallback_reply,
    )


def _prepare_chat_turn(
    db: Session,
    *,
    user: User,
    message: str,
    session_id: uuid.UUID | None,
    restaurant_id: uuid.UUID | None,
    restaurant_location_id: uuid.UUID | None,
) -> PreparedChatTurn:
    active_session_id = session_id or uuid.uuid4()
    timings = RagStageTimings()
    session_history_messages: list[ChatHistory] = []
    session_state = SessionConversationState()
    session_state_cache_hit = False

    if _is_greeting_message(message):
        prompt_started_at = perf_counter()
        prompt = _build_greeting_prompt(message)
        timings.prompt_ms = round((perf_counter() - prompt_started_at) * 1000, 2)
        logger.info("RAG greeting intent detected normalized_query=%s", _normalize_text(message))
        return PreparedChatTurn(
            active_session_id=active_session_id,
            message=message,
            effective_message=message,
            restaurant_id=restaurant_id,
            retrieval_source="greeting",
            is_greeting=True,
            is_follow_up=False,
            uses_personal_context=False,
            should_bypass_llm=False,
            suggestion_limit=0,
            vector_result_count=0,
            extracted_intent=ExtractedIntent(intent="greeting"),
            session_state=session_state,
            final_candidates=[],
            suggestions=[],
            history_messages=[],
            history_block="No recent history.",
            context_block="",
            prompt=prompt,
            timings=timings,
        )

    if session_id is not None:
        session_state_started_at = perf_counter()
        cached_state = _load_cached_session_state_only(user_id=user.id, session_id=active_session_id)
        timings.session_state_ms = round((perf_counter() - session_state_started_at) * 1000, 2)
        if cached_state is not None:
            session_state = cached_state
            session_state_cache_hit = True
            logger.info(
                "RAG session state cache hit session_id=%s state=%s",
                active_session_id,
                _session_state_summary(session_state),
            )

    likely_follow_up = _is_follow_up_recommendation_message(message)
    requires_session_context = (
        likely_follow_up
        or _message_requests_personal_context(message)
        # "how much does it cost?" needs the session to know what "it" is.
        or _is_contextual_menu_question(message)
    )
    if session_id is not None and requires_session_context and not session_state_cache_hit:
        history_started_at = perf_counter()
        session_history_messages = _fetch_recent_history_messages(
            db,
            user_id=user.id,
            session_id=active_session_id,
        )
        timings.history_ms = round((perf_counter() - history_started_at) * 1000, 2)
        session_state_started_at = perf_counter()
        session_state = _load_session_state(
            db,
            user_id=user.id,
            session_id=active_session_id,
            history_messages=session_history_messages,
        )
        timings.session_state_ms = round(
            timings.session_state_ms + ((perf_counter() - session_state_started_at) * 1000),
            2,
        )
        logger.info(
            "RAG session state rebuilt session_id=%s state=%s",
            active_session_id,
            _session_state_summary(session_state),
        )

    intent_started_at = perf_counter()
    extracted_intent = _extract_intent(
        message,
        session_state,
        force_lightweight=requires_session_context and not session_state_cache_hit and likely_follow_up,
    )
    timings.intent_ms = round((perf_counter() - intent_started_at) * 1000, 2)
    resolved_intent = _merge_intent_with_session(extracted_intent, session_state)
    is_follow_up = resolved_intent.show_more
    next_active_topic = _derive_active_topic(
        resolved_intent,
        _build_effective_query_from_intent(message, resolved_intent, session_state),
        session_state,
        allow_prior_fallback=is_follow_up or resolved_intent.intent == "other",
    )
    logger.info(
        "RAG topic resolution raw_message=%s detected_intent=%s extracted_topic=%s is_follow_up=%s previous_active_topic=%s final_active_topic=%s",
        message,
        resolved_intent.intent,
        _display_requested_topics(resolved_intent) or resolved_intent.cuisine or resolved_intent.category or resolved_intent.restaurant_query,
        is_follow_up,
        session_state.active_topic,
        next_active_topic,
    )

    if resolved_intent.intent == "small_talk":
        prompt_started_at = perf_counter()
        prompt = f"{SMALL_TALK_PROMPT}\n\nUSER MESSAGE:\n{_trim_text(message, 220)}\n"
        timings.prompt_ms = round((perf_counter() - prompt_started_at) * 1000, 2)
        logger.info("RAG small talk via LLM normalized_query=%s", _normalize_text(message))
        return PreparedChatTurn(
            active_session_id=active_session_id,
            message=message,
            effective_message=message,
            restaurant_id=restaurant_id,
            retrieval_source="small_talk",
            is_greeting=False,
            is_follow_up=False,
            uses_personal_context=False,
            should_bypass_llm=False,
            suggestion_limit=0,
            vector_result_count=0,
            extracted_intent=resolved_intent,
            session_state=session_state,
            final_candidates=[],
            suggestions=[],
            history_messages=session_history_messages,
            history_block=_build_history_block(session_history_messages),
            context_block="",
            prompt=prompt,
            timings=timings,
            fallback_reply=_build_small_talk_reply(),
        )

    instant_domain_reply = _instant_reply_for_intent(resolved_intent, message)
    if instant_domain_reply is not None:
        logger.info(
            "RAG instant domain reply intent=%s normalized_query=%s",
            resolved_intent.intent,
            _normalize_text(message),
        )
        return PreparedChatTurn(
            active_session_id=active_session_id,
            message=message,
            effective_message=message,
            restaurant_id=restaurant_id,
            retrieval_source=resolved_intent.intent,
            is_greeting=resolved_intent.intent == "greeting",
            is_follow_up=False,
            uses_personal_context=False,
            should_bypass_llm=True,
            suggestion_limit=0,
            vector_result_count=0,
            extracted_intent=resolved_intent,
            session_state=session_state,
            final_candidates=[],
            suggestions=[],
            history_messages=session_history_messages,
            history_block=_build_history_block(session_history_messages),
            context_block="",
            prompt="",
            timings=timings,
            fallback_reply=instant_domain_reply,
        )

    if resolved_intent.intent == "restaurant_list" and not _intent_requested_topics(resolved_intent):
        restaurant_list_reply = _build_restaurant_list_reply(
            db,
            message=message,
            restaurant_id=restaurant_id,
        )
        logger.info(
            "RAG restaurant list reply restaurant_id=%s normalized_query=%s",
            restaurant_id,
            _normalize_text(message),
        )
        return PreparedChatTurn(
            active_session_id=active_session_id,
            message=message,
            effective_message=message,
            restaurant_id=restaurant_id,
            retrieval_source="restaurant_list",
            is_greeting=False,
            is_follow_up=False,
            uses_personal_context=False,
            should_bypass_llm=True,
            suggestion_limit=0,
            vector_result_count=0,
            extracted_intent=resolved_intent,
            session_state=session_state,
            final_candidates=[],
            suggestions=[],
            history_messages=session_history_messages,
            history_block=_build_history_block(session_history_messages),
            context_block="",
            prompt="",
            timings=timings,
            fallback_reply=restaurant_list_reply,
        )

    if is_follow_up:
        if session_id is not None and not session_history_messages:
            history_started_at = perf_counter()
            session_history_messages = _fetch_recent_history_messages(
                db,
                user_id=user.id,
                session_id=active_session_id,
            )
            timings.history_ms = round(timings.history_ms + ((perf_counter() - history_started_at) * 1000), 2)
        if session_id is not None and not session_state_cache_hit and session_state.last_recommendation_context is None:
            session_state_started_at = perf_counter()
            session_state = _load_session_state(
                db,
                user_id=user.id,
                session_id=active_session_id,
                history_messages=session_history_messages,
            )
            timings.session_state_ms = round(
                timings.session_state_ms + ((perf_counter() - session_state_started_at) * 1000),
                2,
            )
        logger.info(
            "RAG follow-up context selection session_id=%s previous_contexts=%s selected_active_context=%s seen_item_ids=%s",
            active_session_id,
            json.dumps(_recent_recommendation_contexts(session_history_messages), default=str),
            json.dumps(
                session_state.last_recommendation_context
                or {
                    "intent": session_state.active_intent or session_state.last_intent,
                    "topic": session_state.active_topic,
                    "effective_query": session_state.last_successful_user_query or session_state.base_query,
                },
                default=str,
            ),
            [str(item_id) for item_id in sorted(session_state.seen_item_ids or set(), key=str)],
        )
    uses_personal_context = _message_requests_personal_context(message) or is_follow_up

    effective_message = _build_effective_query_from_intent(message, resolved_intent, session_state)
    preferences: UserPreferences | None = None
    if uses_personal_context:
        preferences_started_at = perf_counter()
        preferences = _fetch_user_preferences(db, user.id)
        timings.preferences_ms = round((perf_counter() - preferences_started_at) * 1000, 2)

    budget_limit = (
        resolved_intent.budget
        if resolved_intent.budget is not None
        else _resolve_budget_limit(effective_message, preferences) if uses_personal_context else None
    )
    strict_budget = resolved_intent.budget is not None or _has_explicit_budget_limit(effective_message)

    if resolved_intent.intent == "offer_query":
        raw_offer_rows = get_personalized_offers_for_user(db, user, limit=8)
        offer_rows = _filter_offer_cards_for_chat_query(
            raw_offer_rows,
            restaurant_id=restaurant_id,
            restaurant_location_id=restaurant_location_id,
            intent=resolved_intent,
            message=message,
        )
        context_block = _build_offer_context_block(offer_rows)
        history_messages = session_history_messages
        history_block = _build_history_block(history_messages)
        fallback_reply = (
            _build_offer_reply_from_cards(offer_rows, message=message)
            if offer_rows
            else _build_offer_no_match_reply(intent=resolved_intent, message=message)
        )
        prompt = (
            _build_prompt(
                message=message,
                context_block=context_block or "No live offer context available.",
                history_block=history_block,
                intent=resolved_intent,
                session_state=session_state,
            )
            if offer_rows
            else ""
        )
        logger.info(
            "RAG offer query user_id=%s raw_message=%s detected_intent=%s restaurant_id=%s restaurant_location_id=%s active_offer_count=%d filtered_offer_count=%d requested_items=%s requested_cuisine=%s requested_restaurant=%s",
            user.id,
            message,
            resolved_intent.intent,
            restaurant_id,
            restaurant_location_id,
            len(raw_offer_rows),
            len(offer_rows),
            resolved_intent.items,
            resolved_intent.cuisine,
            resolved_intent.restaurant_query,
        )
        return PreparedChatTurn(
            active_session_id=active_session_id,
            message=message,
            effective_message=effective_message,
            restaurant_id=restaurant_id,
            retrieval_source="offer_query" if offer_rows else "offer_no_match",
            is_greeting=False,
            is_follow_up=is_follow_up,
            uses_personal_context=True,
            should_bypass_llm=not offer_rows,
            suggestion_limit=0,
            vector_result_count=0,
            extracted_intent=resolved_intent,
            session_state=session_state,
            final_candidates=[],
            suggestions=[],
            history_messages=history_messages,
            history_block=history_block,
            context_block=context_block,
            prompt=prompt,
            timings=timings,
            offer_suggestions=offer_rows,
            fallback_reply=fallback_reply,
        )

    if _is_combo_query(message, resolved_intent):
        combo_topic = _extract_combo_topic(message) or _display_requested_topics(resolved_intent) or session_state.active_topic
        combo_rows = find_generated_combos_for_query(
            db,
            topic=combo_topic,
            restaurant_id=restaurant_id,
            restaurant_location_id=None,
            budget_limit=budget_limit if strict_budget else None,
            limit=3,
        )
        combo_context_entries = [
            {
                "combo_name": combo.combo_name,
                "restaurant_name": combo.restaurant_name,
                "suggested_combo_price": combo.suggested_combo_price,
                "item_names": [item.name for item in combo.items],
            }
            for combo in combo_rows
        ]
        context_block = _build_combo_context_block(combo_context_entries)
        history_messages = session_history_messages
        history_block = _build_history_block(history_messages)
        fallback_reply = (
            _build_combo_reply_from_context(message, len(combo_rows))
            if combo_rows
            else (
                f"I don't have any generated {combo_topic} combos right now."
                if combo_topic
                else "I don't have any generated combos available right now."
            )
        )
        prompt = (
            _build_prompt(
                message=message,
                context_block=context_block or "No combo context available.",
                history_block=history_block,
                intent=resolved_intent,
                session_state=session_state,
            )
            if combo_rows
            else ""
        )
        logger.info(
            "RAG combo query raw_message=%s extracted_topic=%s combo_count=%d",
            message,
            combo_topic,
            len(combo_rows),
        )
        return PreparedChatTurn(
            active_session_id=active_session_id,
            message=message,
            effective_message=effective_message,
            restaurant_id=restaurant_id,
            retrieval_source="combo_query" if combo_rows else "combo_no_match",
            is_greeting=False,
            is_follow_up=is_follow_up,
            uses_personal_context=uses_personal_context,
            should_bypass_llm=not combo_rows,
            suggestion_limit=0,
            vector_result_count=0,
            extracted_intent=resolved_intent,
            session_state=session_state,
            final_candidates=[],
            suggestions=[],
            history_messages=history_messages,
            history_block=history_block,
            context_block=context_block,
            prompt=prompt,
            timings=timings,
            fallback_reply=fallback_reply,
            combo_suggestions=combo_rows,
        )

    exclude_item_ids = set(session_state.seen_item_ids or set()) if is_follow_up else set()
    exclude_dish_keys = _fetch_dish_keys_for_item_ids(db, exclude_item_ids)
    search_limit = min(max(TOP_K_RESULTS + len(exclude_item_ids), TOP_K_RESULTS), 20)
    prior_retrieval_source = None
    if isinstance(session_state.last_recommendation_context, dict):
        prior_retrieval_source = session_state.last_recommendation_context.get("retrieval_source")

    retrieval_source = "vector"
    suggestion_limit = SUGGESTION_LIMIT
    vector_result_count = 0
    final_candidates: list[RetrievedMenuCandidate]

    keyword_started_at = perf_counter()
    if resolved_intent.new_only:
        filtered_keyword_candidates: list[RetrievedMenuCandidate] = []
        timings.keyword_ms = round((perf_counter() - keyword_started_at) * 1000, 2)
        db_filter_started_at = perf_counter()
        final_candidates, retrieval_source = _resolve_new_item_candidates_fast(
            db,
            message=effective_message,
            restaurant_id=restaurant_id,
            restaurant_location_id=restaurant_location_id,
            budget_limit=budget_limit,
            strict_budget=strict_budget,
            intent=resolved_intent,
            preferences=preferences if uses_personal_context else None,
            exclude_item_ids=exclude_item_ids,
            exclude_dish_keys=exclude_dish_keys,
            limit=search_limit,
        )
        timings.db_filter_ms = round((perf_counter() - db_filter_started_at) * 1000, 2)
        vector_result_count = 0
        logger.info(
            "RAG new-item fast path query=%s matched_menu_items=%s excluded_item_ids=%s",
            effective_message,
            _candidate_name_summary(final_candidates),
            [str(item_id) for item_id in sorted(exclude_item_ids, key=str)],
        )
    else:
        keyword_candidates = (
            _fetch_keyword_candidates(
                db,
                effective_message,
                restaurant_id,
                restaurant_location_id,
                limit=search_limit,
            )
            if _intent_prefers_keyword_first(resolved_intent, effective_message)
            else []
        )
        filtered_keyword_candidates = _filter_candidates(
            keyword_candidates,
            budget_limit,
            strict_budget=strict_budget,
            intent=resolved_intent,
            exclude_item_ids=exclude_item_ids,
            exclude_dish_keys=exclude_dish_keys,
        )
        timings.keyword_ms = round((perf_counter() - keyword_started_at) * 1000, 2)
        logger.info(
            "RAG retrieval precheck normalized_query=%s intent=%s final_retrieval_query=%s keyword_matches=%d matched_menu_items=%s excluded_item_ids=%s",
            _normalize_text(effective_message),
            resolved_intent.intent,
            effective_message,
            len(filtered_keyword_candidates),
            _candidate_name_summary(filtered_keyword_candidates),
            [str(item_id) for item_id in sorted(exclude_item_ids, key=str)],
        )

        db_filter_started_at = perf_counter()
        if filtered_keyword_candidates and (
            _intent_prefers_keyword_first(resolved_intent, effective_message)
            or _has_strong_keyword_signal(filtered_keyword_candidates)
        ):
            final_candidates = filtered_keyword_candidates[:TOP_K_RESULTS]
            retrieval_source = "keyword_follow_up" if is_follow_up else "keyword_intent"
        else:
            embedding_started_at = perf_counter()
            query_embedding = _embed_query(effective_message)
            timings.embedding_ms = round((perf_counter() - embedding_started_at) * 1000, 2)

            vector_started_at = perf_counter()
            final_candidates, retrieval_source, vector_result_count = _resolve_final_candidates(
                db,
                message=effective_message,
                restaurant_id=restaurant_id,
                restaurant_location_id=restaurant_location_id,
                budget_limit=budget_limit,
                strict_budget=strict_budget,
                intent=resolved_intent,
                query_embedding=query_embedding,
                exclude_item_ids=exclude_item_ids,
                exclude_dish_keys=exclude_dish_keys,
                limit=search_limit,
                allow_popular_fallback=(
                    not is_follow_up
                    or prior_retrieval_source in {"popular_fallback", "emergency_db_fallback"}
                ),
            )
            timings.vector_ms = round((perf_counter() - vector_started_at) * 1000, 2)
        timings.db_filter_ms = round((perf_counter() - db_filter_started_at) * 1000, 2)

    if is_follow_up and not final_candidates:
        retrieval_source = "no_more_matches"
        logger.info(
            "RAG follow-up fallback reason=no_more_matches session_id=%s base_message=%s seen_item_count=%d",
            active_session_id,
            session_state.base_query,
            len(session_state.seen_item_ids or set()),
        )
    elif retrieval_source in {"popular_fallback", "emergency_db_fallback"}:
        logger.info(
            "RAG fallback trigger reason=%s normalized_query=%s matched_menu_items=%s",
            retrieval_source,
            _normalize_text(effective_message),
            _candidate_name_summary(final_candidates),
        )

    if resolved_intent.new_only and final_candidates and retrieval_source != "new_item_fast_path":
        final_candidates = _sort_new_item_candidates(
            final_candidates,
            intent=resolved_intent,
            preferences=preferences if uses_personal_context else None,
        )[:TOP_K_RESULTS]

    if _intent_requested_topics(resolved_intent) and retrieval_source in {"popular_fallback", "emergency_db_fallback"}:
        suggestion_limit = 3

    suggestions = _suggestion_items(
        final_candidates[:suggestion_limit],
        intent=resolved_intent,
        uses_personal_context=uses_personal_context,
    )
    should_bypass_llm = _should_bypass_llm(
        retrieval_source=retrieval_source,
        candidates=final_candidates,
        intent=resolved_intent,
        is_follow_up=is_follow_up,
    )

    history_messages: list[ChatHistory] = session_history_messages
    history_block = "Skipped for fast DB-backed reply."
    context_block = _build_context_block(final_candidates)
    prompt = ""
    if not should_bypass_llm:
        if not history_messages:
            history_started_at = perf_counter()
            history_messages = _fetch_recent_history_messages(
                db,
                user_id=user.id,
                session_id=active_session_id,
            )
            timings.history_ms = round((perf_counter() - history_started_at) * 1000, 2)

        prompt_started_at = perf_counter()
        history_block = _build_history_block(history_messages)
        availability_note = None
        if retrieval_source in {"popular_fallback", "emergency_db_fallback"} and _intent_requested_topics(resolved_intent):
            # The context items are alternatives, not matches; without this
            # signal the model can answer "Yes" to a dish that is not sold.
            availability_note = (
                f"The menu context contains NO exact match for '{_display_requested_topics(resolved_intent)}'. "
                "Say that plainly first, then offer the closest grounded alternatives from the context."
            )
        prompt = _build_prompt(
            message=message,
            context_block=context_block,
            history_block=history_block,
            intent=resolved_intent,
            session_state=session_state,
            availability_note=availability_note,
        )
        timings.prompt_ms = round((perf_counter() - prompt_started_at) * 1000, 2)
        logger.info(
            "RAG prompt payload session_id=%s history_messages=%d prompt_chars=%d prompt_preview=%s",
            active_session_id,
            len(history_messages),
            len(prompt),
            _trim_text(prompt, 600),
        )
    else:
        logger.info(
            "RAG prompt bypassed session_id=%s history_messages=%d reason=%s candidates=%d",
            active_session_id,
            len(history_messages),
            retrieval_source,
            len(final_candidates),
        )

    logger.info(
        "RAG final context source=%s items=%d final_candidate_count=%d",
        retrieval_source,
        len(final_candidates),
        len(final_candidates),
    )

    return PreparedChatTurn(
        active_session_id=active_session_id,
        message=message,
        effective_message=effective_message,
        restaurant_id=restaurant_id,
        retrieval_source=retrieval_source,
        is_greeting=False,
        is_follow_up=is_follow_up,
        uses_personal_context=uses_personal_context,
        should_bypass_llm=should_bypass_llm,
        suggestion_limit=suggestion_limit,
        vector_result_count=vector_result_count,
        extracted_intent=resolved_intent,
        session_state=session_state,
        final_candidates=final_candidates,
        suggestions=suggestions,
        history_messages=history_messages,
        history_block=history_block,
        context_block=context_block,
        prompt=prompt,
        timings=timings,
    )


def _persist_chat_exchange(
    db: Session,
    *,
    user: User,
    prepared: PreparedChatTurn,
    raw_reply: str,
    reply: str,
    llm_strategy: str,
) -> None:
    user_context = {
        "restaurant_id": str(prepared.restaurant_id) if prepared.restaurant_id else None,
        "vector_result_count": prepared.vector_result_count,
        "final_candidate_count": len(prepared.final_candidates),
        "retrieval_source": prepared.retrieval_source,
        "effective_message": prepared.effective_message,
        "resolved_intent": prepared.extracted_intent.intent,
        "intent_payload": {
            "intent": prepared.extracted_intent.intent,
            "dish": prepared.extracted_intent.dish,
            "items": prepared.extracted_intent.items or [],
            "cuisine": prepared.extracted_intent.cuisine,
            "category": prepared.extracted_intent.category,
            "restaurant_query": prepared.extracted_intent.restaurant_query,
            "budget": str(prepared.extracted_intent.budget) if prepared.extracted_intent.budget is not None else None,
            "diet": prepared.extracted_intent.diet,
            "spicy": prepared.extracted_intent.spicy,
            "mood": prepared.extracted_intent.mood,
            "show_more": prepared.extracted_intent.show_more,
        },
        "is_follow_up": prepared.is_follow_up,
        "suggested_item_ids": [str(item.id) for item in prepared.suggestions],
        "suggested_combo_ids": [str(combo.id) for combo in prepared.combo_suggestions],
        "suggested_offer_ids": [str(offer.offer_id) for offer in prepared.offer_suggestions],
        "history_turns_seen": len(prepared.history_messages),
        "session_state": _serialize_session_state(
            _build_session_state_from_turn(
                prepared.session_state,
                prepared.extracted_intent,
                prepared.effective_message,
                prepared.suggestions,
                prepared.retrieval_source,
            )
        ),
        "timings_ms": {
            "cache_lookup": prepared.timings.cache_lookup_ms,
            "session_state": prepared.timings.session_state_ms,
            "intent": prepared.timings.intent_ms,
            "preferences": prepared.timings.preferences_ms,
            "history": prepared.timings.history_ms,
            "keyword": prepared.timings.keyword_ms,
            "db_filter": prepared.timings.db_filter_ms,
            "embedding": prepared.timings.embedding_ms,
            "vector": prepared.timings.vector_ms,
            "prompt": prepared.timings.prompt_ms,
            "llm": prepared.timings.llm_ms,
        },
    }
    assistant_context = {
        "restaurant_id": str(prepared.restaurant_id) if prepared.restaurant_id else None,
        "retrieval_source": prepared.retrieval_source,
        "effective_message": prepared.effective_message,
        "is_follow_up": prepared.is_follow_up,
        "vector_result_count": prepared.vector_result_count,
        "context_preview": _trim_text(prepared.context_block, 800),
        "suggestions": [item.model_dump(mode="json") for item in prepared.suggestions],
        "combo_suggestions": [combo.model_dump(mode="json") for combo in prepared.combo_suggestions],
        "offer_suggestions": [offer.model_dump(mode="json") for offer in prepared.offer_suggestions],
        "session_state": _serialize_session_state(
            _build_session_state_from_turn(
                prepared.session_state,
                prepared.extracted_intent,
                prepared.effective_message,
                prepared.suggestions,
                prepared.retrieval_source,
            )
        ),
        "raw_reply": raw_reply,
        "llm_strategy": llm_strategy,
    }

    _save_message(
        db,
        user_id=user.id,
        restaurant_id=prepared.restaurant_id,
        session_id=prepared.active_session_id,
        role=ChatMessageRole.USER,
        message=prepared.message,
        context_payload=user_context,
    )
    _save_message(
        db,
        user_id=user.id,
        restaurant_id=prepared.restaurant_id,
        session_id=prepared.active_session_id,
        role=ChatMessageRole.ASSISTANT,
        message=reply,
        context_payload=assistant_context,
    )
    db_commit_started_at = perf_counter()
    db.commit()
    prepared.timings.db_commit_ms = round((perf_counter() - db_commit_started_at) * 1000, 2)
    latest_messages = _fetch_recent_history_messages_from_db(
        db,
        user_id=user.id,
        session_id=prepared.active_session_id,
    )
    cache_set_json(
        _session_cache_key(user.id, prepared.active_session_id),
        _serialize_history_entries(latest_messages),
    )
    cache_set_json(
        _session_state_cache_key(user.id, prepared.active_session_id),
        _serialize_session_state(
            _build_session_state_from_turn(
                prepared.session_state,
                prepared.extracted_intent,
                prepared.effective_message,
                prepared.suggestions,
                prepared.retrieval_source,
            )
        ),
    )


def _log_rag_timings(user: User, prepared: PreparedChatTurn) -> None:
    logger.info(
        "RAG timings user_id=%s session_id=%s total=%.2fms cache=%.2fms session=%.2fms intent=%.2fms prefs=%.2fms history=%.2fms keyword=%.2fms db_filter=%.2fms embed=%.2fms vector=%.2fms prompt=%.2fms llm=%.2fms commit=%.2fms source=%s intent=%s candidates=%d vector_rows=%d",
        user.id,
        prepared.active_session_id,
        prepared.timings.total_ms,
        prepared.timings.cache_lookup_ms,
        prepared.timings.session_state_ms,
        prepared.timings.intent_ms,
        prepared.timings.preferences_ms,
        prepared.timings.history_ms,
        prepared.timings.keyword_ms,
        prepared.timings.db_filter_ms,
        prepared.timings.embedding_ms,
        prepared.timings.vector_ms,
        prepared.timings.prompt_ms,
        prepared.timings.llm_ms,
        prepared.timings.db_commit_ms,
        prepared.retrieval_source,
        prepared.extracted_intent.intent,
        len(prepared.final_candidates),
        prepared.vector_result_count,
    )


def _sse_frame(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


def handle_chat_message(
    db: Session,
    *,
    user: User,
    message: str,
    session_id: uuid.UUID | None,
    restaurant_id: uuid.UUID | None,
    restaurant_location_id: uuid.UUID | None = None,
) -> ChatMessageResponse:
    started_at = perf_counter()
    if _is_acknowledgement_message(message):
        prepared = _prepare_instant_reply_turn(
            message=message,
            session_id=session_id,
            restaurant_id=restaurant_id,
            retrieval_source="acknowledgement",
            extracted_intent=ExtractedIntent(intent="other"),
        )
        reply = _build_acknowledgement_reply(message)
        _persist_chat_exchange(
            db,
            user=user,
            prepared=prepared,
            raw_reply="",
            reply=reply,
            llm_strategy="instant_acknowledgement",
        )
        prepared.timings.total_ms = round((perf_counter() - started_at) * 1000, 2)
        _log_rag_timings(user, prepared)
        return ChatMessageResponse(
            reply=reply,
            session_id=prepared.active_session_id,
            suggestions=[],
            combo_suggestions=[],
            offer_suggestions=[],
        )

    if _is_greeting_message(message):
        cache_started_at = perf_counter()
        logger.info("RAG greeting intent detected normalized_query=%s", _normalize_text(message))
        greeting_cache_key = _greeting_response_cache_key(message)
        logger.info("RAG greeting cache lookup key=%s", greeting_cache_key)
        cached_response_payload = _deserialize_chat_response_cache_payload(cache_get_json(greeting_cache_key))
        cache_lookup_ms = round((perf_counter() - cache_started_at) * 1000, 2)
        prepared = _prepare_instant_reply_turn(
            message=message,
            session_id=session_id,
            restaurant_id=restaurant_id,
            retrieval_source="greeting_cache",
            extracted_intent=ExtractedIntent(intent="greeting"),
        )
        prepared.timings.cache_lookup_ms = cache_lookup_ms
        raw_reply = ""
        if cached_response_payload is not None:
            logger.info("RAG greeting cache hit key=%s", greeting_cache_key)
            reply, cached_suggestions, cached_combo_suggestions, cached_offer_suggestions, cached_retrieval_source = cached_response_payload
            prepared.suggestions = cached_suggestions
            prepared.combo_suggestions = cached_combo_suggestions
            prepared.offer_suggestions = cached_offer_suggestions
            prepared.retrieval_source = cached_retrieval_source
            llm_strategy = "redis_greeting_cache"
        else:
            logger.info("RAG greeting cache miss key=%s", greeting_cache_key)
            reply = _build_greeting_reply(message)
            llm_strategy = "instant_greeting"
            cache_set_json(
                greeting_cache_key,
                _serialize_chat_response_cache_payload(
                    reply=reply,
                    suggestions=prepared.suggestions,
                    combo_suggestions=prepared.combo_suggestions,
                    offer_suggestions=prepared.offer_suggestions,
                    retrieval_source="greeting_cache",
                ),
            )
            prepared.retrieval_source = "greeting_cache"
            logger.info("RAG greeting response generated key=%s", greeting_cache_key)

        _persist_chat_exchange(
            db,
            user=user,
            prepared=prepared,
            raw_reply=raw_reply,
            reply=reply,
            llm_strategy=llm_strategy,
        )
        prepared.timings.total_ms = round((perf_counter() - started_at) * 1000, 2)
        _log_rag_timings(user, prepared)
        prepared.suggestions = _attach_suggestion_favorites(db, user, prepared.suggestions)
        return ChatMessageResponse(
            reply=reply,
            session_id=prepared.active_session_id,
            suggestions=prepared.suggestions,
            combo_suggestions=prepared.combo_suggestions,
            offer_suggestions=prepared.offer_suggestions,
        )

    cache_started_at = perf_counter()
    response_cache_key, cached_response_payload, cacheable_response, cache_reason = _lookup_global_response_cache(
        message=message,
        restaurant_id=restaurant_id,
        is_greeting=False,
        uses_personal_context=_message_requests_personal_context(message),
        is_follow_up=_is_follow_up_recommendation_message(message),
    )
    cache_lookup_ms = round((perf_counter() - cache_started_at) * 1000, 2)
    if cached_response_payload is not None:
        reply, cached_suggestions, cached_combo_suggestions, cached_offer_suggestions, cached_retrieval_source = cached_response_payload
        prepared = _prepare_cached_response_turn(
            db,
            user=user,
            message=message,
            session_id=session_id,
            restaurant_id=restaurant_id,
            suggestions=cached_suggestions,
            combo_suggestions=cached_combo_suggestions,
            offer_suggestions=cached_offer_suggestions,
            retrieval_source=cached_retrieval_source,
        )
        prepared.timings.cache_lookup_ms = cache_lookup_ms
        _persist_chat_exchange(
            db,
            user=user,
            prepared=prepared,
            raw_reply="",
            reply=reply,
            llm_strategy="redis_response_cache",
        )
        prepared.timings.total_ms = round((perf_counter() - started_at) * 1000, 2)
        _log_rag_timings(user, prepared)
        prepared.suggestions = _attach_suggestion_favorites(db, user, prepared.suggestions)
        return ChatMessageResponse(
            reply=reply,
            session_id=prepared.active_session_id,
            suggestions=prepared.suggestions,
            combo_suggestions=prepared.combo_suggestions,
            offer_suggestions=prepared.offer_suggestions,
        )

    try:
        prepared = _prepare_chat_turn(
            db,
            user=user,
            message=message,
            session_id=session_id,
            restaurant_id=restaurant_id,
            restaurant_location_id=restaurant_location_id,
        )
    except Exception as exc:  # pragma: no cover - defensive fail-open path
        logger.exception(
            "RAG prepare turn failed user_id=%s session_id=%s message=%s",
            user.id,
            session_id,
            message,
        )
        prepared = _prepare_safe_fallback_turn(
            db,
            user=user,
            message=message,
            session_id=session_id,
            restaurant_id=restaurant_id,
            failure_reason=type(exc).__name__,
        )
    prepared.timings.cache_lookup_ms = cache_lookup_ms
    cacheable_response, cache_reason = _resolve_global_cacheability(
        message=message,
        restaurant_id=restaurant_id,
        is_greeting=prepared.is_greeting,
        uses_personal_context=prepared.uses_personal_context,
        is_follow_up=prepared.is_follow_up,
    )

    raw_reply = ""
    llm_strategy = "skipped"
    if prepared.should_bypass_llm:
        reply = prepared.fallback_reply or _build_safe_reply(
            message,
            prepared.suggestions,
            prepared.retrieval_source,
            extracted_intent=prepared.extracted_intent,
            is_follow_up=prepared.is_follow_up,
            follow_up_base_message=prepared.effective_message,
        )
    else:
        llm_started_at = perf_counter()
        try:
            raw_reply = _generate_reply(prepared.prompt)
            llm_strategy = "generated"
        except HTTPException:
            llm_strategy = "fallback_after_llm_failure"
        prepared.timings.llm_ms = round((perf_counter() - llm_started_at) * 1000, 2)
        reply = (
            _ensure_useful_reply(
                message=message,
                raw_reply=raw_reply,
                suggestions=prepared.suggestions,
                retrieval_source=prepared.retrieval_source,
                extracted_intent=prepared.extracted_intent,
                is_follow_up=prepared.is_follow_up,
                follow_up_base_message=prepared.effective_message,
                fallback_reply_override=prepared.fallback_reply,
            )
            if raw_reply
            else (
                prepared.fallback_reply
                or _build_safe_reply(
                    message,
                    prepared.suggestions,
                    prepared.retrieval_source,
                    extracted_intent=prepared.extracted_intent,
                    is_follow_up=prepared.is_follow_up,
                    follow_up_base_message=prepared.effective_message,
                )
            )
        )
    if cacheable_response:
        cache_set_json(
            response_cache_key,
            _serialize_chat_response_cache_payload(
                reply=reply,
                suggestions=prepared.suggestions,
                combo_suggestions=prepared.combo_suggestions,
                offer_suggestions=prepared.offer_suggestions,
                retrieval_source=prepared.retrieval_source,
            ),
        )
    else:
        logger.info("RAG response cache skipped save key=%s reason=%s", response_cache_key, cache_reason)

    try:
        _persist_chat_exchange(
            db,
            user=user,
            prepared=prepared,
            raw_reply=raw_reply,
            reply=reply,
            llm_strategy=llm_strategy,
        )
    except Exception:  # pragma: no cover - defensive fail-open path
        logger.exception(
            "RAG persist chat exchange failed user_id=%s session_id=%s message=%s",
            user.id,
            prepared.active_session_id,
            message,
        )
    prepared.timings.total_ms = round((perf_counter() - started_at) * 1000, 2)
    _log_rag_timings(user, prepared)
    prepared.suggestions = _attach_suggestion_favorites(db, user, prepared.suggestions)

    return ChatMessageResponse(
        reply=reply,
        session_id=prepared.active_session_id,
        suggestions=prepared.suggestions,
        combo_suggestions=prepared.combo_suggestions,
        offer_suggestions=prepared.offer_suggestions,
    )


def stream_chat_message(
    db: Session,
    *,
    user: User,
    message: str,
    session_id: uuid.UUID | None,
    restaurant_id: uuid.UUID | None,
    restaurant_location_id: uuid.UUID | None = None,
) -> Iterator[str]:
    started_at = perf_counter()
    if _is_acknowledgement_message(message):
        prepared = _prepare_instant_reply_turn(
            message=message,
            session_id=session_id,
            restaurant_id=restaurant_id,
            retrieval_source="acknowledgement",
            extracted_intent=ExtractedIntent(intent="other"),
        )
        reply = _build_acknowledgement_reply(message)
        yield _sse_frame(
            "meta",
            {
                "session_id": str(prepared.active_session_id),
                "suggestions": [],
                "combo_suggestions": [],
                "offer_suggestions": [],
            },
        )
        yield _sse_frame("token", {"text": reply})
        _persist_chat_exchange(
            db,
            user=user,
            prepared=prepared,
            raw_reply="",
            reply=reply,
            llm_strategy="instant_acknowledgement",
        )
        prepared.timings.total_ms = round((perf_counter() - started_at) * 1000, 2)
        _log_rag_timings(user, prepared)
        yield _sse_frame(
            "done",
            {
                "reply": reply,
                "session_id": str(prepared.active_session_id),
                "suggestions": [],
                "combo_suggestions": [],
                "offer_suggestions": [],
            },
        )
        return

    if _is_greeting_message(message):
        cache_started_at = perf_counter()
        logger.info("RAG greeting intent detected normalized_query=%s", _normalize_text(message))
        greeting_cache_key = _greeting_response_cache_key(message)
        logger.info("RAG greeting cache lookup key=%s", greeting_cache_key)
        cached_response_payload = _deserialize_chat_response_cache_payload(cache_get_json(greeting_cache_key))
        cache_lookup_ms = round((perf_counter() - cache_started_at) * 1000, 2)
        prepared = _prepare_instant_reply_turn(
            message=message,
            session_id=session_id,
            restaurant_id=restaurant_id,
            retrieval_source="greeting_cache",
            extracted_intent=ExtractedIntent(intent="greeting"),
        )
        prepared.timings.cache_lookup_ms = cache_lookup_ms
        yield _sse_frame(
            "meta",
            {
                "session_id": str(prepared.active_session_id),
                "suggestions": [],
                "combo_suggestions": [],
                "offer_suggestions": [],
            },
        )
        raw_reply = ""
        if cached_response_payload is not None:
            logger.info("RAG greeting cache hit key=%s", greeting_cache_key)
            reply, _, cached_combo_suggestions, cached_offer_suggestions, cached_retrieval_source = cached_response_payload
            prepared.combo_suggestions = cached_combo_suggestions
            prepared.offer_suggestions = cached_offer_suggestions
            prepared.retrieval_source = cached_retrieval_source
            llm_strategy = "redis_greeting_cache"
            yield _sse_frame("token", {"text": reply})
        else:
            logger.info("RAG greeting cache miss key=%s", greeting_cache_key)
            llm_strategy = "instant_greeting"
            reply = _build_greeting_reply(message)
            yield _sse_frame("token", {"text": reply})
            cache_set_json(
                greeting_cache_key,
                _serialize_chat_response_cache_payload(
                    reply=reply,
                    suggestions=[],
                    combo_suggestions=[],
                    offer_suggestions=[],
                    retrieval_source="greeting_cache",
                ),
            )
            prepared.retrieval_source = "greeting_cache"
            logger.info("RAG greeting response generated key=%s", greeting_cache_key)

        _persist_chat_exchange(
            db,
            user=user,
            prepared=prepared,
            raw_reply=raw_reply,
            reply=reply,
            llm_strategy=llm_strategy,
        )
        prepared.timings.total_ms = round((perf_counter() - started_at) * 1000, 2)
        _log_rag_timings(user, prepared)
        yield _sse_frame(
            "done",
            {
                "reply": reply,
                "session_id": str(prepared.active_session_id),
                "suggestions": [],
                "combo_suggestions": [item.model_dump(mode="json") for item in prepared.combo_suggestions],
                "offer_suggestions": [item.model_dump(mode="json") for item in prepared.offer_suggestions],
            },
        )
        return

    cache_started_at = perf_counter()
    response_cache_key, cached_response_payload, cacheable_response, cache_reason = _lookup_global_response_cache(
        message=message,
        restaurant_id=restaurant_id,
        is_greeting=False,
        uses_personal_context=_message_requests_personal_context(message),
        is_follow_up=_is_follow_up_recommendation_message(message),
    )
    cache_lookup_ms = round((perf_counter() - cache_started_at) * 1000, 2)
    if cached_response_payload is not None:
        reply, cached_suggestions, cached_combo_suggestions, cached_offer_suggestions, cached_retrieval_source = cached_response_payload
        prepared = _prepare_cached_response_turn(
            db,
            user=user,
            message=message,
            session_id=session_id,
            restaurant_id=restaurant_id,
            suggestions=cached_suggestions,
            combo_suggestions=cached_combo_suggestions,
            offer_suggestions=cached_offer_suggestions,
            retrieval_source=cached_retrieval_source,
        )
        prepared.suggestions = _attach_suggestion_favorites(db, user, prepared.suggestions)
        prepared.timings.cache_lookup_ms = cache_lookup_ms
        yield _sse_frame(
            "meta",
            {
                "session_id": str(prepared.active_session_id),
                "suggestions": [item.model_dump(mode="json") for item in prepared.suggestions],
                "combo_suggestions": [item.model_dump(mode="json") for item in prepared.combo_suggestions],
                "offer_suggestions": [item.model_dump(mode="json") for item in prepared.offer_suggestions],
            },
        )
        yield _sse_frame("token", {"text": reply})
        _persist_chat_exchange(
            db,
            user=user,
            prepared=prepared,
            raw_reply="",
            reply=reply,
            llm_strategy="redis_response_cache",
        )
        prepared.timings.total_ms = round((perf_counter() - started_at) * 1000, 2)
        _log_rag_timings(user, prepared)
        yield _sse_frame(
            "done",
            {
                "reply": reply,
                "session_id": str(prepared.active_session_id),
                "suggestions": [item.model_dump(mode="json") for item in prepared.suggestions],
                "combo_suggestions": [item.model_dump(mode="json") for item in prepared.combo_suggestions],
                "offer_suggestions": [item.model_dump(mode="json") for item in prepared.offer_suggestions],
            },
        )
        return

    try:
        prepared = _prepare_chat_turn(
            db,
            user=user,
            message=message,
            session_id=session_id,
            restaurant_id=restaurant_id,
            restaurant_location_id=restaurant_location_id,
        )
    except Exception as exc:  # pragma: no cover - defensive fail-open path
        logger.exception(
            "RAG stream prepare turn failed user_id=%s session_id=%s message=%s",
            user.id,
            session_id,
            message,
        )
        prepared = _prepare_safe_fallback_turn(
            db,
            user=user,
            message=message,
            session_id=session_id,
            restaurant_id=restaurant_id,
            failure_reason=f"stream:{type(exc).__name__}",
        )
    prepared.timings.cache_lookup_ms = cache_lookup_ms
    cacheable_response, cache_reason = _resolve_global_cacheability(
        message=message,
        restaurant_id=restaurant_id,
        is_greeting=prepared.is_greeting,
        uses_personal_context=prepared.uses_personal_context,
        is_follow_up=prepared.is_follow_up,
    )

    response_suggestions = _attach_suggestion_favorites(db, user, prepared.suggestions)
    yield _sse_frame(
        "meta",
        {
            "session_id": str(prepared.active_session_id),
            "suggestions": [item.model_dump(mode="json") for item in response_suggestions],
            "combo_suggestions": [item.model_dump(mode="json") for item in prepared.combo_suggestions],
            "offer_suggestions": [item.model_dump(mode="json") for item in prepared.offer_suggestions],
        },
    )

    raw_reply = ""
    llm_strategy = "skipped"
    if prepared.should_bypass_llm:
        reply = prepared.fallback_reply or _build_safe_reply(
            message,
            prepared.suggestions,
            prepared.retrieval_source,
            extracted_intent=prepared.extracted_intent,
            is_follow_up=prepared.is_follow_up,
            follow_up_base_message=prepared.effective_message,
        )
        yield _sse_frame("token", {"text": reply})
    else:
        llm_strategy = "generated"
        llm_started_at = perf_counter()
        chunks: list[str] = []
        try:
            for event in _stream_reply_events(prepared.prompt):
                token_text = event.get("response")
                if isinstance(token_text, str) and token_text:
                    chunks.append(token_text)
                    yield _sse_frame("token", {"text": token_text})
                if event.get("done"):
                    break
        except HTTPException:
            llm_strategy = "fallback_after_llm_failure"
        prepared.timings.llm_ms = round((perf_counter() - llm_started_at) * 1000, 2)
        raw_reply = "".join(chunks).strip()
        reply = (
            _ensure_useful_reply(
                message=message,
                raw_reply=raw_reply,
                suggestions=prepared.suggestions,
                retrieval_source=prepared.retrieval_source,
                extracted_intent=prepared.extracted_intent,
                is_follow_up=prepared.is_follow_up,
                follow_up_base_message=prepared.effective_message,
                fallback_reply_override=prepared.fallback_reply,
            )
            if raw_reply
            else (
                prepared.fallback_reply
                or _build_safe_reply(
                    message,
                    prepared.suggestions,
                    prepared.retrieval_source,
                    extracted_intent=prepared.extracted_intent,
                    is_follow_up=prepared.is_follow_up,
                    follow_up_base_message=prepared.effective_message,
                )
            )
        )
        if not raw_reply:
            yield _sse_frame("token", {"text": reply})
    if cacheable_response:
        cache_set_json(
            response_cache_key,
            _serialize_chat_response_cache_payload(
                reply=reply,
                suggestions=prepared.suggestions,
                combo_suggestions=prepared.combo_suggestions,
                offer_suggestions=prepared.offer_suggestions,
                retrieval_source=prepared.retrieval_source,
            ),
        )
    else:
        logger.info("RAG response cache skipped save key=%s reason=%s", response_cache_key, cache_reason)

    try:
        _persist_chat_exchange(
            db,
            user=user,
            prepared=prepared,
            raw_reply=raw_reply,
            reply=reply,
            llm_strategy=llm_strategy,
        )
    except Exception:  # pragma: no cover - defensive fail-open path
        logger.exception(
            "RAG stream persist chat exchange failed user_id=%s session_id=%s message=%s",
            user.id,
            prepared.active_session_id,
            message,
        )
    prepared.timings.total_ms = round((perf_counter() - started_at) * 1000, 2)
    _log_rag_timings(user, prepared)
    yield _sse_frame(
        "done",
        {
            "reply": reply,
            "session_id": str(prepared.active_session_id),
            "suggestions": [item.model_dump(mode="json") for item in response_suggestions],
            "combo_suggestions": [item.model_dump(mode="json") for item in prepared.combo_suggestions],
            "offer_suggestions": [item.model_dump(mode="json") for item in prepared.offer_suggestions],
        },
    )

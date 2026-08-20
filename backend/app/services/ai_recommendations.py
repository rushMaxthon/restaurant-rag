from __future__ import annotations

import json
import logging
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.config.celery import celery_app
from app.models.enums import UserRole
from app.models.favorite import Favorite
from app.models.menu_item import MenuItem
from app.models.personalized_recommendation_snapshot import (
    PersonalizedRecommendationSnapshot,
)
from app.models.user import User
from app.models.user_preferences import UserPreferences
from app.schemas.recommendation import (
    PersonalizedRecommendationContextResponse,
    RecommendationItemResponse,
)
from app.services.recommendations import (
    _dedupe_multi_location_recommendations,
    _load_order_history,
    _normalize_choice_key,
    _normalize_text,
    get_deterministic_recommendations_for_user,
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
    read=settings.ollama_chat_timeout_seconds,
    write=10.0,
    pool=5.0,
)
GENERATE_CLIENT = build_client(GENERATE_TIMEOUT, limits=HTTP_LIMITS)

STATUS_PENDING = "PENDING"
STATUS_READY = "READY"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED_SMALL_SET = "SKIPPED_SMALL_SET"


class RankedCandidatePayload(BaseModel):
    candidate_id: str
    reason: str | None = None
    badge: str | None = None


class AIRerankPayload(BaseModel):
    collection_title: str | None = None
    insight: str | None = None
    ranked_candidates: list[RankedCandidatePayload]


def _candidate_group_key(item: RecommendationItemResponse) -> str:
    return "|".join(
        [
            str(item.restaurant_id),
            _normalize_choice_key(item.name),
            _normalize_choice_key(item.category),
            _normalize_choice_key(item.cuisine_type or item.restaurant.cuisine_type),
            "veg" if item.is_veg else "non_veg",
        ]
    )


def _serialize_candidate_snapshot(items: list[RecommendationItemResponse]) -> str:
    rows = [
        {
            "group_key": _candidate_group_key(item),
            "score": round(item.score, 4),
            "restaurant": item.restaurant.name,
            "cuisine": item.cuisine_type or item.restaurant.cuisine_type,
            "category": item.category,
            "is_veg": item.is_veg,
        }
        for item in items
    ]
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def _candidate_snapshot_hash(items: list[RecommendationItemResponse]) -> str:
    import hashlib

    return hashlib.sha256(_serialize_candidate_snapshot(items).encode("utf-8")).hexdigest()


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


def _clean_text(value: str | None, *, max_length: int) -> str | None:
    cleaned = " ".join((value or "").strip().split())
    if not cleaned:
        return None
    return cleaned[:max_length].strip()


def _load_snapshot_record(
    db: Session,
    *,
    user_id: uuid.UUID,
) -> PersonalizedRecommendationSnapshot | None:
    return db.scalar(
        select(PersonalizedRecommendationSnapshot).where(
            PersonalizedRecommendationSnapshot.user_id == user_id,
        )
    )


def _ensure_snapshot_record(
    db: Session,
    *,
    user_id: uuid.UUID,
) -> PersonalizedRecommendationSnapshot:
    existing = _load_snapshot_record(db, user_id=user_id)
    if existing is not None:
        return existing
    record = PersonalizedRecommendationSnapshot(user_id=user_id)
    db.add(record)
    db.flush()
    return record


def _build_candidate_pool(
    items: list[RecommendationItemResponse],
) -> list[RecommendationItemResponse]:
    return _dedupe_multi_location_recommendations(
        items,
        location_context=None,
        limit=settings.ai_recommendation_candidate_limit,
    )


def _build_current_deduped_items(
    items: list[RecommendationItemResponse],
    *,
    location_context: Any,
    final_limit: int,
) -> list[RecommendationItemResponse]:
    return _dedupe_multi_location_recommendations(
        items,
        location_context=location_context,
        limit=max(final_limit, settings.ai_recommendation_candidate_limit),
    )


def _queue_refresh(
    *,
    user_id: uuid.UUID,
    reason: str,
    force_refresh: bool = False,
) -> None:
    try:
        celery_app.send_task(
            "app.tasks.ai_recommendations.generate_ai_recommendations_task",
            kwargs={
                "user_id": str(user_id),
                "reason": reason,
                "force_refresh": force_refresh,
            },
        )
    except Exception:
        logger.exception(
            "Failed to enqueue AI recommendation rerank user_id=%s reason=%s",
            user_id,
            reason,
        )


def queue_ai_recommendation_refresh(
    *,
    user_id: uuid.UUID,
    reason: str,
    force_refresh: bool = False,
) -> None:
    if not settings.enable_ai_recommendation_reranking:
        return
    _queue_refresh(user_id=user_id, reason=reason, force_refresh=force_refresh)


def _load_user_behavior_context(
    db: Session,
    *,
    user: User,
    candidates: list[RecommendationItemResponse],
) -> dict[str, Any]:
    preferences = db.scalar(
        select(UserPreferences).where(UserPreferences.user_id == user.id)
    )
    history = _load_order_history(db, user.id)
    favorite_names = db.execute(
        select(MenuItem.name)
        .join(Favorite, Favorite.menu_item_id == MenuItem.id)
        .where(Favorite.user_id == user.id)
        .limit(8)
    ).scalars().all()

    top_items = sorted(
        history.item_scores.items(),
        key=lambda entry: entry[1],
        reverse=True,
    )[:5]
    top_cuisines = sorted(
        history.cuisine_scores.items(),
        key=lambda entry: entry[1],
        reverse=True,
    )[:4]
    top_categories = sorted(
        history.category_scores.items(),
        key=lambda entry: entry[1],
        reverse=True,
    )[:4]

    return {
        "favorite_cuisines": list(getattr(preferences, "favorite_cuisines", []) or []),
        "favorite_items": list(getattr(preferences, "favorite_items", []) or []),
        "dietary_preferences": list(getattr(preferences, "dietary_preferences", []) or []),
        "spice_level": getattr(preferences, "spice_level", None),
        "budget_tier": getattr(preferences, "budget_tier", None),
        "saved_favorites": [name for name in favorite_names if name],
        "recent_order_signal_count": history.eligible_order_count,
        "status_counts": history.status_counts,
        "top_item_signals": top_items,
        "top_cuisine_signals": top_cuisines,
        "top_category_signals": top_categories,
        "candidates": [
            {
                "candidate_id": f"c{index + 1:02d}",
                "name": item.name,
                "restaurant": item.restaurant.name,
                "cuisine": item.cuisine_type or item.restaurant.cuisine_type,
                "category": item.category,
                "is_veg": item.is_veg,
                "price": str(item.display_price or item.price),
                "score": round(item.score, 4),
                "label": item.recommendation_label,
                "reason": item.recommendation_reason,
            }
            for index, item in enumerate(candidates)
        ],
    }


def _build_prompt(
    *,
    user: User,
    behavior_context: dict[str, Any],
) -> str:
    return f"""
You are re-ranking backend-approved restaurant menu recommendations for one customer.

Important rules:
- Do not invent items
- Only use candidate_id values from the provided candidate list
- Never add items outside the candidate set
- Respect the backend-approved candidates as the only valid universe
- Prefer diversity across restaurant, cuisine, and category when reasonable
- Keep recommendations aligned with actual user behavior and preferences
- If evidence is weak, stay conservative

Return strict JSON with this exact shape:
{{
  "collection_title": "string or null",
  "insight": "string or null",
  "ranked_candidates": [
    {{
      "candidate_id": "c01",
      "reason": "string or null",
      "badge": "string or null"
    }}
  ]
}}

Copy rules:
- collection_title under 60 characters
- insight under 120 characters
- each reason under 90 characters
- each badge under 32 characters
- one badge max per item
- reasons must be grounded in the provided behavior context only

Customer:
- email: {user.email}

Behavior and candidate context:
{json.dumps(behavior_context, ensure_ascii=True)}
""".strip()


def _call_llm_for_rerank(
    *,
    user: User,
    behavior_context: dict[str, Any],
) -> AIRerankPayload:
    payload = {
        "model": settings.ollama_chat_model,
        "prompt": _build_prompt(user=user, behavior_context=behavior_context),
        "stream": False,
        "format": "json",
        **local_only_options(),
    }
    response = GENERATE_CLIENT.post(GENERATE_ENDPOINT, json=payload)
    response.raise_for_status()
    raw_reply = str(response.json().get("response") or "").strip()
    parsed = _extract_json_payload(raw_reply)
    return AIRerankPayload.model_validate(parsed)


def _apply_diversity(
    ordered_items: list[RecommendationItemResponse],
    *,
    limit: int,
) -> list[RecommendationItemResponse]:
    if not ordered_items:
        return []

    selected: list[RecommendationItemResponse] = []
    deferred: list[RecommendationItemResponse] = []
    restaurant_counts: Counter[str] = Counter()
    cuisine_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()

    for index, item in enumerate(ordered_items):
        if len(selected) >= limit:
            break
        restaurant_key = str(item.restaurant_id)
        cuisine_key = _normalize_text(item.cuisine_type or item.restaurant.cuisine_type)
        category_key = _normalize_text(item.category)

        has_alternative_restaurant = any(
            str(other.restaurant_id) != restaurant_key
            for other in ordered_items[index + 1 :]
        )
        has_alternative_cuisine = any(
            _normalize_text(other.cuisine_type or other.restaurant.cuisine_type)
            != cuisine_key
            for other in ordered_items[index + 1 :]
        )
        has_alternative_category = any(
            _normalize_text(other.category) != category_key
            for other in ordered_items[index + 1 :]
        )

        over_restaurant = (
            restaurant_counts[restaurant_key]
            >= settings.ai_recommendation_max_same_restaurant
            and has_alternative_restaurant
        )
        over_cuisine = (
            cuisine_key
            and cuisine_counts[cuisine_key]
            >= settings.ai_recommendation_max_same_cuisine
            and has_alternative_cuisine
        )
        over_category = (
            category_key
            and category_counts[category_key]
            >= settings.ai_recommendation_max_same_category
            and has_alternative_category
        )

        if over_restaurant or over_cuisine or over_category:
            deferred.append(item)
            continue

        selected.append(item)
        restaurant_counts[restaurant_key] += 1
        if cuisine_key:
            cuisine_counts[cuisine_key] += 1
        if category_key:
            category_counts[category_key] += 1

    for item in deferred:
        if len(selected) >= limit:
            break
        selected.append(item)

    return selected[:limit]


def _upsert_snapshot(
    db: Session,
    *,
    user_id: uuid.UUID,
    snapshot_hash: str,
    candidate_count: int,
    status: str,
    ranked_keys: list[str],
    collection_title: str | None,
    insight: str | None,
    item_metadata: dict[str, dict[str, str | None]],
    model_name: str | None,
    generated_at: datetime,
    last_error: str | None,
) -> PersonalizedRecommendationSnapshot:
    record = _ensure_snapshot_record(db, user_id=user_id)
    record.candidate_snapshot_hash = snapshot_hash
    record.candidate_count = candidate_count
    record.generation_status = status
    record.ranked_recommendation_keys = ranked_keys
    record.ai_collection_title = collection_title
    record.ai_insight = insight
    record.item_metadata = item_metadata
    record.ai_model = model_name
    record.generated_at = generated_at
    record.last_error = last_error
    db.add(record)
    db.flush()
    return record


def generate_ai_recommendation_snapshot(
    db: Session,
    *,
    user_id: uuid.UUID,
    reason: str,
    force_refresh: bool = False,
) -> dict[str, Any]:
    if not settings.enable_ai_recommendation_reranking:
        return {"status": "skipped", "reason": "feature_disabled"}

    user = db.scalar(
        select(User).where(
            User.id == user_id,
            User.role == UserRole.CUSTOMER,
            User.is_active.is_(True),
        )
    )
    if user is None:
        return {"status": "skipped", "reason": "user_not_found"}

    deterministic_items = get_deterministic_recommendations_for_user(db, user)
    candidate_pool = _build_candidate_pool(deterministic_items)
    snapshot_hash = _candidate_snapshot_hash(candidate_pool)
    candidate_count = len(candidate_pool)
    existing = _load_snapshot_record(db, user_id=user.id)
    now = datetime.now(UTC)

    if (
        not force_refresh
        and existing is not None
        and existing.candidate_snapshot_hash == snapshot_hash
        and existing.generation_status in {STATUS_READY, STATUS_SKIPPED_SMALL_SET}
    ):
        return {"status": "skipped", "reason": "snapshot_unchanged"}

    if candidate_count < settings.ai_recommendation_min_candidate_count:
        _upsert_snapshot(
            db,
            user_id=user.id,
            snapshot_hash=snapshot_hash,
            candidate_count=candidate_count,
            status=STATUS_SKIPPED_SMALL_SET,
            ranked_keys=[_candidate_group_key(item) for item in candidate_pool[: settings.ai_recommendation_final_limit]],
            collection_title=None,
            insight=None,
            item_metadata={},
            model_name=None,
            generated_at=now,
            last_error=None,
        )
        db.commit()
        return {"status": "skipped_small_set", "candidate_count": candidate_count}

    behavior_context = _load_user_behavior_context(
        db,
        user=user,
        candidates=candidate_pool,
    )
    candidate_id_map = {
        f"c{index + 1:02d}": item
        for index, item in enumerate(candidate_pool)
    }

    try:
        llm_payload = _call_llm_for_rerank(
            user=user,
            behavior_context=behavior_context,
        )
        ranked_ids: list[str] = []
        item_metadata: dict[str, dict[str, str | None]] = {}
        for candidate in llm_payload.ranked_candidates:
            if candidate.candidate_id not in candidate_id_map:
                continue
            if candidate.candidate_id in ranked_ids:
                continue
            ranked_ids.append(candidate.candidate_id)
            item = candidate_id_map[candidate.candidate_id]
            item_metadata[_candidate_group_key(item)] = {
                "ai_reason": _clean_text(candidate.reason, max_length=90),
                "ai_badge": _clean_text(candidate.badge, max_length=32),
            }

        ordered_candidates = [
            candidate_id_map[candidate_id]
            for candidate_id in ranked_ids
        ]
        ordered_candidates.extend(
            item
            for candidate_id, item in candidate_id_map.items()
            if candidate_id not in ranked_ids
        )
        final_candidates = _apply_diversity(
            ordered_candidates,
            limit=settings.ai_recommendation_final_limit,
        )
        final_keys = [_candidate_group_key(item) for item in final_candidates]

        _upsert_snapshot(
            db,
            user_id=user.id,
            snapshot_hash=snapshot_hash,
            candidate_count=candidate_count,
            status=STATUS_READY,
            ranked_keys=final_keys,
            collection_title=_clean_text(llm_payload.collection_title, max_length=60),
            insight=_clean_text(llm_payload.insight, max_length=120),
            item_metadata=item_metadata,
            model_name=settings.ollama_chat_model,
            generated_at=now,
            last_error=None,
        )
        db.commit()
        logger.info(
            "AI recommendation rerank generated user_id=%s reason=%s candidate_count=%s final_count=%s",
            user.id,
            reason,
            candidate_count,
            len(final_keys),
        )
        return {
            "status": "ready",
            "candidate_count": candidate_count,
            "final_count": len(final_keys),
        }
    except (httpx.TimeoutException, httpx.HTTPError, ValidationError, ValueError) as error:
        logger.warning(
            "AI recommendation rerank failed user_id=%s reason=%s error=%s",
            user.id,
            reason,
            error,
        )
        _upsert_snapshot(
            db,
            user_id=user.id,
            snapshot_hash=snapshot_hash,
            candidate_count=candidate_count,
            status=STATUS_FAILED,
            ranked_keys=[],
            collection_title=None,
            insight=None,
            item_metadata={},
            model_name=settings.ollama_chat_model,
            generated_at=now,
            last_error=str(error),
        )
        db.commit()
        return {
            "status": "failed",
            "candidate_count": candidate_count,
            "error": str(error),
        }


def get_personalized_recommendation_context(
    db: Session,
    *,
    user: User,
    restaurant_id: uuid.UUID | None = None,
) -> PersonalizedRecommendationContextResponse:
    if not settings.enable_ai_recommendation_reranking:
        return PersonalizedRecommendationContextResponse()

    # Built from the same scoped pool as the list itself, so the candidate
    # count and AI copy describe what the app actually shows.
    deterministic_items = get_deterministic_recommendations_for_user(
        db,
        user,
        restaurant_id=restaurant_id,
    )
    candidate_pool = _build_candidate_pool(deterministic_items)
    snapshot_hash = _candidate_snapshot_hash(candidate_pool)
    record = _load_snapshot_record(db, user_id=user.id)

    if (
        record is None
        or record.candidate_snapshot_hash != snapshot_hash
        or record.generation_status != STATUS_READY
    ):
        return PersonalizedRecommendationContextResponse(
            candidate_count=len(candidate_pool),
        )

    return PersonalizedRecommendationContextResponse(
        ai_collection_title=record.ai_collection_title,
        ai_insight=record.ai_insight,
        generated_at=record.generated_at,
        model_name=record.ai_model,
        candidate_count=record.candidate_count,
    )


def apply_cached_ai_recommendations(
    db: Session,
    *,
    user: User,
    items: list[RecommendationItemResponse],
    location_context: Any,
) -> list[RecommendationItemResponse]:
    if not settings.enable_ai_recommendation_reranking:
        return _dedupe_multi_location_recommendations(
            items,
            location_context=location_context,
            limit=settings.ai_recommendation_final_limit,
        )

    candidate_pool = _build_candidate_pool(items)
    candidate_count = len(candidate_pool)
    if candidate_count < settings.ai_recommendation_min_candidate_count:
        current = _build_current_deduped_items(
            items,
            location_context=location_context,
            final_limit=settings.ai_recommendation_final_limit,
        )
        record = _load_snapshot_record(db, user_id=user.id)
        snapshot_hash = _candidate_snapshot_hash(candidate_pool)
        if (
            record is None
            or record.candidate_snapshot_hash != snapshot_hash
            or record.generation_status != STATUS_SKIPPED_SMALL_SET
        ):
            queue_ai_recommendation_refresh(
                user_id=user.id,
                reason="small_candidate_set_seen",
            )
        return current[: settings.ai_recommendation_final_limit]

    snapshot_hash = _candidate_snapshot_hash(candidate_pool)
    record = _load_snapshot_record(db, user_id=user.id)
    current_candidates = _build_current_deduped_items(
        items,
        location_context=location_context,
        final_limit=settings.ai_recommendation_final_limit,
    )

    if (
        record is None
        or record.candidate_snapshot_hash != snapshot_hash
        or record.generation_status not in {STATUS_READY, STATUS_PENDING}
    ):
        should_enqueue = True
        if (
            record is not None
            and record.generation_status == STATUS_FAILED
            and record.updated_at is not None
            and datetime.now(UTC) - record.updated_at
            < timedelta(minutes=settings.ai_recommendation_retry_cooldown_minutes)
        ):
            should_enqueue = False
        if should_enqueue:
            queue_ai_recommendation_refresh(
                user_id=user.id,
                reason="cache_miss",
            )
        return current_candidates[: settings.ai_recommendation_final_limit]

    if record.generation_status == STATUS_PENDING:
        return current_candidates[: settings.ai_recommendation_final_limit]

    current_by_key = {
        _candidate_group_key(item): item
        for item in current_candidates
    }
    ordered: list[RecommendationItemResponse] = []
    used_keys: set[str] = set()
    for group_key in record.ranked_recommendation_keys:
        item = current_by_key.get(group_key)
        if item is None:
            continue
        metadata = dict(record.item_metadata or {}).get(group_key, {})
        ordered.append(
            item.model_copy(
                update={
                    "ai_badge": metadata.get("ai_badge"),
                    "ai_reason": metadata.get("ai_reason"),
                }
            )
        )
        used_keys.add(group_key)

    for item in current_candidates:
        group_key = _candidate_group_key(item)
        if group_key in used_keys:
            continue
        ordered.append(item)
        used_keys.add(group_key)

    return ordered[: settings.ai_recommendation_final_limit]

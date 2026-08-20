from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import AppScopeDep
from app.config.database import get_db
from app.models.user import User
from app.schemas.preferences import RecommendationLocationContext, RecommendationQueryRequest
from app.schemas.recommendation import (
    PersonalizedRecommendationContextResponse,
    RecommendationItemResponse,
)
from app.services.auth import get_current_user, get_current_user_optional
from app.services.favorites import apply_recommendation_favorite_flags, get_user_favorite_ids
from app.services.recommendations import get_recommendations_for_request, get_recommendations_for_user
from app.services.ai_recommendations import get_personalized_recommendation_context

router = APIRouter(prefix="/recommendations", tags=["Recommendations"])


@router.get("", response_model=list[RecommendationItemResponse])
def get_recommendations(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
    dedupe_multi_location: bool = Query(default=False),
    location_city: str | None = Query(default=None),
    latitude: float | None = Query(default=None),
    longitude: float | None = Query(default=None),
) -> list[RecommendationItemResponse]:
    location_context = (
        RecommendationLocationContext(
            city=location_city,
            latitude=latitude,
            longitude=longitude,
        )
        if location_city or latitude is not None or longitude is not None
        else None
    )
    items = get_recommendations_for_user(
        db,
        current_user,
        dedupe_multi_location=dedupe_multi_location,
        location_context=location_context,
        restaurant_id=app_scope.restaurant_filter_id,
    )
    favorite_ids = get_user_favorite_ids(db, current_user, menu_item_ids=[item.id for item in items])
    return apply_recommendation_favorite_flags(items, favorite_ids)


@router.get(
    "/personalized-context",
    response_model=PersonalizedRecommendationContextResponse,
)
def get_personalized_context(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    app_scope: AppScopeDep,
) -> PersonalizedRecommendationContextResponse:
    return get_personalized_recommendation_context(
        db,
        user=current_user,
        restaurant_id=app_scope.restaurant_filter_id,
    )


@router.post("/query", response_model=list[RecommendationItemResponse])
def query_recommendations(
    payload: RecommendationQueryRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    app_scope: AppScopeDep,
) -> list[RecommendationItemResponse]:
    items = get_recommendations_for_request(
        db,
        user=current_user,
        preference_payload=payload.preferences,
        dedupe_multi_location=payload.dedupe_multi_location,
        location_context=payload.location_context,
        restaurant_id=app_scope.restaurant_filter_id,
    )
    favorite_ids = get_user_favorite_ids(db, current_user, menu_item_ids=[item.id for item in items])
    return apply_recommendation_favorite_flags(items, favorite_ids)

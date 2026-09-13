from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.config.database import get_db
from app.dependencies import AppScopeDep
from app.models.user import User
from app.schemas.preferences import (
    PreferenceAnswerResponse,
    PreferenceAnswersPayload,
    PreferenceOptionResponse,
    PreferenceQuestionResponse,
    PreferenceSchemaResponse,
    UserPreferenceAnswersResponse,
    UserPreferencesPayload,
    UserPreferencesResponse,
)
from app.services.auth import get_current_user
from app.services.preference_schema import (
    PreferenceValidationError,
    build_answer_view,
    resolve_questionnaire,
    save_user_answers,
)
from app.services.recommendations import (
    get_user_preferences_response,
    invalidate_user_recommendation_cache,
    upsert_user_preferences,
)

router = APIRouter(prefix="/preferences", tags=["Preferences"])
logger = logging.getLogger(__name__)


@router.get("/me", response_model=UserPreferencesResponse)
def get_my_preferences(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserPreferencesResponse:
    preferences = get_user_preferences_response(db, current_user)
    if preferences is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preferences not found",
        )
    return preferences


@router.put("/me", response_model=UserPreferencesResponse)
def update_my_preferences(
    payload: UserPreferencesPayload,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserPreferencesResponse:
    try:
        return upsert_user_preferences(db, current_user, payload)
    except SQLAlchemyError:
        logger.exception(
            "Failed to update preferences for user %s",
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save preferences right now. Please try again.",
        )


# ---------------------------------------------------------------------------
# Dynamic questionnaire
# ---------------------------------------------------------------------------


def _resolve_schema_restaurant(
    app_scope: AppScopeDep,
    requested_restaurant_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """Which restaurant's questionnaire to serve.

    A branded mobile build identifies itself with `X-App-Bundle-Id`, and that
    scope always wins - it cannot be talked into another restaurant's questions
    by a query parameter.

    The customer website has no bundle id by design: sending one would change
    which app client its accounts belong to and lock every existing web customer
    out. So it names the restaurant explicitly here, exactly as it already does
    for `/app-config`. This endpoint is a read of public configuration, so
    taking the value from the caller carries none of the identity risk the
    header would.
    """

    scoped = app_scope.restaurant_filter_id
    if scoped is not None:
        return scoped
    return requested_restaurant_id


@router.get("/schema", response_model=PreferenceSchemaResponse)
def get_preference_schema(
    db: Annotated[Session, Depends(get_db)],
    app_scope: AppScopeDep,
    restaurant_id: uuid.UUID | None = Query(default=None),
) -> PreferenceSchemaResponse:
    """The questions this app should ask, in order.

    Public on purpose: onboarding runs before a customer has an account, so this
    has to answer without a token.
    """

    restaurant_id = _resolve_schema_restaurant(app_scope, restaurant_id)
    resolved = resolve_questionnaire(db, restaurant_id=restaurant_id)
    return PreferenceSchemaResponse(
        restaurant_id=restaurant_id,
        questions=[
            PreferenceQuestionResponse(
                id=entry.question.id,
                key=entry.question.key,
                prompt=entry.question.prompt,
                help_text=entry.question.help_text,
                input_type=entry.question.input_type,
                is_required=entry.question.is_required,
                min_selections=entry.question.min_selections,
                max_selections=entry.question.max_selections,
                allows_free_text=entry.question.allows_free_text,
                signal_role=entry.question.signal_role,
                display_order=entry.display_order,
                is_inherited=entry.is_inherited,
                options=[
                    PreferenceOptionResponse.model_validate(option) for option in entry.options
                ],
            )
            for entry in resolved
        ],
    )


@router.get("/me/answers", response_model=UserPreferenceAnswersResponse)
def get_my_preference_answers(
    db: Annotated[Session, Depends(get_db)],
    app_scope: AppScopeDep,
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: uuid.UUID | None = Query(default=None),
) -> UserPreferenceAnswersResponse:
    view = build_answer_view(
        db,
        user_id=current_user.id,
        restaurant_id=_resolve_schema_restaurant(app_scope, restaurant_id),
    )
    legacy = get_user_preferences_response(db, current_user) or UserPreferencesPayload()
    return UserPreferenceAnswersResponse(
        answers=[PreferenceAnswerResponse(**entry) for entry in view],
        legacy=UserPreferencesPayload(
            cuisines=legacy.cuisines,
            diet=legacy.diet,
            spice_level=legacy.spice_level,
            budget=legacy.budget,
            favorite_items=legacy.favorite_items,
        ),
    )


@router.put("/me/answers", response_model=UserPreferenceAnswersResponse)
def update_my_preference_answers(
    payload: PreferenceAnswersPayload,
    db: Annotated[Session, Depends(get_db)],
    app_scope: AppScopeDep,
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: uuid.UUID | None = Query(default=None),
) -> UserPreferenceAnswersResponse:
    """Save answers, and reproject the legacy row in the same transaction.

    The projection is not optional bookkeeping: `services/recommendations.py`
    still reads `user_preferences` on every request, so letting the two diverge
    would change a customer's feed without anyone touching their answers.
    """

    try:
        save_user_answers(
            db,
            user_id=current_user.id,
            restaurant_id=_resolve_schema_restaurant(app_scope, restaurant_id),
            submissions=[
                (entry.question_id, entry.option_ids, entry.free_text)
                for entry in payload.answers
            ],
        )
        db.commit()
    except PreferenceValidationError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Failed to save preference answers for user %s", current_user.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save preferences right now. Please try again.",
        )

    invalidate_user_recommendation_cache(current_user.id)
    return get_my_preference_answers(db, app_scope, current_user, restaurant_id)

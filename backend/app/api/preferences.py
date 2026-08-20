from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.config.database import get_db
from app.models.user import User
from app.schemas.preferences import UserPreferencesPayload, UserPreferencesResponse
from app.services.auth import get_current_user
from app.services.recommendations import get_user_preferences_response, upsert_user_preferences

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

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.user import User
from app.schemas.auth import UserResponse
from app.schemas.profile import (
    SavedAddressCreateRequest,
    SavedAddressResponse,
    SavedAddressUpdateRequest,
    UserProfileSummaryResponse,
    UserProfileUpdateRequest,
)
from app.services.auth import require_customer
from app.services.profile import (
    create_user_saved_address,
    delete_user_saved_address,
    get_user_profile_summary,
    list_user_saved_addresses,
    set_default_user_saved_address,
    update_user_profile,
    update_user_saved_address,
)

router = APIRouter(prefix="/profile", tags=["Profile"])


@router.get("/me", response_model=UserProfileSummaryResponse)
def get_my_profile(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
) -> UserProfileSummaryResponse:
    return get_user_profile_summary(db, current_user)


@router.patch("/me", response_model=UserResponse)
def patch_my_profile(
    payload: UserProfileUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
) -> UserResponse:
    return update_user_profile(db, current_user, payload)


@router.get("/addresses", response_model=list[SavedAddressResponse])
def get_my_saved_addresses(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
) -> list[SavedAddressResponse]:
    return list_user_saved_addresses(db, current_user)


@router.post(
    "/addresses",
    response_model=SavedAddressResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_my_saved_address(
    payload: SavedAddressCreateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
) -> SavedAddressResponse:
    return create_user_saved_address(db, current_user, payload)


@router.patch("/addresses/{address_id}", response_model=SavedAddressResponse)
def patch_my_saved_address(
    address_id: uuid.UUID,
    payload: SavedAddressUpdateRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
) -> SavedAddressResponse:
    return update_user_saved_address(db, current_user, address_id, payload)


@router.delete("/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_my_saved_address(
    address_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
) -> Response:
    delete_user_saved_address(db, current_user, address_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/addresses/{address_id}/default",
    response_model=SavedAddressResponse,
)
def mark_my_saved_address_default(
    address_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
) -> SavedAddressResponse:
    return set_default_user_saved_address(db, current_user, address_id)

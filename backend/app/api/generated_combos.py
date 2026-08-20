from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import AppScopeDep, ensure_restaurant_readable
from app.config.database import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.schemas.generated_combo import (
    ComboUpsellSuggestionResponse,
    GeneratedComboRebuildResponse,
    GeneratedComboResponse,
    GeneratedComboStatusUpdate,
)
from app.services.auth import get_current_user, get_current_user_optional, require_admin, resolve_owner_restaurant_id
from app.services.favorites import get_user_favorite_ids
from app.services.generated_combos import (
    get_combo_upsell_suggestions,
    get_generated_combo,
    list_generated_combos,
    rebuild_generated_combos,
    set_generated_combo_status,
)

router = APIRouter(tags=["Generated Combos"])


@router.get("/generated-combos", response_model=list[GeneratedComboResponse])
def get_generated_combos(
    db: Annotated[Session, Depends(get_db)],
    app_scope: AppScopeDep,
    limit: int = Query(default=12, ge=1, le=50),
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> list[GeneratedComboResponse]:
    favorite_ids = get_user_favorite_ids(db, current_user)
    return list_generated_combos(
        db,
        restaurant_id=app_scope.restaurant_filter_id,
        limit=limit,
        favorite_ids=favorite_ids,
    )


@router.get("/generated-combos/{combo_id}", response_model=GeneratedComboResponse)
def get_generated_combo_detail(
    combo_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    app_scope: AppScopeDep,
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> GeneratedComboResponse:
    favorite_ids = get_user_favorite_ids(db, current_user)
    combo = get_generated_combo(db, combo_id, favorite_ids=favorite_ids)
    ensure_restaurant_readable(app_scope, combo.restaurant_id)
    return combo


@router.get("/restaurants/{restaurant_id}/generated-combos", response_model=list[GeneratedComboResponse])
def get_restaurant_generated_combos(
    restaurant_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    app_scope: AppScopeDep,
    limit: int = Query(default=12, ge=1, le=50),
    location_id: uuid.UUID | None = Query(default=None),
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> list[GeneratedComboResponse]:
    ensure_restaurant_readable(app_scope, restaurant_id)
    favorite_ids = get_user_favorite_ids(db, current_user)
    return list_generated_combos(
        db,
        restaurant_id=restaurant_id,
        restaurant_location_id=location_id,
        limit=limit,
        favorite_ids=favorite_ids,
    )


@router.get("/cart/upsell-suggestions", response_model=list[ComboUpsellSuggestionResponse])
def get_cart_upsell_suggestions(
    db: Annotated[Session, Depends(get_db)],
    app_scope: AppScopeDep,
    restaurant_id: uuid.UUID = Query(...),
    location_id: uuid.UUID | None = Query(default=None),
    item_id: uuid.UUID = Query(...),
    cart_item_ids: list[uuid.UUID] = Query(default=[]),
    limit: int = Query(default=3, ge=1, le=10),
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> list[ComboUpsellSuggestionResponse]:
    ensure_restaurant_readable(app_scope, restaurant_id)
    favorite_ids = get_user_favorite_ids(db, current_user)
    return get_combo_upsell_suggestions(
        db,
        restaurant_id=restaurant_id,
        restaurant_location_id=location_id,
        item_id=item_id,
        cart_item_ids=cart_item_ids,
        limit=limit,
        favorite_ids=favorite_ids,
    )


@router.get("/admin/generated-combos", response_model=list[GeneratedComboResponse])
def get_admin_generated_combos(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    restaurant_id: uuid.UUID | None = Query(default=None),
    location_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[GeneratedComboResponse]:
    if current_user.role == UserRole.OWNER:
        owner_restaurant_id = resolve_owner_restaurant_id(db, current_user)
        if restaurant_id is not None and restaurant_id != owner_restaurant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Owners can only access generated combos for their assigned restaurant",
            )
        restaurant_id = owner_restaurant_id
    elif current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this resource",
        )

    return list_generated_combos(
        db,
        restaurant_id=restaurant_id,
        restaurant_location_id=location_id,
        limit=limit,
        active_only=False,
        customer_visible_only=False,
        fail_open=False,
    )


@router.post("/admin/generated-combos/rebuild", response_model=GeneratedComboRebuildResponse)
def rebuild_admin_generated_combos(
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
    lookback_days: int | None = Query(default=None, ge=1, le=365),
) -> GeneratedComboRebuildResponse:
    return rebuild_generated_combos(db, lookback_days=lookback_days)


@router.patch("/admin/generated-combos/{combo_id}/status", response_model=GeneratedComboResponse)
def patch_admin_generated_combo_status(
    combo_id: uuid.UUID,
    payload: GeneratedComboStatusUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> GeneratedComboResponse:
    if current_user.role == UserRole.OWNER:
        owner_restaurant_id = resolve_owner_restaurant_id(db, current_user)
        combo = get_generated_combo(db, combo_id, include_hidden=True)
        if combo.restaurant_id != owner_restaurant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Owners can only manage generated combos for their assigned restaurant",
            )
    elif current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this resource",
        )

    return set_generated_combo_status(db, combo_id=combo_id, status_value=payload.status)

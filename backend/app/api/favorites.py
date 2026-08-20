from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AppScopeDep, ensure_restaurant_writable
from app.config.database import get_db
from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.schemas.favorite import FavoriteItemResponse, FavoriteStatusResponse
from app.services.auth import require_customer
from app.services.favorites import (
    add_user_favorite,
    delete_user_favorite,
    get_user_favorite_ids,
    serialize_favorite_list,
)

router = APIRouter(prefix="/favorites", tags=["Favorites"])


def _get_favoritable_menu_item(db: Session, menu_item_id: uuid.UUID) -> MenuItem:
    menu_item = db.scalar(
        select(MenuItem)
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
    if menu_item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu item is unavailable for favorites",
        )
    return menu_item


@router.get("", response_model=list[FavoriteItemResponse])
def list_favorites(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> list[FavoriteItemResponse]:
    return serialize_favorite_list(
        db,
        current_user,
        restaurant_id=app_scope.restaurant_filter_id,
    )


@router.get("/ids", response_model=list[uuid.UUID])
def list_favorite_ids(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> list[uuid.UUID]:
    return sorted(
        get_user_favorite_ids(
            db,
            current_user,
            fail_open=False,
            restaurant_id=app_scope.restaurant_filter_id,
        ),
        key=str,
    )


@router.post("/{menu_item_id}", response_model=FavoriteStatusResponse)
def add_favorite(
    menu_item_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> FavoriteStatusResponse:
    menu_item = _get_favoritable_menu_item(db, menu_item_id)
    ensure_restaurant_writable(app_scope, menu_item.restaurant_id)
    add_user_favorite(db, current_user, menu_item_id)

    return FavoriteStatusResponse(menu_item_id=menu_item_id, is_favorite=True)


@router.delete("/{menu_item_id}", response_model=FavoriteStatusResponse)
def remove_favorite(
    menu_item_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_customer)],
    app_scope: AppScopeDep,
) -> FavoriteStatusResponse:
    if app_scope.restaurant_filter_id is not None:
        # A missing item stays removable so stale favorites can be cleaned up;
        # only an item that demonstrably belongs elsewhere is refused.
        owning_restaurant_id = db.scalar(
            select(MenuItem.restaurant_id).where(MenuItem.id == menu_item_id)
        )
        if owning_restaurant_id is not None:
            ensure_restaurant_writable(app_scope, owning_restaurant_id)
    delete_user_favorite(db, current_user, menu_item_id)
    return FavoriteStatusResponse(menu_item_id=menu_item_id, is_favorite=False)

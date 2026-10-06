from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.menu_items import _invalidate_discovery_caches
from app.config.database import get_db
from app.models.user import User
from app.schemas.kitchen_menu import KitchenMenuItemResponse, KitchenSizeStockUpdate, KitchenStockUpdate
from app.services.auth import require_order_board
from app.services.kitchen_menu import (
    kitchen_scope,
    list_kitchen_menu,
    update_dish_stock,
    update_size_stock,
)

# The kitchen's view of the menu: stock only. Menu visibility, prices and
# creating or deleting dishes stay on /menu-items, ADMIN and OWNER only.
router = APIRouter(prefix="/kitchen/menu", tags=["Kitchen menu"])

BoardUser = Annotated[User, Depends(require_order_board)]


@router.get("", response_model=list[KitchenMenuItemResponse])
def get_kitchen_menu(
    db: Annotated[Session, Depends(get_db)],
    current_user: BoardUser,
    restaurant_id: uuid.UUID | None = Query(default=None),
    location_id: uuid.UUID | None = Query(default=None),
) -> list[KitchenMenuItemResponse]:
    scope = kitchen_scope(db, current_user, restaurant_id=restaurant_id, location_id=location_id)
    return list_kitchen_menu(db, scope)


@router.patch("/{menu_item_id}/stock", response_model=KitchenMenuItemResponse)
def patch_kitchen_dish_stock(
    menu_item_id: uuid.UUID,
    payload: KitchenStockUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: BoardUser,
    restaurant_id: uuid.UUID | None = Query(default=None),
) -> KitchenMenuItemResponse:
    scope = kitchen_scope(db, current_user, restaurant_id=restaurant_id, location_id=None)
    result = update_dish_stock(db, scope, current_user, menu_item_id, payload)
    # What the chat and the recommendations may suggest has just changed.
    _invalidate_discovery_caches()
    return result


@router.patch("/{menu_item_id}/sizes/{size_id}/stock", response_model=KitchenMenuItemResponse)
def patch_kitchen_size_stock(
    menu_item_id: uuid.UUID,
    size_id: uuid.UUID,
    payload: KitchenSizeStockUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: BoardUser,
    restaurant_id: uuid.UUID | None = Query(default=None),
) -> KitchenMenuItemResponse:
    scope = kitchen_scope(db, current_user, restaurant_id=restaurant_id, location_id=None)
    result = update_size_stock(db, scope, current_user, menu_item_id, size_id, payload)
    _invalidate_discovery_caches()
    return result

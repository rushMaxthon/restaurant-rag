"""Menu stock from the kitchen: read a branch's menu, change what is in stock.

The owner manages the MENU — what is on it, at what price — from the admin
panel. The kitchen manages STOCK — whether the tray is empty, how many are
left, how many to start each morning with. The split follows the fields the
stock feature already kept apart (`menu_item.py`): `is_available` takes a dish
off the menu; `out_of_stock` and the counts say it cannot be had right now.

Scope is `resolve_order_board_scope`, the same rule as the order board, so a
cook reaches exactly the dishes of the branches whose orders they cook: a
pinned cook one branch, an unpinned cook or the owner the whole restaurant.
Out of scope is 404, never 403 — the same as an order — so a cook learns
nothing about another branch's dishes, including that they exist.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.menu_item import MenuItem
from app.models.menu_item_size import MenuItemSize
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.schemas.kitchen_menu import (
    KitchenMenuItemResponse,
    KitchenMenuSizeResponse,
    KitchenSizeStockUpdate,
    KitchenStockUpdate,
)
from app.services.auth import OrderBoardScope, resolve_order_board_scope

logger = logging.getLogger(__name__)


def kitchen_scope(
    db: Session,
    user: User,
    *,
    restaurant_id: uuid.UUID | None,
    location_id: uuid.UUID | None,
) -> OrderBoardScope:
    scope = resolve_order_board_scope(
        db,
        user,
        requested_restaurant_id=restaurant_id,
        requested_restaurant_location_id=location_id,
    )
    # An ADMIN who named no restaurant has the whole platform as a board; a
    # menu has no such meaning. Same answer as every tenant-scoped screen.
    if scope.restaurant_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="restaurant_id is required for admin menu requests",
        )
    return scope


def _in_scope(query, scope: OrderBoardScope):
    query = query.where(MenuItem.restaurant_id == scope.restaurant_id)
    if scope.restaurant_location_id is not None:
        query = query.where(MenuItem.restaurant_location_id == scope.restaurant_location_id)
    return query


def _serialize(dish: MenuItem, branch_name: str) -> KitchenMenuItemResponse:
    return KitchenMenuItemResponse(
        id=dish.id,
        name=dish.name,
        category=dish.category,
        is_veg=dish.is_veg,
        restaurant_location_id=dish.restaurant_location_id,
        branch_name=branch_name,
        is_available=dish.is_available,
        out_of_stock=dish.out_of_stock,
        stock_quantity=dish.stock_quantity,
        stock_daily_quantity=dish.stock_daily_quantity,
        is_on_sale=dish.is_on_sale,
        # Only sizes a customer can pick: a retired size has no stock to keep.
        sizes=[
            KitchenMenuSizeResponse(
                id=size.id,
                name=size.name,
                stock_quantity=size.stock_quantity,
                stock_daily_quantity=size.stock_daily_quantity,
            )
            for size in sorted(dish.sizes or [], key=lambda s: (s.sort_order, s.name))
            if size.is_active
        ],
        updated_at=dish.updated_at,
    )


def list_kitchen_menu(db: Session, scope: OrderBoardScope) -> list[KitchenMenuItemResponse]:
    """Every dish in scope, INCLUDING ones the owner switched off — a cook
    must be able to see a dish to know it is missing from the storefront."""

    rows = db.execute(
        _in_scope(
            select(MenuItem, RestaurantLocation.branch_name)
            .join(RestaurantLocation, RestaurantLocation.id == MenuItem.restaurant_location_id)
            .options(selectinload(MenuItem.sizes)),
            scope,
        ).order_by(RestaurantLocation.branch_name, MenuItem.category, MenuItem.name)
    ).all()
    return [_serialize(dish, branch) for dish, branch in rows]


def _dish_in_scope(db: Session, scope: OrderBoardScope, menu_item_id: uuid.UUID) -> tuple[MenuItem, str]:
    row = db.execute(
        _in_scope(
            select(MenuItem, RestaurantLocation.branch_name)
            .join(RestaurantLocation, RestaurantLocation.id == MenuItem.restaurant_location_id)
            .options(selectinload(MenuItem.sizes))
            .where(MenuItem.id == menu_item_id),
            scope,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu item not found")
    return row[0], row[1]


def update_dish_stock(
    db: Session,
    scope: OrderBoardScope,
    user: User,
    menu_item_id: uuid.UUID,
    payload: KitchenStockUpdate,
) -> KitchenMenuItemResponse:
    dish, branch = _dish_in_scope(db, scope, menu_item_id)
    sent = payload.model_fields_set
    if "out_of_stock" in sent and payload.out_of_stock is not None:
        dish.out_of_stock = payload.out_of_stock
    if "stock_quantity" in sent:
        dish.stock_quantity = payload.stock_quantity
    if "stock_daily_quantity" in sent:
        dish.stock_daily_quantity = payload.stock_daily_quantity
    db.commit()
    db.refresh(dish)
    # No history table records stock yet; the log says who, so a "who marked
    # this sold out?" can at least be answered from the server.
    logger.info(
        "Kitchen stock change menu_item_id=%s by user_id=%s role=%s fields=%s",
        dish.id, user.id, user.role.value, sorted(sent),
    )
    return _serialize(dish, branch)


def update_size_stock(
    db: Session,
    scope: OrderBoardScope,
    user: User,
    menu_item_id: uuid.UUID,
    size_id: uuid.UUID,
    payload: KitchenSizeStockUpdate,
) -> KitchenMenuItemResponse:
    dish, branch = _dish_in_scope(db, scope, menu_item_id)
    size = next((s for s in dish.sizes or [] if s.id == size_id), None)
    if size is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Size not found")
    sent = payload.model_fields_set
    if "stock_quantity" in sent:
        size.stock_quantity = payload.stock_quantity
    if "stock_daily_quantity" in sent:
        size.stock_daily_quantity = payload.stock_daily_quantity
    db.commit()
    db.refresh(dish)
    logger.info(
        "Kitchen size stock change menu_item_id=%s size_id=%s by user_id=%s role=%s fields=%s",
        dish.id, size.id, user.id, user.role.value, sorted(sent),
    )
    return _serialize(dish, branch)

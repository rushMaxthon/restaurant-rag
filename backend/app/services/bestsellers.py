from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Iterable, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import OrderStatus, PaymentStatus
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.services.cache import cache_delete, cache_get_json, cache_set_json

settings = get_settings()

BESTSELLER_CACHE_PREFIX = "bestsellers:location"
BESTSELLER_DYNAMIC_ATTR = "_dynamic_bestseller_flag"
VALID_ORDER_COUNT_DYNAMIC_ATTR = "_recent_valid_order_count"


def _bestseller_cache_key(location_id: uuid.UUID) -> str:
    return f"{BESTSELLER_CACHE_PREFIX}:{location_id}"


def _coerce_uuid_list(values: Iterable[str] | None) -> list[uuid.UUID]:
    normalized: list[uuid.UUID] = []
    for value in values or []:
        try:
            normalized.append(uuid.UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return normalized


def _valid_bestseller_statuses() -> tuple[OrderStatus, ...]:
    allowed = {
        OrderStatus.ACCEPTED,
        OrderStatus.PREPARING,
        OrderStatus.OUT_FOR_DELIVERY,
        OrderStatus.DELIVERED,
    }
    configured: list[OrderStatus] = []
    for raw_value in settings.bestseller_counted_statuses_list:
        try:
            parsed = OrderStatus(raw_value)
        except ValueError:
            continue
        if parsed in allowed:
            configured.append(parsed)
    if configured:
        return tuple(dict.fromkeys(configured))
    return tuple(allowed)


def get_menu_item_featured_flag(menu_item: MenuItem) -> bool:
    return bool(getattr(menu_item, "is_bestseller", False))


def is_menu_item_bestseller(menu_item: MenuItem) -> bool:
    cached_flag = getattr(menu_item, BESTSELLER_DYNAMIC_ATTR, None)
    if cached_flag is None:
        return False
    return bool(cached_flag)


def get_menu_item_recent_valid_order_count(menu_item: MenuItem) -> int:
    cached_count = getattr(menu_item, VALID_ORDER_COUNT_DYNAMIC_ATTR, None)
    if cached_count is None:
        return 0
    return int(cached_count)


def invalidate_bestseller_cache_for_location(location_id: uuid.UUID | None) -> None:
    if location_id is None:
        return
    cache_delete(_bestseller_cache_key(location_id))


def invalidate_bestseller_cache_for_locations(location_ids: Iterable[uuid.UUID | None]) -> None:
    keys = [_bestseller_cache_key(location_id) for location_id in location_ids if location_id is not None]
    if not keys:
        return
    cache_delete(*keys)


def invalidate_all_bestseller_caches() -> None:
    from app.services.cache import cache_delete_pattern

    cache_delete_pattern(f"{BESTSELLER_CACHE_PREFIX}:*")


def _compute_dynamic_bestseller_ids(
    db: Session,
    location_ids: Sequence[uuid.UUID],
) -> dict[uuid.UUID, list[uuid.UUID]]:
    if not location_ids:
        return {}

    window_days = max(settings.bestseller_window_days, 0)
    min_valid_orders = max(settings.bestseller_min_valid_orders, 1)
    top_item_count = max(settings.bestseller_top_item_count, 0)
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    counted_statuses = _valid_bestseller_statuses()
    valid_payment_statuses = (PaymentStatus.PAID,)

    order_count = func.count(OrderItem.id).label("order_count")
    ordered_quantity = func.coalesce(func.sum(OrderItem.quantity), 0).label("ordered_quantity")

    rows = db.execute(
        select(
            MenuItem.restaurant_location_id.label("location_id"),
            OrderItem.menu_item_id.label("menu_item_id"),
            MenuItem.name.label("item_name"),
            order_count,
            ordered_quantity,
        )
        .join(Order, OrderItem.order_id == Order.id)
        .join(MenuItem, OrderItem.menu_item_id == MenuItem.id)
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .join(RestaurantLocation, MenuItem.restaurant_location_id == RestaurantLocation.id)
        .where(
            MenuItem.restaurant_location_id.in_(location_ids),
            Order.restaurant_location_id == MenuItem.restaurant_location_id,
            Order.status.in_(counted_statuses),
            Order.payment_status.in_(valid_payment_statuses),
            Order.placed_at >= cutoff,
            MenuItem.is_available.is_(True),
            Restaurant.is_active.is_(True),
            Restaurant.is_approved.is_(True),
            RestaurantLocation.is_active.is_(True),
        )
        .group_by(
            MenuItem.restaurant_location_id,
            OrderItem.menu_item_id,
            MenuItem.name,
        )
        .having(order_count >= min_valid_orders)
        .order_by(
            MenuItem.restaurant_location_id.asc(),
            order_count.desc(),
            ordered_quantity.desc(),
            MenuItem.name.asc(),
        )
    ).all()

    by_location: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for row in rows:
        location_id = row.location_id
        if top_item_count > 0 and len(by_location[location_id]) >= top_item_count:
            continue
        by_location[location_id].append(row.menu_item_id)

    return {location_id: item_ids for location_id, item_ids in by_location.items()}


def get_dynamic_bestseller_ids_by_location(
    db: Session,
    location_ids: Iterable[uuid.UUID | None],
) -> dict[uuid.UUID, set[uuid.UUID]]:
    requested_ids = {location_id for location_id in location_ids if location_id is not None}
    if not requested_ids:
        return {}

    resolved: dict[uuid.UUID, set[uuid.UUID]] = {}
    missing: list[uuid.UUID] = []

    for location_id in requested_ids:
        cached_payload = cache_get_json(_bestseller_cache_key(location_id))
        if isinstance(cached_payload, dict):
            resolved[location_id] = set(_coerce_uuid_list(cached_payload.get("menu_item_ids")))
            continue
        missing.append(location_id)

    if missing:
        computed = _compute_dynamic_bestseller_ids(db, missing)
        ttl_seconds = max(settings.bestseller_cache_ttl_seconds, 1)
        for location_id in missing:
            item_ids = computed.get(location_id, [])
            cache_set_json(
                _bestseller_cache_key(location_id),
                {"menu_item_ids": [str(item_id) for item_id in item_ids]},
                ttl_seconds=ttl_seconds,
            )
            resolved[location_id] = set(item_ids)

    for location_id in requested_ids:
        resolved.setdefault(location_id, set())

    return resolved


def hydrate_dynamic_bestseller_flags(
    db: Session,
    menu_items: Iterable[MenuItem],
) -> list[MenuItem]:
    items = list(menu_items)
    if not items:
        return items

    bestseller_map = get_dynamic_bestseller_ids_by_location(
        db,
        [item.restaurant_location_id for item in items],
    )
    for item in items:
        location_bestsellers = bestseller_map.get(item.restaurant_location_id, set())
        setattr(item, BESTSELLER_DYNAMIC_ATTR, item.id in location_bestsellers)
    return items


def hydrate_recent_valid_order_counts(
    db: Session,
    menu_items: Iterable[MenuItem],
) -> list[MenuItem]:
    items = list(menu_items)
    if not items:
        return items

    window_days = max(settings.bestseller_window_days, 0)
    cutoff = datetime.now(UTC) - timedelta(days=window_days)
    counted_statuses = _valid_bestseller_statuses()
    valid_payment_statuses = (PaymentStatus.PAID,)
    item_ids = [item.id for item in items]

    rows = db.execute(
        select(
            OrderItem.menu_item_id,
            func.count(OrderItem.id).label("valid_order_count"),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .join(MenuItem, OrderItem.menu_item_id == MenuItem.id)
        .where(
            OrderItem.menu_item_id.in_(item_ids),
            Order.restaurant_location_id == MenuItem.restaurant_location_id,
            Order.status.in_(counted_statuses),
            Order.payment_status.in_(valid_payment_statuses),
            Order.placed_at >= cutoff,
        )
        .group_by(OrderItem.menu_item_id)
    ).all()

    counts = {row.menu_item_id: int(row.valid_order_count or 0) for row in rows}
    for item in items:
        setattr(item, VALID_ORDER_COUNT_DYNAMIC_ATTR, counts.get(item.id, 0))
    return items

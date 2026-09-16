from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from collections.abc import Callable, Sequence
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.config.celery import celery_app
from app.api.deps import AppScopeDep, ensure_restaurant_readable
from app.config.database import get_db
from app.models.enums import UserRole
from app.models.menu_item_customization_group import MenuItemCustomizationGroup
from app.models.menu_item_customization_option import MenuItemCustomizationOption
from app.models.menu_item import MenuItem
from app.models.menu_item_size import MenuItemSize
from app.models.restaurant import Restaurant
from app.models.user import User
from app.schemas.menu_item import (
    MenuItemCustomizationGroupPayload,
    MenuItemCustomizationOptionPayload,
    MenuItemAvailabilityUpdate,
    MenuItemBulkCreate,
    MenuItemBulkCreateResponse,
    MenuItemBulkSkippedLocation,
    MenuItemCreate,
    MenuItemRequestBase,
    MenuItemResponse,
    MenuItemSizePayload,
    MenuItemUpdate,
)
from app.services.order_events import actor_for_user, record_menu_availability_event
from app.services.auth import get_current_user, get_current_user_optional, resolve_owner_restaurant_id
from app.services.bestsellers import (
    hydrate_dynamic_bestseller_flags,
    hydrate_recent_valid_order_counts,
    invalidate_bestseller_cache_for_locations,
)
from app.services.cache import cache_delete_pattern
from app.services.favorites import get_user_favorite_ids, serialize_menu_item, serialize_menu_items
from app.services.generated_combos import refresh_generated_combo_availability
from app.services.personalized_offers import invalidate_all_personalized_offer_caches
from app.services.recommendations import invalidate_all_recommendation_caches
from app.services.restaurant_locations import (
    require_location_for_restaurant,
    resolve_location_for_restaurant,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/menu-items", tags=["Menu Items"])


def _menu_item_load_options():
    return (
        selectinload(MenuItem.restaurant_location),
        selectinload(MenuItem.sizes)
        .selectinload(MenuItemSize.customization_groups)
        .selectinload(MenuItemCustomizationGroup.options),
        selectinload(MenuItem.customization_groups).selectinload(
            MenuItemCustomizationGroup.options
        ),
    )


def _invalidate_discovery_caches() -> None:
    invalidate_all_recommendation_caches()
    invalidate_all_personalized_offer_caches()
    cache_delete_pattern("rag:response:*")


def _resolve_featured_flag(payload: MenuItemRequestBase) -> bool:
    # Legacy compatibility: older clients may still send featured fields,
    # but the manual featured-item behavior has been retired.
    _ = payload
    return False


def _get_manageable_restaurant(db: Session, restaurant_id: uuid.UUID, current_user: User) -> Restaurant:
    query = select(Restaurant).where(Restaurant.id == restaurant_id)
    if current_user.role == UserRole.ADMIN:
        restaurant = db.scalar(query)
    elif current_user.role == UserRole.OWNER:
        restaurant = db.scalar(query.where(Restaurant.owner_id == current_user.id, Restaurant.is_active.is_(True)))
    else:
        restaurant = None
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found for this user")
    return restaurant


def _get_manageable_menu_item(db: Session, menu_item_id: uuid.UUID, current_user: User) -> MenuItem:
    query = (
        select(MenuItem)
        .options(*_menu_item_load_options())
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .where(MenuItem.id == menu_item_id)
    )
    if current_user.role == UserRole.ADMIN:
        menu_item = db.scalar(query)
    elif current_user.role == UserRole.OWNER:
        menu_item = db.scalar(query.where(Restaurant.owner_id == current_user.id, Restaurant.is_active.is_(True)))
    else:
        menu_item = None
    if menu_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu item not found for this user")
    return menu_item


def _queue_embedding_job(menu_item_id: uuid.UUID) -> None:
    try:
        celery_app.send_task("app.tasks.embed.embed_menu_item", args=[str(menu_item_id)])
    except Exception:
        logger.exception("Failed to queue embedding task for menu item %s", menu_item_id)


def _resolve_manageable_location_id(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID | None,
) -> uuid.UUID:
    location = resolve_location_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        location_id=location_id,
        include_inactive=True,
    )
    if location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant location not found")
    return location.id


_Row = TypeVar("_Row")
_Payload = TypeVar("_Payload")


def _match_existing_rows(
    existing: Sequence[_Row],
    payloads: Sequence[_Payload],
    *,
    name_of: Callable[[_Row], str],
    payload_name_of: Callable[[_Payload], str],
    payload_id_of: Callable[[_Payload], uuid.UUID | None],
) -> tuple[list[_Row | None], list[_Row]]:
    """Pair each payload with the row it is editing, if any.

    Two passes on purpose. Ids win, because they say exactly which row the
    owner had in front of them and they survive a rename. Whatever is left is
    then matched by name, which is all an older client can offer -- and is
    right far more often than not, since most saves move a price or a cap
    rather than a name.

    Returns the row chosen for each payload, in payload order, alongside the
    rows nothing claimed. Those are the deletions.
    """
    unclaimed = list(existing)
    by_id = {row.id: row for row in unclaimed}
    matched: list[_Row | None] = [None] * len(payloads)

    for index, payload in enumerate(payloads):
        wanted = payload_id_of(payload)
        row = by_id.get(wanted) if wanted is not None else None
        if row is not None and row in unclaimed:
            matched[index] = row
            unclaimed.remove(row)

    by_name: dict[str, list[_Row]] = {}
    for row in unclaimed:
        by_name.setdefault(name_of(row).strip().casefold(), []).append(row)
    for index, payload in enumerate(payloads):
        if matched[index] is not None:
            continue
        candidates = by_name.get(payload_name_of(payload).strip().casefold())
        if candidates:
            row = candidates.pop(0)
            matched[index] = row
            unclaimed.remove(row)

    return matched, unclaimed


def _apply_customization_option(
    option: MenuItemCustomizationOption,
    payload: MenuItemCustomizationOptionPayload,
) -> MenuItemCustomizationOption:
    option.name = payload.name.strip()
    option.extra_price = payload.extra_price
    option.is_active = payload.is_active
    option.is_countable = payload.is_countable
    option.sort_order = payload.sort_order
    return option


def _build_customization_option(
    payload: MenuItemCustomizationOptionPayload,
) -> MenuItemCustomizationOption:
    return _apply_customization_option(MenuItemCustomizationOption(), payload)


def _sync_customization_options(
    group: MenuItemCustomizationGroup,
    payloads: Sequence[MenuItemCustomizationOptionPayload],
) -> None:
    matched, removed = _match_existing_rows(
        list(group.options),
        payloads,
        name_of=lambda option: option.name,
        payload_name_of=lambda option_payload: option_payload.name,
        payload_id_of=lambda option_payload: option_payload.id,
    )
    for option in removed:
        group.options.remove(option)
    for row, option_payload in zip(matched, payloads):
        if row is None:
            group.options.append(_build_customization_option(option_payload))
        else:
            _apply_customization_option(row, option_payload)


def _apply_customization_group(
    group: MenuItemCustomizationGroup,
    payload: MenuItemCustomizationGroupPayload,
    *,
    menu_item: MenuItem,
    menu_item_size: MenuItemSize | None,
) -> MenuItemCustomizationGroup:
    group.menu_item = menu_item
    group.menu_item_size = menu_item_size
    group.title = payload.title.strip()
    group.selection_type = payload.selection_type
    group.is_required = payload.is_required
    group.min_selection = payload.min_selection
    group.max_selection = payload.max_selection
    # Whether the kitchen can split these options across halves.
    group.supports_halves = payload.supports_halves
    group.is_active = payload.is_active
    group.sort_order = payload.sort_order
    _sync_customization_options(group, payload.options)
    return group


def _resolve_effective_menu_item_price(payload: MenuItemRequestBase):
    if not payload.has_sizes:
        return payload.price
    active_prices = [size.price for size in payload.sizes if size.is_active]
    if active_prices:
        return min(active_prices)
    return payload.price


def _sync_menu_item_customizations(
    menu_item: MenuItem,
    payload: MenuItemRequestBase,
) -> None:
    """Bring an item's sizes and customizations in line with what was saved.

    Rows are matched to the payload and updated in place. This used to clear
    both collections and rebuild them, which read as equivalent - same names,
    same prices - and was not: every id changed. Carts live in the customer's
    browser for days holding `menu_item_size_id` and `option_id`, and
    `resolve_menu_item_selection` refuses ids it cannot find, so an owner
    correcting a price broke every cart already holding that dish, and the only
    way out was for the customer to delete the line. The screen just said "The
    selected size is unavailable".

    Matching is by id where the client sends one, then by name. Two things
    still lose their id, both deliberately: a row renamed by a client that does
    not send ids, and a group moved between the item and a size - it is a
    different group in a different place.
    """
    menu_item.has_sizes = payload.has_sizes
    menu_item.has_customizations = payload.has_customizations
    menu_item.price = _resolve_effective_menu_item_price(payload)

    # Which size each group belongs to, read now, before any size is removed.
    # `menu_item_size` is a lazy many-to-one: reading it later could emit a
    # query, and a query autoflushes - half-applied, with sizes already marked
    # for deletion and their groups cascading away underneath this loop.
    scope_of = {group: group.menu_item_size for group in menu_item.customization_groups}

    size_payloads = list(payload.sizes) if payload.has_sizes else []
    matched_sizes, removed_sizes = _match_existing_rows(
        list(menu_item.sizes),
        size_payloads,
        name_of=lambda size: size.name,
        payload_name_of=lambda size_payload: size_payload.name,
        payload_id_of=lambda size_payload: size_payload.id,
    )
    for size in removed_sizes:
        menu_item.sizes.remove(size)

    live_sizes: list[tuple[MenuItemSize, MenuItemSizePayload]] = []
    for matched_size, size_payload in zip(matched_sizes, size_payloads):
        size = matched_size
        if size is None:
            size = MenuItemSize()
            menu_item.sizes.append(size)
        size.name = size_payload.name.strip()
        size.price = size_payload.price
        size.is_active = size_payload.is_active
        size.sort_order = size_payload.sort_order
        live_sizes.append((size, size_payload))

    # Groups are scoped: one set hangs off the item, one off each size, and
    # "Toppings" on the Large is not "Toppings" on the Small. Reconciling them
    # in a single pool would let those two swap rows on a save.
    wanted: list[tuple[MenuItemSize | None, MenuItemCustomizationGroupPayload]] = []
    if payload.has_customizations:
        wanted.extend((None, group) for group in payload.customization_groups)
        for size, size_payload in live_sizes:
            wanted.extend((size, group) for group in size_payload.customization_groups)

    scopes: list[MenuItemSize | None] = [None, *(size for size, _ in live_sizes)]
    keep: list[MenuItemCustomizationGroup] = []
    for scope in scopes:
        here = [g for g in menu_item.customization_groups if scope_of.get(g) is scope]
        group_payloads = [group for owner, group in wanted if owner is scope]
        matched_groups, removed_groups = _match_existing_rows(
            here,
            group_payloads,
            name_of=lambda group: group.title,
            payload_name_of=lambda group_payload: group_payload.title,
            payload_id_of=lambda group_payload: group_payload.id,
        )
        for group in removed_groups:
            menu_item.customization_groups.remove(group)
        for matched_group, group_payload in zip(matched_groups, group_payloads):
            group = matched_group
            if group is None:
                # Not appended here: _apply_customization_group sets
                # `group.menu_item`, and the back-reference does the appending.
                # Doing both listed every new group twice.
                group = MenuItemCustomizationGroup()
            _apply_customization_group(
                group,
                group_payload,
                menu_item=menu_item,
                menu_item_size=scope,
            )
            keep.append(group)

    # Whatever is left belonged to a scope that no longer exists -- a deleted
    # size, or a group the payload moved elsewhere. Sizes cascade on delete,
    # but their groups are on the item too, so they need removing here.
    kept = set(keep)
    for group in [g for g in menu_item.customization_groups if g not in kept]:
        menu_item.customization_groups.remove(group)


def _reload_menu_item_for_response(db: Session, menu_item_id: uuid.UUID) -> MenuItem:
    menu_item = db.scalar(
        select(MenuItem)
        .options(*_menu_item_load_options())
        .where(MenuItem.id == menu_item_id)
    )
    if menu_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu item not found")
    return menu_item


@router.post("", response_model=MenuItemResponse, status_code=status.HTTP_201_CREATED)
def create_menu_item(
    payload: MenuItemCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MenuItemResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to manage menu items")
    if current_user.role == UserRole.OWNER:
        owner_restaurant_id = resolve_owner_restaurant_id(db, current_user)
        if payload.restaurant_id != owner_restaurant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Owners can only manage menu items for their own restaurant",
            )

    _get_manageable_restaurant(db, payload.restaurant_id, current_user)
    menu_item = MenuItem(
        restaurant_id=payload.restaurant_id,
        restaurant_location_id=_resolve_manageable_location_id(
            db,
            restaurant_id=payload.restaurant_id,
            location_id=payload.restaurant_location_id,
        ),
        name=payload.name,
        category=payload.category,
        cuisine_type=payload.cuisine_type,
        description=payload.description,
        is_veg=payload.is_veg,
        is_available=payload.is_available,
        is_bestseller=_resolve_featured_flag(payload),
        image_url=payload.image_url,
        launched_at=payload.launched_at or datetime.now(UTC),
        is_new_launch=payload.is_new_launch,
    )
    _sync_menu_item_customizations(menu_item, payload)
    db.add(menu_item)
    db.commit()
    menu_item = _reload_menu_item_for_response(db, menu_item.id)

    _invalidate_discovery_caches()
    invalidate_bestseller_cache_for_locations([menu_item.restaurant_location_id])
    refresh_generated_combo_availability(
        db,
        restaurant_id=menu_item.restaurant_id,
        restaurant_location_id=menu_item.restaurant_location_id,
    )
    _queue_embedding_job(menu_item.id)
    hydrate_dynamic_bestseller_flags(db, [menu_item])
    hydrate_recent_valid_order_counts(db, [menu_item])
    return serialize_menu_item(menu_item)


@router.post("/bulk", response_model=MenuItemBulkCreateResponse, status_code=status.HTTP_201_CREATED)
def create_menu_item_bulk(
    payload: MenuItemBulkCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MenuItemBulkCreateResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to manage menu items")
    if current_user.role == UserRole.OWNER:
        owner_restaurant_id = resolve_owner_restaurant_id(db, current_user)
        if payload.restaurant_id != owner_restaurant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Owners can only manage menu items for their own restaurant",
            )

    _get_manageable_restaurant(db, payload.restaurant_id, current_user)
    location_ids = list(dict.fromkeys(payload.restaurant_location_ids))
    locations = [
        require_location_for_restaurant(
            db,
            restaurant_id=payload.restaurant_id,
            location_id=location_id,
            include_inactive=True,
        )
        for location_id in location_ids
    ]

    item_name = payload.name.strip()
    conflicting_location_ids = set(
        db.scalars(
            select(MenuItem.restaurant_location_id).where(
                MenuItem.restaurant_id == payload.restaurant_id,
                MenuItem.restaurant_location_id.in_(location_ids),
                func.lower(func.trim(MenuItem.name)) == item_name.lower(),
            )
        ).all()
    )
    conflicting = [location for location in locations if location.id in conflicting_location_ids]
    creatable = [location for location in locations if location.id not in conflicting_location_ids]

    if conflicting and not payload.skip_duplicates:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    f"'{item_name}' already exists at: "
                    f"{', '.join(location.branch_name for location in conflicting)}."
                ),
                "conflicting_location_ids": [str(location.id) for location in conflicting],
            },
        )
    if not creatable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": f"'{item_name}' already exists at every selected location.",
                "conflicting_location_ids": [str(location.id) for location in conflicting],
            },
        )

    launched_at = payload.launched_at or datetime.now(UTC)
    created_items: list[MenuItem] = []
    for location in creatable:
        menu_item = MenuItem(
            restaurant_id=payload.restaurant_id,
            restaurant_location_id=location.id,
            name=payload.name,
            category=payload.category,
            cuisine_type=payload.cuisine_type,
            description=payload.description,
            is_veg=payload.is_veg,
            is_available=payload.is_available,
            is_bestseller=_resolve_featured_flag(payload),
            image_url=payload.image_url,
            launched_at=launched_at,
            is_new_launch=payload.is_new_launch,
        )
        _sync_menu_item_customizations(menu_item, payload)
        db.add(menu_item)
        created_items.append(menu_item)
    db.commit()
    menu_items = [_reload_menu_item_for_response(db, item.id) for item in created_items]

    _invalidate_discovery_caches()
    invalidate_bestseller_cache_for_locations([item.restaurant_location_id for item in menu_items])
    for item in menu_items:
        refresh_generated_combo_availability(
            db,
            restaurant_id=item.restaurant_id,
            restaurant_location_id=item.restaurant_location_id,
        )
        _queue_embedding_job(item.id)
    hydrate_dynamic_bestseller_flags(db, menu_items)
    hydrate_recent_valid_order_counts(db, menu_items)
    return MenuItemBulkCreateResponse(
        created=[serialize_menu_item(item) for item in menu_items],
        skipped=[
            MenuItemBulkSkippedLocation(
                restaurant_location_id=location.id,
                restaurant_location_name=location.branch_name,
            )
            for location in conflicting
        ],
    )


@router.get("", response_model=list[MenuItemResponse])
def list_menu_items(
    db: Annotated[Session, Depends(get_db)],
    app_scope: AppScopeDep,
    restaurant_id: uuid.UUID = Query(...),
    location_id: uuid.UUID | None = Query(default=None),
    include_unavailable: bool = Query(default=False),
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> list[MenuItemResponse]:
    ensure_restaurant_readable(app_scope, restaurant_id)
    if current_user is not None and current_user.role == UserRole.OWNER:
        owner_restaurant_id = resolve_owner_restaurant_id(db, current_user)
        if restaurant_id != owner_restaurant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Owners can only access menu items for their own restaurant",
            )

    if current_user is not None and current_user.role == UserRole.ADMIN:
        restaurant = db.scalar(select(Restaurant).where(Restaurant.id == restaurant_id))
    else:
        restaurant = db.scalar(
            select(Restaurant).where(Restaurant.id == restaurant_id, Restaurant.is_active.is_(True))
        )
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    admin_can_view_all = current_user is not None and current_user.role == UserRole.ADMIN
    owner_can_view_all = (
        current_user is not None and current_user.role == UserRole.OWNER and restaurant.owner_id == current_user.id
    )
    location = resolve_location_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        location_id=location_id,
        include_inactive=admin_can_view_all or owner_can_view_all,
    )
    if location_id is not None and location is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant location not found")
    if location is None and not (admin_can_view_all or owner_can_view_all):
        return []

    query: Select[tuple[MenuItem]] = (
        select(MenuItem)
        .options(*_menu_item_load_options())
        .where(MenuItem.restaurant_id == restaurant_id)
    )
    if location is not None:
        query = query.where(MenuItem.restaurant_location_id == location.id)

    if admin_can_view_all:
        if not include_unavailable:
            query = query.where(MenuItem.is_available.is_(True))
    elif not owner_can_view_all:
        if not restaurant.is_approved:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
        if location is None or not location.is_active:
            return []
        query = query.where(MenuItem.is_available.is_(True))
    elif not include_unavailable:
        query = query.where(MenuItem.is_available.is_(True))

    menu_items = db.scalars(query.order_by(MenuItem.category.asc(), MenuItem.name.asc())).all()
    hydrate_dynamic_bestseller_flags(db, menu_items)
    hydrate_recent_valid_order_counts(db, menu_items)
    favorite_ids = get_user_favorite_ids(db, current_user, menu_item_ids=[menu_item.id for menu_item in menu_items])
    return serialize_menu_items(menu_items, favorite_ids=favorite_ids)


@router.get("/{menu_item_id}", response_model=MenuItemResponse)
def get_menu_item(
    menu_item_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    app_scope: AppScopeDep,
    current_user: Annotated[User | None, Depends(get_current_user_optional)] = None,
) -> MenuItemResponse:
    query = (
        select(MenuItem)
        .options(*_menu_item_load_options())
        .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
        .where(MenuItem.id == menu_item_id)
    )
    if current_user is not None and current_user.role == UserRole.ADMIN:
        menu_item = db.scalar(query)
    elif current_user is not None and current_user.role == UserRole.OWNER:
        menu_item = db.scalar(query.where(Restaurant.owner_id == current_user.id, Restaurant.is_active.is_(True)))
    else:
        menu_item = db.scalar(
            query.where(
                Restaurant.is_active.is_(True),
                Restaurant.is_approved.is_(True),
                MenuItem.is_available.is_(True),
            )
        )
        if menu_item is not None and not menu_item.restaurant_location.is_active:
            menu_item = None
    if menu_item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Menu item not found")

    ensure_restaurant_readable(app_scope, menu_item.restaurant_id)

    hydrate_dynamic_bestseller_flags(db, [menu_item])
    hydrate_recent_valid_order_counts(db, [menu_item])
    favorite_ids = get_user_favorite_ids(db, current_user, menu_item_ids=[menu_item.id])
    return serialize_menu_item(menu_item, favorite_ids=favorite_ids)


@router.put("/{menu_item_id}", response_model=MenuItemResponse)
def update_menu_item(
    menu_item_id: uuid.UUID,
    payload: MenuItemUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MenuItemResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to manage menu items")
    menu_item = _get_manageable_menu_item(db, menu_item_id, current_user)
    previous_location_id = menu_item.restaurant_location_id

    menu_item.restaurant_location_id = _resolve_manageable_location_id(
        db,
        restaurant_id=menu_item.restaurant_id,
        location_id=payload.restaurant_location_id or menu_item.restaurant_location_id,
    )
    menu_item.name = payload.name
    menu_item.category = payload.category
    menu_item.cuisine_type = payload.cuisine_type
    menu_item.description = payload.description
    menu_item.is_veg = payload.is_veg
    previous_available = menu_item.is_available
    menu_item.is_available = payload.is_available
    record_menu_availability_event(
        db,
        menu_item=menu_item,
        is_available=payload.is_available,
        previous_available=previous_available,
        actor=actor_for_user(current_user),
        actor_user_id=current_user.id,
    )
    menu_item.is_bestseller = _resolve_featured_flag(payload)
    menu_item.image_url = payload.image_url
    menu_item.is_new_launch = payload.is_new_launch
    if payload.launched_at is not None:
        menu_item.launched_at = payload.launched_at
    _sync_menu_item_customizations(menu_item, payload)

    db.add(menu_item)
    db.commit()
    menu_item = _reload_menu_item_for_response(db, menu_item.id)
    _invalidate_discovery_caches()
    invalidate_bestseller_cache_for_locations([previous_location_id, menu_item.restaurant_location_id])
    refresh_generated_combo_availability(
        db,
        restaurant_id=menu_item.restaurant_id,
        restaurant_location_id=menu_item.restaurant_location_id,
        menu_item_id=menu_item.id,
    )
    _queue_embedding_job(menu_item.id)
    hydrate_dynamic_bestseller_flags(db, [menu_item])
    hydrate_recent_valid_order_counts(db, [menu_item])
    return serialize_menu_item(menu_item)


@router.patch("/{menu_item_id}/availability", response_model=MenuItemResponse)
def update_menu_item_availability(
    menu_item_id: uuid.UUID,
    payload: MenuItemAvailabilityUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MenuItemResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to manage menu items")
    menu_item = _get_manageable_menu_item(db, menu_item_id, current_user)
    affected_location_id = menu_item.restaurant_location_id
    previous_available = menu_item.is_available
    menu_item.is_available = payload.is_available

    # Records the switch-off/switch-on so a later sales dip can be told apart
    # from lost demand. A no-op when the value did not actually change.
    record_menu_availability_event(
        db,
        menu_item=menu_item,
        is_available=payload.is_available,
        previous_available=previous_available,
        actor=actor_for_user(current_user),
        actor_user_id=current_user.id,
    )

    db.add(menu_item)
    db.commit()
    db.refresh(menu_item)
    _invalidate_discovery_caches()
    invalidate_bestseller_cache_for_locations([affected_location_id])
    refresh_generated_combo_availability(
        db,
        restaurant_id=menu_item.restaurant_id,
        restaurant_location_id=menu_item.restaurant_location_id,
        menu_item_id=menu_item.id,
    )
    hydrate_dynamic_bestseller_flags(db, [menu_item])
    hydrate_recent_valid_order_counts(db, [menu_item])
    return serialize_menu_item(menu_item)


@router.delete("/{menu_item_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_menu_item(
    menu_item_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have permission to manage menu items")

    menu_item = _get_manageable_menu_item(db, menu_item_id, current_user)
    restaurant_id = menu_item.restaurant_id
    restaurant_location_id = menu_item.restaurant_location_id
    db.delete(menu_item)
    db.commit()
    _invalidate_discovery_caches()
    invalidate_bestseller_cache_for_locations([restaurant_location_id])
    refresh_generated_combo_availability(
        db,
        restaurant_id=restaurant_id,
        restaurant_location_id=restaurant_location_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

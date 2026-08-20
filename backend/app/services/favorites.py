from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.models.favorite import Favorite
from app.models.menu_item import MenuItem
from app.models.menu_item_customization_group import MenuItemCustomizationGroup
from app.models.menu_item_customization_option import MenuItemCustomizationOption
from app.models.menu_item_size import MenuItemSize
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.schemas.chat import ChatSuggestionItem
from app.schemas.favorite import FavoriteItemResponse
from app.schemas.generated_combo import GeneratedComboItemSummary
from app.schemas.menu_item import (
    MenuItemCustomizationGroupResponse,
    MenuItemCustomizationOptionResponse,
    MenuItemResponse,
    MenuItemSizeResponse,
)
from app.schemas.recommendation import RecommendationItemResponse
from app.services.bestsellers import (
    get_menu_item_featured_flag,
    get_menu_item_recent_valid_order_count,
    hydrate_dynamic_bestseller_flags,
    is_menu_item_bestseller,
)
from app.config import get_settings
from app.services.recommendations import invalidate_user_recommendation_cache
from app.services.menu_item_metadata import (
    build_generic_menu_item_badge_metadata,
    get_new_item_reason,
    is_menu_item_new,
    resolve_menu_item_launch_timestamp,
)

logger = logging.getLogger(__name__)
settings = get_settings()


def _serialize_menu_item_customization_option(
    option: MenuItemCustomizationOption,
) -> MenuItemCustomizationOptionResponse:
    return MenuItemCustomizationOptionResponse(
        id=option.id,
        name=option.name,
        extra_price=option.extra_price,
        is_active=option.is_active,
        is_countable=option.is_countable,
        sort_order=option.sort_order,
    )


def _serialize_menu_item_customization_group(
    group: MenuItemCustomizationGroup,
) -> MenuItemCustomizationGroupResponse:
    sorted_options = sorted(
        group.options,
        key=lambda option: (option.sort_order, option.name.lower(), str(option.id)),
    )
    return MenuItemCustomizationGroupResponse(
        id=group.id,
        menu_item_size_id=group.menu_item_size_id,
        title=group.title,
        selection_type=group.selection_type,
        is_required=group.is_required,
        min_selection=group.min_selection,
        max_selection=group.max_selection,
        is_active=group.is_active,
        sort_order=group.sort_order,
        options=[
            _serialize_menu_item_customization_option(option)
            for option in sorted_options
        ],
    )


def _serialize_menu_item_size(size: MenuItemSize) -> MenuItemSizeResponse:
    sorted_groups = sorted(
        size.customization_groups,
        key=lambda group: (group.sort_order, group.title.lower(), str(group.id)),
    )
    return MenuItemSizeResponse(
        id=size.id,
        name=size.name,
        price=size.price,
        is_active=size.is_active,
        sort_order=size.sort_order,
        customization_groups=[
            _serialize_menu_item_customization_group(group)
            for group in sorted_groups
        ],
    )


def _is_missing_favorites_schema(error: Exception) -> bool:
    if not isinstance(error, ProgrammingError):
        return False
    message = str(getattr(error, "orig", error)).lower()
    return "favorites" in message and "does not exist" in message


def _favorites_schema_not_ready_http_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Favorites are temporarily unavailable. Run `alembic upgrade head` to apply the latest database schema.",
    )


def _coerce_id_set(menu_item_ids: Iterable[uuid.UUID | str] | None) -> set[uuid.UUID]:
    if menu_item_ids is None:
        return set()
    normalized: set[uuid.UUID] = set()
    for menu_item_id in menu_item_ids:
        normalized.add(menu_item_id if isinstance(menu_item_id, uuid.UUID) else uuid.UUID(str(menu_item_id)))
    return normalized


def get_user_favorite_ids(
    db: Session,
    user: User | None,
    *,
    menu_item_ids: Iterable[uuid.UUID | str] | None = None,
    fail_open: bool = True,
    restaurant_id: uuid.UUID | None = None,
) -> set[uuid.UUID]:
    if user is None or user.role.value != "CUSTOMER":
        return set()

    scoped_ids = _coerce_id_set(menu_item_ids)
    if menu_item_ids is not None and not scoped_ids:
        return set()

    query = select(Favorite.menu_item_id).where(Favorite.user_id == user.id)
    if scoped_ids:
        query = query.where(Favorite.menu_item_id.in_(scoped_ids))
    if restaurant_id is not None:
        query = query.join(MenuItem, Favorite.menu_item_id == MenuItem.id).where(
            MenuItem.restaurant_id == restaurant_id
        )
    try:
        return set(db.scalars(query).all())
    except ProgrammingError as exc:
        if not _is_missing_favorites_schema(exc):
            raise
        logger.warning(
            "Favorite ID lookup skipped because schema is not ready user_id=%s scoped_item_count=%d",
            user.id,
            len(scoped_ids),
        )
        if fail_open:
            return set()
        raise _favorites_schema_not_ready_http_error() from exc


def serialize_menu_item(menu_item: MenuItem, *, favorite_ids: set[uuid.UUID] | None = None) -> MenuItemResponse:
    favorite_ids = favorite_ids or set()
    location = getattr(menu_item, "restaurant_location", None)
    is_new = is_menu_item_new(menu_item)
    recommendation_label, recommendation_reason = build_generic_menu_item_badge_metadata(menu_item)
    sorted_sizes = sorted(
        menu_item.sizes,
        key=lambda size: (size.sort_order, size.name.lower(), str(size.id)),
    )
    sorted_groups = sorted(
        [group for group in menu_item.customization_groups if group.menu_item_size_id is None],
        key=lambda group: (group.sort_order, group.title.lower(), str(group.id)),
    )
    return MenuItemResponse(
        id=menu_item.id,
        restaurant_id=menu_item.restaurant_id,
        restaurant_location_id=menu_item.restaurant_location_id,
        restaurant_location_name=location.branch_name if location is not None else None,
        restaurant_location_city=location.city if location is not None else None,
        name=menu_item.name,
        category=menu_item.category,
        cuisine_type=menu_item.cuisine_type,
        description=menu_item.description,
        price=menu_item.price,
        is_veg=menu_item.is_veg,
        is_available=menu_item.is_available,
        is_bestseller=is_menu_item_bestseller(menu_item),
        is_featured=get_menu_item_featured_flag(menu_item),
        image_url=menu_item.image_url,
        recent_valid_order_count=get_menu_item_recent_valid_order_count(menu_item),
        recent_valid_order_window_days=settings.bestseller_window_days,
        popularity_score=menu_item.popularity_score,
        launched_at=resolve_menu_item_launch_timestamp(menu_item),
        created_at=menu_item.created_at,
        updated_at=menu_item.updated_at,
        is_new_launch=menu_item.is_new_launch,
        is_new=is_new,
        recommendation_label=recommendation_label,
        recommendation_reason=recommendation_reason,
        new_item_reason=get_new_item_reason(menu_item) if is_new else None,
        is_favorite=menu_item.id in favorite_ids,
        has_sizes=menu_item.has_sizes,
        has_customizations=menu_item.has_customizations,
        sizes=[_serialize_menu_item_size(size) for size in sorted_sizes],
        customization_groups=[
            _serialize_menu_item_customization_group(group)
            for group in sorted_groups
        ],
    )


def serialize_menu_items(
    menu_items: list[MenuItem],
    *,
    favorite_ids: set[uuid.UUID] | None = None,
) -> list[MenuItemResponse]:
    favorite_ids = favorite_ids or set()
    return [serialize_menu_item(menu_item, favorite_ids=favorite_ids) for menu_item in menu_items]


def apply_recommendation_favorite_flags(
    items: list[RecommendationItemResponse],
    favorite_ids: set[uuid.UUID],
) -> list[RecommendationItemResponse]:
    return [
        item.model_copy(update={"is_favorite": item.id in favorite_ids})
        for item in items
    ]


def apply_chat_suggestion_favorite_flags(
    items: list[ChatSuggestionItem],
    favorite_ids: set[uuid.UUID],
) -> list[ChatSuggestionItem]:
    return [
        item.model_copy(update={"is_favorite": item.id in favorite_ids})
        for item in items
    ]


def apply_generated_combo_item_favorite_flags(
    items: list[GeneratedComboItemSummary],
    favorite_ids: set[uuid.UUID],
) -> list[GeneratedComboItemSummary]:
    return [
        item.model_copy(update={"is_favorite": item.menu_item_id in favorite_ids})
        for item in items
    ]


def serialize_favorite_list(
    db: Session,
    user: User,
    *,
    restaurant_id: uuid.UUID | None = None,
) -> list[FavoriteItemResponse]:
    try:
        query = (
            select(Favorite, MenuItem, Restaurant, RestaurantLocation)
            .join(MenuItem, Favorite.menu_item_id == MenuItem.id)
            .join(Restaurant, MenuItem.restaurant_id == Restaurant.id)
            .join(RestaurantLocation, MenuItem.restaurant_location_id == RestaurantLocation.id)
            .where(Favorite.user_id == user.id)
        )
        if restaurant_id is not None:
            query = query.where(MenuItem.restaurant_id == restaurant_id)
        rows = db.execute(
            query.order_by(Favorite.created_at.desc(), MenuItem.name.asc())
        ).all()
    except ProgrammingError as exc:
        if not _is_missing_favorites_schema(exc):
            raise
        logger.warning(
            "Favorite list skipped because schema is not ready user_id=%s",
            user.id,
        )
        raise _favorites_schema_not_ready_http_error() from exc

    items: list[FavoriteItemResponse] = []
    hydrate_dynamic_bestseller_flags(db, [menu_item for _, menu_item, _, _ in rows])
    for favorite, menu_item, restaurant, location in rows:
        is_orderable = bool(
            menu_item.is_available
            and restaurant.is_active
            and restaurant.is_approved
            and location.is_active
        )
        items.append(
            FavoriteItemResponse(
                id=menu_item.id,
                restaurant_id=restaurant.id,
                restaurant_location_id=location.id,
                restaurant_location_name=location.branch_name,
                restaurant_name=restaurant.name,
                restaurant_slug=restaurant.slug,
                restaurant_is_active=restaurant.is_active,
                restaurant_is_approved=restaurant.is_approved,
                restaurant_is_open=restaurant.is_open,
                name=menu_item.name,
                category=menu_item.category,
                cuisine_type=menu_item.cuisine_type,
                description=menu_item.description,
                price=menu_item.price,
                is_available=menu_item.is_available,
                is_orderable=is_orderable,
                is_veg=menu_item.is_veg,
                is_bestseller=is_menu_item_bestseller(menu_item),
                is_featured=get_menu_item_featured_flag(menu_item),
                image_url=menu_item.image_url,
                popularity_score=menu_item.popularity_score,
                is_favorite=True,
                favorited_at=favorite.created_at,
                created_at=menu_item.created_at,
                updated_at=menu_item.updated_at,
            )
        )
    return items


def add_user_favorite(db: Session, user: User, menu_item_id: uuid.UUID) -> None:
    favorite = Favorite(user_id=user.id, menu_item_id=menu_item_id)
    try:
        db.add(favorite)
        db.commit()
        invalidate_user_recommendation_cache(user.id)
        from app.services.ai_recommendations import queue_ai_recommendation_refresh

        queue_ai_recommendation_refresh(
            user_id=user.id,
            reason="favorite_added",
            force_refresh=True,
        )
    except IntegrityError:
        db.rollback()
    except ProgrammingError as exc:
        db.rollback()
        if not _is_missing_favorites_schema(exc):
            raise
        logger.warning(
            "Favorite add failed because schema is not ready user_id=%s menu_item_id=%s",
            user.id,
            menu_item_id,
        )
        raise _favorites_schema_not_ready_http_error() from exc


def delete_user_favorite(db: Session, user: User, menu_item_id: uuid.UUID) -> bool:
    try:
        result = db.execute(
            delete(Favorite).where(
                Favorite.user_id == user.id,
                Favorite.menu_item_id == menu_item_id,
            )
        )
        db.commit()
        if result.rowcount:
            invalidate_user_recommendation_cache(user.id)
            from app.services.ai_recommendations import queue_ai_recommendation_refresh

            queue_ai_recommendation_refresh(
                user_id=user.id,
                reason="favorite_removed",
                force_refresh=True,
            )
        return bool(result.rowcount)
    except ProgrammingError as exc:
        db.rollback()
        if not _is_missing_favorites_schema(exc):
            raise
        logger.warning(
            "Favorite delete failed because schema is not ready user_id=%s menu_item_id=%s",
            user.id,
            menu_item_id,
        )
        raise _favorites_schema_not_ready_http_error() from exc

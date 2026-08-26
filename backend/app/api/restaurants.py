from __future__ import annotations

import re
import uuid
from typing import Annotated

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.deps import AppScopeDep, ensure_restaurant_readable
from app.config.database import get_db
from app.models.enums import OrderFulfillmentType, UserRole
from app.models.location_fulfillment_slot import LocationFulfillmentSlot
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.schemas.restaurant import (
    RestaurantThemeResponse,
    RestaurantThemeUpdate,
    ThemePresetResponse,
    AdminRestaurantCreate,
    AdminRestaurantCreateResponse,
    AppClientResponse,
    AppClientUpsertRequest,
    LocationScheduleOptionsResponse,
    LocationFulfillmentSlotCreate,
    LocationFulfillmentSlotResponse,
    LocationFulfillmentSlotUpdate,
    RestaurantDetailResponse,
    RestaurantLocationCreate,
    RestaurantLocationGeneralSettingsUpdate,
    RestaurantLocationResponse,
    RestaurantLocationUpdate,
    RestaurantResponse,
    RestaurantSettingsUpdate,
)
from app.services.app_clients import (
    build_app_client_for_restaurant,
    get_app_client_for_restaurant,
    upsert_app_client_for_restaurant,
)
from app.services.restaurant_theme import (
    THEME_PRESETS,
    ThemeValidationError,
    read_theme,
    resolve_theme,
)
from app.services.auth import get_current_user, get_current_user_optional, hash_password, require_admin, require_owner
from app.services.personalized_offers import invalidate_all_personalized_offer_caches
from app.services.restaurant_locations import (
    build_default_location_for_restaurant,
    build_location_response,
    create_location_slot,
    ensure_default_location_slots,
    list_available_schedule_options,
    list_location_fulfillment_slots,
    list_restaurant_locations,
    require_location_slot,
    require_location_for_restaurant,
    sorted_slots,
    update_location_slot,
)

router = APIRouter(prefix="/restaurants", tags=["Restaurants"])


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return normalized or "restaurant"


def _generate_unique_slug(
    db: Session,
    restaurant_name: str,
    *,
    exclude_restaurant_id: uuid.UUID | None = None,
) -> str:
    base_slug = _slugify(restaurant_name)
    candidate = base_slug
    suffix = 2

    while True:
        query = select(Restaurant.id).where(Restaurant.slug == candidate)
        if exclude_restaurant_id is not None:
            query = query.where(Restaurant.id != exclude_restaurant_id)
        if db.scalar(query) is None:
            return candidate
        candidate = f"{base_slug}-{suffix}"
        suffix += 1


def _restaurant_query() -> Select[tuple[Restaurant]]:
    return select(Restaurant).options(
        selectinload(Restaurant.owner),
        selectinload(Restaurant.locations),
    )


def _get_accessible_restaurant(
    db: Session,
    restaurant_id: uuid.UUID,
    current_user: User,
) -> Restaurant:
    restaurant = db.scalar(_restaurant_query().where(Restaurant.id == restaurant_id))
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    if current_user.role == UserRole.ADMIN:
        return restaurant
    if current_user.role == UserRole.OWNER and restaurant.owner_id == current_user.id:
        return restaurant
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to access this restaurant",
    )


def _detail_response(
    restaurant: Restaurant,
    *,
    locations: list[RestaurantLocation],
) -> RestaurantDetailResponse:
    response = RestaurantDetailResponse.model_validate(restaurant)
    response.locations = [build_location_response(location) for location in locations]
    return response


@router.post("", response_model=AdminRestaurantCreateResponse, status_code=status.HTTP_201_CREATED)
def create_restaurant(
    payload: AdminRestaurantCreate,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
) -> AdminRestaurantCreateResponse:
    existing_user = db.scalar(
        select(User).where(func.lower(User.email) == payload.owner_email.strip().lower())
    )
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this owner email already exists",
        )

    owner = User(
        full_name=payload.owner_name,
        # Staff emails are unique platform-wide and compared case-insensitively
        # by uq_users_email_platform, so normalize here as /auth/register does.
        email=payload.owner_email.strip().lower(),
        hashed_password=hash_password(payload.owner_password),
        role=UserRole.OWNER,
        # Platform staff belong to no app; the CHECK constraint requires this.
        app_client_id=None,
        is_active=True,
        is_verified=False,
    )
    restaurant = Restaurant(
        owner=owner,
        name=payload.name,
        slug=_generate_unique_slug(db, payload.name),
        description=None,
        cuisine_type="General",
        address_line_1="Pending restaurant setup",
        address_line_2=None,
        city="Pending",
        state="Pending",
        country="India",
        postal_code="000000",
        phone_number=None,
        minimum_order_amount=0,
        delivery_fee=0,
        logo_image_url=None,
        cover_image_url=None,
        is_open=False,
        is_approved=False,
        is_active=True,
    )

    try:
        db.add(owner)
        db.add(restaurant)
        db.flush()
        db.add(build_default_location_for_restaurant(restaurant))
        db.add(
            build_app_client_for_restaurant(
                db,
                restaurant_id=restaurant.id,
                restaurant_name=payload.name,
                payload=payload,
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This owner email, app key, or bundle ID is already in use",
        ) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(restaurant)
    return AdminRestaurantCreateResponse.model_validate(restaurant)


@router.get("", response_model=list[RestaurantResponse])
def list_restaurants(
    db: Annotated[Session, Depends(get_db)],
    app_scope: AppScopeDep,
    city: str | None = Query(default=None, max_length=120),
    cuisine_type: str | None = Query(default=None, max_length=120),
) -> list[RestaurantResponse]:
    query: Select[tuple[Restaurant]] = select(Restaurant).where(
        Restaurant.is_active.is_(True),
        Restaurant.is_approved.is_(True),
    )
    if app_scope.restaurant_filter_id is not None:
        query = query.where(Restaurant.id == app_scope.restaurant_filter_id)
    if city:
        query = query.where(Restaurant.city.ilike(city))
    if cuisine_type:
        query = query.where(Restaurant.cuisine_type.ilike(cuisine_type))

    restaurants = db.scalars(
        query.order_by(Restaurant.is_open.desc(), Restaurant.created_at.desc(), Restaurant.name.asc())
    ).all()
    return [RestaurantResponse.model_validate(restaurant) for restaurant in restaurants]


@router.get("/mine", response_model=list[RestaurantResponse])
def list_owner_restaurants(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_owner)],
) -> list[RestaurantResponse]:
    restaurants = db.scalars(
        select(Restaurant)
        .where(Restaurant.owner_id == current_user.id)
        .order_by(Restaurant.created_at.desc())
    ).all()
    return [RestaurantResponse.model_validate(restaurant) for restaurant in restaurants]


@router.get("/{restaurant_id}", response_model=RestaurantDetailResponse)
def get_restaurant_detail(
    restaurant_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    app_scope: AppScopeDep,
) -> RestaurantDetailResponse:
    ensure_restaurant_readable(app_scope, restaurant_id)
    if current_user is None or current_user.role == UserRole.CUSTOMER:
        restaurant = db.scalar(
            _restaurant_query().where(
                Restaurant.id == restaurant_id,
                Restaurant.is_active.is_(True),
                Restaurant.is_approved.is_(True),
            )
        )
        if restaurant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
        return _detail_response(
            restaurant,
            locations=list_restaurant_locations(db, restaurant_id=restaurant.id, include_inactive=False),
        )

    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access this restaurant",
        )

    restaurant = _get_accessible_restaurant(db, restaurant_id, current_user)
    return _detail_response(
        restaurant,
        locations=list_restaurant_locations(db, restaurant_id=restaurant.id, include_inactive=True),
    )


@router.patch("/{restaurant_id}/settings", response_model=RestaurantDetailResponse)
def update_restaurant_settings(
    restaurant_id: uuid.UUID,
    payload: RestaurantSettingsUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RestaurantDetailResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to update this restaurant",
        )

    restaurant = _get_accessible_restaurant(db, restaurant_id, current_user)
    if payload.name is not None:
        restaurant.name = payload.name
        restaurant.slug = _generate_unique_slug(db, payload.name, exclude_restaurant_id=restaurant.id)
    if payload.description is not None:
        restaurant.description = payload.description
    if payload.cuisine_type is not None:
        restaurant.cuisine_type = payload.cuisine_type
    if payload.address_line_1 is not None:
        restaurant.address_line_1 = payload.address_line_1
    if payload.address_line_2 is not None:
        restaurant.address_line_2 = payload.address_line_2
    if payload.city is not None:
        restaurant.city = payload.city
    if payload.state is not None:
        restaurant.state = payload.state
    if payload.country is not None:
        restaurant.country = payload.country
    if payload.postal_code is not None:
        restaurant.postal_code = payload.postal_code
    if payload.phone_number is not None:
        restaurant.phone_number = payload.phone_number
    if payload.logo_image_url is not None:
        restaurant.logo_image_url = payload.logo_image_url
    if payload.cover_image_url is not None:
        restaurant.cover_image_url = payload.cover_image_url
    if payload.is_open is not None:
        restaurant.is_open = payload.is_open
    if payload.is_active is not None:
        if current_user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only admins can enable or disable restaurants",
            )
        restaurant.is_active = payload.is_active
        if not payload.is_active:
            restaurant.is_open = False

    db.add(restaurant)
    db.commit()
    invalidate_all_personalized_offer_caches()
    refreshed = _get_accessible_restaurant(db, restaurant_id, current_user)
    return _detail_response(
        refreshed,
        locations=list_restaurant_locations(db, restaurant_id=restaurant_id, include_inactive=True),
    )


@router.get("/{restaurant_id}/app-client", response_model=AppClientResponse)
def get_restaurant_app_client(
    restaurant_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
) -> AppClientResponse:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    app_client = get_app_client_for_restaurant(db, restaurant_id=restaurant_id)
    if app_client is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This restaurant does not have an app client yet",
        )
    return AppClientResponse.model_validate(app_client)


@router.put("/{restaurant_id}/app-client", response_model=AppClientResponse)
def put_restaurant_app_client(
    restaurant_id: uuid.UUID,
    payload: AppClientUpsertRequest,
    db: Annotated[Session, Depends(get_db)],
    _current_user: Annotated[User, Depends(require_admin)],
) -> AppClientResponse:
    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    try:
        app_client = upsert_app_client_for_restaurant(db, restaurant=restaurant, payload=payload)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This app key or bundle ID is already in use",
        ) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(app_client)
    return AppClientResponse.model_validate(app_client)


@router.get("/{restaurant_id}/locations", response_model=list[RestaurantLocationResponse])
def get_restaurant_locations(
    restaurant_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    app_scope: AppScopeDep,
) -> list[RestaurantLocationResponse]:
    ensure_restaurant_readable(app_scope, restaurant_id)
    if current_user is not None and current_user.role in {UserRole.ADMIN, UserRole.OWNER}:
        _get_accessible_restaurant(db, restaurant_id, current_user)
        locations = list_restaurant_locations(db, restaurant_id=restaurant_id, include_inactive=True)
    else:
        restaurant = db.scalar(
            select(Restaurant).where(
                Restaurant.id == restaurant_id,
                Restaurant.is_active.is_(True),
                Restaurant.is_approved.is_(True),
            )
        )
        if restaurant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")
        locations = list_restaurant_locations(db, restaurant_id=restaurant_id, include_inactive=False)
    return [build_location_response(location) for location in locations]


@router.get("/{restaurant_id}/locations/{location_id}", response_model=RestaurantLocationResponse)
def get_restaurant_location(
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    app_scope: AppScopeDep,
) -> RestaurantLocationResponse:
    ensure_restaurant_readable(app_scope, restaurant_id)
    include_inactive = bool(current_user is not None and current_user.role in {UserRole.ADMIN, UserRole.OWNER})
    if include_inactive:
        _get_accessible_restaurant(db, restaurant_id, current_user)
    else:
        restaurant = db.scalar(
            select(Restaurant).where(
                Restaurant.id == restaurant_id,
                Restaurant.is_active.is_(True),
                Restaurant.is_approved.is_(True),
            )
        )
        if restaurant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    location = require_location_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        location_id=location_id,
        include_inactive=include_inactive,
    )
    return build_location_response(location)


@router.get(
    "/{restaurant_id}/locations/{location_id}/schedule-options",
    response_model=LocationScheduleOptionsResponse,
)
def get_restaurant_location_schedule_options(
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    app_scope: AppScopeDep,
    current_user: Annotated[User | None, Depends(get_current_user_optional)],
    fulfillment_type: OrderFulfillmentType = Query(default=OrderFulfillmentType.DELIVERY),
) -> LocationScheduleOptionsResponse:
    ensure_restaurant_readable(app_scope, restaurant_id)
    include_inactive = bool(current_user is not None and current_user.role in {UserRole.ADMIN, UserRole.OWNER})
    if include_inactive:
        _get_accessible_restaurant(db, restaurant_id, current_user)
    else:
        restaurant = db.scalar(
            select(Restaurant).where(
                Restaurant.id == restaurant_id,
                Restaurant.is_active.is_(True),
                Restaurant.is_approved.is_(True),
            )
        )
        if restaurant is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found")

    location = require_location_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        location_id=location_id,
        include_inactive=include_inactive,
    )
    return list_available_schedule_options(
        location,
        restaurant_id=restaurant_id,
        fulfillment_type=fulfillment_type,
    )


@router.post(
    "/{restaurant_id}/locations",
    response_model=RestaurantLocationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_restaurant_location(
    restaurant_id: uuid.UUID,
    payload: RestaurantLocationCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RestaurantLocationResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage restaurant locations",
        )
    _get_accessible_restaurant(db, restaurant_id, current_user)
    location = RestaurantLocation(restaurant_id=restaurant_id, **payload.model_dump())
    db.add(location)
    db.flush()
    ensure_default_location_slots(db, location_id=location.id)
    db.commit()
    db.refresh(location)
    invalidate_all_personalized_offer_caches()
    return build_location_response(location)


@router.patch("/{restaurant_id}/locations/{location_id}", response_model=RestaurantLocationResponse)
def update_restaurant_location(
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID,
    payload: RestaurantLocationUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RestaurantLocationResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage restaurant locations",
        )
    _get_accessible_restaurant(db, restaurant_id, current_user)
    location = require_location_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        location_id=location_id,
        include_inactive=True,
    )
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(location, field_name, value)
    db.add(location)
    db.commit()
    db.refresh(location)
    invalidate_all_personalized_offer_caches()
    return build_location_response(location)


@router.delete("/{restaurant_id}/locations/{location_id}", response_model=RestaurantLocationResponse)
def deactivate_restaurant_location(
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RestaurantLocationResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage restaurant locations",
        )
    _get_accessible_restaurant(db, restaurant_id, current_user)
    location = require_location_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        location_id=location_id,
        include_inactive=True,
    )
    location.is_active = False
    location.is_open = False
    db.add(location)
    db.commit()
    db.refresh(location)
    invalidate_all_personalized_offer_caches()
    return build_location_response(location)


@router.get(
    "/{restaurant_id}/locations/{location_id}/general-settings",
    response_model=RestaurantLocationResponse,
)
def get_restaurant_location_general_settings(
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RestaurantLocationResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage restaurant locations",
        )
    _get_accessible_restaurant(db, restaurant_id, current_user)
    location = require_location_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        location_id=location_id,
        include_inactive=True,
    )
    return build_location_response(location)


@router.patch(
    "/{restaurant_id}/locations/{location_id}/general-settings",
    response_model=RestaurantLocationResponse,
)
def update_restaurant_location_general_settings(
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID,
    payload: RestaurantLocationGeneralSettingsUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RestaurantLocationResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage restaurant locations",
        )
    _get_accessible_restaurant(db, restaurant_id, current_user)
    location = require_location_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        location_id=location_id,
        include_inactive=True,
    )
    for field_name, value in payload.model_dump(exclude_unset=True).items():
        setattr(location, field_name, value)
    db.add(location)
    db.commit()
    db.refresh(location)
    invalidate_all_personalized_offer_caches()
    return build_location_response(location)


@router.get(
    "/{restaurant_id}/locations/{location_id}/slots",
    response_model=list[LocationFulfillmentSlotResponse],
)
def get_restaurant_location_slots(
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[LocationFulfillmentSlotResponse]:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage restaurant locations",
        )
    _get_accessible_restaurant(db, restaurant_id, current_user)
    require_location_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        location_id=location_id,
        include_inactive=True,
    )
    return [
        LocationFulfillmentSlotResponse.model_validate(slot)
        for slot in list_location_fulfillment_slots(db, location_id=location_id, include_inactive=True)
    ]


@router.post(
    "/{restaurant_id}/locations/{location_id}/slots",
    response_model=LocationFulfillmentSlotResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_restaurant_location_slot(
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID,
    payload: LocationFulfillmentSlotCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LocationFulfillmentSlotResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage restaurant locations",
        )
    _get_accessible_restaurant(db, restaurant_id, current_user)
    location = require_location_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        location_id=location_id,
        include_inactive=True,
    )
    slot = create_location_slot(db, location=location, payload=payload)
    db.commit()
    db.refresh(slot)
    return LocationFulfillmentSlotResponse.model_validate(slot)


@router.patch(
    "/{restaurant_id}/locations/{location_id}/slots/{slot_id}",
    response_model=LocationFulfillmentSlotResponse,
)
def update_restaurant_location_slot(
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID,
    slot_id: uuid.UUID,
    payload: LocationFulfillmentSlotUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LocationFulfillmentSlotResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage restaurant locations",
        )
    _get_accessible_restaurant(db, restaurant_id, current_user)
    require_location_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        location_id=location_id,
        include_inactive=True,
    )
    slot = require_location_slot(db, location_id=location_id, slot_id=slot_id)
    slot = update_location_slot(db, slot=slot, payload=payload)
    db.commit()
    db.refresh(slot)
    return LocationFulfillmentSlotResponse.model_validate(slot)


@router.delete(
    "/{restaurant_id}/locations/{location_id}/slots/{slot_id}",
    response_model=LocationFulfillmentSlotResponse,
)
def delete_restaurant_location_slot(
    restaurant_id: uuid.UUID,
    location_id: uuid.UUID,
    slot_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LocationFulfillmentSlotResponse:
    if current_user.role not in {UserRole.ADMIN, UserRole.OWNER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to manage restaurant locations",
        )
    _get_accessible_restaurant(db, restaurant_id, current_user)
    require_location_for_restaurant(
        db,
        restaurant_id=restaurant_id,
        location_id=location_id,
        include_inactive=True,
    )
    slot = require_location_slot(db, location_id=location_id, slot_id=slot_id)
    db.delete(slot)
    db.commit()
    return LocationFulfillmentSlotResponse.model_validate(slot)


logger = logging.getLogger(__name__)


def _theme_restaurant_for(
    db: Session, *, restaurant_id: uuid.UUID, user: User
) -> Restaurant:
    """Load a restaurant the caller is allowed to theme.

    An owner may only reach their own; an admin may reach any. Anyone else gets
    a 404 rather than a 403, so the endpoint does not confirm which restaurant
    ids exist.
    """

    restaurant = db.get(Restaurant, restaurant_id)
    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found"
        )
    if user.role == UserRole.ADMIN:
        return restaurant
    if user.role == UserRole.OWNER and restaurant.owner_id == user.id:
        return restaurant
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="Restaurant not found"
    )


@router.get("/{restaurant_id}/theme", response_model=RestaurantThemeResponse)
def get_restaurant_theme(
    restaurant_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RestaurantThemeResponse:
    """This restaurant's theme and the presets available to it."""

    restaurant = _theme_restaurant_for(db, restaurant_id=restaurant_id, user=current_user)
    stored = read_theme(restaurant)
    return RestaurantThemeResponse(
        restaurant_id=restaurant.id,
        restaurant_name=restaurant.name,
        preset=stored["preset"],
        primary_color=stored["primary_color"],
        presets=[ThemePresetResponse(**vars(preset)) for preset in THEME_PRESETS],
    )


@router.put("/{restaurant_id}/theme", response_model=RestaurantThemeResponse)
def put_restaurant_theme(
    restaurant_id: uuid.UUID,
    payload: RestaurantThemeUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> RestaurantThemeResponse:
    """Change this restaurant's theme.

    Owner-writable, unlike the app-client record it used to live on: the colour
    is the restaurant's own branding, not part of its mobile build configuration,
    and an owner should not need an administrator to change it.
    """

    restaurant = _theme_restaurant_for(db, restaurant_id=restaurant_id, user=current_user)
    try:
        resolved = resolve_theme(
            preset_id=payload.preset, primary_color=payload.primary_color
        )
    except ThemeValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error

    restaurant.theme = resolved
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)

    logger.info(
        "Restaurant theme updated restaurant_id=%s user_id=%s preset=%s color=%s",
        restaurant.id,
        current_user.id,
        resolved["preset"],
        resolved["primary_color"],
    )
    return RestaurantThemeResponse(
        restaurant_id=restaurant.id,
        restaurant_name=restaurant.name,
        preset=resolved["preset"],
        primary_color=resolved["primary_color"],
        presets=[ThemePresetResponse(**vars(preset)) for preset in THEME_PRESETS],
    )

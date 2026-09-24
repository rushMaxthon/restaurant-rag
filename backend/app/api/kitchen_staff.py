"""Creating and managing the logins an order board runs on.

Without this the KITCHEN role added in migration 0071 would be unreachable:
nothing else on the platform creates a staff account except
`POST /restaurants`, which makes exactly one OWNER alongside a new restaurant.

An OWNER manages the accounts for their own restaurant and an ADMIN for any,
which is the same split every other restaurant-scoped route follows — and it
goes through `resolve_order_board_scope`, so "which restaurant" is answered by
the one function the order board itself uses rather than by a second rule that
could drift from it.

A KITCHEN account cannot create another. That is the point of the role.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.database import get_db
from app.models.enums import UserRole
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.schemas.kitchen_staff import (
    KitchenStaffCreate,
    KitchenStaffResponse,
    KitchenStaffUpdate,
)
from app.services.auth import (
    get_current_user,
    hash_password,
    normalize_phone_number,
    resolve_order_board_scope,
)

router = APIRouter(prefix="/kitchen-staff", tags=["Kitchen"])

MANAGER_ROLES = (UserRole.ADMIN, UserRole.OWNER)


# Spelled out rather than built with `_require_role` so the refusal names the
# case that matters: a KITCHEN account authenticates perfectly well here and
# still must not be able to create or re-point its own peers.
def require_staff_manager(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if current_user.role not in MANAGER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner or an admin can manage kitchen accounts",
        )
    return current_user


def _restaurant_id_for(
    db: Session, current_user: User, requested_restaurant_id: uuid.UUID | None
) -> uuid.UUID:
    """Which restaurant this call is about, by the order board's own rule."""

    scope = resolve_order_board_scope(
        db, current_user, requested_restaurant_id=requested_restaurant_id
    )
    if scope.restaurant_id is None:
        # Only reachable by an ADMIN who named none. Same refusal as
        # `resolve_insights_scope`, for the same reason: platform staff have no
        # implicit restaurant and guessing one would be a silent mistake.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="restaurant_id is required for admin kitchen staff requests",
        )
    return scope.restaurant_id


def _validate_branch(
    db: Session, restaurant_id: uuid.UUID, location_id: uuid.UUID | None
) -> RestaurantLocation | None:
    """A branch, if one was named, and only if it is this restaurant's.

    The composite foreign key would refuse a mismatch anyway, but an
    IntegrityError reaches the owner as a 500 with nothing they can act on.
    """

    if location_id is None:
        return None
    location = db.scalar(
        select(RestaurantLocation).where(
            RestaurantLocation.id == location_id,
            RestaurantLocation.restaurant_id == restaurant_id,
        )
    )
    if location is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That branch does not belong to this restaurant",
        )
    return location


def _serialize(user: User, branch_name: str | None) -> KitchenStaffResponse:
    return KitchenStaffResponse(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        phone_number=user.phone_number,
        is_active=user.is_active,
        # Non-null for any row this route can return: every one of them is a
        # KITCHEN account, and the CHECK constraint guarantees the column.
        restaurant_id=user.staff_restaurant_id,  # type: ignore[arg-type]
        restaurant_location_id=user.staff_restaurant_location_id,
        branch_name=branch_name,
        created_at=user.created_at,
    )


@router.get("", response_model=list[KitchenStaffResponse])
def list_kitchen_staff(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_staff_manager)],
    restaurant_id: uuid.UUID | None = Query(default=None),
) -> list[KitchenStaffResponse]:
    scoped_restaurant_id = _restaurant_id_for(db, current_user, restaurant_id)
    rows = db.execute(
        select(User, RestaurantLocation.branch_name)
        .outerjoin(
            RestaurantLocation,
            RestaurantLocation.id == User.staff_restaurant_location_id,
        )
        .where(
            User.role == UserRole.KITCHEN,
            User.staff_restaurant_id == scoped_restaurant_id,
        )
        .order_by(User.created_at.desc())
    ).all()
    return [_serialize(user, branch_name) for user, branch_name in rows]


@router.post("", response_model=KitchenStaffResponse, status_code=status.HTTP_201_CREATED)
def create_kitchen_staff(
    payload: KitchenStaffCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_staff_manager)],
) -> KitchenStaffResponse:
    scoped_restaurant_id = _restaurant_id_for(db, current_user, payload.restaurant_id)
    branch = _validate_branch(db, scoped_restaurant_id, payload.restaurant_location_id)

    # Normalized to match `uq_users_email_platform`, which is on lower(email)
    # and now covers KITCHEN as well as ADMIN and OWNER.
    normalized_email = payload.email.strip().lower()
    clash = db.scalar(
        select(User).where(
            func.lower(User.email) == normalized_email,
            User.role.in_((UserRole.ADMIN, UserRole.OWNER, UserRole.KITCHEN)),
        )
    )
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A staff account with this email already exists",
        )

    staff = User(
        full_name=payload.full_name,
        email=normalized_email,
        phone_number=normalize_phone_number(payload.phone_number),
        hashed_password=hash_password(payload.password),
        role=UserRole.KITCHEN,
        # Platform staff belong to no app client; the CHECK constraint on
        # `users` requires this to be set explicitly rather than defaulted.
        app_client_id=None,
        is_active=True,
        is_verified=True,
        staff_restaurant_id=scoped_restaurant_id,
        staff_restaurant_location_id=branch.id if branch is not None else None,
    )
    db.add(staff)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That kitchen account could not be created",
        )
    db.refresh(staff)
    return _serialize(staff, branch.branch_name if branch is not None else None)


@router.patch("/{staff_id}", response_model=KitchenStaffResponse)
def update_kitchen_staff(
    staff_id: uuid.UUID,
    payload: KitchenStaffUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_staff_manager)],
    restaurant_id: uuid.UUID | None = Query(default=None),
) -> KitchenStaffResponse:
    scoped_restaurant_id = _restaurant_id_for(db, current_user, restaurant_id)
    # Narrowed by restaurant in the lookup, so an account belonging to another
    # restaurant is a 404 rather than a 403 — the caller learns nothing about
    # staff that are not theirs.
    staff = db.scalar(
        select(User).where(
            User.id == staff_id,
            User.role == UserRole.KITCHEN,
            User.staff_restaurant_id == scoped_restaurant_id,
        )
    )
    if staff is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kitchen account not found")

    if payload.full_name is not None:
        staff.full_name = payload.full_name
    if payload.is_active is not None:
        staff.is_active = payload.is_active
        if not payload.is_active:
            # Deactivating must end the sessions already issued, or the tablet
            # in the kitchen keeps working until its token expires on its own.
            staff.token_version += 1

    branch: RestaurantLocation | None = None
    if payload.clear_restaurant_location:
        staff.staff_restaurant_location_id = None
    elif payload.restaurant_location_id is not None:
        branch = _validate_branch(db, scoped_restaurant_id, payload.restaurant_location_id)
        staff.staff_restaurant_location_id = payload.restaurant_location_id
        # A cook moved to another branch must not keep the old board on the
        # strength of a token issued before the move.
        staff.token_version += 1

    db.commit()
    db.refresh(staff)

    if branch is None and staff.staff_restaurant_location_id is not None:
        branch = db.get(RestaurantLocation, staff.staff_restaurant_location_id)
    return _serialize(staff, branch.branch_name if branch is not None else None)

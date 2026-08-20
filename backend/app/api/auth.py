from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AppScopeDep, IdentityAppClientDep
from app.config.database import get_db
from app.models.enums import UserRole
from app.models.app_client import AppClient
from app.models.user import User
from app.schemas.auth import AuthResponse, LogoutAllResponse, UserLogin, UserRegister, UserResponse
from app.services.personalized_offers import (
    invalidate_user_personalized_offers_cache,
    sync_global_welcome_offer_for_user,
)
from app.services.auth import (
    get_current_user,
    authenticate_user,
    create_access_token,
    hash_password,
    normalize_phone_number,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)


def _owner_restaurant_id(user: User):
    if user.role != UserRole.OWNER or user.owned_restaurant is None:
        return None
    return user.owned_restaurant.id


def _auth_response(db: Session, user: User) -> AuthResponse:
    app_key = None
    if user.app_client_id is not None:
        app_key = db.scalar(select(AppClient.key).where(AppClient.id == user.app_client_id))

    return AuthResponse(
        access_token=create_access_token(user),
        role=user.role,
        restaurant_id=_owner_restaurant_id(user),
        app_client_id=user.app_client_id,
        app_key=app_key,
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: UserRegister,
    db: Annotated[Session, Depends(get_db)],
    app_client_id: IdentityAppClientDep,
) -> AuthResponse:
    normalized_email = payload.email.strip().lower()
    normalized_phone_number = normalize_phone_number(payload.phone_number)

    # Conflicts are per app: the same email may already be a customer of a
    # different app, and may also belong to platform staff. Neither blocks
    # registration here - the partial unique indexes define what is actually
    # forbidden, and are enforced below.
    existing_email_user = db.scalar(
        select(User).where(
            func.lower(User.email) == normalized_email,
            User.role == UserRole.CUSTOMER,
            User.app_client_id == app_client_id,
        )
    )
    if existing_email_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    if normalized_phone_number:
        existing_phone_user = db.scalar(
            select(User).where(
                User.phone_number == normalized_phone_number,
                User.role == UserRole.CUSTOMER,
                User.app_client_id == app_client_id,
            )
        )
        if existing_phone_user is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this phone number already exists",
            )

    user = User(
        full_name=payload.full_name,
        email=normalized_email,
        phone_number=normalized_phone_number,
        default_address=payload.default_address,
        hashed_password=hash_password(payload.password),
        role=UserRole.CUSTOMER,
        app_client_id=app_client_id,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # The checks above are read-then-write and therefore racy; the partial
        # unique indexes are the real authority.
        db.rollback()
        constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", "") or ""
        if constraint == "uq_users_app_client_id_email_customer":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists",
            ) from exc
        if constraint == "uq_users_app_client_id_phone_number_customer":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this phone number already exists",
            ) from exc
        logger.exception("Registration failed constraint=%s", constraint)
        raise
    db.refresh(user)

    if user.role == UserRole.CUSTOMER:
        try:
            if sync_global_welcome_offer_for_user(db, user=user):
                db.commit()
                invalidate_user_personalized_offers_cache(user.id)
        except Exception:
            db.rollback()
            logger.exception(
                "Global welcome offer bootstrap failed during registration user_id=%s",
                user.id,
            )

    return _auth_response(db, user)


@router.post("/login", response_model=AuthResponse)
def login(
    payload: UserLogin,
    db: Annotated[Session, Depends(get_db)],
    app_scope: AppScopeDep,
    app_client_id: IdentityAppClientDep,
) -> AuthResponse:
    # A branded app never signs in staff, so only its own customers are
    # candidates. Callers without a bundle id (admin panel, customer web) may
    # also match platform staff.
    allow_platform_users = app_scope.app_client_id is None

    user = authenticate_user(
        db,
        payload.password,
        email=payload.email,
        phone_number=payload.phone_number,
        app_client_id=app_client_id,
        allow_platform_users=allow_platform_users,
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or phone number or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return _auth_response(db, user)


@router.post("/logout-all", response_model=LogoutAllResponse)
def logout_all(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> LogoutAllResponse:
    """Invalidate every access token already issued to this account.

    Bumping `token_version` makes existing tokens fail the version check in
    `_get_user_from_token`, including the one used to make this call, so the
    caller is signed out here too. Only this account is affected; the same
    person's accounts in other apps are separate users and keep their sessions.
    """

    current_user.token_version += 1
    db.add(current_user)
    db.commit()
    db.refresh(current_user)

    logger.info(
        "All sessions invalidated user_id=%s app_client_id=%s token_version=%s",
        current_user.id,
        current_user.app_client_id,
        current_user.token_version,
    )
    return LogoutAllResponse(token_version=current_user.token_version)

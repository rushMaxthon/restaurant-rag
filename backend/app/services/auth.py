from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Annotated, Callable
import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.config.database import get_db
from app.models.enums import UserRole
from app.models.restaurant import Restaurant
from app.models.user import User
from app.dependencies import get_app_scope
from app.schemas.auth import TokenPayload
from app.services.app_clients import AppScope, resolve_identity_app_client_id

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger(__name__)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.api_v1_prefix}/auth/login")
optional_oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.api_v1_prefix}/auth/login",
    auto_error=False,
)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def normalize_phone_number(phone_number: str | None) -> str | None:
    if not phone_number:
        return None

    trimmed = phone_number.strip()
    if not trimmed:
        return None

    if trimmed.startswith("+"):
        return f"+{''.join(character for character in trimmed[1:] if character.isdigit())}"

    return "".join(character for character in trimmed if character.isdigit())


def create_access_token(user: User) -> str:
    """Issue an access token bound to the user's app.

    `app_client_id` is null for platform staff, who are not tied to an app.
    `token_version` lets every token for a user be invalidated at once.
    The app *key* and bundle id are deliberately not claims: both are editable
    from the admin panel, and an authorization claim must not be mutable.
    """

    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "exp": expires_at,
        "iat": issued_at,
        "app_client_id": str(user.app_client_id) if user.app_client_id else None,
        "token_version": user.token_version,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def _identity_filters(email: str | None, phone_number: str | None):
    """Match on email when given, else phone. Email comparison is
    case-insensitive to match the lower(email) unique indexes."""

    if email:
        return func.lower(User.email) == email
    return User.phone_number == phone_number


def authenticate_user(
    db: Session,
    password: str,
    *,
    email: str | None = None,
    phone_number: str | None = None,
    app_client_id: uuid.UUID,
    allow_platform_users: bool = False,
) -> User | None:
    """Find the account matching these credentials within one app.

    Customers are scoped to `app_client_id`, so the same email can be a
    different person in a different app. Platform staff (ADMIN/OWNER) have no
    app client, and are only considered when `allow_platform_users` is set -
    which is the case for callers that sent no bundle id, i.e. the admin panel
    and the customer web app.

    Candidates are tried staff-first so an owner whose email is also a
    marketplace customer still lands on their staff account in the admin panel.
    """

    normalized_email = email.strip().lower() if email else None
    normalized_phone_number = normalize_phone_number(phone_number)

    if not normalized_email and not normalized_phone_number:
        return None

    identity_filter = _identity_filters(normalized_email, normalized_phone_number)

    candidates: list[User] = []
    if allow_platform_users:
        candidates.extend(
            db.scalars(
                select(User).where(
                    identity_filter,
                    User.role != UserRole.CUSTOMER,
                    User.app_client_id.is_(None),
                )
            ).all()
        )
    candidates.extend(
        db.scalars(
            select(User).where(
                identity_filter,
                User.role == UserRole.CUSTOMER,
                User.app_client_id == app_client_id,
            )
        ).all()
    )

    for candidate in candidates:
        if not verify_password(password, candidate.hashed_password):
            continue
        if not candidate.is_active:
            # Previously an inactive user received a token that failed on the
            # very next request; refuse at the door instead.
            logger.info("Login refused for inactive user_id=%s", candidate.id)
            return None
        return candidate
    return None


def _assert_token_matches_app(
    db: Session,
    user: User,
    token_data: TokenPayload,
    app_scope: AppScope,
    credentials_exception: HTTPException,
) -> None:
    """Reject a token presented by an app it was not issued for.

    A token from the Bangkok Bowl app must not work in the Marketplace app, and
    stripping the bundle header must not help: a missing header resolves to the
    default marketplace client, so it is just another app rather than an escape.
    """

    if token_data.token_version is None or token_data.token_version != user.token_version:
        logger.info("Token rejected: stale token_version user_id=%s", user.id)
        raise credentials_exception

    if "app_client_id" not in token_data.model_fields_set:
        logger.info("Token rejected: issued before per-app identity user_id=%s", user.id)
        raise credentials_exception

    if token_data.app_client_id is None:
        # Platform staff: no app, and the admin panel sends no bundle header.
        if user.app_client_id is not None or user.role == UserRole.CUSTOMER:
            logger.warning("Token rejected: platform token for an app-scoped user user_id=%s", user.id)
            raise credentials_exception
        return

    if user.app_client_id != token_data.app_client_id:
        logger.warning("Token rejected: user was re-keyed to another app user_id=%s", user.id)
        raise credentials_exception

    expected_app_client_id = resolve_identity_app_client_id(db, app_scope)
    if token_data.app_client_id != expected_app_client_id:
        logger.warning(
            "Token rejected: issued for app %s but presented by app %s",
            token_data.app_client_id,
            expected_app_client_id,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token was issued for a different app",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _get_user_from_token(db: Session, token: str, app_scope: AppScope) -> User:
    started_at = perf_counter()
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        decode_started_at = perf_counter()
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        token_data = TokenPayload(**payload)
        user_id = uuid.UUID(token_data.sub)
        decode_ms = round((perf_counter() - decode_started_at) * 1000, 2)
    except (JWTError, ValueError):
        raise credentials_exception

    lookup_started_at = perf_counter()
    user = db.get(User, user_id)
    lookup_ms = round((perf_counter() - lookup_started_at) * 1000, 2)
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user account")

    _assert_token_matches_app(db, user, token_data, app_scope, credentials_exception)

    total_ms = round((perf_counter() - started_at) * 1000, 2)
    logger.info(
        "Auth timings user_id=%s jwt_decode=%.2fms user_lookup=%.2fms total=%.2fms",
        user.id,
        decode_ms,
        lookup_ms,
        total_ms,
    )
    return user


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
    app_scope: Annotated[AppScope, Depends(get_app_scope)],
) -> User:
    return _get_user_from_token(db=db, token=token, app_scope=app_scope)


def get_current_user_optional(
    token: Annotated[str | None, Depends(optional_oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)],
    app_scope: Annotated[AppScope, Depends(get_app_scope)],
) -> User | None:
    """As `get_current_user`, but anonymous instead of failing.

    A cross-app token degrades to anonymous here, which is what guest browsing
    endpoints want. `_assert_token_matches_app` logs the mismatch so a
    misconfigured client is still diagnosable rather than silently anonymous.
    """

    if token is None:
        return None
    try:
        return _get_user_from_token(db=db, token=token, app_scope=app_scope)
    except HTTPException as exc:
        if exc.status_code in {
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        }:
            return None
        raise


def resolve_owner_restaurant_id(db: Session, owner: User) -> uuid.UUID:
    if owner.role != UserRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owners can access restaurant-scoped resources",
        )

    restaurant_id = db.scalar(
        select(Restaurant.id).where(
            Restaurant.owner_id == owner.id,
            Restaurant.is_active.is_(True),
        )
    )
    if restaurant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner does not have an active restaurant assigned",
        )
    return restaurant_id


def _require_role(*roles: UserRole) -> Callable[[User], User]:
    def dependency(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource",
            )
        return current_user

    return dependency


require_admin = _require_role(UserRole.ADMIN)
require_owner = _require_role(UserRole.OWNER)
require_customer = _require_role(UserRole.CUSTOMER)


def get_owner_restaurant_id(
    current_user: Annotated[User, Depends(require_owner)],
    db: Annotated[Session, Depends(get_db)],
) -> uuid.UUID:
    return resolve_owner_restaurant_id(db, current_user)

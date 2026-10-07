from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import AppScopeDep, IdentityAppClientDep
from app.config import get_settings
from app.config.database import get_db
from app.models.enums import UserRole
from app.models.app_client import AppClient
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    LogoutAllResponse,
    OtpRequest,
    OtpRequestResponse,
    OtpVerify,
    UserLogin,
    UserRegister,
    UserResponse,
)
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
from app.services.otp import (
    code_is_valid,
    matches_subscriber,
    otp_availability,
    subscriber_key,
)
from app.services.realtime.outbox import queue_session_revoked
from app.services import rate_limit
from app.services.rate_limit import per_ip

router = APIRouter(prefix="/auth", tags=["Authentication"])
logger = logging.getLogger(__name__)


def _staff_restaurant_id(user: User):
    """The restaurant a staff account belongs to, however it belongs to one.

    An OWNER reaches theirs through `Restaurant.owner_id`; a KITCHEN account
    carries it on its own row because it owns nothing. An ADMIN has none on
    purpose and names one per request instead.
    """

    if user.role == UserRole.OWNER:
        return user.owned_restaurant.id if user.owned_restaurant is not None else None
    if user.role == UserRole.KITCHEN:
        return user.staff_restaurant_id
    return None


def _staff_restaurant_location_id(user: User):
    """The one branch a kitchen account sees, or None for all of them."""

    if user.role != UserRole.KITCHEN:
        return None
    return user.staff_restaurant_location_id


def _auth_response(db: Session, user: User) -> AuthResponse:
    app_key = None
    if user.app_client_id is not None:
        app_key = db.scalar(select(AppClient.key).where(AppClient.id == user.app_client_id))

    return AuthResponse(
        access_token=create_access_token(user),
        role=user.role,
        restaurant_id=_staff_restaurant_id(user),
        restaurant_location_id=_staff_restaurant_location_id(user),
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
    # Counted before anything else runs (`services/rate_limit.py`).
    _rate_limited: Annotated[None, Depends(per_ip("register", limit=10, window_seconds=3600))],
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
    # Counted before anything else runs (`services/rate_limit.py`).
    _rate_limited: Annotated[None, Depends(per_ip("login", limit=20, window_seconds=60))],
    payload: UserLogin,
    db: Annotated[Session, Depends(get_db)],
    app_scope: AppScopeDep,
    app_client_id: IdentityAppClientDep,
) -> AuthResponse:
    # A branded app never signs in staff, so only its own customers are
    # candidates. Callers without a bundle id (admin panel, customer web) may
    # also match platform staff.
    # Per account as well as per IP: guessing one person's password from many
    # machines is the attack the per-IP limit alone does not stop.
    identifier = (payload.email or payload.phone_number or "").strip().lower()
    rate_limit.hit("login-account", f"id:{identifier}", limit=10, window_seconds=900)
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


def _otp_customer(db: Session, *, key: str, app_client_id) -> User | None:
    """The customer on this app whose number ends in these digits.

    Matched on the trailing digits rather than the stored string: the column
    holds `(982) 000-0011`, `+19059039992` and `9192127000`, all written by
    different paths over the years. A literal comparison would hand a
    returning customer a second account and an empty order history.
    """

    return db.scalar(
        select(User).where(
            matches_subscriber(User.phone_number, key),
            User.role == UserRole.CUSTOMER,
            User.app_client_id == app_client_id,
        )
    )


def _require_otp_available() -> None:
    """Refuse the whole flow unless a code can actually be checked."""

    availability = otp_availability()
    if availability.available:
        return
    if availability.reason == "no_sender":
        # The flag is on somewhere real with nothing to send with. Said out
        # loud: the alternative is accepting a code printed in a config file.
        logger.error(
            "enable_phone_otp_login is on in environment=%s with no SMS sender. "
            "Refusing to sign anybody in rather than accepting the fixed code.",
            get_settings().environment,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="We cannot send a code right now. Please sign in with your email instead.",
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Signing in by phone is not available here.",
    )


@router.post("/otp/request", response_model=OtpRequestResponse)
def request_otp(
    # Counted before anything else runs (`services/rate_limit.py`).
    _rate_limited: Annotated[None, Depends(per_ip("otp-request", limit=10, window_seconds=3600))],
    payload: OtpRequest,
    db: Annotated[Session, Depends(get_db)],
    app_client_id: IdentityAppClientDep,
) -> OtpRequestResponse:
    """Start a phone sign-in.

    Answers whether this number is already an account, so the next screen can
    ask a first-time caller for their name — and, while the fixed code is in
    use, hands back the code so a demo needs no SMS at all.
    """

    _require_otp_available()
    key = subscriber_key(payload.phone_number)
    # Per number: a short code is guessable if it can be tried without end.
    rate_limit.hit("otp-verify-phone", f"phone:{key}", limit=10, window_seconds=900)
    # Per number: a code is a message somebody pays for and a phone that buzzes.
    rate_limit.hit("otp-request-phone", f"phone:{key}", limit=5, window_seconds=3600)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter a phone number.",
        )

    existing = _otp_customer(db, key=key, app_client_id=app_client_id)
    settings = get_settings()
    return OtpRequestResponse(
        sent=True,
        is_new_account=existing is None,
        debug_code=settings.otp_debug_code.strip() or None,
    )


@router.post("/otp/verify", response_model=AuthResponse)
def verify_otp(
    # Counted before anything else runs (`services/rate_limit.py`).
    _rate_limited: Annotated[None, Depends(per_ip("otp-verify", limit=20, window_seconds=600))],
    payload: OtpVerify,
    db: Annotated[Session, Depends(get_db)],
    app_client_id: IdentityAppClientDep,
) -> AuthResponse:
    """Finish a phone sign-in, creating the account the first time.

    An account made this way has no password anyone knows: `hashed_password`
    is NOT NULL, so it is filled with the hash of a random secret that is
    discarded here. That is deliberate rather than a placeholder — it means
    the row cannot be signed into through `/auth/login` by guessing, and the
    phone is the only way in.

    The email is synthesised for the same reason the password is: the column
    is NOT NULL and this customer has not given one. It is put under
    `example.com`, which RFC 2606 reserves precisely so it can be used this
    way and which therefore can never belong to anybody — `.invalid` says it
    more plainly and `EmailStr` rejects it, which is the right call for a
    column every other path treats as a real address.
    """

    _require_otp_available()
    key = subscriber_key(payload.phone_number)
    if not key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter a phone number.",
        )
    if not code_is_valid(payload.code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="That code is not right. Check it and try again.",
        )

    user = _otp_customer(db, key=key, app_client_id=app_client_id)
    if user is not None:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account is not active. Please contact us.",
            )
        return _auth_response(db, user)

    stored_phone = normalize_phone_number(payload.phone_number) or key
    name = (payload.full_name or "").strip()
    user = User(
        # Their own name when they gave one. Never a generated stand-in: a
        # storefront greeting "Hi, Customer" is worse than one greeting
        # nobody, and the checkout asks for a name again anyway.
        full_name=name,
        email=f"{key}@phone.example.com",
        phone_number=stored_phone,
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        role=UserRole.CUSTOMER,
        app_client_id=app_client_id,
        is_active=True,
        # The phone IS the verification: they just proved they hold it.
        is_verified=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # Two requests for the same new number at once. The partial unique
        # indexes are the authority; the loser re-reads the winner's row and
        # signs in, because both callers proved the same thing.
        db.rollback()
        user = _otp_customer(db, key=key, app_client_id=app_client_id)
        if user is None:
            logger.exception("Phone sign-up failed and no row was found afterwards")
            raise
        return _auth_response(db, user)
    db.refresh(user)

    try:
        if sync_global_welcome_offer_for_user(db, user=user):
            db.commit()
            invalidate_user_personalized_offers_cache(user.id)
    except Exception:
        db.rollback()
        logger.exception("Welcome offer bootstrap failed for phone sign-up user_id=%s", user.id)

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
    # Open sockets are sessions too; ended once the bump has committed.
    queue_session_revoked(db, user_id=current_user.id)
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

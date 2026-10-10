"""Rider self sign-up, and the rider's own application.

The two sign-up routes are public and rate-limited per IP (on top of the
per-phone limits in `onboarding.phone`). Everything after sign-up is the
rider's own, behind `require_rider` - which a PENDING rider passes, because
filling in the application is the one thing they are signed in to do. What
they may NOT do (go online, take orders) is refused where those happen.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import _auth_response
from app.config import get_settings
from app.config.database import get_db
from app.models.enums import ApplicationItemKind, RiderOnboarding, RiderStatus, UserRole, VehicleType
from app.models.rider import Rider
from app.models.rider_application import RiderApplication
from app.models.user import User
from app.schemas.auth import AuthResponse
from app.schemas.rider_onboarding import (
    ApplicationView,
    PasswordResetRequest,
    SignupCheckRequest,
    SignupCodeRequest,
    SignupCodeResponse,
    SignupRequest,
)
from app.services.auth import hash_password, require_rider
from app.services.fleet.onboarding import applications, phone
from app.services.fleet.onboarding.views import application_view
from app.services.fleet.riders import _phone_taken, _placeholder_email, canonical_phone, reset_own_password
from app.services.rate_limit import per_ip

router = APIRouter(prefix="/rider", tags=["rider-signup"])
RiderUser = Annotated[User, Depends(require_rider)]
Db = Annotated[Session, Depends(get_db)]


def _phone(raw: str) -> str:
    number = canonical_phone(raw)
    if not number or len(number) != 13:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "bad_phone")
    return number


@router.post("/signup/code", response_model=SignupCodeResponse)
def signup_code(
    _rate_limited: Annotated[None, Depends(per_ip("rider-signup-code", limit=10, window_seconds=3600))],
    payload: SignupCodeRequest,
    db: Db,
) -> SignupCodeResponse:
    number = _phone(payload.phone_number)
    # Said before a code is sent, not after it is typed: the rider is told to
    # sign in instead, and nobody is sent a code for an account they have.
    if _phone_taken(db, number):
        raise HTTPException(status.HTTP_409_CONFLICT, "phone_in_use")
    result = phone.request_code(db, number)
    return SignupCodeResponse(sent=result.sent, retry_after=result.retry_after, debug_code=result.debug_code)


@router.post("/signup/check", status_code=status.HTTP_204_NO_CONTENT)
def signup_check(
    _rate_limited: Annotated[None, Depends(per_ip("rider-signup-check", limit=30, window_seconds=3600))],
    payload: SignupCheckRequest,
    db: Db,
) -> Response:
    """Is this the code? Asked on the code screen, so a typo is said there and
    not after the rider has typed a name and password. Does not use the code
    up (sign-up does); a wrong guess still counts towards the lock."""

    phone.verify_code(db, _phone(payload.phone_number), payload.code, consume=False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(
    _rate_limited: Annotated[None, Depends(per_ip("rider-signup", limit=10, window_seconds=3600))],
    payload: SignupRequest,
    db: Db,
) -> AuthResponse:
    number = _phone(payload.phone_number)
    if _phone_taken(db, number):
        raise HTTPException(status.HTTP_409_CONFLICT, "phone_in_use")
    wants_referral = bool(payload.referral_code and payload.referral_code.strip())
    if wants_referral:
        from app.services.fleet import referral

        # Before the phone code is used up: a mistyped referral code must
        # leave the rider able to fix it and send the form again.
        referral.check_code(db, payload.referral_code)
    phone.verify_code(db, number, payload.code)

    user = User(
        full_name=" ".join(payload.full_name.split()),
        phone_number=number,
        email=_placeholder_email(number),
        hashed_password=hash_password(payload.password),
        role=UserRole.RIDER,
        app_client_id=None,
        is_active=True,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "phone_in_use") from None
    # The vehicle is a placeholder until the application says what it is; the
    # rider cannot work before approval copies the real one across.
    db.add(
        Rider(
            user_id=user.id,
            vehicle_type=VehicleType.BIKE,
            status=RiderStatus.OFFLINE,
            onboarding=RiderOnboarding.PENDING,
        )
    )
    db.flush()
    applications.start(db, user)
    if wants_referral:
        from app.services.fleet import referral

        # Checked again with the new rider (self/taken), before the commit:
        # a refusal now leaves nothing half-made.
        try:
            referral.accept_code(db, user.id, payload.referral_code)
        except HTTPException:
            db.rollback()
            raise
    db.commit()
    db.refresh(user)
    return _auth_response(db, user)


# --- forgot password ----------------------------------------------------------
#
# The sign-up code machinery with its own purpose (`phone.RESET`). Unlike
# sign-up these say whether the number has an account: sign-up already
# answers `phone_in_use` for the same question, so hiding it here would
# protect nothing and leave a rider who mistyped their number waiting for a
# code that is never coming.


def _rider_for_reset(db: Session, number: str) -> User:
    user = db.scalar(select(User).where(User.phone_number == number, User.role == UserRole.RIDER).limit(1))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no_account")
    # A deactivated rider is off the fleet by the admin's decision; a reset
    # must not be a way back in around it.
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account_inactive")
    return user


@router.post("/password/code", response_model=SignupCodeResponse)
def password_code(
    _rate_limited: Annotated[None, Depends(per_ip("rider-password-code", limit=10, window_seconds=3600))],
    payload: SignupCodeRequest,
    db: Db,
) -> SignupCodeResponse:
    number = _phone(payload.phone_number)
    _rider_for_reset(db, number)
    result = phone.request_code(db, number, purpose=phone.RESET)
    return SignupCodeResponse(sent=result.sent, retry_after=result.retry_after, debug_code=result.debug_code)


@router.post("/password/check", status_code=status.HTTP_204_NO_CONTENT)
def password_check(
    _rate_limited: Annotated[None, Depends(per_ip("rider-password-check", limit=30, window_seconds=3600))],
    payload: SignupCheckRequest,
    db: Db,
) -> Response:
    """The code screen's check, as for sign-up: a typo is said there, and the
    code is only used up by the reset itself."""

    phone.verify_code(db, _phone(payload.phone_number), payload.code, consume=False, purpose=phone.RESET)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password/reset", response_model=AuthResponse)
def password_reset(
    _rate_limited: Annotated[None, Depends(per_ip("rider-password-reset", limit=10, window_seconds=3600))],
    payload: PasswordResetRequest,
    db: Db,
) -> AuthResponse:
    number = _phone(payload.phone_number)
    user = _rider_for_reset(db, number)
    phone.verify_code(db, number, payload.code, purpose=phone.RESET)
    reset_own_password(db, user, payload.password)
    db.refresh(user)
    # Signed straight in with the new password's session: the rider proved
    # the phone is theirs a moment ago, typing the password again proves less.
    return _auth_response(db, user)


@router.get("/application", response_model=ApplicationView)
def my_application(user: RiderUser, db: Db) -> ApplicationView:
    return application_view(db, _mine(db, user))


@router.put("/application/{section}", response_model=ApplicationView)
def save_section(section: str, body: dict[str, Any], user: RiderUser, db: Db) -> ApplicationView:
    if section not in applications.SECTIONS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown section")
    _mine(db, user)
    app = applications.save_section(db, user, section, body, today=date.today())  # type: ignore[arg-type]
    return application_view(db, app)


@router.post("/application/items/{kind}", response_model=ApplicationView)
def upload_item(
    kind: ApplicationItemKind, user: RiderUser, db: Db, file: Annotated[UploadFile, File()]
) -> ApplicationView:
    # A plain `def`, so FastAPI runs it in a worker thread: the storage upload
    # is a blocking network call, and Socket.IO shares this event loop - an
    # `async` route here stalled every board and rider on the worker.
    _mine(db, user)
    # Read one byte past the limit: an oversized photo is refused without
    # being copied into memory whole. (Starlette has already spooled the
    # request to a temporary file by now; memory is bounded, disk is not.)
    data = file.file.read(get_settings().rider_doc_max_bytes + 1)
    applications.save_photo(db, user, kind, data)
    return application_view(db, db.get(RiderApplication, user.id))


@router.post("/application/submit", response_model=ApplicationView)
def submit(user: RiderUser, db: Db) -> ApplicationView:
    _mine(db, user)
    return application_view(db, applications.submit(db, user))


def _mine(db: Session, user: User) -> RiderApplication:
    app = db.get(RiderApplication, user.id)
    if app is None:
        # An admin-made rider has no application; there is nothing to show.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no_application")
    return app

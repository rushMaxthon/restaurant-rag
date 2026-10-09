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

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
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
    SignupCodeRequest,
    SignupCodeResponse,
    SignupRequest,
)
from app.services.auth import hash_password, require_rider
from app.services.fleet.onboarding import applications, phone
from app.services.fleet.onboarding.views import application_view
from app.services.fleet.riders import _phone_taken, _placeholder_email, canonical_phone
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


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(
    _rate_limited: Annotated[None, Depends(per_ip("rider-signup", limit=10, window_seconds=3600))],
    payload: SignupRequest,
    db: Db,
) -> AuthResponse:
    number = _phone(payload.phone_number)
    if _phone_taken(db, number):
        raise HTTPException(status.HTTP_409_CONFLICT, "phone_in_use")
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
    db.commit()
    db.refresh(user)
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
async def upload_item(
    kind: ApplicationItemKind, user: RiderUser, db: Db, file: Annotated[UploadFile, File()]
) -> ApplicationView:
    _mine(db, user)
    # Read one byte past the limit and no further: a 50 MB upload is refused
    # without ever being held in memory whole.
    data = await file.read(get_settings().rider_doc_max_bytes + 1)
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

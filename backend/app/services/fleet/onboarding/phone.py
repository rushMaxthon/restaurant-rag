"""Sign-up codes for a rider's phone.

One live code per phone, stored only as an HMAC (so a database read cannot be
turned into somebody's account), valid 10 minutes, 5 wrong tries and it is
locked, a new one at most once a minute and five an hour.

Two modes (`rider_signup_otp_mode`):
- `static` (for now, the owner's decision until Meta approves a template):
  the code is `otp_debug_code`, on every environment, and nothing is sent.
  The limits and the lock still apply, so the flow behaves as it will.
- `whatsapp`: a random code through the Business number's AUTHENTICATION
  template. No template configured means 503 `no_sender`, said out loud.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.rider_application import PhoneVerification

PURPOSE = "RIDER_SIGNUP"
VALID_FOR = timedelta(minutes=10)
RESEND_AFTER = timedelta(seconds=60)
PER_HOUR = 5
MAX_ATTEMPTS = 5


@dataclass(frozen=True, slots=True)
class RequestResult:
    sent: bool
    retry_after: int
    #: Only in static mode: what to type. The app shows it as "Test code".
    debug_code: str | None = None


def _hash(phone: str, code: str) -> str:
    key = get_settings().jwt_secret_key.encode()
    return hmac.new(key, f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def _latest(db: Session, phone: str) -> PhoneVerification | None:
    return db.scalar(
        select(PhoneVerification)
        .where(PhoneVerification.phone == phone, PhoneVerification.purpose == PURPOSE)
        .order_by(PhoneVerification.created_at.desc())
        .limit(1)
    )


def mode() -> str:
    return get_settings().rider_signup_otp_mode.strip().lower()


def request_code(db: Session, phone: str, now: datetime | None = None) -> RequestResult:
    now = now or datetime.now(UTC)
    settings = get_settings()
    latest = _latest(db, phone)
    if latest is not None and now - latest.created_at < RESEND_AFTER:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "code_too_soon")
    sent_last_hour = db.scalar(
        select(func.count())
        .select_from(PhoneVerification)
        .where(
            PhoneVerification.phone == phone,
            PhoneVerification.purpose == PURPOSE,
            PhoneVerification.created_at >= now - timedelta(hours=1),
        )
    )
    if (sent_last_hour or 0) >= PER_HOUR:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "code_too_many")

    whatsapp_mode = mode() == "whatsapp"
    if whatsapp_mode:
        if not settings.whatsapp_otp_template:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "no_sender")
        code = f"{secrets.randbelow(10**6):06d}"
    else:
        code = settings.otp_debug_code

    db.add(
        PhoneVerification(
            phone=phone, purpose=PURPOSE, code_hash=_hash(phone, code), expires_at=now + VALID_FOR, created_at=now
        )
    )
    db.commit()

    if whatsapp_mode:
        from app.services import whatsapp

        if not whatsapp.send_template(phone, settings.whatsapp_otp_template, [code]):
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "send_failed")
        return RequestResult(sent=True, retry_after=int(RESEND_AFTER.total_seconds()))
    return RequestResult(sent=False, retry_after=int(RESEND_AFTER.total_seconds()), debug_code=code)


def verify_code(
    db: Session, phone: str, code: str, now: datetime | None = None, *, consume: bool = True
) -> None:
    """Passes, or raises `code_expired` (also: already used, or none sent),
    `code_locked` or `code_wrong`. A pass uses the code up, unless `consume`
    is False: the code screen checks it so a typo is said THERE, before the
    rider types a name and password, and sign-up then uses it. A wrong guess
    counts towards the lock either way."""

    now = now or datetime.now(UTC)
    row = _latest(db, phone)
    if row is None or row.verified_at is not None or row.expires_at <= now:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "code_expired")
    if row.attempts >= MAX_ATTEMPTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "code_locked")
    if not hmac.compare_digest(row.code_hash, _hash(phone, (code or "").strip())):
        row.attempts += 1
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "code_wrong")
    if consume:
        row.verified_at = now
        db.commit()

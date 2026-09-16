"""The account behind a verified phone number.

A customer ordering over WhatsApp cannot sign in, and asking them to would
end the conversation. What they do have is a phone number Meta has already
verified belongs to them — a stronger claim than anything typed into a form,
and the one thing this app already treats as an identity: customer
uniqueness is `(app_client_id, phone_number)`, and the mobile app signs in
by phone.

So the number becomes an account. `create_order` then works unchanged, the
order belongs to somebody, and a returning customer is recognised with their
history and their saved address instead of being asked everything again.

**Only ever call this with a number a channel has verified.** A number typed
into a web chat proves nothing: anyone can type anyone's. That path signs in
instead, which is why this takes `verified` rather than assuming it.
"""

from __future__ import annotations

import logging
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import UserRole
from app.models.user import User
from app.services.auth import hash_password, normalize_phone_number

logger = logging.getLogger(__name__)


class PhoneNotVerified(Exception):
    """Raised rather than quietly provisioning from an unverified number."""


def customer_for_verified_phone(
    db: Session,
    *,
    phone_number: str,
    app_client_id: uuid.UUID | None,
    verified: bool,
    full_name: str,
    email: str,
) -> User:
    """Find or create the customer this verified number belongs to.

    `full_name` and `email` are required columns, so an account cannot be
    provisioned before the conversation has collected them — which is why the
    draft gathers them first and this runs at the moment of placing, not at
    the first "hello".

    The password is random and never shown to anyone. This account is reached
    by proving the number, not by typing a secret; leaving the column empty
    was not an option and a guessable value would be worse than a random one
    nobody holds.
    """

    if not verified:
        raise PhoneNotVerified("Refusing to provision an account from an unverified number.")
    normalized = normalize_phone_number(phone_number)
    if not normalized:
        raise PhoneNotVerified(f"Not a usable phone number: {phone_number!r}")

    existing = db.scalar(
        select(User).where(
            User.phone_number == normalized,
            User.role == UserRole.CUSTOMER,
            User.app_client_id == app_client_id,
        )
    )
    if existing is not None:
        return existing

    user = User(
        full_name=full_name.strip()[:255],
        email=email.strip().lower()[:255],
        phone_number=normalized,
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        role=UserRole.CUSTOMER,
        app_client_id=app_client_id,
        is_active=True,
        # The number is verified — that is the whole premise of this function
        # — so there is nothing left for the customer to confirm.
        is_verified=True,
    )
    db.add(user)
    db.flush()
    logger.info(
        "Provisioned a customer from a verified phone user_id=%s app_client_id=%s",
        user.id,
        app_client_id,
    )
    return user


__all__ = ["PhoneNotVerified", "customer_for_verified_phone"]

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


class EmailAlreadyUsed(Exception):
    """The email belongs to another account in this app.

    Not an error to swallow: handing a verified phone the account that owns
    an address would let anyone claim a stranger's order history by typing
    their email.
    """


def find_customer(
    db: Session,
    *,
    phone_number: str,
    app_client_id: uuid.UUID | None,
) -> User | None:
    """The customer this number already belongs to, or None. Creates nothing.

    `customer_for_verified_phone` provisions, which is right at the moment
    an order is placed and wrong at the start of a conversation: asking a
    returning customer for their name because we only look them up at the
    end is how every conversation started as a stranger.

    Both spellings of the number are accepted, for the same reason they are
    there — a wa_id arrives without its plus, and accounts provisioned
    before that was restored hold the plus-less form.
    """

    normalized = normalize_phone_number(phone_number)
    if not normalized:
        return None
    return db.scalars(
        select(User)
        .where(
            User.phone_number.in_({normalized, normalized.lstrip("+")}),
            User.role == UserRole.CUSTOMER,
            User.app_client_id == app_client_id,
        )
        .order_by(User.phone_number.desc())
    ).first()


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

    # The same number, written either way. A wa_id arrives as E.164 with the
    # "+" stripped, and accounts provisioned from one before that was
    # restored hold the plus-less form — so an exact-string match made a
    # returning customer a stranger, and then refused them their own email
    # address. One number is one person.
    digits = normalized.lstrip("+")
    existing = db.scalars(
        select(User)
        .where(
            User.phone_number.in_({normalized, digits}),
            User.role == UserRole.CUSTOMER,
            User.app_client_id == app_client_id,
        )
        # The canonical spelling first, so a customer holding both rows is
        # served the one every other part of the app would have written.
        .order_by(User.phone_number.desc())
    ).first()
    if existing is not None:
        return existing

    # An email already spoken for in this app belongs to somebody, and a
    # verified phone is no reason to hand them that account: anyone could
    # type a stranger's address and inherit their order history. So the
    # collision is reported and the customer is asked for another one —
    # refusing is the only safe answer here.
    clean_email = email.strip().lower()[:255]
    taken = db.scalar(
        select(User).where(
            User.email == clean_email,
            User.role == UserRole.CUSTOMER,
            User.app_client_id == app_client_id,
        )
    )
    if taken is not None:
        raise EmailAlreadyUsed(clean_email)

    user = User(
        full_name=full_name.strip()[:255],
        email=clean_email,
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


__all__ = [
    "EmailAlreadyUsed",
    "PhoneNotVerified",
    "customer_for_verified_phone",
    "find_customer",
]

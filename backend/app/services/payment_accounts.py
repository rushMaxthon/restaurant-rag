"""Reading and writing a restaurant's own gateway credentials.

The only module that decrypts a payment secret. Everything above it works with
a configured provider or with nothing, and never with a key.

Three rules hold this together, and each of them is a thing that goes wrong
quietly if it is not written down:

**A secret is never returned.** `describe_accounts` is what the admin screen
reads, and it carries the gateway, whether it is on, the public key and the
last four of the secret. There is no endpoint, anywhere, that hands a stored
secret back — not to an admin, not to the owner who typed it.

**A missing key is a missing gateway, not a broken request.** A restaurant
that has not been given an account cannot take that method through its own
account, and the checkout screen offers what is left. Whether it then falls
back to this deployment's own keys is `payments_require_restaurant_account`,
decided in `payments/registry.py` — not here, and never silently: the admin
screen states which account is settling a restaurant.

**Encryption is required, not preferred.** `services/secrets.py` refuses to
store plaintext when no encryption key is configured, and this does not catch
that: a deployment that cannot encrypt a gateway secret must not accept one.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import PaymentGateway
from app.models.restaurant_payment_account import RestaurantPaymentAccount
from app.services.secrets import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PaymentAccountSummary:
    """What the admin screen is allowed to know about an account."""

    gateway: PaymentGateway
    is_enabled: bool
    public_key: str
    # Enough to tell two keys apart when somebody is checking which is live,
    # and useless to anyone who obtains it.
    secret_last4: str | None
    has_webhook_secret: bool
    updated_by: str | None
    updated_at: datetime | None


@dataclass(frozen=True)
class PaymentCredentials:
    """Decrypted credentials, for building a provider and nothing else."""

    gateway: PaymentGateway
    public_key: str
    secret_key: str
    webhook_secret: str | None


def _last4(value: str) -> str:
    cleaned = (value or "").strip()
    return cleaned[-4:] if len(cleaned) >= 4 else "•" * len(cleaned)


def list_accounts(db: Session, *, restaurant_id: uuid.UUID) -> list[RestaurantPaymentAccount]:
    return list(
        db.scalars(
            select(RestaurantPaymentAccount)
            .where(RestaurantPaymentAccount.restaurant_id == restaurant_id)
            .order_by(RestaurantPaymentAccount.gateway.asc())
        ).all()
    )


def describe_accounts(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    actor_names: dict[uuid.UUID, str] | None = None,
) -> list[PaymentAccountSummary]:
    """Every gateway this restaurant has, with no secret in the result."""

    names = actor_names or {}
    return [
        PaymentAccountSummary(
            gateway=row.gateway,
            is_enabled=row.is_enabled,
            public_key=row.public_key,
            secret_last4=row.secret_last4,
            has_webhook_secret=bool(row.webhook_secret_encrypted),
            updated_by=names.get(row.updated_by_user_id) if row.updated_by_user_id else None,
            updated_at=row.updated_at,
        )
        for row in list_accounts(db, restaurant_id=restaurant_id)
    ]


def read_credentials(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    gateway: PaymentGateway,
    require_enabled: bool = True,
) -> PaymentCredentials | None:
    """This restaurant's credentials for one gateway, or None.

    None is the answer for "no account", "switched off", and "the stored
    ciphertext will not decrypt" alike, because every one of them means the
    same thing to a caller: this restaurant cannot take money through this
    gateway right now. A decryption failure is logged loudly — it means the
    encryption key changed under a stored secret — but it must not become a
    500 on a customer's checkout screen.
    """

    row = db.get(RestaurantPaymentAccount, (restaurant_id, gateway))
    if row is None:
        return None
    if require_enabled and not row.is_enabled:
        return None

    try:
        secret = decrypt_secret(row.secret_key_encrypted)
        webhook = (
            decrypt_secret(row.webhook_secret_encrypted)
            if row.webhook_secret_encrypted
            else None
        )
    except Exception:
        logger.exception(
            "Could not decrypt %s credentials for restaurant %s — the encryption key "
            "has probably changed since they were stored, and they must be re-entered",
            gateway.value,
            restaurant_id,
        )
        return None

    return PaymentCredentials(
        gateway=gateway,
        public_key=row.public_key,
        secret_key=secret,
        webhook_secret=webhook,
    )


def save_account(
    db: Session,
    *,
    restaurant_id: uuid.UUID,
    gateway: PaymentGateway,
    public_key: str,
    secret_key: str | None,
    webhook_secret: str | None,
    is_enabled: bool,
    updated_by_user_id: uuid.UUID | None,
) -> RestaurantPaymentAccount:
    """Store or update one gateway's credentials.

    `secret_key` and `webhook_secret` of None mean "leave what is there".
    That is what makes the admin form workable at all: the screen cannot show
    the stored secret, so it submits an empty field whenever nobody retyped
    it, and treating that as "clear it" would wipe a live gateway every time
    somebody toggled it on.

    The caller commits.
    """

    row = db.get(RestaurantPaymentAccount, (restaurant_id, gateway))
    if row is None:
        if not secret_key:
            raise ValueError("A secret key is required the first time a gateway is added.")
        row = RestaurantPaymentAccount(restaurant_id=restaurant_id, gateway=gateway)
        db.add(row)

    row.public_key = (public_key or "").strip()
    if secret_key:
        cleaned = secret_key.strip()
        # `encrypt_secret` raises when the deployment has no encryption key.
        # Deliberately uncaught: storing a gateway secret in plaintext is not
        # a degraded mode, it is a different product.
        row.secret_key_encrypted = encrypt_secret(cleaned)
        row.secret_last4 = _last4(cleaned)
    if webhook_secret is not None:
        row.webhook_secret_encrypted = (
            encrypt_secret(webhook_secret.strip()) if webhook_secret.strip() else None
        )
    row.is_enabled = is_enabled
    row.updated_by_user_id = updated_by_user_id

    # No key material in the log line, on purpose.
    logger.info(
        "Payment account %s for restaurant %s saved (enabled=%s, webhook=%s) by %s",
        gateway.value,
        restaurant_id,
        is_enabled,
        bool(row.webhook_secret_encrypted),
        updated_by_user_id,
    )
    return row


def delete_account(db: Session, *, restaurant_id: uuid.UUID, gateway: PaymentGateway) -> bool:
    """Forget a gateway entirely. The caller commits."""

    row = db.get(RestaurantPaymentAccount, (restaurant_id, gateway))
    if row is None:
        return False
    db.delete(row)
    logger.info("Payment account %s removed for restaurant %s", gateway.value, restaurant_id)
    return True


__all__ = [
    "PaymentAccountSummary",
    "PaymentCredentials",
    "delete_account",
    "describe_accounts",
    "list_accounts",
    "read_credentials",
    "save_account",
]

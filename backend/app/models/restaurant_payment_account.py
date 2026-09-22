"""A restaurant's own gateway account.

The money goes to the restaurant, not to this platform. That is the whole
point of the record: one deployment serves every tenant, and each one holds
its own credentials with its own gateway, so a charge made on Radhe Dhokla's
storefront settles into Radhe Dhokla's account.

**The secret never leaves the server.** Every gateway issues two credentials:
a public one the browser needs to open a checkout, and a secret one that
creates charges and issues refunds. `public_key` is sent to the storefront;
`secret_key_encrypted` and `webhook_secret_encrypted` are encrypted at rest by
`services/secrets.py` and are only ever decrypted inside a request that is
already talking to the gateway. A read endpoint never returns either.

One row per restaurant per gateway, so a restaurant can hold both — an Indian
kitchen taking UPI through Razorpay while also accepting foreign cards through
Stripe — and enable them independently.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import PaymentGateway


class RestaurantPaymentAccount(Base):
    __tablename__ = "restaurant_payment_accounts"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    gateway: Mapped[PaymentGateway] = mapped_column(
        Enum(PaymentGateway, name="payment_gateway"),
        primary_key=True,
    )
    # Separate from having credentials: an account can be configured and
    # switched off, which is how a restaurant pauses a gateway without anyone
    # having to paste keys again to bring it back.
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Razorpay's `key_id`, Stripe's `pk_...`. Public by design — it is in the
    # page source of every checkout that uses it.
    public_key: Mapped[str] = mapped_column(String(255), nullable=False)
    # Fernet ciphertext. Never returned by any endpoint, never logged.
    secret_key_encrypted: Mapped[str] = mapped_column(String(1024), nullable=False)
    # Also Fernet. Separate from the secret because gateways rotate them
    # separately, and a restaurant can be taking payments before its webhook
    # is wired up.
    webhook_secret_encrypted: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # The last four of the secret, for the admin screen. Enough to tell two
    # keys apart when somebody is checking which one is live; useless to
    # anybody who obtains it.
    secret_last4: Mapped[str | None] = mapped_column(String(8), nullable=True)

    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

"""A restaurant's Razorpay linked account, and one payout row per order.

Statuses are stored as strings rather than Postgres enums. Adding a value to a
Postgres enum inside an Alembic upgrade is the trap `0071` documents (unsafe
use of a new value in the same transaction), and these vocabularies are
Razorpay's to extend.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import PayoutAccountStatus


class RestaurantPayoutAccount(Base):
    __tablename__ = "restaurant_payout_accounts"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), primary_key=True
    )
    razorpay_account_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    stakeholder_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    product_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=PayoutAccountStatus.DRAFT.value,
        server_default=PayoutAccountStatus.DRAFT.value,
    )
    legal_business_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    business_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="proprietorship", server_default="proprietorship"
    )
    pan: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    email: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    phone: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    street: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    city: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    state: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    postal_code: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    # Encrypted like a gateway secret; only the last four are ever returned.
    bank_account_number_encrypted: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    bank_account_last4: Mapped[str] = mapped_column(String(4), nullable=False, default="", server_default="")
    ifsc: Mapped[str] = mapped_column(String(11), nullable=False, default="", server_default="")
    beneficiary_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # What Razorpay still needs, as it phrased it, for the screen.
    requirements: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class RestaurantPayout(TimestampMixin, Base):
    __tablename__ = "restaurant_payouts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Unique: one row per order is what makes every step idempotent.
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    payment_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    restaurant_share: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    platform_keeps: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR", server_default="INR")
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    transfer_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="", index=True)
    settlement_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

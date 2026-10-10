"""Referrals between riders and the bonuses they pay (`services/fleet/referral.py`).

`rider_referrals` is keyed by the REFERRED rider: one referrer per rider,
ever. Its terms are copied from the admin's settings when the code is
accepted, so a later change never breaks a promise already made.

`rider_bonuses` is money owed outside trips. UNIQUE (referral_id, kind, step) is
the guard that a reward is written once, whatever races; `payout_id` is set
by the payout that paid it, after which the row never changes. Both are
mirrored in migration 0091, because the test suites build from create_all.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import ReferralStatus, RiderBonusKind


def _enum(cls: type, name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda members: [m.value for m in members])


class RiderReferral(TimestampMixin, Base):
    __tablename__ = "rider_referrals"

    referred_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.user_id", ondelete="CASCADE"), primary_key=True
    )
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    referrer_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    joiner_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    deliveries_required: Mapped[int] = mapped_column(Integer, nullable=False)
    days_allowed: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The milestone steps accepted with the code (v2): [{deliveries,
    #: referrer_amount, joiner_amount}]. The columns above are their totals.
    steps: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    status: Mapped[ReferralStatus] = mapped_column(
        _enum(ReferralStatus, "rider_referral_status"),
        nullable=False,
        default=ReferralStatus.WAITING,
        server_default="WAITING",
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    earned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    cancelled_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (CheckConstraint("referred_user_id <> referrer_user_id", name="not_self"),)


class RiderBonus(TimestampMixin, Base):
    __tablename__ = "rider_bonuses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rider_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.user_id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[RiderBonusKind] = mapped_column(_enum(RiderBonusKind, "rider_bonus_kind"), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    referral_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rider_referrals.referred_user_id", ondelete="CASCADE"), nullable=False
    )
    payout_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rider_payouts.id", ondelete="SET NULL"), nullable=True
    )
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Which milestone step this pays (0-based).
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (
        UniqueConstraint("referral_id", "kind", "step", name="uq_rider_bonuses_referral_kind_step"),
        CheckConstraint("amount > 0", name="positive"),
    )

"""The platform's own riders: who they are, what they were offered, what they carried.

One `riders` row per RIDER account (1:1 with users, keyed by user_id), so a
user is never half a rider. Offers and trips hang off `order_deliveries`, not
`orders`, because the delivery row is the one courier-neutral record of "who
is carrying this" - the same row Pidge's webhook writes. A fallback to Pidge
re-points that row, and the offers and trips here stay as its history.

The two partial unique indexes are the money guards, mirrored in migration
0089 because the test suites build from `create_all`:

* `uq_rider_offers_one_pending` - one open offer per delivery, so two riders
  can never both be looking at an Accept button for the same food;
* `uq_rider_trips_one_live` - one live trip per delivery, so a race between
  two accepts that slips past the row lock still fails at the database.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, Enum, Float, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import OfferOutcome, RiderOnboarding, RiderStatus, TripEndReason, VehicleType


def _enum(cls: type, name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda members: [m.value for m in members])


class Rider(TimestampMixin, Base):
    __tablename__ = "riders"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    vehicle_type: Mapped[VehicleType] = mapped_column(_enum(VehicleType, "rider_vehicle_type"), nullable=False)
    vehicle_number: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    city: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    status: Mapped[RiderStatus] = mapped_column(
        _enum(RiderStatus, "rider_status"), nullable=False, default=RiderStatus.OFFLINE, server_default="OFFLINE"
    )
    status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_location_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fcm_token: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    app_version: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # APPROVED by default, so every rider an admin made - and every rider that
    # existed before self sign-up - keeps working with no backfill. Sign-up
    # sets PENDING; only APPROVED may go online, be offered or claim.
    onboarding: Mapped[RiderOnboarding] = mapped_column(
        _enum(RiderOnboarding, "rider_onboarding"),
        nullable=False,
        default=RiderOnboarding.APPROVED,
        server_default="APPROVED",
    )

    __table_args__ = (Index("ix_riders_status", "status"),)


class RiderPayout(TimestampMixin, Base):
    __tablename__ = "rider_payouts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rider_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.user_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    period_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    trips: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reference: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class RiderOffer(TimestampMixin, Base):
    __tablename__ = "rider_offers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_deliveries.id", ondelete="CASCADE"), nullable=False
    )
    rider_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.user_id", ondelete="CASCADE"), nullable=False
    )
    offered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[OfferOutcome] = mapped_column(
        _enum(OfferOutcome, "rider_offer_outcome"), nullable=False, default=OfferOutcome.PENDING, server_default="PENDING"
    )
    distance_to_pickup_m: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index(
            "uq_rider_offers_one_pending",
            "order_delivery_id",
            unique=True,
            postgresql_where=text("outcome = 'PENDING'"),
        ),
        Index("ix_rider_offers_rider", "rider_user_id", "outcome"),
        Index("ix_rider_offers_delivery", "order_delivery_id"),
    )


class RiderTrip(TimestampMixin, Base):
    __tablename__ = "rider_trips"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_deliveries.id", ondelete="CASCADE"), nullable=False
    )
    rider_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.user_id", ondelete="RESTRICT"), nullable=False
    )
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    arrived_pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    arrived_drop_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_reason: Mapped[TripEndReason | None] = mapped_column(
        _enum(TripEndReason, "rider_trip_end_reason"), nullable=True
    )
    call_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    earning_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    earning_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: Client action ids already applied: a retried request on a bad network
    #: is answered with the trip as it is, and nothing happens twice.
    applied_actions: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    payout_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rider_payouts.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index(
            "uq_rider_trips_one_live",
            "order_delivery_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        Index("ix_rider_trips_rider", "rider_user_id", "accepted_at"),
    )


__all__ = ["Rider", "RiderOffer", "RiderPayout", "RiderTrip"]

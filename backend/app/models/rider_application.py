"""A rider's own application to join the fleet, and the phone codes behind sign-up.

The application is 1:1 with the rider (who exists from the moment they sign
up, PENDING). Each reviewable thing - a typed-in section, or one side of a
document - is its own `rider_application_items` row with its own status and
reason, so an admin can send back only the blurry licence photo and the rider
fixes only that. `rider_application_events` is the audit trail of who decided
what.

Sensitive numbers are never stored in the clear: Aadhaar as its last four
digits only (the full number is never asked for), PAN, licence and bank
account Fernet-encrypted beside a last-four for display.

Mirrored in migration 0090; the test suites build from `create_all`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin
from app.models.enums import ApplicationAction, ApplicationItemKind, ApplicationStatus, ItemStatus, VehicleType


def _enum(cls: type, name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda members: [m.value for m in members])


class RiderApplication(TimestampMixin, Base):
    __tablename__ = "rider_applications"

    rider_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("riders.user_id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[ApplicationStatus] = mapped_column(
        _enum(ApplicationStatus, "rider_application_status"),
        nullable=False,
        default=ApplicationStatus.DRAFT,
        server_default="DRAFT",
    )
    full_name: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    city: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    address_line: Mapped[str] = mapped_column(String(240), nullable=False, default="", server_default="")
    pincode: Mapped[str] = mapped_column(String(6), nullable=False, default="", server_default="")
    emergency_name: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    emergency_phone: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    vehicle_type: Mapped[VehicleType | None] = mapped_column(_enum(VehicleType, "rider_vehicle_type"), nullable=True)
    vehicle_number: Mapped[str] = mapped_column(String(16), nullable=False, default="", server_default="")
    aadhaar_last4: Mapped[str] = mapped_column(String(4), nullable=False, default="", server_default="")
    pan_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    pan_last4: Mapped[str] = mapped_column(String(4), nullable=False, default="", server_default="")
    licence_number_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    licence_last4: Mapped[str] = mapped_column(String(4), nullable=False, default="", server_default="")
    licence_expiry: Mapped[date | None] = mapped_column(Date, nullable=True)
    bank_holder: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    bank_account_encrypted: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    bank_account_last4: Mapped[str] = mapped_column(String(4), nullable=False, default="", server_default="")
    ifsc: Mapped[str] = mapped_column(String(11), nullable=False, default="", server_default="")
    upi_id: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    final_reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    __table_args__ = (Index("ix_rider_applications_status", "status", "submitted_at"),)


class RiderApplicationItem(TimestampMixin, Base):
    __tablename__ = "rider_application_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rider_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rider_applications.rider_user_id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[ApplicationItemKind] = mapped_column(
        _enum(ApplicationItemKind, "rider_application_item_kind"), nullable=False
    )
    status: Mapped[ItemStatus] = mapped_column(
        _enum(ItemStatus, "rider_application_item_status"),
        nullable=False,
        default=ItemStatus.MISSING,
        server_default="MISSING",
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # Null for the typed-in sections; a private-bucket path for a photo.
    storage_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str] = mapped_column(String(40), nullable=False, default="", server_default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("rider_user_id", "kind", name="uq_rider_application_items_kind"),)


class RiderApplicationEvent(Base):
    __tablename__ = "rider_application_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rider_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rider_applications.rider_user_id", ondelete="CASCADE"), nullable=False
    )
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[ApplicationAction] = mapped_column(
        _enum(ApplicationAction, "rider_application_action"), nullable=False
    )
    item_kind: Mapped[ApplicationItemKind | None] = mapped_column(
        _enum(ApplicationItemKind, "rider_application_item_kind"), nullable=True
    )
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    __table_args__ = (Index("ix_rider_application_events_rider", "rider_user_id", "at"),)


class PhoneVerification(Base):
    """A sign-up code sent to a phone. The code itself is never stored, only
    its HMAC, so a database read cannot be turned into somebody's account."""

    __tablename__ = "phone_verifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_phone_verifications_phone", "phone", "purpose", "created_at"),)

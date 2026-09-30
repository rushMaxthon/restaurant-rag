from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class UserSavedAddress(TimestampMixin, Base):
    __tablename__ = "user_saved_addresses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(24), nullable=False, default="OTHER")
    address_line_1: Mapped[str] = mapped_column(Text, nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    landmark: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    state: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    postal_code: Mapped[str] = mapped_column(
        String(20), nullable=False, default="", server_default=""
    )
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Filled when the customer picked this address from the autocomplete, so
    # the coordinates are the ones Google holds for that building rather than
    # an interpretation of the text below. This is what makes a repeat order
    # cost ZERO geocoder calls: the point is already on the row.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    # `GeocodeConfidence`, so a delivery is never priced from a city centroid
    # that happens to be stored here. Empty means nobody has located it.
    geocode_confidence: Mapped[str] = mapped_column(
        String(16), nullable=False, default="", server_default=""
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    user: Mapped["User"] = relationship(back_populates="saved_addresses")

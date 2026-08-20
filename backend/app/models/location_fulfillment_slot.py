from __future__ import annotations

import uuid
from datetime import time
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import LocationDayOfWeek, OrderFulfillmentType

if TYPE_CHECKING:
    from app.models.restaurant_location import RestaurantLocation


class LocationFulfillmentSlot(TimestampMixin, Base):
    __tablename__ = "location_fulfillment_slots"
    __table_args__ = (
        UniqueConstraint(
            "location_id",
            "day_of_week",
            "fulfillment_type",
            "start_time",
            "end_time",
            name="uq_location_fulfillment_slots_window",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurant_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day_of_week: Mapped[LocationDayOfWeek] = mapped_column(
        Enum(LocationDayOfWeek, name="location_day_of_week"),
        nullable=False,
        index=True,
    )
    fulfillment_type: Mapped[OrderFulfillmentType] = mapped_column(
        Enum(OrderFulfillmentType, name="order_fulfillment_type"),
        nullable=False,
        index=True,
    )
    start_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    end_time: Mapped[time] = mapped_column(Time(timezone=False), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    location: Mapped["RestaurantLocation"] = relationship(back_populates="fulfillment_slots")

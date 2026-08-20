from __future__ import annotations

import uuid
from datetime import time
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.chat_history import ChatHistory
    from app.models.generated_combo import GeneratedCombo
    from app.models.location_fulfillment_slot import LocationFulfillmentSlot
    from app.models.menu_item import MenuItem
    from app.models.order import Order
    from app.models.restaurant import Restaurant


class RestaurantLocation(TimestampMixin, Base):
    __tablename__ = "restaurant_locations"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "branch_name", name="uq_restaurant_locations_restaurant_id_branch_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    branch_name: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line_1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(120), nullable=False)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    delivery_fee: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    minimum_order_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    estimated_delivery_time: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=30,
        server_default="30",
    )
    estimated_pickup_time: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=20,
        server_default="20",
    )
    delivery_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    pickup_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    google_pay_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    razorpay_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    card_payment_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    cash_on_delivery_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    temporary_closed_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    preparation_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    service_radius_km: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    future_order_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    max_future_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=7,
        server_default="7",
    )
    slot_interval_minutes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=15,
        server_default="15",
    )
    opening_time: Mapped[time | None] = mapped_column(Time(timezone=False), nullable=True)
    closing_time: Mapped[time | None] = mapped_column(Time(timezone=False), nullable=True)

    restaurant: Mapped["Restaurant"] = relationship(back_populates="locations")
    menu_items: Mapped[list["MenuItem"]] = relationship(back_populates="restaurant_location")
    orders: Mapped[list["Order"]] = relationship(back_populates="restaurant_location")
    generated_combos: Mapped[list["GeneratedCombo"]] = relationship(
        back_populates="restaurant_location",
    )
    chat_messages: Mapped[list["ChatHistory"]] = relationship(
        back_populates="restaurant_location",
    )
    fulfillment_slots: Mapped[list["LocationFulfillmentSlot"]] = relationship(
        back_populates="location",
        cascade="all, delete-orphan",
        order_by="LocationFulfillmentSlot.day_of_week.asc(), LocationFulfillmentSlot.start_time.asc()",
    )

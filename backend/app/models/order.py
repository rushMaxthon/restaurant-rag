from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import (
    OrderCancellationReason,
    OrderEventActor,
    OrderFulfillmentType,
    OrderScheduleType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)

if TYPE_CHECKING:
    from app.models.order_item import OrderItem
    from app.models.payment import PaymentTransaction
    from app.models.restaurant import Restaurant
    from app.models.restaurant_location import RestaurantLocation
    from app.models.user import User


class Order(TimestampMixin, Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    restaurant_location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurant_locations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status"),
        nullable=False,
        default=OrderStatus.PLACED,
        server_default=OrderStatus.PLACED.value,
        index=True,
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="payment_status"),
        nullable=False,
        default=PaymentStatus.PENDING,
        server_default=PaymentStatus.PENDING.value,
        index=True,
    )
    payment_method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, name="payment_method"),
        nullable=False,
        default=PaymentMethod.COD,
        server_default=PaymentMethod.COD.value,
        index=True,
    )
    payment_provider: Mapped[str] = mapped_column(String(50), nullable=False, default="mock", server_default="mock")
    payment_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    fulfillment_type: Mapped[OrderFulfillmentType] = mapped_column(
        Enum(OrderFulfillmentType, name="order_fulfillment_type"),
        nullable=False,
        default=OrderFulfillmentType.DELIVERY,
        server_default=OrderFulfillmentType.DELIVERY.value,
        index=True,
    )
    schedule_type: Mapped[OrderScheduleType] = mapped_column(
        Enum(OrderScheduleType, name="order_schedule_type"),
        nullable=False,
        default=OrderScheduleType.ASAP,
        server_default=OrderScheduleType.ASAP.value,
        index=True,
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    delivery_fee: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="INR", server_default="INR")
    special_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivery_address: Mapped[str] = mapped_column(Text, nullable=False)
    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # Why this order was cancelled, when it was. Always system-derived: the
    # platform has no human cancellation flow, so there is nothing to prompt a
    # person for and nothing to guess.
    cancellation_reason: Mapped[OrderCancellationReason | None] = mapped_column(
        Enum(OrderCancellationReason, name="order_cancellation_reason"),
        nullable=True,
        index=True,
    )
    cancelled_by: Mapped[OrderEventActor | None] = mapped_column(
        Enum(OrderEventActor, name="order_event_actor"),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Which offer produced this order, if any. `discount_amount` already records
    # what the offer cost; these record who to credit for the revenue, so an
    # owner can ask whether a promotion actually paid for itself.
    #
    # All nullable: orders placed without an offer, and every order that existed
    # before attribution was added, simply carry no link.
    applied_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personalized_offers.id", ondelete="SET NULL", name="fk_orders_applied_offer"),
        nullable=True,
        index=True,
    )
    applied_generated_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generated_offers.id", ondelete="SET NULL", name="fk_orders_applied_generated_offer"),
        nullable=True,
        index=True,
    )
    applied_offer_user_match_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "generated_offer_user_matches.id",
            ondelete="SET NULL",
            name="fk_orders_applied_offer_match",
        ),
        nullable=True,
        index=True,
    )

    customer: Mapped["User"] = relationship(back_populates="customer_orders", foreign_keys=[customer_id])
    restaurant: Mapped["Restaurant"] = relationship(back_populates="orders")
    restaurant_location: Mapped["RestaurantLocation"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )
    payment_transactions: Mapped[list["PaymentTransaction"]] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
    )

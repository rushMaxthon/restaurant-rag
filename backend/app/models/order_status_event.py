from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import OrderCancellationReason, OrderEventActor, OrderStatus

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.restaurant import Restaurant
    from app.models.user import User


class OrderStatusEvent(TimestampMixin, Base):
    """One recorded transition in an order's life.

    Orders only ever carried their *current* status, so questions an owner
    naturally asks — how long until orders get accepted, where do they stall,
    how long does the kitchen take — had no data behind them. This is that data.

    `from_status` is null for the first event, which records the status the
    order was created in.

    `restaurant_id` is denormalised so the insights layer can scope and group
    without joining `orders` on every query; it is copied from the order at
    write time and never changes.
    """

    __tablename__ = "order_status_events"
    __table_args__ = (
        Index("ix_order_status_events_order_created", "order_id", "created_at"),
        Index("ix_order_status_events_scope_created", "restaurant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="CASCADE", name="fk_order_status_events_order"),
        nullable=False,
        index=True,
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE", name="fk_order_status_events_restaurant"),
        nullable=False,
        index=True,
    )
    restaurant_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "restaurant_locations.id",
            ondelete="SET NULL",
            name="fk_order_status_events_location",
        ),
        nullable=True,
        index=True,
    )
    from_status: Mapped[OrderStatus | None] = mapped_column(
        Enum(OrderStatus, name="order_status"),
        nullable=True,
    )
    to_status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status"),
        nullable=False,
        index=True,
    )
    actor: Mapped[OrderEventActor] = mapped_column(
        Enum(OrderEventActor, name="order_event_actor"),
        nullable=False,
        default=OrderEventActor.SYSTEM,
        server_default=OrderEventActor.SYSTEM.value,
        index=True,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_order_status_events_actor"),
        nullable=True,
    )
    cancellation_reason: Mapped[OrderCancellationReason | None] = mapped_column(
        Enum(OrderCancellationReason, name="order_cancellation_reason"),
        nullable=True,
    )
    # Free-form context for debugging (the task that wrote it, the provider
    # error). Never shown to an owner and never used in analytics.
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    order: Mapped["Order"] = relationship()
    restaurant: Mapped["Restaurant"] = relationship()
    actor_user: Mapped["User | None"] = relationship()


__all__ = ["OrderStatusEvent"]

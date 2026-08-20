from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import OrderEventActor

if TYPE_CHECKING:
    from app.models.menu_item import MenuItem
    from app.models.restaurant import Restaurant
    from app.models.user import User


class MenuItemAvailabilityEvent(TimestampMixin, Base):
    """A record of a dish being switched off or back on.

    `menu_items.is_available` is current-state only, so "this dish sold nothing
    on Tuesday because it was unavailable for six hours" was unanswerable — the
    decline looked like lost demand rather than lost supply. These rows are what
    let the two be told apart.
    """

    __tablename__ = "menu_item_availability_events"
    __table_args__ = (
        Index("ix_menu_availability_item_created", "menu_item_id", "created_at"),
        Index("ix_menu_availability_scope_created", "restaurant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menu_items.id", ondelete="CASCADE", name="fk_menu_availability_item"),
        nullable=False,
        index=True,
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE", name="fk_menu_availability_restaurant"),
        nullable=False,
        index=True,
    )
    restaurant_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "restaurant_locations.id",
            ondelete="SET NULL",
            name="fk_menu_availability_location",
        ),
        nullable=True,
        index=True,
    )
    # The state after the change. A row is only written when it actually differs
    # from the previous state, so the log holds transitions rather than saves.
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    # Name at the time, so a later rename does not rewrite history.
    item_name_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    actor: Mapped[OrderEventActor] = mapped_column(
        Enum(OrderEventActor, name="order_event_actor"),
        nullable=False,
        default=OrderEventActor.SYSTEM,
        server_default=OrderEventActor.SYSTEM.value,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_menu_availability_actor"),
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    menu_item: Mapped["MenuItem"] = relationship()
    restaurant: Mapped["Restaurant"] = relationship()
    actor_user: Mapped["User | None"] = relationship()


__all__ = ["MenuItemAvailabilityEvent"]

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.menu_item import MenuItem
    from app.models.restaurant import Restaurant
    from app.models.restaurant_location import RestaurantLocation


class GeneratedCombo(TimestampMixin, Base):
    __tablename__ = "generated_combos"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
    signature: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    combo_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unique_user_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT", server_default="DRAFT", index=True)
    manual_status_override: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_customer_visible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
    )
    original_total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    suggested_combo_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true", index=True)
    generated_from_orders: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    restaurant: Mapped["Restaurant"] = relationship(back_populates="generated_combos")
    restaurant_location: Mapped["RestaurantLocation"] = relationship(back_populates="generated_combos")
    combo_items: Mapped[list["GeneratedComboItem"]] = relationship(
        back_populates="combo",
        cascade="all, delete-orphan",
        order_by="GeneratedComboItem.sort_order.asc()",
    )


class GeneratedComboItem(TimestampMixin, Base):
    __tablename__ = "generated_combo_items"
    __table_args__ = (
        UniqueConstraint("combo_id", "menu_item_id", name="uq_generated_combo_items_combo_id_menu_item_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    combo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generated_combos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menu_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    combo: Mapped["GeneratedCombo"] = relationship(back_populates="combo_items")
    menu_item: Mapped["MenuItem"] = relationship(back_populates="generated_combo_items")

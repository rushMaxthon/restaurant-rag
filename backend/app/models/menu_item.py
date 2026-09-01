from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.favorite import Favorite
    from app.models.generated_combo import GeneratedComboItem
    from app.models.menu_embedding import MenuEmbedding
    from app.models.menu_item_customization_group import MenuItemCustomizationGroup
    from app.models.menu_item_size import MenuItemSize
    from app.models.order_item import OrderItem
    from app.models.restaurant import Restaurant
    from app.models.restaurant_location import RestaurantLocation


class MenuItem(TimestampMixin, Base):
    __tablename__ = "menu_items"

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
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    cuisine_type: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    is_veg: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_bestseller: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    popularity_score: Mapped[Decimal] = mapped_column(
        Numeric(6, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    # Nullable on purpose: a dish nobody has rated yet has no rating, which is
    # a different fact from a rating of zero and has to render differently.
    rating: Mapped[Decimal | None] = mapped_column(Numeric(2, 1), nullable=True)
    rating_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    launched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        server_default=func.now(),
    )
    is_new_launch: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        index=True,
    )
    has_sizes: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    has_customizations: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )

    restaurant: Mapped["Restaurant"] = relationship(back_populates="menu_items")
    restaurant_location: Mapped["RestaurantLocation"] = relationship(back_populates="menu_items")
    embedding: Mapped["MenuEmbedding | None"] = relationship(
        back_populates="menu_item",
        uselist=False,
        cascade="all, delete-orphan",
    )
    favorites: Mapped[list["Favorite"]] = relationship(
        back_populates="menu_item",
        cascade="all, delete-orphan",
    )
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="menu_item")
    generated_combo_items: Mapped[list["GeneratedComboItem"]] = relationship(back_populates="menu_item")
    sizes: Mapped[list["MenuItemSize"]] = relationship(
        back_populates="menu_item",
        cascade="all, delete-orphan",
    )
    customization_groups: Mapped[list["MenuItemCustomizationGroup"]] = relationship(
        back_populates="menu_item",
        cascade="all, delete-orphan",
    )

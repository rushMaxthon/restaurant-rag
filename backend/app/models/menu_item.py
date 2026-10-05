from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, and_, func, or_
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.hybrid import hybrid_property
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
    # Mirrored from migration 0078 because the test suites build from
    # `create_all` and never run a migration. The bare name: the metadata's
    # naming convention adds `ck_menu_items_` to it.
    __table_args__ = (
        CheckConstraint(
            "stock_quantity IS NULL OR stock_quantity >= 0",
            name="stock_quantity_not_negative",
        ),
        CheckConstraint(
            "stock_daily_quantity IS NULL OR stock_daily_quantity >= 0",
            name="stock_daily_quantity_not_negative",
        ),
    )

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
    #: What the owner typed, where `price` is what the customer pays: the
    #: typed figure plus the branch's `commission_percent`. NULL means the
    #: two are the same figure and nothing has yet needed to tell them apart.
    base_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    is_veg: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    #: How many can still be sold. NULL means nobody is counting, which is a
    #: different fact from zero: zero is sold out, NULL is unlimited. Written
    #: by `services/stock.py` when an order is placed or cancelled, and by the
    #: owner when they restock. See that module for why it is one UPDATE.
    stock_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Marked out of stock by hand. Stays on the menu, cannot be added. A
    #: different fact from a count of zero - nobody need be counting - and
    #: from `is_available`, which takes the dish off the menu altogether.
    out_of_stock: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    #: What the count goes back to each morning (`stock.restock_daily`). NULL
    #: means it is restocked by hand.
    stock_daily_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    @hybrid_property
    def is_on_sale(self) -> bool:
        """Can be ordered right now: switched on, and not sold out.

        The two were one fact until stock existed, and every place that
        suggests a dish - the chat, the recommendations, the cart's "add
        something else" - filtered on `is_available` alone. A dish at zero
        would then be recommended, tapped, and refused at checkout. Those
        places ask this instead. An owner's own menu list does not: they
        need to see the sold-out dish in order to restock it.
        """

        return (
            bool(self.is_available)
            and not self.out_of_stock
            and (self.stock_quantity is None or self.stock_quantity > 0)
        )

    @is_on_sale.inplace.expression
    @classmethod
    def _is_on_sale_expression(cls):
        return and_(
            cls.is_available.is_(True),
            cls.out_of_stock.is_(False),
            or_(cls.stock_quantity.is_(None), cls.stock_quantity > 0),
        )
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

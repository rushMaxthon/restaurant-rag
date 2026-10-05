from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.menu_item import MenuItem
    from app.models.menu_item_customization_group import MenuItemCustomizationGroup


class MenuItemSize(TimestampMixin, Base):
    __tablename__ = "menu_item_sizes"
    # Mirrored from migration 0080; the test suites build from `create_all`.
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
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menu_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    #: What the owner typed. See `MenuItem.base_price`.
    base_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    #: This size's own count. NULL means it has none and draws on the dish's
    #: count instead, one per unit. See `services/stock.py`.
    stock_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock_daily_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)

    menu_item: Mapped["MenuItem"] = relationship(back_populates="sizes")
    customization_groups: Mapped[list["MenuItemCustomizationGroup"]] = relationship(
        back_populates="menu_item_size",
        cascade="all, delete-orphan",
    )

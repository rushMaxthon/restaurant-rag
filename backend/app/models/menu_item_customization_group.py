from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import MenuItemCustomizationSelectionType

if TYPE_CHECKING:
    from app.models.menu_item import MenuItem
    from app.models.menu_item_customization_option import MenuItemCustomizationOption
    from app.models.menu_item_size import MenuItemSize


class MenuItemCustomizationGroup(TimestampMixin, Base):
    __tablename__ = "menu_item_customization_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menu_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    menu_item_size_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menu_item_sizes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    selection_type: Mapped[MenuItemCustomizationSelectionType] = mapped_column(
        Enum(
            MenuItemCustomizationSelectionType,
            name="menu_item_customization_selection_type",
        ),
        nullable=False,
        default=MenuItemCustomizationSelectionType.MULTI,
        server_default=MenuItemCustomizationSelectionType.MULTI.value,
    )
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    min_selection: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_selection: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    menu_item: Mapped["MenuItem"] = relationship(back_populates="customization_groups")
    menu_item_size: Mapped["MenuItemSize | None"] = relationship(back_populates="customization_groups")
    options: Mapped[list["MenuItemCustomizationOption"]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
    )

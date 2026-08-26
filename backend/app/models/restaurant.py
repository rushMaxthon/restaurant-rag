from __future__ import annotations

import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.app_client import AppClient
    from app.models.chat_history import ChatHistory
    from app.models.generated_combo import GeneratedCombo
    from app.models.menu_item import MenuItem
    from app.models.order import Order
    from app.models.restaurant_location import RestaurantLocation
    from app.models.user import User


class Restaurant(TimestampMixin, Base):
    __tablename__ = "restaurants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cuisine_type: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    address_line_1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line_2: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(120), nullable=False)
    country: Mapped[str] = mapped_column(String(120), nullable=False, default="India", server_default="India")
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    minimum_order_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    delivery_fee: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    is_approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    logo_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cover_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # The restaurant's own look, owned by the owner rather than by whoever
    # configured its mobile build. Empty means "use the platform default", which
    # is what every restaurant starts as.
    theme: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    owner: Mapped["User"] = relationship(back_populates="owned_restaurant", foreign_keys=[owner_id])
    # One app client per restaurant is a product rule, not a DB constraint:
    # `app_clients.restaurant_id` is nullable so MARKETPLACE clients can exist
    # without a restaurant, and its FK is ON DELETE RESTRICT.
    app_client: Mapped["AppClient | None"] = relationship(
        back_populates="restaurant",
        uselist=False,
    )
    locations: Mapped[list["RestaurantLocation"]] = relationship(
        back_populates="restaurant",
        cascade="all, delete-orphan",
        order_by="RestaurantLocation.created_at.asc()",
    )
    menu_items: Mapped[list["MenuItem"]] = relationship(
        back_populates="restaurant",
        cascade="all, delete-orphan",
    )
    orders: Mapped[list["Order"]] = relationship(back_populates="restaurant")
    chat_messages: Mapped[list["ChatHistory"]] = relationship(back_populates="restaurant")
    generated_combos: Mapped[list["GeneratedCombo"]] = relationship(
        back_populates="restaurant",
        cascade="all, delete-orphan",
    )

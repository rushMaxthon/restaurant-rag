from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User


class UserPreferences(TimestampMixin, Base):
    __tablename__ = "user_preferences"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    favorite_cuisines: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    disliked_cuisines: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    dietary_preferences: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    preferred_meal_times: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    price_sensitivity: Mapped[Decimal] = mapped_column(
        Numeric(4, 2),
        nullable=False,
        default=Decimal("1.00"),
        server_default="1.00",
    )
    average_budget: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    cuisine_affinity_scores: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    spice_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    budget_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    favorite_items: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    last_recalculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="preferences")

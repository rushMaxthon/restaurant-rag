"""A commercial decision about one restaurant, with its provenance.

Deliberately NOT `AppClient.config`, which was the first instinct and is
wrong: that JSONB is *build* configuration with additive-merge semantics,
marketplace clients have no restaurant at all, JSONB carries no per-key actor
or timestamp, you cannot answer "who has Ask AI" with an index, and one
careless whole-object write silently drops keys. A grant is a record of a
decision somebody made, not a config value.

When plans arrive they become a nullable `plan_id` and a resolution layer
*below* this table, so no call site changes.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RestaurantCapability(Base):
    """One restaurant's answer for one capability key.

    No row means "the catalog default", which is what makes onboarding a
    restaurant need zero rows and what makes shipping the catalog a no-op for
    every tenant that already exists.
    """

    __tablename__ = "restaurant_capabilities"

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Validated against `config/capabilities.py` on the way in, never trusted
    # on the way out — a key that leaves the catalog must not break a read.
    capability_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Who decided, and why. A capability that is off with nobody's name on it
    # is the state that made the deleted allowlist harmful.
    granted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

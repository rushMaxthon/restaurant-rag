"""A platform-wide value an administrator sets from the panel.

The first is "delivery_pricing" (2026-10-07): the distance slabs, how far the
platform delivers and the GST on delivery, which apply to every restaurant.
Environment settings could not do that job - changing one needs a deploy -
and a restaurant's own row is the wrong home for a rule that is the same for
all of them.

One row per key, written only through `services/delivery/slabs.py`, which
validates before it saves. No row means the settings default, so a fresh
database prices exactly as the code does without one.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PlatformSetting(Base):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Who last changed it. A price every customer pays deserves a name on it.
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import ChatMessageRole

if TYPE_CHECKING:
    from app.models.restaurant import Restaurant
    from app.models.restaurant_location import RestaurantLocation
    from app.models.user import User


class OwnerChatMessage(TimestampMixin, Base):
    """One turn of an owner's conversation with the AI Restaurant Manager.

    Deliberately separate from `chat_history`, which serves the customer RAG
    assistant. That table is shaped around menu retrieval and carries a nullable
    restaurant, whereas every owner turn is bound to exactly one restaurant.
    Keeping them apart makes the tenancy boundary structural rather than a
    convention someone has to remember.

    `facts` stores the numbers the answer was allowed to state, so any reply can
    be audited against the data that produced it long after the fact.
    """

    __tablename__ = "owner_chat_messages"
    __table_args__ = (
        Index("ix_owner_chat_messages_scope_session", "restaurant_id", "session_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE", name="fk_owner_chat_restaurant"),
        nullable=False,
        index=True,
    )
    restaurant_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "restaurant_locations.id", ondelete="SET NULL", name="fk_owner_chat_location"
        ),
        nullable=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_owner_chat_user"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    role: Mapped[ChatMessageRole] = mapped_column(
        Enum(ChatMessageRole, name="chat_message_role"),
        nullable=False,
        index=True,
    )
    # Position within the turn: 0 for the question, 1 for the answer. Both rows
    # are written in one transaction, where Postgres `now()` returns the same
    # instant for each, so `created_at` alone cannot order them.
    sequence: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Which analysis answered the question, and where the wording came from.
    skill: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    answer_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The parameters the router resolved for this turn. A follow-up inherits
    # them, so "and last month?" keeps the analysis and changes only the window.
    skill_params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    facts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    restaurant: Mapped["Restaurant"] = relationship()
    restaurant_location: Mapped["RestaurantLocation | None"] = relationship()
    user: Mapped["User"] = relationship()


__all__ = ["OwnerChatMessage"]

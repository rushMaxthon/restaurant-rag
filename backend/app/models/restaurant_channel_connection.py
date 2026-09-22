from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import ChannelConnectionStatus

if TYPE_CHECKING:
    from app.models.restaurant import Restaurant


class RestaurantChannelConnection(TimestampMixin, Base):
    """One restaurant's link to one marketing channel.

    Everything a send needs that is not the campaign: which WhatsApp number to
    send from, which Instagram account to post as, which sender id the telecom
    operator approved. It lives per restaurant rather than in settings because
    it *is* per restaurant — two brands on this platform send from two
    different numbers, and a settings value cannot hold both.

    **Absence of a row means the channel is not connected.** There is no
    NOT_CONNECTED status, so the row and the status can never disagree.

    **`config` is shown to the owner; `credentials` is never returned.** The
    split is what lets the Hub render "sending as +91 80 4718 2203" without
    the API ever serialising a token. Note what this is not: the credentials
    column is ordinary JSONB, not encrypted at rest. The protection is that
    Postgres is reachable only by the backend, the column is excluded from
    every response schema, and RLS denies the anon key - the same posture as
    every other secret this database holds. A deployment that needs envelope
    encryption should add it here, in one place.

    Push is the deliberate exception: it has no row. Its credentials are the
    platform's Firebase service account, shared by every restaurant, and
    inventing a per-restaurant connection for it would mean an owner could
    disconnect the channel their order notifications ride on.
    """

    __tablename__ = "restaurant_channel_connections"
    __table_args__ = (
        # One connection per channel per restaurant. Two rows for WhatsApp
        # would make "which number do we send from" a question with two
        # answers, decided by row order.
        UniqueConstraint(
            "restaurant_id", "channel", name="uq_channel_connection_restaurant_channel"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # A string, not a Postgres enum, for the same reason `goal` is: the channel
    # list grows as the Hub grows, and a VARCHAR makes that a code change
    # rather than a migration with an ALTER TYPE in it. The schema layer
    # validates it against `MarketingChannel`.
    channel: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    status: Mapped[ChannelConnectionStatus] = mapped_column(
        Enum(ChannelConnectionStatus, name="channel_connection_status"),
        nullable=False,
        default=ChannelConnectionStatus.CONNECTED,
        server_default="CONNECTED",
        index=True,
    )
    # What the owner may see: sender ids, page names, the from-address. Safe to
    # return, and the Hub renders it so a send is never anonymous to them.
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # What the owner may not see. Excluded from every response schema.
    credentials: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When the credentials were last proven to work against the provider.
    # Separate from `connected_at` because a token that worked in March is not
    # a token that works today, and an owner should be told which they have.
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    restaurant: Mapped["Restaurant"] = relationship()

    def is_sendable(self) -> bool:
        """Whether a campaign may actually go out on this channel.

        ERROR is sendable on purpose. The error may be a verification that
        failed for a reason that has since gone away, and refusing the send
        would leave an owner with no way to find out other than reconnecting.
        The send itself will fail loudly and record why.
        """

        return self.status is not ChannelConnectionStatus.DISABLED

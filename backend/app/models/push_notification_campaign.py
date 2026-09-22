from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import (
    PushNotificationAudience,
    PushNotificationCampaignKind,
    PushNotificationCampaignStatus,
    PushNotificationDeliveryType,
)

if TYPE_CHECKING:
    from app.models.push_notification_campaign_recipient import (
        PushNotificationCampaignRecipient,
    )
    from app.models.push_notification_event import PushNotificationEvent
    from app.models.restaurant import Restaurant
    from app.models.user import User


class PushNotificationCampaign(TimestampMixin, Base):
    """One push send, transactional or marketing.

    The table predates the Marketing Hub and was already a campaign in all but
    name - status, schedule, timezone, deep link and four delivery counters
    were here before any of this. The marketing columns below are additive and
    every one of them is nullable or defaulted, so the transactional path that
    has been writing rows since `order_placed` shipped continues to write
    exactly the same row it always did.

    `kind` is what separates the two. Read paths for the Hub filter on
    MARKETING; the order-status path never sets it and stays TRANSACTIONAL.
    """

    __tablename__ = "push_notification_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    specific_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    restaurant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    audience: Mapped[PushNotificationAudience] = mapped_column(
        Enum(PushNotificationAudience, name="notification_audience"),
        nullable=False,
        index=True,
    )
    delivery_type: Mapped[PushNotificationDeliveryType] = mapped_column(
        Enum(PushNotificationDeliveryType, name="notification_delivery_type"),
        nullable=False,
        default=PushNotificationDeliveryType.INSTANT,
        server_default="INSTANT",
    )
    status: Mapped[PushNotificationCampaignStatus] = mapped_column(
        Enum(PushNotificationCampaignStatus, name="notification_campaign_status"),
        nullable=False,
        default=PushNotificationCampaignStatus.DRAFT,
        server_default="DRAFT",
        index=True,
    )
    template_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    deep_link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata", server_default="Asia/Kolkata")
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    estimated_recipient_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    delivered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    opened_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # --- marketing campaign fields -----------------------------------------
    #
    # All nullable or defaulted: a transactional push sets none of them.

    kind: Mapped[PushNotificationCampaignKind] = mapped_column(
        Enum(PushNotificationCampaignKind, name="notification_campaign_kind"),
        nullable=False,
        default=PushNotificationCampaignKind.TRANSACTIONAL,
        server_default="TRANSACTIONAL",
        index=True,
    )
    # The owner's name for the campaign, which is not the push's title: "May
    # winback push" is what they look for in a list, "We miss you!" is what the
    # customer sees on their lock screen.
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Goal and segment are stored as plain strings validated by the schema
    # layer rather than as Postgres enums. Both are product taxonomy that will
    # gain members as the Hub grows, and a VARCHAR turns each of those into a
    # code change instead of a migration with an ALTER TYPE in it. The status
    # and audience columns above stay enums because the send path branches on
    # them, and a typo there has to fail loudly.
    goal: Mapped[str | None] = mapped_column(String(32), nullable=True)
    segment_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Branch ids as JSONB rather than an association table: the list is read
    # and written whole, always by the campaign that owns it, and is never
    # joined against. A join table would add a migration and two queries to
    # store what is effectively one value.
    branch_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    channels: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default="[]",
    )
    offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generated_offers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # How far through the five-step wizard the draft got, so it reopens where
    # it was left rather than at step one.
    last_step: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=1,
        server_default="1",
    )
    clicked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unsubscribed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # 0..1 while SENDING, so the list can show a live bar. Null when the
    # campaign is not mid-flight - which is different from 0, meaning "started
    # and nothing delivered yet".
    sending_progress: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    # Days after the send in which an order still counts as attributed. Stored
    # per campaign, not read from settings at report time, so a campaign's
    # numbers cannot change retroactively because the default was retuned.
    attribution_window_days: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=7,
        server_default="7",
    )

    created_by_user: Mapped["User | None"] = relationship(
        foreign_keys=[created_by_user_id],
        back_populates="created_push_notification_campaigns",
    )
    specific_user: Mapped["User | None"] = relationship(
        foreign_keys=[specific_user_id],
        back_populates="targeted_push_notification_campaigns",
    )
    restaurant: Mapped["Restaurant | None"] = relationship()
    events: Mapped[list["PushNotificationEvent"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    # Who this went to, one row per customer. Only marketing campaigns have
    # these: a transactional order push is addressed to one person already
    # named by the order.
    recipients: Mapped[list["PushNotificationCampaignRecipient"]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
    )

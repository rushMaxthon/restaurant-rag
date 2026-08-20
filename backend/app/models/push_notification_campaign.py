from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import (
    PushNotificationAudience,
    PushNotificationCampaignStatus,
    PushNotificationDeliveryType,
)

if TYPE_CHECKING:
    from app.models.push_notification_event import PushNotificationEvent
    from app.models.restaurant import Restaurant
    from app.models.user import User


class PushNotificationCampaign(TimestampMixin, Base):
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

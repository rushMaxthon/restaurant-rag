from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import CampaignRecipientState

if TYPE_CHECKING:
    from app.models.push_notification_campaign import PushNotificationCampaign
    from app.models.user import User


class PushNotificationCampaignRecipient(Base):
    """One customer, one campaign, one delivery attempt.

    The row exists so the campaign report can answer "did this cause an order?"
    against the people who actually received it. Segment membership cannot
    answer that: it is recomputed continuously, and by the time a report is
    read it no longer describes who was messaged.
    """

    __tablename__ = "push_notification_campaign_recipients"
    __table_args__ = (
        # What makes a retried send idempotent per recipient: a dispatch that
        # died halfway re-sends to whoever it missed without messaging the rest
        # a second time.
        UniqueConstraint("campaign_id", "user_id", name="uq_push_notification_campaign_recipients_campaign_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("push_notification_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    state: Mapped[CampaignRecipientState] = mapped_column(
        Enum(CampaignRecipientState, name="campaign_recipient_state"),
        nullable=False,
        default=CampaignRecipientState.PENDING,
        server_default=CampaignRecipientState.PENDING.value,
    )
    # The attribution window opens from here, per recipient, not from the
    # campaign's own sent_at: a large send spans minutes, and the last
    # customer's window must not be cut short by the first customer's clock.
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    device_token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    campaign: Mapped["PushNotificationCampaign"] = relationship(back_populates="recipients")
    user: Mapped["User"] = relationship()

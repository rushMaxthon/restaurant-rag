"""One visitor on one restaurant's website on one day.

The whole of "real, not repeated" is the primary key: (restaurant, business
day, visitor). The storefront keeps an anonymous random id in the browser and
sends it with a heartbeat every 60 seconds while the page is on screen; every
beat that day lands on the same row, so reloads, extra tabs and the heartbeat
itself never add a visitor (`services/traffic.py`).

Nothing here identifies a person by itself: the visitor id is random and
generated in the browser, no IP address or user agent is stored, and
`user_id` is filled only once the visitor signs in to the storefront, which is
what lets "visitors who ordered" be counted at all.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StorefrontVisitorDay(Base):
    __tablename__ = "storefront_visitor_days"
    __table_args__ = (
        # "Online now" reads the last two minutes of one restaurant.
        Index("ix_storefront_visitor_days_restaurant_last_seen", "restaurant_id", "last_seen_at"),
        # "Has this visitor been here before?" when a day's first row is written.
        Index("ix_storefront_visitor_days_restaurant_visitor", "restaurant_id", "visitor_id"),
    )

    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    #: The business's day (`business_timezone`), not UTC's.
    visit_date: Mapped[date] = mapped_column(Date, primary_key=True)
    visitor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    #: "phone", "tablet" or "desktop", from the browser's user agent.
    device: Mapped[str] = mapped_column(String(8), nullable=False, default="desktop")
    #: True when this visitor had no earlier day at this restaurant.
    is_new: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    #: The storefront account, once they sign in. Kept when they sign out.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Bit n set = seen during hour n of the business day. One integer rather
    #: than a row per hour, so "busiest hours" counts people, not heartbeats.
    hours_mask: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

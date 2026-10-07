"""The admin panel's Traffic page."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel


class TrafficToday(BaseModel):
    visitors: int
    new: int
    returning: int
    #: "phone", "tablet", "desktop".
    devices: dict[str, int]
    #: Visitors whose storefront account placed an order today here.
    ordered: int
    #: `ordered` as a share of `visitors`; null with no visitors.
    conversion_percent: float | None
    #: Every order placed today at this restaurant, from any channel.
    orders: int


class TrafficDay(BaseModel):
    day: date
    visitors: int
    ordered: int


class TrafficSummaryResponse(BaseModel):
    restaurant_id: uuid.UUID
    #: Visitors with the storefront open in the last 2 minutes.
    online_now: int
    today: TrafficToday
    #: The last 30 business days, oldest first, quiet days as zero.
    daily: list[TrafficDay]
    #: 24 numbers: unique visitors seen in each hour, over the last 7 days.
    hours: list[int]
    generated_at: datetime


class TrafficOverviewRow(BaseModel):
    restaurant_id: uuid.UUID
    restaurant_name: str
    online_now: int
    visitors_today: int
    visitors_yesterday: int
    ordered_today: int
    conversion_percent: float | None


class TrafficOverviewResponse(BaseModel):
    generated_at: datetime
    restaurants: list[TrafficOverviewRow]

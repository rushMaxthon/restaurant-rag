"""The admin's Delivery pricing page: what it reads and what it sends."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class DeliverySlab(BaseModel):
    #: The top of this slab in km, inclusive. Null on the last slab only:
    #: "everything further", up to `max_distance_km`.
    up_to_km: float | None = Field(default=None, gt=0, le=200)
    #: Before GST.
    fee: Decimal = Field(max_digits=8, decimal_places=2)


class DeliveryPricingUpdate(BaseModel):
    slabs: list[DeliverySlab] = Field(min_length=1, max_length=12)
    #: The furthest the platform delivers. A branch's own service radius
    #: still wins where it is set.
    max_distance_km: float = Field(gt=0, le=200)
    gst_percent: Decimal = Field(ge=0, max_digits=5, decimal_places=2)


class DeliveryPricingResponse(DeliveryPricingUpdate):
    #: False while nothing has been saved and the built-in defaults apply.
    saved: bool = False
    updated_at: datetime | None = None
    updated_by_name: str | None = None
    updated_by_user_id: uuid.UUID | None = None

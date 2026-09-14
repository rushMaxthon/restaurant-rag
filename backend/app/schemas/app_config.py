from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import AppMode


class AppConfigResponse(BaseModel):
    """Startup configuration a mobile build resolves from its own bundle ID.

    `restaurant_id` is null for `MARKETPLACE` apps, which browse every
    restaurant, and set for `SINGLE_RESTAURANT` apps, which are scoped to one.
    """

    app_client_id: uuid.UUID
    app_key: str
    app_mode: AppMode
    restaurant_id: uuid.UUID | None
    display_name: str
    branding: dict[str, Any] = Field(default_factory=dict)
    order_prefix: str
    minimum_supported_version: str
    bundle_id: str
    # The clock every opening hour, slot and cutoff in this system is written
    # in. Sent because the client cannot guess it: a browser builds dates in
    # the DEVICE's zone, so a customer in Toronto reading a branch in Ahmedabad
    # would turn the branch's 7pm window into their own 7pm, send an instant
    # nine and a half hours off, and be refused by a server that was right.
    # An IANA name rather than an offset, so DST is the platform's problem.
    business_timezone: str

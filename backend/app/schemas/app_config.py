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

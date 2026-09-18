from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import AppMode


class CurrencyResponse(BaseModel):
    """A currency as a client needs it to format money."""

    code: str
    symbol: str
    locale: str
    # Whole rupees are how an Indian menu is written (₹35, not ₹35.00); cents
    # are how a dollar menu is written. Maximum stays 2 either way, because a
    # total with paise still has to be printable.
    min_fraction_digits: int
    max_fraction_digits: int = 2


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
    # How this configuration was resolved, echoed back. A mobile build gets
    # the bundle id it asked with; a storefront gets the host. Both are
    # optional because a caller only ever supplies one of them.
    bundle_id: str = ""
    host: str = ""
    # The clock every opening hour, slot and cutoff in this system is written
    # in. Sent because the client cannot guess it: a browser builds dates in
    # the DEVICE's zone, so a customer in Toronto reading a branch in Ahmedabad
    # would turn the branch's 7pm window into their own 7pm, send an instant
    # nine and a half hours off, and be refused by a server that was right.
    # An IANA name rather than an offset, so DST is the platform's problem.
    business_timezone: str
    # The restaurant's own words — page title, meta description, hero copy.
    # Sent here because this is the one call a storefront makes before it
    # renders anything, and the title has to be right in the FIRST response or
    # a crawler indexes the wrong business.
    #
    # Empty for a MARKETPLACE client, which is not a restaurant and has no
    # marketing of its own. Every key is always present for one that is, so no
    # client has to decide what to do about a missing field.
    storefront: dict[str, str] = Field(default_factory=dict)
    # What this restaurant charges in, and everything needed to write it.
    #
    # `locale` carries the GROUPING rule rather than the symbol, which matters
    # more than it looks: Indian grouping is 2-2-3, so a client formatting
    # with `en-US` writes ₹1,234,567 where the customer reads ₹12,34,567.
    #
    # Sent alongside the branding it belongs with, because a storefront needs
    # it before it renders its first price and this is the one call it makes
    # before rendering anything.
    currency: CurrencyResponse

"""The platform's view of its own tenants.

Everything else that touches `AppClient` looks at exactly one of them: a
storefront resolving its own branding, an admin editing one restaurant's app
configuration. These are the shapes for the other question — "who is on this
platform, and what state are they in" — which nothing could answer before.

Deliberately a summary rather than the full record. The tenants list renders a
row per restaurant and the switcher renders a name; neither needs the branding
blob, the config blob or the identifier rows, and sending them would make the
one screen that lists every tenant the heaviest response in the API.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import AppClientStatus, AppMode


class TenantSummaryResponse(BaseModel):
    """One tenant as the operator's console lists it."""

    id: uuid.UUID
    app_key: str
    display_name: str
    app_mode: AppMode
    status: AppClientStatus

    # Null for the marketplace client, which is a tenant of this platform
    # without being a restaurant on it.
    restaurant_id: uuid.UUID | None
    restaurant_name: str | None
    restaurant_slug: str | None
    cuisine_type: str | None
    city: str | None
    is_approved: bool | None

    # The address the storefront answers on. `primary_host` is the subdomain
    # this platform issued; a tenant that has since attached its own domain
    # still shows the one we control, because that is the one that always
    # works and the one support will ask them to try.
    primary_host: str | None
    custom_host_count: int

    brand_primary_color: str | None
    # What this tenant charges in, so the console can label its money.
    currency: str

    # Why this tenant is in the state it is. Null on one that has never been
    # touched since onboarding, which is the common case and reads correctly
    # as "nothing has happened to it".
    status_note: str | None
    status_changed_at: datetime | None
    status_changed_by: str | None

    location_count: int
    menu_item_count: int
    order_count: int
    customer_count: int

    created_at: datetime
    updated_at: datetime


class TenantStatusUpdate(BaseModel):
    """A lifecycle change, with the sentence explaining it.

    `note` is required for anything other than reactivation. A tenant whose
    storefront stops answering generates a support call within the hour, and
    "who turned this off and why" should be answerable from the record rather
    than from memory.
    """

    status: AppClientStatus
    note: str | None = Field(default=None, max_length=500)

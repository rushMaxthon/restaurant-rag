"""The shapes for creating and listing a restaurant's kitchen accounts.

A kitchen account is the narrow login an order board runs on. It exists so a
tablet on a kitchen wall is not signed in as the owner — see `UserRole.KITCHEN`
and migration 0071.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class KitchenStaffCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    phone_number: str | None = Field(default=None, min_length=8, max_length=20)
    # Which branch this account sees. Omitted means every branch of the
    # restaurant, which is the right answer for a single-branch restaurant and
    # for a head kitchen — not a missing value to be defaulted.
    restaurant_location_id: uuid.UUID | None = None
    # An ADMIN must name the restaurant because they have none of their own;
    # an OWNER may not, because they have exactly one. `resolve_order_board_scope`
    # is what enforces that, so this is only ever a request.
    restaurant_id: uuid.UUID | None = None


class KitchenStaffUpdate(BaseModel):
    """What may be changed after the fact.

    Deliberately not the email or the password: re-pointing an existing login
    at a different person is how a revoked account quietly comes back. Deactivate
    and create another.
    """

    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    # Explicitly nullable: clearing the branch widens the account to the whole
    # restaurant, which is a real thing an owner may want to do.
    restaurant_location_id: uuid.UUID | None = None
    # Whether the above was sent at all, since None is itself a meaningful
    # value here and Pydantic cannot tell the two apart without this.
    clear_restaurant_location: bool = False
    is_active: bool | None = None


class KitchenStaffResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str
    phone_number: str | None
    is_active: bool
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID | None
    # The branch's own name, so a list of accounts is readable without the
    # caller resolving every id itself.
    branch_name: str | None
    created_at: datetime

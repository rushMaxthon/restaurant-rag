"""What the kitchen sees of a menu, and the only things it may change.

Deliberately its own schemas rather than `MenuItemResponse` with fields left
out: a kitchen screen has no business with prices, commission or the
owner's typed figures, and a request schema that cannot NAME `price` or
`is_available` cannot be used to change them — so "the kitchen may not touch
pricing or visibility" is a property of the type, not of a check somebody
could forget. `extra="forbid"` makes an attempt a 422 rather than a silent
no-op that looks like it worked.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_COUNT = Field(default=None, ge=0, le=1_000_000)


class KitchenMenuSizeResponse(BaseModel):
    id: uuid.UUID
    name: str
    # NULL: this size draws on the dish's count (or nobody counts it).
    stock_quantity: int | None
    stock_daily_quantity: int | None


class KitchenMenuItemResponse(BaseModel):
    id: uuid.UUID
    name: str
    category: str
    is_veg: bool
    restaurant_location_id: uuid.UUID
    branch_name: str
    # The owner's switch. Shown so a cook knows why a dish is missing from the
    # storefront; never writable from here.
    is_available: bool
    out_of_stock: bool
    # NULL is "not counted" (unlimited) — a different fact from 0 (sold out).
    stock_quantity: int | None
    stock_daily_quantity: int | None
    # Exactly what a customer can do right now: `MenuItem.is_on_sale`.
    is_on_sale: bool
    sizes: list[KitchenMenuSizeResponse]
    updated_at: datetime


class KitchenStockUpdate(BaseModel):
    """Only what is sent changes. Sending `stock_quantity: null` stops
    counting; leaving it out keeps the count — the editor-left-open-while-
    three-sold problem `frontend-admin/src/services/menuStock.ts` describes."""

    model_config = ConfigDict(extra="forbid")

    out_of_stock: bool | None = None
    stock_quantity: int | None = _COUNT
    stock_daily_quantity: int | None = _COUNT


class KitchenSizeStockUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stock_quantity: int | None = _COUNT
    stock_daily_quantity: int | None = _COUNT

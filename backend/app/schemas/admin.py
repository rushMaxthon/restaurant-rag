from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import AppMode
from app.schemas.auth import UserResponse


class AdminDashboardStats(BaseModel):
    total_orders: int
    total_revenue: float
    total_restaurants: int
    total_users: int


class RestaurantApprovalUpdate(BaseModel):
    is_approved: bool


class UserStatusUpdate(BaseModel):
    is_active: bool


class AdminUserUpdate(BaseModel):
    """Editable customer details.

    Email is deliberately absent: it is half of the per-app login identity
    (`uq_users_app_client_id_email_customer`), so changing it here would
    silently change who can sign in to the account.
    """

    full_name: str = Field(min_length=2, max_length=255)
    phone_number: str | None = Field(default=None, min_length=8, max_length=20)
    default_address: str | None = Field(default=None, max_length=2000)


class AdminMenuItemResponse(BaseModel):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    restaurant_name: str
    restaurant_location_name: str
    restaurant_city: str
    name: str
    category: str
    cuisine_type: str | None
    description: str | None
    price: Decimal
    is_veg: bool
    is_available: bool
    is_bestseller: bool
    is_featured: bool = False
    image_url: str | None
    recent_valid_order_count: int = 0
    recent_valid_order_window_days: int = 30
    popularity_score: Decimal
    launched_at: datetime
    created_at: datetime
    updated_at: datetime
    is_new_launch: bool = False
    is_new: bool = False


class AdminAILogResponse(BaseModel):
    session_id: uuid.UUID
    user_name: str
    user_email: str
    restaurant_name: str | None
    query_text: str
    reply_text: str
    retrieved_count: int
    filtered_count: int
    suggestions_count: int
    success: bool
    response_time_ms: int | None
    created_at: datetime


class AdminAIOfferGenerationRequest(BaseModel):
    user_limit: int | None = None
    batch_size: int | None = None
    force_refresh: bool = False
    queue_only: bool = False


class OwnerAIOfferGenerationRequest(BaseModel):
    """An owner's request to generate offers for their own restaurant.

    Deliberately has no restaurant field and no `queue_only`: the scope comes
    from the signed-in owner, and the run is always inline so the screen can
    report a result without a worker attached.
    """

    user_limit: int | None = None
    batch_size: int | None = None
    force_refresh: bool = False


class AdminAIOfferGenerationTriggerResponse(BaseModel):
    task_id: str | None = None
    queued: bool
    status: str
    message: str
    ready: bool = False
    successful: bool | None = None
    summary: dict[str, int] | None = None
    error: str | None = None


class AdminAIOfferGenerationStatusResponse(BaseModel):
    task_id: str
    status: str
    ready: bool
    successful: bool | None = None
    summary: dict[str, int] | None = None
    error: str | None = None


class AdminUserResponse(UserResponse):
    """A user row for the admin console, with the app it belongs to.

    Customers are scoped to one app client; `app_label` is what the console
    shows. Platform staff (ADMIN/OWNER) have no app client, so every app field
    is null and the console renders them as platform accounts.
    """

    app_client_id: uuid.UUID | None = None
    app_key: str | None = None
    app_mode: AppMode | None = None
    # Display name of the owning app: the brand for a single-restaurant app,
    # or the marketplace app's own name.
    app_label: str | None = None
    restaurant_id: uuid.UUID | None = None
    restaurant_name: str | None = None

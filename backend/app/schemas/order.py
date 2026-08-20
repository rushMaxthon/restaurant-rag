from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    OrderFulfillmentType,
    OrderScheduleType,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
)


class OrderRestaurantSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    cuisine_type: str
    city: str
    address_line_1: str


class OrderRestaurantLocationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    branch_name: str
    city: str
    address_line_1: str
    delivery_fee: Decimal
    minimum_order_amount: Decimal
    estimated_delivery_time: int
    estimated_pickup_time: int
    delivery_enabled: bool
    pickup_enabled: bool
    enabled_payment_methods: list[PaymentMethod]
    is_open: bool
    is_active: bool


class OrderCustomerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str
    phone_number: str | None


class OrderCreateItemCustomizationOption(BaseModel):
    option_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=99)


class OrderCreateItem(BaseModel):
    menu_item_id: uuid.UUID
    menu_item_size_id: uuid.UUID | None = None
    selected_options: list[OrderCreateItemCustomizationOption] = Field(default_factory=list)
    quantity: int = Field(ge=1, le=99)


class OrderCreateRequest(BaseModel):
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID | None = None
    personalized_offer_id: uuid.UUID | None = None
    generated_offer_id: uuid.UUID | None = None
    generated_offer_user_match_id: uuid.UUID | None = None
    fulfillment_type: OrderFulfillmentType = OrderFulfillmentType.DELIVERY
    schedule_type: OrderScheduleType = OrderScheduleType.ASAP
    scheduled_at: datetime | None = None
    items: list[OrderCreateItem] = Field(min_length=1, max_length=50)
    delivery_address: str = Field(min_length=5, max_length=2000)
    special_instructions: str | None = Field(default=None, max_length=2000)
    payment_method: PaymentMethod = PaymentMethod.COD
    # Accepted for backwards compatibility with older clients and IGNORED. The
    # provider is derived from the method, and the reference is written only by
    # the payment service once a real provider intent exists. A client can never
    # describe its own payment.
    payment_provider: str | None = Field(
        default=None, max_length=50, deprecated=True
    )
    payment_reference: str | None = Field(
        default=None, max_length=255, deprecated=True
    )


class OrderValidationResponse(BaseModel):
    valid: bool = True
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    fulfillment_type: OrderFulfillmentType
    schedule_type: OrderScheduleType
    scheduled_at: datetime
    subtotal: Decimal
    delivery_fee: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    currency: str
    item_count: int


class OrderStatusUpdateRequest(BaseModel):
    status: OrderStatus


class OrderItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    menu_item_id: uuid.UUID
    menu_item_size_id: uuid.UUID | None = None
    item_name_snapshot: str
    size_name_snapshot: str | None = None
    quantity: int
    base_unit_price: Decimal
    customization_total_price: Decimal
    unit_price: Decimal
    total_price: Decimal
    selected_options_snapshot: list[dict[str, object]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class OrderResponse(BaseModel):
    id: uuid.UUID
    customer_id: uuid.UUID
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    restaurant: OrderRestaurantSummary
    restaurant_location: OrderRestaurantLocationSummary
    customer: OrderCustomerSummary
    status: OrderStatus
    payment_status: PaymentStatus
    payment_method: PaymentMethod
    payment_provider: str
    payment_reference: str | None
    fulfillment_type: OrderFulfillmentType
    schedule_type: OrderScheduleType
    scheduled_at: datetime
    subtotal: Decimal
    delivery_fee: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    currency: str
    special_instructions: str | None
    delivery_address: str
    placed_at: datetime
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]

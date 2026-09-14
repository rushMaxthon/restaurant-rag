from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import get_settings
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
    # Who to ring about this delivery. Optional so the mobile client, which
    # does not send them yet, keeps working; the web checkout requires them.
    contact_name: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=32)
    special_instructions: str | None = Field(default=None, max_length=2000)

    @field_validator("contact_name")
    @classmethod
    def clean_contact_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("contact_phone")
    @classmethod
    def normalize_contact_phone(cls, value: str | None) -> str | None:
        """One number, one shape.

        The same phone typed as "(415) 555-0132", "415-555-0132" and
        "+1 415 555 0132" must reach the kitchen identically, or two identical
        numbers look like two different people and nobody can search for one.

        Country code and national length come from settings rather than being
        written in here, so a deployment outside North America changes a
        setting instead of editing a validator.
        """

        if value is None:
            return None
        raw = value.strip()
        if not raw:
            return None

        had_plus = raw.startswith("+")
        digits = "".join(character for character in raw if character.isdigit())
        if not digits:
            raise ValueError("Enter a phone number using digits.")

        settings = get_settings()
        national_length = int(settings.default_phone_national_digits)
        country_code = settings.default_phone_country_code.lstrip("+")

        if had_plus:
            if len(digits) < 8 or len(digits) > 15:
                raise ValueError("Enter a valid phone number, including the country code.")
            return f"+{digits}"

        if len(digits) == national_length:
            return f"+{country_code}{digits}"
        # Typed with the country code but no plus, e.g. "1 415 555 0132".
        if len(digits) == national_length + len(country_code) and digits.startswith(country_code):
            return f"+{digits}"
        raise ValueError(
            f"Enter a {national_length}-digit phone number, or include the country code."
        )
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
    contact_name: str | None = None
    contact_phone: str | None = None
    placed_at: datetime
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]

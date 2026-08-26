from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import (
    AppClientStatus,
    AppMode,
    LocationDayOfWeek,
    OrderFulfillmentType,
    OrderScheduleType,
    PaymentMethod,
)

APP_KEY_PATTERN = r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$"
APP_KEY_MAX_LENGTH = 64
ORDER_NUMBER_PREFIX_MAX_LENGTH = 8
BUNDLE_ID_PATTERN = r"^[a-zA-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z][a-zA-Z0-9_]*)+$"
ORDER_NUMBER_PREFIX_PATTERN = r"^[A-Z][A-Z0-9]{1,7}$"
BRAND_COLOR_PATTERN = r"^#[0-9A-F]{6}$"
APP_VERSION_PATTERN = r"^\d+\.\d+\.\d+$"


class RestaurantBase(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    slug: str = Field(min_length=2, max_length=255, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    description: str | None = None
    cuisine_type: str = Field(min_length=2, max_length=120)
    address_line_1: str = Field(min_length=3, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    city: str = Field(min_length=2, max_length=120)
    state: str = Field(min_length=2, max_length=120)
    country: str = Field(default="India", min_length=2, max_length=120)
    postal_code: str = Field(min_length=3, max_length=20)
    phone_number: str | None = Field(default=None, min_length=8, max_length=20)
    minimum_order_amount: Decimal = Field(default=Decimal("0.00"), ge=0)
    delivery_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    logo_image_url: str | None = Field(default=None, max_length=500)
    cover_image_url: str | None = Field(default=None, max_length=500)


class RestaurantCreate(RestaurantBase):
    is_open: bool = False


class AdminRestaurantCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    owner_name: str = Field(min_length=2, max_length=255)
    owner_email: EmailStr
    owner_password: str = Field(min_length=8, max_length=128)

    # App client identity. Every field is optional so existing callers keep
    # working; anything omitted is derived from the restaurant name.
    app_key: str | None = Field(default=None, min_length=2, max_length=APP_KEY_MAX_LENGTH, pattern=APP_KEY_PATTERN)
    app_mode: AppMode = AppMode.SINGLE_RESTAURANT
    ios_bundle_id: str | None = Field(default=None, min_length=3, max_length=255, pattern=BUNDLE_ID_PATTERN)
    android_package_name: str | None = Field(
        default=None,
        min_length=3,
        max_length=255,
        pattern=BUNDLE_ID_PATTERN,
    )
    order_number_prefix: str | None = Field(
        default=None,
        min_length=2,
        max_length=ORDER_NUMBER_PREFIX_MAX_LENGTH,
        pattern=ORDER_NUMBER_PREFIX_PATTERN,
    )
    brand_primary_color: str | None = Field(default=None, min_length=7, max_length=7, pattern=BRAND_COLOR_PATTERN)
    minimum_supported_version: str | None = Field(
        default=None,
        min_length=5,
        max_length=20,
        pattern=APP_VERSION_PATTERN,
    )

    @field_validator("app_key", mode="before")
    @classmethod
    def normalize_app_key(cls, value: object) -> object:
        return value.strip().lower() or None if isinstance(value, str) else value

    @field_validator("ios_bundle_id", "android_package_name", "minimum_supported_version", mode="before")
    @classmethod
    def normalize_trimmed_value(cls, value: object) -> object:
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("order_number_prefix", "brand_primary_color", mode="before")
    @classmethod
    def normalize_uppercase_value(cls, value: object) -> object:
        return value.strip().upper() or None if isinstance(value, str) else value


class AppClientUpsertRequest(BaseModel):
    """Full app client configuration for an existing restaurant.

    Every field is required: the admin edit form always submits the complete
    configuration, and restaurants without an app client get one created here.
    """

    app_key: str = Field(min_length=2, max_length=APP_KEY_MAX_LENGTH, pattern=APP_KEY_PATTERN)
    app_mode: AppMode
    ios_bundle_id: str = Field(min_length=3, max_length=255, pattern=BUNDLE_ID_PATTERN)
    android_package_name: str = Field(min_length=3, max_length=255, pattern=BUNDLE_ID_PATTERN)
    order_number_prefix: str = Field(
        min_length=2,
        max_length=ORDER_NUMBER_PREFIX_MAX_LENGTH,
        pattern=ORDER_NUMBER_PREFIX_PATTERN,
    )
    brand_primary_color: str = Field(min_length=7, max_length=7, pattern=BRAND_COLOR_PATTERN)
    minimum_supported_version: str = Field(min_length=5, max_length=20, pattern=APP_VERSION_PATTERN)

    @field_validator("app_key", mode="before")
    @classmethod
    def normalize_app_key(cls, value: object) -> object:
        return value.strip().lower() if isinstance(value, str) else value

    @field_validator("ios_bundle_id", "android_package_name", "minimum_supported_version", mode="before")
    @classmethod
    def normalize_trimmed_value(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("order_number_prefix", "brand_primary_color", mode="before")
    @classmethod
    def normalize_uppercase_value(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class AppClientResponse(BaseModel):
    """Flattened view of an app client and its PROD platform identifiers."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID | None
    app_key: str = Field(validation_alias="key")
    display_name: str
    app_mode: AppMode
    status: AppClientStatus
    ios_bundle_id: str | None
    android_package_name: str | None
    order_number_prefix: str
    brand_primary_color: str | None
    minimum_supported_version: str | None
    created_at: datetime
    updated_at: datetime


class AdminRestaurantUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = None
    cuisine_type: str = Field(min_length=2, max_length=120)
    address_line_1: str = Field(min_length=3, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    city: str = Field(min_length=2, max_length=120)
    state: str = Field(min_length=2, max_length=120)
    country: str = Field(default="India", min_length=2, max_length=120)
    postal_code: str = Field(min_length=3, max_length=20)
    phone_number: str | None = Field(default=None, min_length=8, max_length=20)
    minimum_order_amount: Decimal = Field(default=Decimal("0.00"), ge=0)
    delivery_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    logo_image_url: str | None = Field(default=None, max_length=500)
    cover_image_url: str | None = Field(default=None, max_length=500)
    is_open: bool = False


class ThemePresetResponse(BaseModel):
    id: str
    label: str
    primary_color: str
    description: str


class RestaurantThemeResponse(BaseModel):
    """The restaurant's look, plus the gallery to pick from."""

    restaurant_id: uuid.UUID
    # Returned so the preview can show the real restaurant. An owner's user
    # record leaves `restaurant_name` null - it is a platform account - so the
    # caller has no other way to label it without a second request.
    restaurant_name: str
    preset: str
    primary_color: str
    presets: list[ThemePresetResponse]


class RestaurantThemeUpdate(BaseModel):
    """Either a named preset or a custom colour; the preset wins if both come."""

    preset: str | None = None
    primary_color: str | None = Field(
        default=None, min_length=7, max_length=7, pattern=r"^#[0-9A-Fa-f]{6}$"
    )


class RestaurantOwnerSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: EmailStr


class RestaurantLocationBase(BaseModel):
    branch_name: str = Field(min_length=2, max_length=255)
    address_line_1: str = Field(min_length=3, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    city: str = Field(min_length=2, max_length=120)
    state: str = Field(min_length=2, max_length=120)
    postal_code: str = Field(min_length=3, max_length=20)
    latitude: Decimal | None = Field(default=None)
    longitude: Decimal | None = Field(default=None)
    phone_number: str | None = Field(default=None, min_length=8, max_length=20)
    delivery_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    minimum_order_amount: Decimal = Field(default=Decimal("0.00"), ge=0)
    estimated_delivery_time: int = Field(default=30, ge=1, le=240)
    estimated_pickup_time: int = Field(default=20, ge=1, le=240)
    delivery_enabled: bool = True
    pickup_enabled: bool = True
    google_pay_enabled: bool = True
    razorpay_enabled: bool = True
    card_payment_enabled: bool = True
    cash_on_delivery_enabled: bool = True
    is_open: bool = False
    is_active: bool = True
    temporary_closed_reason: str | None = Field(default=None, max_length=255)
    preparation_time_minutes: int | None = Field(default=None, ge=0, le=240)
    service_radius_km: Decimal | None = Field(default=None, ge=0)
    future_order_enabled: bool = True
    max_future_days: int = Field(default=7, ge=1, le=30)
    slot_interval_minutes: int = Field(default=15, ge=15, le=30)
    opening_time: time | None = None
    closing_time: time | None = None

    @field_validator("slot_interval_minutes")
    @classmethod
    def validate_slot_interval_minutes(cls, value: int) -> int:
        if value not in {15, 30}:
            raise ValueError("Slot interval must be either 15 or 30 minutes")
        return value


class RestaurantLocationCreate(RestaurantLocationBase):
    pass


class RestaurantLocationUpdate(BaseModel):
    branch_name: str | None = Field(default=None, min_length=2, max_length=255)
    address_line_1: str | None = Field(default=None, min_length=3, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, min_length=2, max_length=120)
    state: str | None = Field(default=None, min_length=2, max_length=120)
    postal_code: str | None = Field(default=None, min_length=3, max_length=20)
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    phone_number: str | None = Field(default=None, min_length=8, max_length=20)
    delivery_fee: Decimal | None = Field(default=None, ge=0)
    minimum_order_amount: Decimal | None = Field(default=None, ge=0)
    estimated_delivery_time: int | None = Field(default=None, ge=1, le=240)
    estimated_pickup_time: int | None = Field(default=None, ge=1, le=240)
    delivery_enabled: bool | None = None
    pickup_enabled: bool | None = None
    google_pay_enabled: bool | None = None
    razorpay_enabled: bool | None = None
    card_payment_enabled: bool | None = None
    cash_on_delivery_enabled: bool | None = None
    is_open: bool | None = None
    is_active: bool | None = None
    temporary_closed_reason: str | None = Field(default=None, max_length=255)
    preparation_time_minutes: int | None = Field(default=None, ge=0, le=240)
    service_radius_km: Decimal | None = Field(default=None, ge=0)
    future_order_enabled: bool | None = None
    max_future_days: int | None = Field(default=None, ge=1, le=30)
    slot_interval_minutes: int | None = Field(default=None, ge=15, le=30)
    opening_time: time | None = None
    closing_time: time | None = None

    @field_validator("slot_interval_minutes")
    @classmethod
    def validate_slot_interval_minutes(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value not in {15, 30}:
            raise ValueError("Slot interval must be either 15 or 30 minutes")
        return value


class RestaurantLocationGeneralSettingsUpdate(BaseModel):
    delivery_enabled: bool | None = None
    pickup_enabled: bool | None = None
    google_pay_enabled: bool | None = None
    razorpay_enabled: bool | None = None
    card_payment_enabled: bool | None = None
    cash_on_delivery_enabled: bool | None = None
    delivery_fee: Decimal | None = Field(default=None, ge=0)
    minimum_order_amount: Decimal | None = Field(default=None, ge=0)
    estimated_delivery_time: int | None = Field(default=None, ge=1, le=240)
    estimated_pickup_time: int | None = Field(default=None, ge=1, le=240)
    is_open: bool | None = None
    is_active: bool | None = None
    temporary_closed_reason: str | None = Field(default=None, max_length=255)
    preparation_time_minutes: int | None = Field(default=None, ge=0, le=240)
    service_radius_km: Decimal | None = Field(default=None, ge=0)
    future_order_enabled: bool | None = None
    max_future_days: int | None = Field(default=None, ge=1, le=30)
    slot_interval_minutes: int | None = Field(default=None, ge=15, le=30)

    @field_validator("slot_interval_minutes")
    @classmethod
    def validate_slot_interval_minutes(cls, value: int | None) -> int | None:
        if value is None:
            return value
        if value not in {15, 30}:
            raise ValueError("Slot interval must be either 15 or 30 minutes")
        return value


class LocationFulfillmentSlotBase(BaseModel):
    day_of_week: LocationDayOfWeek
    fulfillment_type: OrderFulfillmentType
    start_time: time
    end_time: time
    is_active: bool = True


class LocationFulfillmentSlotCreate(LocationFulfillmentSlotBase):
    pass


class LocationFulfillmentSlotUpdate(BaseModel):
    day_of_week: LocationDayOfWeek | None = None
    fulfillment_type: OrderFulfillmentType | None = None
    start_time: time | None = None
    end_time: time | None = None
    is_active: bool | None = None


class LocationFulfillmentSlotResponse(LocationFulfillmentSlotBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    location_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class LocationScheduleOption(BaseModel):
    scheduled_at: datetime
    label: str


class LocationScheduleDayGroup(BaseModel):
    date: date
    label: str
    slots: list[LocationScheduleOption]


class LocationScheduleOptionsResponse(BaseModel):
    restaurant_id: uuid.UUID
    location_id: uuid.UUID
    fulfillment_type: OrderFulfillmentType
    schedule_type: OrderScheduleType
    asap_available: bool
    asap_eta_minutes: int
    asap_unavailable_reason: str | None = None
    future_order_enabled: bool
    max_future_days: int
    slot_interval_minutes: int
    prep_buffer_minutes: int
    scheduled_available: bool
    scheduled_unavailable_reason: str | None = None
    groups: list[LocationScheduleDayGroup]


class RestaurantLocationResponse(RestaurantLocationBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    delivery_available_now: bool = False
    pickup_available_now: bool = False
    delivery_unavailable_reason: str | None = None
    pickup_unavailable_reason: str | None = None
    enabled_payment_methods: list[PaymentMethod] = []
    fulfillment_slots: list[LocationFulfillmentSlotResponse] = []
    created_at: datetime
    updated_at: datetime


class RestaurantResponse(RestaurantBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    is_approved: bool
    is_open: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RestaurantDetailResponse(RestaurantResponse):
    owner: RestaurantOwnerSummary
    locations: list[RestaurantLocationResponse] = []


class AdminRestaurantCreateResponse(RestaurantResponse):
    app_client: AppClientResponse


class RestaurantSettingsUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = None
    cuisine_type: str | None = Field(default=None, min_length=2, max_length=120)
    address_line_1: str | None = Field(default=None, min_length=3, max_length=255)
    address_line_2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, min_length=2, max_length=120)
    state: str | None = Field(default=None, min_length=2, max_length=120)
    country: str | None = Field(default=None, min_length=2, max_length=120)
    postal_code: str | None = Field(default=None, min_length=3, max_length=20)
    phone_number: str | None = Field(default=None, min_length=8, max_length=20)
    logo_image_url: str | None = Field(default=None, max_length=500)
    cover_image_url: str | None = Field(default=None, max_length=500)
    is_open: bool | None = None
    is_active: bool | None = None

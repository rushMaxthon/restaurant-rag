from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import (
    AppClientStatus,
    AppMode,
    LocationDayOfWeek,
    OrderFulfillmentType,
    OrderScheduleType,
    PaymentGateway,
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


class RestaurantStorefrontUpdate(BaseModel):
    """The restaurant's own words for its website.

    Every field optional, and only the ones sent are changed — a form that
    edits the hero must not blank the meta description. Sending a field as an
    empty string clears it, which means "go back to the derived default"
    rather than "this restaurant's hero has no words".

    Validation of length and shape belongs to `restaurant_storefront.py`, so
    the rules are the same wherever copy is written, rather than half here and
    half there.
    """

    meta_title: str | None = None
    meta_description: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    hero_headline: str | None = None
    hero_subcopy: str | None = None
    concierge_intro: str | None = None
    login_blurb: str | None = None
    #: Claims rather than labels, so the owner writes them — see
    #: `restaurant_storefront.py`.
    kitchen_headline: str | None = None
    promise_note: str | None = None


class BrandSectionPayload(BaseModel):
    """One headed section of what a restaurant says about itself."""

    heading: str = ""
    body: str = ""
    bullets: list[str] = Field(default_factory=list)


class BrandFaqPayload(BaseModel):
    """One question a customer asks before a first order, and its answer."""

    question: str = ""
    answer: str = ""


class BrandHighlightPayload(BaseModel):
    """One figure worth putting in a band, and where it came from."""

    value: str = ""
    label: str = ""
    #: Attribution, for a figure the restaurant earned somewhere else. A
    #: rating from a listing site is a real fact and not this platform's
    #: measurement; shown without a source it reads as ours.
    note: str = ""


class RestaurantBrandUpdate(BaseModel):
    """The long-form content on a restaurant's own website.

    Both halves optional, and only the ones sent are changed — an edit to the
    FAQ must not blank the about sections. Sending a key as an empty list
    clears that half, which is a deliberate act and a different one from not
    mentioning it.

    Length and shape rules belong to `restaurant_brand.py`, so they are the
    same wherever this is written rather than half here and half there.
    """

    about_sections: list[BrandSectionPayload] | None = None
    faqs: list[BrandFaqPayload] | None = None
    #: The YEAR, never a duration. "26 years in business" is what the listing
    #: sites publish and it is right for one year only; the clients subtract.
    #: `model_fields_set` is what distinguishes "clear it" from "leave it".
    established_year: int | None = None
    specialities: list[str] | None = None
    highlights: list[BrandHighlightPayload] | None = None


class RestaurantBrandResponse(BaseModel):
    """What this restaurant says about itself, and the room it has to say it."""

    restaurant_id: uuid.UUID
    restaurant_name: str
    # Always both keys, always lists. Empty is the normal state — nothing here
    # is derived, because a generated paragraph about a real business's
    # standards is a claim nobody there made.
    brand: dict[str, Any]
    # Per field, so a form can count down to the limit rather than refusing on
    # save. Carries the collection caps too.
    limits: dict[str, int]


class RestaurantStorefrontResponse(BaseModel):
    """What this restaurant's website says, and what it would say by itself."""

    restaurant_id: uuid.UUID
    restaurant_name: str
    # Every key filled in: stored values over derived ones.
    storefront: dict[str, str]
    # What each field falls back to when cleared. Shown beside the input so an
    # owner can see what they are replacing before they replace it, and what
    # clearing it would restore.
    defaults: dict[str, str]
    # Per field, so a form can say "62 / 70" rather than refusing on save.
    limits: dict[str, int]
    # Which keys the owner has actually written, so the UI can mark the rest
    # as derived rather than showing eight fields that all look authored.
    customized: list[str]


class PaymentGatewayResponse(BaseModel):
    """One gateway a restaurant holds an account with.

    **No secret appears here, ever.** `secret_last4` is enough to tell two
    keys apart when somebody is checking which one is live and useless to
    anyone who obtains it; the key itself is Fernet ciphertext that no
    endpoint decrypts for a reader.
    """

    gateway: PaymentGateway
    label: str
    # What the customer sees this gateway as on the checkout screen.
    settles_method: PaymentMethod
    # Credentials are stored. Separate from `is_enabled`, so a restaurant can
    # keep its keys while pausing the gateway.
    is_configured: bool
    is_enabled: bool
    public_key: str
    secret_last4: str | None
    # Webhooks are wired separately from the API key and rotated separately.
    # A gateway can take payments before its webhook exists — it just will not
    # hear about them asynchronously.
    has_webhook_secret: bool
    # Where this restaurant's own gateway dashboard should post events, and
    # which events to tick. Null while `public_base_url` is unset — the screen
    # says to set it rather than showing a URL that goes nowhere.
    webhook_url: str | None = None
    webhook_events: list[str] = Field(default_factory=list)
    updated_by: str | None = None
    updated_at: datetime | None = None


class PaymentMethodAvailability(BaseModel):
    """One checkout button, and whether it is really there.

    `is_available` is the answer to the only question the screen is asking:
    would a customer standing at this restaurant's checkout right now see this
    button. It needs the branch toggle and a working gateway to agree, and
    `blocked_reason` says which half is missing rather than leaving an
    operator to guess.
    """

    method: PaymentMethod
    label: str
    is_available: bool
    # "this restaurant" or "the platform" — visible rather than assumed,
    # because being settled through the platform's account is a temporary
    # arrangement somebody should notice they are still in.
    settled_by: str | None = None
    blocked_reason: str | None = None


class RestaurantPaymentSettingsResponse(BaseModel):
    restaurant_id: uuid.UUID
    gateways: list[PaymentGatewayResponse]
    methods: list[PaymentMethodAvailability]
    # True while a restaurant without its own account is still settled through
    # the deployment's keys. The screen says so plainly.
    platform_fallback_in_use: bool


class RestaurantPaymentGatewayUpdate(BaseModel):
    """Store or update one gateway's credentials.

    `secret_key` and `webhook_secret` of null mean "leave what is there". The
    screen cannot show a stored secret, so it submits nothing whenever nobody
    retyped one — and treating that as "clear it" would wipe a live gateway
    every time an operator toggled it off and on.
    """

    public_key: str = Field(min_length=4, max_length=255)
    secret_key: str | None = Field(default=None, min_length=8, max_length=512)
    webhook_secret: str | None = Field(default=None, max_length=512)
    is_enabled: bool = False


class RestaurantCapabilityResponse(BaseModel):
    """One capability, as both screens render it.

    `reason` and `explanation` are not decoration. A capability that is off
    with nothing saying why is the exact state that made the allowlist this
    system replaced harmful — see `config/capabilities.py`.
    """

    key: str
    label: str
    # The sentence the restaurant's owner reads. Required by the catalog, so
    # a capability cannot exist without one.
    owner_description: str
    enabled: bool
    reason: str
    explanation: str
    # False when the platform has made no decision either way: this restaurant
    # is simply on the default, and will follow it if the default changes.
    is_customized: bool
    # Null until somebody decides. Kept when they leave the company.
    granted_by: str | None = None
    granted_at: datetime | None = None
    note: str | None = None


class RestaurantCapabilityUpdate(BaseModel):
    """Switch one capability, or hand it back to the default.

    `enabled: null` clears the decision rather than storing "off" — an
    operator who granted something as a one-off should be able to say "treat
    this like everyone else" without pinning today's default in place.
    """

    enabled: bool | None = None
    note: str | None = Field(default=None, max_length=500)


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
    #: How much the pair above is worth. EMPTY means a person typed them in,
    #: which is trusted above any lookup — they pointed at their own door.
    #: Otherwise a `GeocodeConfidence`, written only by a lookup.
    geocode_confidence: str = Field(default="", max_length=16)
    phone_number: str | None = Field(default=None, min_length=8, max_length=20)
    delivery_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    #: The restaurant's charge for boxes and bags.
    packaging_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    #: What the platform takes per order, inclusive of its own tax.
    platform_fee: Decimal = Field(default=Decimal("0.00"), ge=0)
    #: Percent on the food, after discount. Capped at 100 because a rate above
    #: it is a typo, and a typo here charges every customer of this branch.
    tax_percent: Decimal = Field(default=Decimal("5.00"), ge=0, le=100)
    #: Percent on the delivery fee, at its own rate.
    delivery_tax_percent: Decimal = Field(default=Decimal("0.00"), ge=0, le=100)
    #: The typed menu prices already contain GST, so `tax_percent` is not
    #: charged on food at checkout. Off, it is. No price changes either way.
    gst_in_menu_prices: bool = False
    #: The platform's commission, added to every typed menu price. Capped
    #: at 100 for the reason `tax_percent` is. Only an ADMIN may change it.
    commission_percent: Decimal = Field(default=Decimal("10.00"), ge=0, le=100)
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
    #: Sent as "" by the admin form whenever the pair is saved by hand, which
    #: is how a hand-placed door stops being treated as a lookup's guess.
    geocode_confidence: str | None = Field(default=None, max_length=16)
    phone_number: str | None = Field(default=None, min_length=8, max_length=20)
    delivery_fee: Decimal | None = Field(default=None, ge=0)
    packaging_fee: Decimal | None = Field(default=None, ge=0)
    platform_fee: Decimal | None = Field(default=None, ge=0)
    tax_percent: Decimal | None = Field(default=None, ge=0, le=100)
    delivery_tax_percent: Decimal | None = Field(default=None, ge=0, le=100)
    gst_in_menu_prices: bool | None = None
    commission_percent: Decimal | None = Field(default=None, ge=0, le=100)
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
    # Admin-only, and enforced as such in the endpoint: changing this converts
    # no prices, it relabels every one of them, so it is not an owner's to
    # flip. Validated against the catalog in `services/currency.py` — a
    # free-text code reaches Stripe, where a wrong one is a declined charge.
    currency: str | None = Field(default=None, min_length=3, max_length=3)
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
    """What the branch's settings form may change.

    `extra="forbid"`, and that is the important line. Pydantic's default is to
    DROP a field it does not recognise, so this endpoint answered 200 and saved
    nothing when the form learned to send the charge rates before this schema
    learned to accept them — the admin showed "saved", reloaded, and displayed
    the old values, with nothing in any log.

    A settings endpoint that quietly ignores half of what it was sent is worse
    than one that refuses: the refusal is a 422 somebody fixes in a minute,
    while the silence is a bug reported as "it does not save".
    """

    model_config = ConfigDict(extra="forbid")

    delivery_enabled: bool | None = None
    pickup_enabled: bool | None = None
    google_pay_enabled: bool | None = None
    razorpay_enabled: bool | None = None
    card_payment_enabled: bool | None = None
    cash_on_delivery_enabled: bool | None = None
    delivery_fee: Decimal | None = Field(default=None, ge=0)
    # What a customer pays on top of the food. See services/order_charges.py
    # for which of these is taxed and which is not.
    packaging_fee: Decimal | None = Field(default=None, ge=0)
    platform_fee: Decimal | None = Field(default=None, ge=0)
    tax_percent: Decimal | None = Field(default=None, ge=0, le=100)
    delivery_tax_percent: Decimal | None = Field(default=None, ge=0, le=100)
    gst_in_menu_prices: bool | None = None
    commission_percent: Decimal | None = Field(default=None, ge=0, le=100)
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

    #: Null for everyone but the staff who manage the branch. See
    #: `menu_pricing.sees_typed_prices`.
    commission_percent: Decimal | None = None  # type: ignore[assignment]
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
    # What this restaurant charges in. On the response rather than derived
    # client-side, because the panel shows several restaurants' money on one
    # screen and has to label each figure with the right symbol.
    currency: str
    is_approved: bool
    is_open: bool
    is_active: bool
    # Seeded to develop against; the admin's cross-restaurant views leave it out.
    is_demo: bool = False
    created_at: datetime
    updated_at: datetime


class RestaurantDetailResponse(RestaurantResponse):
    # Optional because this same model answers a PUBLIC endpoint. The owner
    # block carries a real person's name and email address, and /restaurants/
    # {id} is reachable with no credentials at all — so anyone could read the
    # email of every owner on the platform, one id at a time. Staff still get
    # it; customers and anonymous callers get None.
    owner: RestaurantOwnerSummary | None = None
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
    # The handler has read this since per-restaurant currency shipped, and the
    # field was never declared here — so `payload.currency` raised
    # AttributeError on EVERY call to this endpoint, whatever was being
    # changed. Pressing "Disable restaurant" in the admin answered "Unable to
    # update restaurant settings", which is the client's fallback for an error
    # carrying no detail, and a 500 carries none.
    #
    # Deliberately not validated against the catalogue here. The handler
    # normalises it and answers 422 naming the supported codes, which tells an
    # admin what to type; a schema refusal would only say the field was wrong.
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class BranchLocationLookup(BaseModel):
    """What a geocoder made of a branch's own address.

    Every field but `found` exists so a person can judge the answer before
    saving it. A geocoder always answers something, so "it returned a
    coordinate" is not evidence that it found the right building — `precise`
    and `matched` are what make the difference visible.
    """

    found: bool
    latitude: float | None = None
    longitude: float | None = None
    #: `GeocodeConfidence`: ROOFTOP, STREET, POSTCODE, LOCALITY or REGION.
    confidence: str = ""
    #: Whether this is precise enough to price a delivery from. A POSTCODE or
    #: LOCALITY match is a real coordinate and the wrong one to charge from.
    precise: bool = False
    #: The address as the geocoder understood it. The only way to catch a
    #: lookup that quietly landed in a different part of the city.
    matched: str = ""
    provider: str = ""
    #: Which question found it: "address", "locality", "branch name" or
    #: "postcode". A branch found by its postcode and one found by its address
    #: deserve very different amounts of trust, and the coordinate alone does
    #: not show the difference.
    matched_on: str = ""

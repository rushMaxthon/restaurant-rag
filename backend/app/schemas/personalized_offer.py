from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import (
    OrderFulfillmentType,
    PersonalizedOfferAudience,
    PersonalizedOfferDiscountType,
    PersonalizedOfferEventType,
    PersonalizedOfferGenerationReason,
    PersonalizedOfferSource,
    PersonalizedOfferState,
    PersonalizedOfferType,
)


class PersonalizedOfferUpsertRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    offer_type: PersonalizedOfferType
    audience_type: PersonalizedOfferAudience = PersonalizedOfferAudience.ALL_CUSTOMERS
    state: PersonalizedOfferState = PersonalizedOfferState.DRAFT
    restaurant_location_id: uuid.UUID | None = None
    applicable_item_id: uuid.UUID | None = None
    applicable_category: str | None = Field(default=None, min_length=2, max_length=120)
    applicable_cuisine: str | None = Field(default=None, min_length=2, max_length=120)
    discount_type: PersonalizedOfferDiscountType = PersonalizedOfferDiscountType.NONE
    discount_value: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=10, decimal_places=2)
    max_discount_amount: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    minimum_order_amount: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=10, decimal_places=2)
    inactivity_days: int = Field(default=14, ge=1, le=365)
    cooldown_hours: int = Field(default=48, ge=1, le=720)
    valid_for_days: int = Field(default=3, ge=1, le=90)
    cta_label: str | None = Field(default=None, min_length=2, max_length=80)
    business_rules: dict[str, object] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=2000)
    starts_at: datetime | None = None
    expires_at: datetime | None = None


class PersonalizedOfferManagementResponse(BaseModel):
    id: uuid.UUID
    record_kind: str = "TEMPLATE"
    source: PersonalizedOfferSource = PersonalizedOfferSource.MANUAL_TEMPLATE
    template_offer_id: uuid.UUID | None = None
    template_offer_name: str | None = None
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID | None = None
    restaurant_location_name: str | None = None
    applicable_item_id: uuid.UUID | None = None
    applicable_item_name: str | None = None
    generated_combo_id: uuid.UUID | None = None
    generated_combo_name: str | None = None
    name: str
    offer_type: PersonalizedOfferType
    audience_type: PersonalizedOfferAudience
    state: PersonalizedOfferState
    effective_state: PersonalizedOfferState
    discount_type: PersonalizedOfferDiscountType
    discount_value: Decimal
    max_discount_amount: Decimal | None = None
    minimum_order_amount: Decimal
    inactivity_days: int
    cooldown_hours: int
    valid_for_days: int
    applicable_category: str | None = None
    applicable_cuisine: str | None = None
    cta_label: str | None = None
    business_rules: dict[str, object]
    notes: str | None = None
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    generation_reason: PersonalizedOfferGenerationReason | None = None
    generated_title: str | None = None
    generated_subtitle: str | None = None
    generated_badge: str | None = None
    generated_cta_label: str | None = None
    manually_edited: bool = False
    edited_by: str | None = None
    edited_at: datetime | None = None
    eligible_user_count: int = 0
    view_count: int = 0
    click_count: int = 0
    conversion_count: int = 0
    editable: bool = True
    state_mutable: bool = True
    created_at: datetime
    updated_at: datetime


class PersonalizedOfferCardResponse(BaseModel):
    id: str
    generated_offer_id: uuid.UUID | None = None
    generated_offer_user_match_id: uuid.UUID | None = None
    offer_id: uuid.UUID
    offer_name: str
    offer_type: PersonalizedOfferType
    audience_type: PersonalizedOfferAudience
    badge: str
    title: str
    subtitle: str
    cta_label: str
    target_type: str
    restaurant_id: uuid.UUID
    restaurant_name: str
    restaurant_slug: str
    restaurant_location_id: uuid.UUID | None = None
    restaurant_location_name: str | None = None
    offer_restaurant_location_id: uuid.UUID | None = None
    menu_item_id: uuid.UUID | None = None
    menu_item_name: str | None = None
    generated_combo_id: uuid.UUID | None = None
    generated_combo_name: str | None = None
    cuisine_type: str | None = None
    discount_type: PersonalizedOfferDiscountType
    discount_value: Decimal
    discount_label: str | None = None
    max_discount_amount: Decimal | None = None
    minimum_order_amount: Decimal
    terms_label: str | None = None
    valid_for_days: int
    expires_at: datetime | None = None
    created_at: datetime


class PersonalizedOfferEventInput(BaseModel):
    offer_id: uuid.UUID
    generated_offer_id: uuid.UUID | None = None
    generated_offer_user_match_id: uuid.UUID | None = None
    event_type: PersonalizedOfferEventType
    target_type: str | None = Field(default=None, max_length=40)
    target_id: str | None = Field(default=None, max_length=255)


class PersonalizedOfferEventBatchRequest(BaseModel):
    events: list[PersonalizedOfferEventInput] = Field(min_length=1, max_length=20)


class PersonalizedOfferEventBatchResponse(BaseModel):
    recorded_count: int


class PersonalizedOfferPreviewSelectedOptionInput(BaseModel):
    option_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=99)


class PersonalizedOfferPreviewItemInput(BaseModel):
    menu_item_id: uuid.UUID
    menu_item_size_id: uuid.UUID | None = None
    selected_options: list[PersonalizedOfferPreviewSelectedOptionInput] = Field(default_factory=list)
    quantity: int = Field(ge=1, le=99)


class PersonalizedOfferPreviewRequest(BaseModel):
    offer_id: uuid.UUID
    generated_offer_id: uuid.UUID | None = None
    generated_offer_user_match_id: uuid.UUID | None = None
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID | None = None
    fulfillment_type: OrderFulfillmentType = OrderFulfillmentType.DELIVERY
    items: list[PersonalizedOfferPreviewItemInput] = Field(min_length=1, max_length=50)


class PersonalizedOfferPreviewResponse(BaseModel):
    offer_id: uuid.UUID
    eligible: bool
    offer_name: str | None = None
    offer_title: str | None = None
    offer_restaurant_location_id: uuid.UUID | None = None
    discount_type: PersonalizedOfferDiscountType | None = None
    discount_value: Decimal = Decimal("0.00")
    discount_amount: Decimal = Decimal("0.00")
    discount_label: str | None = None
    max_discount_amount: Decimal | None = None
    minimum_order_amount: Decimal = Decimal("0.00")
    subtotal: Decimal = Decimal("0.00")
    amount_to_unlock: Decimal = Decimal("0.00")
    message: str | None = None


class PersonalizedOfferContextRequest(BaseModel):
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID | None = None
    menu_item_id: uuid.UUID


class PersonalizedOfferItemAvailabilityRequest(BaseModel):
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID | None = None
    menu_item_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)


class PersonalizedOfferItemAvailabilityResponse(BaseModel):
    menu_item_id: uuid.UUID
    has_offer: bool
    offer_count: int = 0


class GeneratedOfferUserMatchResponse(BaseModel):
    id: uuid.UUID
    generated_offer_id: uuid.UUID
    user_id: uuid.UUID
    user_name: str
    user_email: str
    matched_reason: PersonalizedOfferGenerationReason
    score: Decimal
    rank: int
    is_current: bool
    target_type: str | None = None
    target_id: str | None = None
    view_count: int = 0
    click_count: int = 0
    conversion_count: int = 0
    viewed_at: datetime | None = None
    clicked_at: datetime | None = None
    converted_at: datetime | None = None
    match_metadata: dict[str, object]
    created_at: datetime
    updated_at: datetime


class GeneratedOfferUpdateRequest(BaseModel):
    state: PersonalizedOfferState | None = None
    title: str | None = Field(default=None, min_length=2, max_length=255)
    subtitle: str | None = Field(default=None, min_length=2, max_length=2000)
    badge: str | None = Field(default=None, min_length=1, max_length=80)
    cta_label: str | None = Field(default=None, min_length=2, max_length=80)
    starts_at: datetime | None = None
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "GeneratedOfferUpdateRequest":
        if (
            self.state is None
            and self.title is None
            and self.subtitle is None
            and self.badge is None
            and self.cta_label is None
            and self.starts_at is None
            and self.expires_at is None
        ):
            raise ValueError("At least one generated offer field must be provided")
        if self.starts_at and self.expires_at and self.starts_at >= self.expires_at:
            raise ValueError("Offer start time must be earlier than the expiry time")
        return self

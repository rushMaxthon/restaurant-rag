from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import MenuItemCustomizationSelectionType


class MenuItemCustomizationOptionPayload(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    extra_price: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=10, decimal_places=2)
    is_active: bool = True
    is_countable: bool = False
    sort_order: int = Field(default=0, ge=0)


class MenuItemCustomizationGroupPayload(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    selection_type: MenuItemCustomizationSelectionType = MenuItemCustomizationSelectionType.MULTI
    is_required: bool = False
    min_selection: int = Field(default=0, ge=0)
    max_selection: int = Field(default=1, ge=1)
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0)
    options: list[MenuItemCustomizationOptionPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_group(self) -> "MenuItemCustomizationGroupPayload":
        if self.selection_type == MenuItemCustomizationSelectionType.SINGLE:
            if self.max_selection != 1:
                raise ValueError("Single select groups must use a max selection of 1.")
            if self.min_selection > 1:
                raise ValueError("Single select groups cannot require more than one selection.")
        if self.max_selection < self.min_selection:
            raise ValueError("Max selection cannot be less than min selection.")
        if self.is_required and self.min_selection < 1:
            raise ValueError("Required groups must enforce at least one selection.")
        if not self.options:
            raise ValueError("Each customization group must include at least one option.")
        return self


class MenuItemSizePayload(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0)
    customization_groups: list[MenuItemCustomizationGroupPayload] = Field(default_factory=list)


class MenuItemCustomizationOptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    extra_price: Decimal
    is_active: bool
    is_countable: bool
    sort_order: int


class MenuItemCustomizationGroupResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    menu_item_size_id: uuid.UUID | None = None
    title: str
    selection_type: MenuItemCustomizationSelectionType
    is_required: bool
    min_selection: int
    max_selection: int
    is_active: bool
    sort_order: int
    options: list[MenuItemCustomizationOptionResponse] = Field(default_factory=list)


class MenuItemSizeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    price: Decimal
    is_active: bool
    sort_order: int
    customization_groups: list[MenuItemCustomizationGroupResponse] = Field(default_factory=list)


class MenuItemRequestBase(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    category: str = Field(min_length=2, max_length=120)
    cuisine_type: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    is_veg: bool = False
    is_available: bool = True
    is_bestseller: bool = False
    is_featured: bool = False
    image_url: str | None = Field(default=None, max_length=500)
    is_new_launch: bool = False
    has_sizes: bool = False
    has_customizations: bool = False
    sizes: list[MenuItemSizePayload] = Field(default_factory=list)
    customization_groups: list[MenuItemCustomizationGroupPayload] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_customizations(self) -> "MenuItemRequestBase":
        if self.has_sizes:
            active_sizes = [size for size in self.sizes if size.is_active]
            if not active_sizes:
                raise ValueError("At least one active size is required when sizes are enabled.")
        elif self.sizes:
            raise ValueError("Sizes can only be provided when size management is enabled.")

        if not self.has_sizes and self.price is None:
            raise ValueError("A standard item price is required when sizes are disabled.")

        active_groups = [group for group in self.customization_groups if group.is_active]
        for size in self.sizes:
            active_groups.extend(group for group in size.customization_groups if group.is_active)

        if self.has_customizations and not active_groups:
            raise ValueError("At least one active customization group is required when customizations are enabled.")
        if not self.has_customizations:
            has_any_groups = bool(self.customization_groups) or any(size.customization_groups for size in self.sizes)
            if has_any_groups:
                raise ValueError("Customization groups can only be provided when customizations are enabled.")

        return self


class MenuItemCreate(MenuItemRequestBase):
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID | None = None
    launched_at: datetime | None = None


class MenuItemBulkCreate(MenuItemRequestBase):
    restaurant_id: uuid.UUID
    restaurant_location_ids: list[uuid.UUID] = Field(min_length=1)
    launched_at: datetime | None = None
    skip_duplicates: bool = False


class MenuItemUpdate(MenuItemRequestBase):
    restaurant_location_id: uuid.UUID | None = None
    launched_at: datetime | None = None


class MenuItemAvailabilityUpdate(BaseModel):
    is_available: bool


class MenuItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    restaurant_location_name: str | None = None
    restaurant_location_city: str | None = None
    name: str
    category: str
    cuisine_type: str | None = None
    description: str | None = None
    price: Decimal
    is_veg: bool
    is_available: bool
    is_bestseller: bool
    is_featured: bool = False
    image_url: str | None = None
    recent_valid_order_count: int = 0
    recent_valid_order_window_days: int = 30
    popularity_score: Decimal
    rating: Decimal | None = None
    rating_count: int = 0
    launched_at: datetime
    created_at: datetime
    updated_at: datetime
    is_new_launch: bool = False
    is_new: bool = False
    recommendation_label: str | None = None
    recommendation_reason: str | None = None
    new_item_reason: str | None = None
    is_favorite: bool = False
    has_sizes: bool = False
    has_customizations: bool = False
    sizes: list[MenuItemSizeResponse] = Field(default_factory=list)
    customization_groups: list[MenuItemCustomizationGroupResponse] = Field(default_factory=list)


class MenuItemBulkSkippedLocation(BaseModel):
    restaurant_location_id: uuid.UUID
    restaurant_location_name: str | None = None


class MenuItemBulkCreateResponse(BaseModel):
    created: list[MenuItemResponse] = Field(default_factory=list)
    skipped: list[MenuItemBulkSkippedLocation] = Field(default_factory=list)

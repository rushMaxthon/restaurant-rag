"""Request and response shapes for managing the questionnaire."""

from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import PreferenceInputType, PreferenceSignalRole

KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def _validate_key(value: str) -> str:
    cleaned = value.strip().lower()
    if not KEY_PATTERN.match(cleaned):
        raise ValueError(
            "Key must start with a letter and contain only lowercase letters, numbers "
            "and underscores."
        )
    return cleaned


class PreferenceOptionCreate(BaseModel):
    value: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    help_text: str | None = None
    #: Interpretation for the scoring engine - `{"is_veg": true}` and so on.
    metadata: dict[str, Any] = Field(default_factory=dict)
    display_order: int | None = None
    is_active: bool = True


class PreferenceOptionUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    help_text: str | None = None
    metadata: dict[str, Any] | None = None
    display_order: int | None = None
    is_active: bool | None = None


class PreferenceQuestionCreate(BaseModel):
    key: str
    prompt: str = Field(min_length=1, max_length=255)
    help_text: str | None = None
    input_type: PreferenceInputType
    is_required: bool = False
    min_selections: int = Field(default=0, ge=0)
    max_selections: int | None = Field(default=None, ge=1)
    allows_free_text: bool = False
    signal_role: PreferenceSignalRole = PreferenceSignalRole.NONE
    is_active: bool = True
    options: list[PreferenceOptionCreate] = Field(default_factory=list)

    @field_validator("key", mode="after")
    @classmethod
    def check_key(cls, value: str) -> str:
        return _validate_key(value)


class PreferenceQuestionUpdate(BaseModel):
    prompt: str | None = Field(default=None, min_length=1, max_length=255)
    help_text: str | None = None
    input_type: PreferenceInputType | None = None
    is_required: bool | None = None
    min_selections: int | None = Field(default=None, ge=0)
    max_selections: int | None = Field(default=None, ge=1)
    allows_free_text: bool | None = None
    signal_role: PreferenceSignalRole | None = None
    is_active: bool | None = None
    display_order: int | None = None


class PreferenceVisibilityRequest(BaseModel):
    is_hidden: bool


class PreferenceReorderRequest(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1)


class AdminPreferenceOptionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    value: str
    label: str
    help_text: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="option_metadata")
    display_order: int
    is_active: bool


class AdminPreferenceQuestionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    restaurant_id: uuid.UUID | None = None
    key: str
    prompt: str
    help_text: str | None = None
    input_type: PreferenceInputType
    is_required: bool
    min_selections: int
    max_selections: int | None = None
    allows_free_text: bool
    signal_role: PreferenceSignalRole
    display_order: int
    is_active: bool
    #: A platform question seen from a restaurant: hideable, not editable.
    is_inherited: bool = False
    #: Hidden for this restaurant specifically, with the global row untouched.
    is_hidden_here: bool = False
    #: How many stored answers point at this question. The admin UI uses it to
    #: warn before retiring something customers have actually answered.
    answer_count: int = 0
    options: list[AdminPreferenceOptionResponse] = Field(default_factory=list)

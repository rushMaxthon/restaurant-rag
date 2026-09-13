from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import PreferenceInputType, PreferenceSignalRole

DietPreference = Literal["VEG", "NON_VEG"]
SpiceLevel = Literal["LOW", "MEDIUM", "HIGH"]
BudgetTier = Literal["LOW", "MID", "HIGH"]


def _normalize_string_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(cleaned)
    return normalized


class UserPreferencesPayload(BaseModel):
    cuisines: list[str] = Field(default_factory=list)
    diet: DietPreference | None = None
    spice_level: SpiceLevel | None = None
    budget: BudgetTier | None = None
    favorite_items: list[str] = Field(default_factory=list)

    @field_validator("cuisines", "favorite_items", mode="after")
    @classmethod
    def normalize_lists(cls, value: list[str]) -> list[str]:
        return _normalize_string_list(value)


class UserPreferencesResponse(UserPreferencesPayload):
    model_config = ConfigDict(from_attributes=True)

    updated_at: datetime | None = None


class RecommendationLocationContext(BaseModel):
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class RecommendationQueryRequest(BaseModel):
    preferences: UserPreferencesPayload | None = None
    dedupe_multi_location: bool = False
    location_context: RecommendationLocationContext | None = None


# ---------------------------------------------------------------------------
# Dynamic questionnaire
# ---------------------------------------------------------------------------


class PreferenceOptionResponse(BaseModel):
    """A choice the customer can pick."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    value: str
    label: str
    help_text: str | None = None
    display_order: int


class PreferenceQuestionResponse(BaseModel):
    """A question, with everything a client needs to render and validate it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    prompt: str
    help_text: str | None = None
    input_type: PreferenceInputType
    is_required: bool
    min_selections: int
    max_selections: int | None = None
    allows_free_text: bool
    #: What the recommender does with this answer. Clients use it only to build
    #: a local profile before sign-in; `NONE` means it is collected, not scored.
    signal_role: PreferenceSignalRole
    display_order: int
    #: True when the question comes from the platform rather than this
    #: restaurant. Clients ignore it; the admin panel uses it to show an owner
    #: what they may hide but not edit.
    is_inherited: bool = False
    options: list[PreferenceOptionResponse] = Field(default_factory=list)


class PreferenceSchemaResponse(BaseModel):
    """The whole questionnaire for one app, in the order to ask it."""

    restaurant_id: uuid.UUID | None = None
    questions: list[PreferenceQuestionResponse] = Field(default_factory=list)


class PreferenceAnswerInput(BaseModel):
    """One question's answer. Either chosen options, free text, or both."""

    question_id: uuid.UUID
    option_ids: list[uuid.UUID] = Field(default_factory=list)
    free_text: list[str] = Field(default_factory=list)

    @field_validator("free_text", mode="after")
    @classmethod
    def clean_free_text(cls, value: list[str]) -> list[str]:
        return _normalize_string_list(value)


class PreferenceAnswersPayload(BaseModel):
    """A full submission. Answers omitted for a question clear that question."""

    answers: list[PreferenceAnswerInput] = Field(default_factory=list)


class PreferenceAnswerResponse(BaseModel):
    question_id: uuid.UUID
    question_key: str
    option_ids: list[uuid.UUID] = Field(default_factory=list)
    free_text: list[str] = Field(default_factory=list)
    #: What the customer chose, as text, including answers whose option has
    #: since been withdrawn - so the edit screen can show them rather than
    #: silently dropping them.
    labels: list[str] = Field(default_factory=list)
    #: True when a stored answer points at a question or option that is no
    #: longer active. The client renders these as removable, not selectable.
    has_stale_selection: bool = False


class UserPreferenceAnswersResponse(BaseModel):
    answers: list[PreferenceAnswerResponse] = Field(default_factory=list)
    #: The legacy projection, so existing clients keep working untouched during
    #: the rollout.
    legacy: UserPreferencesPayload

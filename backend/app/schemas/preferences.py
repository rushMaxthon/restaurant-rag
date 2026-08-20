from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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

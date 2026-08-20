"""Response models for owner action proposals."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.enums import OwnerActionStatus, OwnerActionType
from app.schemas.insights import ActionOutcomeResponse


class OwnerActionProposalResponse(BaseModel):
    id: uuid.UUID
    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID | None
    insight_id: uuid.UUID | None
    briefing_id: uuid.UUID | None
    action_type: OwnerActionType
    status: OwnerActionStatus
    title: str
    rationale: str
    is_executable: bool
    priority: float
    expected_impact_amount: float | None
    expected_impact_basis: str | None
    action_payload: dict[str, Any]
    source_facts: dict[str, Any]
    generated_at: datetime
    expires_at: datetime | None
    decided_at: datetime | None
    executed_at: datetime | None
    executed_offer_id: uuid.UUID | None
    failure_reason: str | None
    # Present once an executed action has been measured.
    outcome: ActionOutcomeResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class OwnerActionApprovalResponse(BaseModel):
    proposal: OwnerActionProposalResponse
    offer_id: uuid.UUID | None
    already_executed: bool
    detail: str


__all__ = [
    "OwnerActionApprovalResponse",
    "OwnerActionProposalResponse",
]

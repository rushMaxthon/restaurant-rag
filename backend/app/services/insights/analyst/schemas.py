"""Argument and result contracts for the analyst tool layer.

Argument models are deliberately narrow. Anything that would let a caller name
a tenant — a restaurant id, a location id, a user id — is absent by design and
checked for at import time in `registry`, because the whole safety story rests
on scope being injected rather than requested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.insights.scope import InsightsScope

settings = get_settings()

# Windows a tool may ask for. An allowlist rather than a range: these are the
# lengths the comparison logic and the adaptive-window notes are written for,
# and an arbitrary 83-day window would produce a comparison nobody has checked.
ALLOWED_WINDOW_DAYS: tuple[int, ...] = (7, 14, 30, 60, 90)

BreakdownDimension = Literal[
    "item",
    "category",
    "hour_of_day",
    "daypart",
    "weekday",
    "customer_cohort",
    "location",
]


class ToolArgs(BaseModel):
    """Base for every argument model.

    `extra="forbid"` matters more than it looks: an unexpected key is rejected
    outright rather than ignored, so a caller cannot pass `restaurant_id`
    alongside valid arguments and have it silently dropped — the call fails and
    is visible.
    """

    model_config = ConfigDict(extra="forbid")


class NoArgs(ToolArgs):
    pass


class WindowArgs(ToolArgs):
    window_days: int = Field(
        default=settings.insights_default_window_days,
        description="Length of the analysis window in days.",
    )


class BreakdownArgs(WindowArgs):
    dimension: BreakdownDimension = Field(
        description="Which dimension to attribute the revenue change to."
    )


class BranchArgs(WindowArgs):
    branch_name: str = Field(
        min_length=1,
        max_length=255,
        description="Branch name exactly as it appears in get_branch_status.",
    )


class BranchPairArgs(WindowArgs):
    branch_a: str = Field(min_length=1, max_length=255)
    branch_b: str = Field(min_length=1, max_length=255)


class LimitArgs(ToolArgs):
    limit: int = Field(default=10, ge=1, le=50)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One callable slice of restaurant data."""

    name: str
    description: str
    args_model: type[ToolArgs]
    handler: Callable[[Session, InsightsScope, Any], dict[str, Any]]


@dataclass(slots=True)
class ToolResult:
    """The outcome of one tool call.

    `ok=False` is a normal, expected outcome — an unknown branch name or a
    rejected window — and carries a machine-readable `error` so a caller can
    correct itself rather than reading failure as absence of data.
    """

    tool: str
    args: dict[str, Any]
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    detail: str | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"tool": self.tool, "args": self.args, "ok": self.ok}
        if self.ok:
            payload["data"] = self.data
        else:
            payload["error"] = self.error
            if self.detail:
                payload["detail"] = self.detail
        return payload


__all__ = [
    "ALLOWED_WINDOW_DAYS",
    "BranchArgs",
    "BranchPairArgs",
    "BreakdownArgs",
    "BreakdownDimension",
    "LimitArgs",
    "NoArgs",
    "ToolArgs",
    "ToolResult",
    "ToolSpec",
    "WindowArgs",
]

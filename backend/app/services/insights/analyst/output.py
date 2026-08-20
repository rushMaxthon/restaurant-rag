"""What an analyst run is allowed to return, as a validated contract.

These models describe the *shape* of a generated analysis. They enforce nothing
about truth — a well-formed finding can still be completely wrong, which is why
`validation` exists and why every field here that carries a claim also carries
the evidence for it.

Two design choices worth stating:

* `evidence` is required and non-empty on every finding and recommendation. A
  claim with no citation cannot be checked, and something that cannot be checked
  should not reach an owner.
* `metrics` are structured rather than left inside prose. A number in a sentence
  can only be checked for membership in the ledger; a named current/previous
  pair can also be checked for internal arithmetic, which catches the far more
  dangerous failure of real numbers combined into a false conclusion.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_TITLE_CHARS = 120
MAX_BODY_CHARS = 600
MAX_FINDINGS = 8
MAX_RECOMMENDATIONS = 5

Confidence = Literal["LOW", "MEDIUM", "HIGH"]
Severity = Literal["INFO", "LOW", "MEDIUM", "HIGH"]


class MetricClaim(BaseModel):
    """One figure a finding rests on, in a form that can be recomputed."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    current: float
    previous: float | None = None
    # Optional because the analyst is not required to do arithmetic — but when
    # it does, the arithmetic is checked.
    absolute_change: float | None = None
    percent_change: float | None = None
    unit: Literal["money", "count", "percent", "minutes", "days"] = "count"

    @field_validator("unit", mode="before")
    @classmethod
    def _coerce_unit(cls, value: object) -> object:
        """Map a plausible synonym onto a known unit rather than failing.

        Only "money" widens what a finding may claim — it is the input to the
        severity clamp — so anything unrecognised becomes "count", which can
        only lower the ceiling. A live run lost three otherwise-valid findings
        to the labels "orders" and "customers".
        """

        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        known = {"money", "count", "percent", "minutes", "days"}
        if normalized in known:
            return normalized
        aliases = {
            "currency": "money", "revenue": "money", "rupees": "money",
            "inr": "money", "amount": "money", "value": "money",
            "%": "percent", "percentage": "percent",
            "minute": "minutes", "hours": "minutes", "day": "days",
        }
        return aliases.get(normalized, "count")


class AIFinding(BaseModel):
    """Something the analyst concluded from the data."""

    model_config = ConfigDict(extra="forbid")

    category: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    body: str = Field(min_length=1, max_length=MAX_BODY_CHARS)
    severity: Severity = "LOW"
    confidence: Confidence = "LOW"
    # Deliberately separate from `body`: an observation and an explanation are
    # different kinds of claim, and only the first is ever measured.
    interpretation: str | None = Field(default=None, max_length=MAX_BODY_CHARS)
    subject: str | None = Field(default=None, max_length=255)
    metrics: list[MetricClaim] = Field(default_factory=list)
    evidence: list[str] = Field(min_length=1)


class AIRecommendation(BaseModel):
    """Something the analyst suggests doing about a finding."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    rationale: str = Field(min_length=1, max_length=MAX_BODY_CHARS)
    # What the analyst *wants*; whether it is allowed to be executable is the
    # validator's decision, never the model's.
    requested_action_type: str | None = Field(default=None, max_length=60)
    discount_percent: float | None = None
    minimum_order_amount: float | None = None
    expected_impact_amount: float | None = None
    expected_impact_basis: str | None = Field(default=None, max_length=MAX_BODY_CHARS)
    priority: float = Field(default=0.0, ge=0.0)
    confidence: Confidence = "LOW"
    evidence: list[str] = Field(min_length=1)


class AIInterpretation(BaseModel):
    """What one rules finding might mean. Never what it says.

    `finding_ref` points at a finding the rules engine already produced and
    ranked. The model cannot add a finding, remove one, reorder them, or change
    a number in one — it can only say what the finding might indicate, and that
    text carries no authority beyond being labelled an interpretation.
    """

    model_config = ConfigDict(extra="forbid")

    finding_ref: int = Field(ge=1, description="1-based index into the ranked findings")
    text: str = Field(min_length=1, max_length=400)
    confidence: Confidence = "LOW"


class AICrossFinding(BaseModel):
    """A connection between findings that no single rule can see.

    This is the one thing the rules engine structurally cannot do: each rule
    looks at one dimension, so nothing in it can notice that a daypart decline
    and a branch closure are the same event seen twice. If the analyst earns its
    place, it is here.
    """

    model_config = ConfigDict(extra="forbid")

    refs: list[int] = Field(min_length=2, max_length=4)
    text: str = Field(min_length=1, max_length=400)
    confidence: Confidence = "LOW"


class AnalystCommentary(BaseModel):
    """One additive pass: interpretation layered onto ranked facts."""

    model_config = ConfigDict(extra="forbid")

    interpretations: list[AIInterpretation] = Field(default_factory=list, max_length=6)
    connections: list[AICrossFinding] = Field(default_factory=list, max_length=3)
    context: str | None = Field(default=None, max_length=400)


class AnalysisVerdict(BaseModel):
    """One complete analyst response."""

    model_config = ConfigDict(extra="forbid")

    # The analyst's own judgement that the data will not support conclusions.
    # Checked against the backend's independent view rather than trusted.
    insufficient_data: bool = False
    summary: str = Field(default="", max_length=MAX_BODY_CHARS)
    findings: list[AIFinding] = Field(default_factory=list, max_length=MAX_FINDINGS)
    recommendations: list[AIRecommendation] = Field(
        default_factory=list, max_length=MAX_RECOMMENDATIONS
    )


__all__ = [
    "AICrossFinding",
    "AIFinding",
    "AIInterpretation",
    "AIRecommendation",
    "AnalysisVerdict",
    "AnalystCommentary",
    "Confidence",
    "MAX_BODY_CHARS",
    "MAX_FINDINGS",
    "MAX_RECOMMENDATIONS",
    "MAX_TITLE_CHARS",
    "MetricClaim",
    "Severity",
]

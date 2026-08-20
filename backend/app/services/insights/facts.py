"""Fact packs: the numbers narration is allowed to use, and the check that it did.

A fact pack is the complete, compact set of figures behind a briefing. It is
what the model is given, and it is what the model's output is verified against
afterwards. Anything numeric in the generated text that is not traceable to this
pack means the model invented a figure, and the generation is thrown away.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

from app.config import get_settings
from app.schemas.insights import DiagnosticsSnapshotResponse
from app.services.insights.rules import CandidateInsight

settings = get_settings()

# Matches figures as they appear in prose: 1,234.56 / 12.5 / 8 — currency symbols
# and percent signs sit outside the capture.
NUMBER_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")

HEADLINE_METRICS = (
    "gross_revenue",
    "orders",
    "average_order_value",
    "customers",
    "items_sold",
    "cancelled_orders",
    "cancelled_value",
)


@dataclass(slots=True)
class FactPack:
    period_label: str
    previous_period_label: str
    timezone: str
    headline: dict[str, Any] = field(default_factory=dict)
    insights: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "period": self.period_label,
            "previous_period": self.previous_period_label,
            "timezone": self.timezone,
            "headline": self.headline,
            "findings": self.insights,
            "caveats": self.notes,
        }

    def numeric_values(self) -> list[float]:
        values: list[float] = []
        _collect_numbers(self.headline, values)
        for finding in self.insights:
            _collect_numbers(finding, values)
        return values


def _collect_numbers(payload: Any, sink: list[float]) -> None:
    if isinstance(payload, bool) or payload is None:
        return
    if isinstance(payload, (int, float)):
        sink.append(float(payload))
        return
    if isinstance(payload, dict):
        for value in payload.values():
            _collect_numbers(value, sink)
        return
    if isinstance(payload, (list, tuple)):
        for value in payload:
            _collect_numbers(value, sink)


def build_fact_pack(
    snapshot: DiagnosticsSnapshotResponse,
    candidates: Iterable[CandidateInsight],
) -> FactPack:
    headline: dict[str, Any] = {}
    for row in snapshot.headline:
        if row.metric not in HEADLINE_METRICS:
            continue
        headline[row.metric] = {
            "current": round(row.current, 2),
            "previous": round(row.previous, 2),
            "change": round(row.absolute_change, 2),
            "percent_change": (
                round(row.percent_change, 1) if row.percent_change is not None else None
            ),
            "direction": row.direction,
        }

    findings = [
        {
            "type": candidate.insight_type.value,
            "severity": candidate.severity.value,
            "subject": candidate.subject,
            "statement": candidate.body,
            "numbers": candidate.facts,
        }
        for candidate in candidates
    ]

    return FactPack(
        period_label=snapshot.current_period.label,
        previous_period_label=snapshot.previous_period.label,
        timezone=snapshot.scope.timezone,
        headline=headline,
        insights=findings,
        notes=list(snapshot.data_quality.notes),
    )


def _expand_allowed(value: float) -> set[float]:
    """Every form a figure may legitimately take in prose.

    Rounded and absolute variants are generated up front so the check itself can
    stay near-exact: a drop of -1234.56 may be written as 1,235 or 1,234.6, but
    not as 1,400.
    """

    variants = {value, abs(value)}
    for candidate in (value, abs(value)):
        variants.add(float(round(candidate)))
        variants.add(round(candidate, 1))
        variants.add(round(candidate, 2))
    return variants


def allowed_numbers(pack: FactPack, *, period_dates: Iterable[date] = ()) -> set[float]:
    allowed: set[float] = set()
    for value in pack.numeric_values():
        allowed |= _expand_allowed(value)

    # Dates get written out ("09 Mar"), so their components are legitimate.
    for day in period_dates:
        allowed |= {float(day.day), float(day.month), float(day.year)}

    return allowed


def allowed_from_payload(payload: Any) -> set[float]:
    """Every figure inside an arbitrary fact payload, in all its written forms.

    The fact pack is not the only thing a final answer is grounded in: a tool
    returns its own structured rows, and once those are handed to the model they
    become legitimate to quote. Without this, a correctly quoted tool figure
    would be treated as invented and the whole answer discarded.
    """

    values: list[float] = []
    _collect_numbers(payload, values)
    allowed: set[float] = set()
    for value in values:
        allowed |= _expand_allowed(value)
    return allowed


def extract_numbers(text: str) -> list[float]:
    values: list[float] = []
    for match in NUMBER_PATTERN.finditer(text):
        raw = match.group(0).replace(",", "")
        try:
            values.append(float(raw))
        except ValueError:
            continue
    return values


def unsupported_numbers(
    text: str,
    allowed: set[float],
    *,
    tolerance: float | None = None,
) -> list[float]:
    """Figures in `text` that no fact in the pack supports.

    An empty list means every number the model wrote is traceable to the data.
    """

    resolved_tolerance = (
        tolerance if tolerance is not None else settings.ai_manager_number_tolerance
    )
    offenders: list[float] = []
    for value in extract_numbers(text):
        if any(abs(value - candidate) <= resolved_tolerance for candidate in allowed):
            continue
        offenders.append(value)
    return offenders


__all__ = [
    "FactPack",
    "allowed_from_payload",
    "allowed_numbers",
    "build_fact_pack",
    "extract_numbers",
    "unsupported_numbers",
]

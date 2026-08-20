"""Additive mode: the rules engine states the facts, the model says what they might mean.

Phase 8D measured the free-exploration analyst against the rules engine on real
data and it lost on every axis that mattered: fewer findings, 385× slower, and
in five runs out of five it missed the largest movement in the period while
reporting a smaller rise as good news. Its figures were exact; its judgement was
not. The conclusion was not that the model is useless but that ranking facts is
the wrong job for it — the rules engine already does that correctly, in under a
second, deterministically.

So this mode gives the model the ranked findings as input and asks for the one
thing rules cannot produce: what the findings might mean, and how they relate to
each other. Each rule looks at a single dimension, so nothing in the rules engine
can notice that a daypart collapse and a branch closure are one event seen twice.
That connection is where an analyst earns its place, and it is all this mode asks
for.

The division of ownership is absolute:

* **Rules own** every number, every severity, the ranking, the scope, and which
  findings exist at all. The model cannot add, drop, reorder, or restate one.
* **The model owns** interpretation, clearly labelled as interpretation, and
  cross-finding connections.
* **The validators own** whether any of that survives: figures must trace to the
  brief, arithmetic in prose is recomputed, causes must be hedged, and an
  explanation reaching for data this platform does not hold is refused outright.

One generation per run instead of several. The exploration loop existed to
discover facts; the facts now arrive already discovered.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.config import get_settings
from app.services.insights.analyst.ledger import FactLedger, collect_numbers
from app.services.insights.analyst.output import AnalystCommentary
from app.services.insights.analyst.schemas import ToolResult
from app.services.insights.analyst.validation import (
    CONFIDENCE_BY_NAME,
    CoverageContext,
    Rejection,
    check_causal_language,
    check_numbers,
    check_prose_arithmetic,
    check_unsupported_domain,
)
from app.models.enums import AnalysisConfidence
from app.schemas.insights import DiagnosticsSnapshotResponse
from app.services.insights.rules import CandidateInsight

settings = get_settings()
logger = logging.getLogger(__name__)

# The brief is one synthetic ledger entry. Everything in it came from the
# deterministic layer, so anything the model writes is checked against the facts
# the rules engine already stood behind.
BRIEF_CALL_TOOL = "rules_brief"


@dataclass(slots=True)
class RulesBrief:
    """The ranked, deterministic input to one additive pass."""

    period_label: str
    previous_period_label: str
    coverage: CoverageContext
    headline: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "period": self.period_label,
            "previous_period": self.previous_period_label,
            "coverage": self.coverage.to_payload(),
            "headline": self.headline,
            "ranked_findings": self.findings,
            "caveats": self.notes,
        }


def build_brief(
    snapshot: DiagnosticsSnapshotResponse,
    candidates: list[CandidateInsight],
    coverage: CoverageContext,
) -> RulesBrief:
    """Everything the model is allowed to reason about, and nothing else.

    Findings arrive numbered in the rules engine's own order. That numbering is
    the only handle the model gets on them, which is what makes re-ranking
    impossible rather than merely discouraged: a reply can point at finding 3,
    it cannot promote it.
    """

    headline = [
        {
            "metric": row.metric,
            "current": round(row.current, 2),
            "previous": round(row.previous, 2),
            "change": round(row.absolute_change, 2),
            "percent_change": (
                round(row.percent_change, 1) if row.percent_change is not None else None
            ),
        }
        for row in snapshot.headline
        if row.metric in {"gross_revenue", "orders", "average_order_value", "customers"}
    ]

    findings = [
        {
            "ref": index,
            "rank": index,
            "severity": candidate.severity.value,
            "dimension": candidate.dimension,
            "subject": candidate.subject,
            "statement": candidate.body,
            # What the deterministic root-cause layer already established, where
            # it established anything. Withholding it makes the model guess at
            # something the system knows.
            "established_cause": candidate.root_cause,
            "numbers": candidate.facts,
        }
        for index, candidate in enumerate(candidates, start=1)
    ]

    return RulesBrief(
        period_label=snapshot.current_period.label,
        previous_period_label=snapshot.previous_period.label,
        coverage=coverage,
        headline=headline,
        findings=findings,
        notes=list(snapshot.data_quality.notes),
    )


def brief_ledger(brief: RulesBrief) -> FactLedger:
    """A ledger holding exactly the brief's numbers.

    The number gate is unchanged; only its source moves. Where the exploring
    analyst was checked against what its tool calls returned, this one is checked
    against what the rules engine stated — a strictly narrower set, because it
    excludes everything the model was never shown.
    """

    ledger = FactLedger()
    ledger.record(
        ToolResult(
            tool=BRIEF_CALL_TOOL,
            args={"period": brief.period_label},
            ok=True,
            data=brief.to_payload(),
        )
    )
    return ledger


def build_commentary_prompt(brief: RulesBrief) -> str:
    """Compact by design: one short reply is the whole latency budget."""

    payload = json.dumps(brief.to_payload(), default=str, separators=(",", ":"))
    return f"""You are advising a restaurant owner. The findings below are already
established and already ranked by importance. They are correct. Your job is NOT
to restate, re-rank, or add findings.

Your job is only:
1. what each finding might mean for the business
2. connections BETWEEN findings that no single finding shows on its own

Return STRICT JSON only:
{{
  "interpretations": [
    {{"finding_ref": 1, "text": "one sentence", "confidence": "LOW|MEDIUM|HIGH"}}
  ],
  "connections": [
    {{"refs": [1,2], "text": "one sentence", "confidence": "LOW|MEDIUM|HIGH"}}
  ],
  "context": "one sentence, or null"
}}

Hard rules, all checked afterwards:
- refer to findings by their ref number; never invent a finding
- every number you write must already appear below, exactly
- an explanation must be hedged: "may", "might", "could", "worth checking"
- NEVER explain anything by marketing, campaigns, advertising, competitors,
  weather, seasons, pricing strategy, staffing, supplier costs, customer
  sentiment or demand. This platform holds NO data about any of them, so such an
  explanation cannot be checked and is worthless. Explain only using what is in
  the data below: branches, dishes, times of day, customer cohorts, availability,
  cancellations, payments
- where a finding carries an "established_cause", use it rather than guessing;
  it is already known to be true
- prefer saying less. An interpretation you are unsure of is worse than none.
  Do not restate a finding back as its own explanation — "revenue fell, which
  may indicate a fall in revenue" is worth nothing
- at most 3 interpretations and 2 connections, one short sentence each

Data:
{payload}

Write the commentary now.
"""


@dataclass(slots=True)
class ValidatedCommentary:
    interpretations: list[dict[str, Any]] = field(default_factory=list)
    connections: list[dict[str, Any]] = field(default_factory=list)
    context: str | None = None
    rejections: list[Rejection] = field(default_factory=list)

    @property
    def accepted_count(self) -> int:
        return len(self.interpretations) + len(self.connections)

    def rejection_payload(self) -> list[dict[str, Any]]:
        return [row.to_payload() for row in self.rejections]

    def to_payload(self) -> dict[str, Any]:
        return {
            "interpretations": self.interpretations,
            "connections": self.connections,
            "context": self.context,
        }


def validate_commentary(
    commentary: AnalystCommentary,
    *,
    brief: RulesBrief,
    ledger: FactLedger,
) -> ValidatedCommentary:
    """Every gate the exploring analyst faced, plus the two 8D asked for.

    Coverage is not re-checked here: the rules engine already refuses to produce
    findings on an insufficient window, so an empty brief means an empty pass.
    Severity and ranking are not checked because the model cannot touch them.
    """

    result = ValidatedCommentary()
    valid_refs = {row["ref"] for row in brief.findings}
    call_ids = [entry.call_id for entry in ledger.entries]

    def gate(text: str, label: str) -> str | None:
        # Order matters: cheapest and most decisive first.
        for check, name in (
            (lambda: check_numbers(text, call_ids, ledger), "numbers"),
            (lambda: check_prose_arithmetic(text), "arithmetic"),
            (lambda: check_unsupported_domain(text), "domain"),
        ):
            error = check()
            if error is not None:
                result.rejections.append(Rejection("commentary", name, label, error))
                return name
        return None

    for interpretation in commentary.interpretations:
        label = f"interpretation on finding {interpretation.finding_ref}"
        if interpretation.finding_ref not in valid_refs:
            result.rejections.append(
                Rejection(
                    "commentary",
                    "reference",
                    label,
                    f"points at finding {interpretation.finding_ref}, which does not exist",
                )
            )
            continue
        if gate(interpretation.text, label) is not None:
            continue
        # An interpretation is an explanation by definition, so it must read as a
        # possibility. The causality gate is applied to it directly here rather
        # than through a finding's body/interpretation split.
        if _unhedged_cause(interpretation.text):
            result.rejections.append(
                Rejection(
                    "commentary",
                    "causality",
                    label,
                    "states a cause as fact; it must read as a possibility",
                )
            )
            continue

        result.interpretations.append(
            {
                "finding_ref": interpretation.finding_ref,
                "text": interpretation.text,
                "confidence": CONFIDENCE_BY_NAME.get(
                    interpretation.confidence, AnalysisConfidence.LOW
                ).value,
            }
        )

    for connection in commentary.connections:
        label = f"connection {connection.refs}"
        unknown = [ref for ref in connection.refs if ref not in valid_refs]
        if unknown:
            result.rejections.append(
                Rejection("commentary", "reference", label, f"unknown findings {unknown}")
            )
            continue
        if gate(connection.text, label) is not None:
            continue
        if _unhedged_cause(connection.text):
            result.rejections.append(
                Rejection("commentary", "causality", label, "states a cause as fact")
            )
            continue

        result.connections.append(
            {
                "refs": list(connection.refs),
                "text": connection.text,
                "confidence": CONFIDENCE_BY_NAME.get(
                    connection.confidence, AnalysisConfidence.LOW
                ).value,
            }
        )

    if commentary.context:
        if gate(commentary.context, "context") is None and not _unhedged_cause(
            commentary.context
        ):
            result.context = commentary.context

    return result


def _unhedged_cause(text: str) -> bool:
    """A causal claim with nothing marking it as a possibility."""

    from app.services.insights.analyst.validation import CAUSAL_MARKERS, HEDGE_MARKERS

    lowered = (text or "").casefold()
    if not any(marker in lowered for marker in CAUSAL_MARKERS):
        return False
    return not any(hedge in lowered for hedge in HEDGE_MARKERS)


__all__ = [
    "BRIEF_CALL_TOOL",
    "RulesBrief",
    "ValidatedCommentary",
    "brief_ledger",
    "build_brief",
    "build_commentary_prompt",
    "validate_commentary",
]

"""The deterministic gate between a generated analysis and an owner.

Nothing a model produces is trusted. Each finding runs a fixed sequence of
checks, and any one of them failing discards that finding whole rather than
patching it — a claim with one invented figure gives no reason to believe the
rest of its sentence.

The gates, in order, and why each exists:

1. **Evidence** — every claim cites tool calls that actually happened in this
   run and returned data. A citation of a call that errored is a citation of an
   absence.
2. **Numbers** — every figure in the prose traces back to what those cited calls
   returned. This is narration's guardrail from Phase 2, over the ledger.
3. **Arithmetic** — where the analyst stated a change or a percentage, it is
   recomputed. Real numbers assembled into a false relationship is the failure a
   membership test cannot catch and the one most likely to mislead.
4. **Coverage** — sufficiency is decided here, from the same thresholds the
   rules engine uses, and never by asking the model whether it had enough data.
5. **Severity** — clamped to what the money justifies, by the same rule that
   stopped small movements shouting in Phase 7. The analyst may rank; it may not
   inflate.
6. **Safety** — a recommendation is executable only if it names one of the six
   existing executable actions and its numbers sit inside the platform's
   discount caps. Everything else is downgraded to advisory, which creates
   nothing. The owner approval boundary is untouched: this decides what may be
   *proposed*, and `actions.approve_proposal` still decides what may run.

A rejection is recorded, never silent. The rate at which these fire is the
evidence for whether the analyst is fit to show anyone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Iterable

from app.config import get_settings
from app.models.enums import (
    AnalysisConfidence,
    OwnerActionType,
    OwnerInsightSeverity,
)
from app.services.insights.analyst.ledger import FactLedger
from app.services.insights.analyst.output import (
    AIFinding,
    AIRecommendation,
    AnalysisVerdict,
)
from app.services.insights.facts import extract_numbers, unsupported_numbers
from app.services.insights.rules import _severity_for

settings = get_settings()

# The six action types approving turns into a live offer. A recommendation that
# names anything else is advisory by definition.
EXECUTABLE_ACTION_TYPES = frozenset(
    {
        OwnerActionType.PROMOTE_ITEM,
        OwnerActionType.PROMOTE_CATEGORY,
        OwnerActionType.DAYPART_OFFER,
        OwnerActionType.WINBACK_INACTIVE,
        OwnerActionType.WELCOME_NEW_CUSTOMERS,
        OwnerActionType.CROSS_SELL_COMBO,
    }
)

# Words that assert one thing made another happen. Permitted in an
# interpretation, which is offered as a possibility; refused in the body, which
# is read as a measurement. Nothing in this platform measures causation — an
# order carries no reason for existing — so a causal claim stated as observed is
# always an overreach, however plausible it sounds.
CAUSAL_MARKERS: tuple[str, ...] = (
    "because",
    "caused by",
    "caused the",
    "due to",
    "led to",
    "leading to",
    "as a result of",
    "resulted in",
    "drove the",
    "driven by",
    "explains the",
    "the reason",
    "thanks to",
    "owing to",
)

# Hedges that turn a causal sentence into a stated possibility. An
# interpretation containing a causal claim must carry one of these.
HEDGE_MARKERS: tuple[str, ...] = (
    "may",
    "might",
    "could",
    "likely",
    "possibly",
    "probably",
    "suggests",
    "appears",
    "looks like",
    "consistent with",
    "one explanation",
    "worth checking",
    "seems",
)

# Domains this platform holds no data about. An explanation that reaches for one
# is not a weak explanation, it is an invented one: nothing in the database could
# ever support or contradict "a successful marketing campaign", so offering it as
# a possible cause dresses a guess as analysis. 8D found every run doing this,
# hedged well enough to pass the causality gate.
UNSUPPORTED_DOMAINS: dict[str, tuple[str, ...]] = {
    "marketing": ("marketing", "advertis", "campaign", "promotion effort", "social media", "brand"),
    "competitors": ("competitor", "rival", "market share", "other restaurants"),
    "weather": ("weather", "rain", "monsoon", "heat wave", "season" ),
    "pricing strategy": ("price increase", "price rise", "pricing issue", "pricing strategy", "raised prices"),
    "staffing": ("staff", "employee", "server", "chef", "kitchen team", "labour", "labor"),
    "customer sentiment": ("customer interest", "customer satisfaction", "loyalty issue",
                           "reputation", "word of mouth", "customer demand",
                           "first-time experience", "poor experience", "engagement with"),
    "footfall": ("foot traffic", "footfall", "passing trade", "walk-in",
                 "customer traffic", "customer activity"),
    "popularity": ("loss of interest", "loss of popularity", "less popular",
                   "dining habits", "customer preferences", "shift in customer behavior",
                   "shift in customer behaviour"),
    "supply cost": ("supplier", "ingredient cost", "food cost", "inflation"),
}

# Arithmetic is checked as arithmetic, not as prose. These are rounding-level
# allowances, not agreement-level ones.
ARITHMETIC_ABSOLUTE_EPSILON = 1.0
ARITHMETIC_RELATIVE_EPSILON = 0.001
PERCENT_ABSOLUTE_EPSILON = 0.5

SEVERITY_BY_NAME = {
    "INFO": OwnerInsightSeverity.INFO,
    "LOW": OwnerInsightSeverity.LOW,
    "MEDIUM": OwnerInsightSeverity.MEDIUM,
    "HIGH": OwnerInsightSeverity.HIGH,
}
SEVERITY_ORDER = {
    OwnerInsightSeverity.INFO: 0,
    OwnerInsightSeverity.LOW: 1,
    OwnerInsightSeverity.MEDIUM: 2,
    OwnerInsightSeverity.HIGH: 3,
}
CONFIDENCE_BY_NAME = {
    "LOW": AnalysisConfidence.LOW,
    "MEDIUM": AnalysisConfidence.MEDIUM,
    "HIGH": AnalysisConfidence.HIGH,
}


@dataclass(frozen=True, slots=True)
class CoverageContext:
    """What the backend measured about the window, independent of the model."""

    orders: int
    trading_days: int
    days_in_window: int
    sufficient_volume: bool

    @property
    def is_sufficient(self) -> bool:
        # Both tests matter. Enough orders concentrated in a single day is not a
        # period anyone should draw a weekday or daypart conclusion from.
        return (
            self.sufficient_volume
            and self.orders >= settings.insights_min_orders_for_delta
            and self.trading_days >= settings.analyst_min_trading_days
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "orders": self.orders,
            "trading_days": self.trading_days,
            "days_in_window": self.days_in_window,
            "sufficient_volume": self.sufficient_volume,
            "is_sufficient": self.is_sufficient,
        }


@dataclass(slots=True)
class Rejection:
    kind: str
    gate: str
    title: str
    detail: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "gate": self.gate,
            "title": self.title,
            "detail": self.detail,
        }


@dataclass(slots=True)
class ValidatedFinding:
    finding: AIFinding
    severity: OwnerInsightSeverity
    confidence: AnalysisConfidence
    evidence: dict[str, Any]
    clamped: bool = False


@dataclass(slots=True)
class ValidatedRecommendation:
    recommendation: AIRecommendation
    action_type: OwnerActionType | None
    is_executable: bool
    priority: Decimal
    confidence: AnalysisConfidence
    evidence: dict[str, Any]
    downgraded_reason: str | None = None


@dataclass(slots=True)
class ValidationOutcome:
    findings: list[ValidatedFinding] = field(default_factory=list)
    recommendations: list[ValidatedRecommendation] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    insufficient_data: bool = False

    @property
    def accepted_count(self) -> int:
        return len(self.findings)

    def rejection_payload(self) -> list[dict[str, Any]]:
        return [rejection.to_payload() for rejection in self.rejections]


# --- individual gates ------------------------------------------------------


def check_evidence(
    evidence: Iterable[str], ledger: FactLedger
) -> tuple[list[str], str | None]:
    """Citations that exist in this run and returned data."""

    cited = [str(call_id).strip() for call_id in evidence if str(call_id).strip()]
    if not cited:
        return [], "no evidence cited"

    known = ledger.known_call_ids()
    unknown = [call_id for call_id in cited if call_id not in known]
    if unknown:
        # Either a fabricated citation or one from a different run. Both mean the
        # claim cannot be traced, and a plausible-looking id is worse than none.
        return [], f"cited calls that were never made: {sorted(unknown)}"

    successful = ledger.successful_call_ids()
    usable = [call_id for call_id in cited if call_id in successful]
    if not usable:
        return [], f"every cited call failed: {sorted(cited)}"

    return usable, None


def check_numbers(text: str, call_ids: Iterable[str], ledger: FactLedger) -> str | None:
    """Every figure in the prose came from the cited calls."""

    allowed = ledger.allowed_numbers(call_ids)
    offenders = unsupported_numbers(text, allowed)
    if offenders:
        return f"figures not supported by the cited data: {offenders}"
    return None


def check_arithmetic(finding: AIFinding, ledger: FactLedger, call_ids: list[str]) -> str | None:
    """Recompute whatever arithmetic the analyst stated.

    A change that is not the difference of the two numbers it sits between, or a
    percentage that is not that change over the base, is a false relationship
    between true figures — which reads more convincingly than an invented number
    and is therefore worse.
    """

    allowed = ledger.allowed_numbers(call_ids)

    for metric in finding.metrics:
        for label, value in (("current", metric.current), ("previous", metric.previous)):
            if value is None:
                continue
            if unsupported_numbers(str(value), allowed):
                return f"{metric.name}.{label} ({value}) is not in the cited data"

        if metric.previous is None:
            continue

        expected_change = metric.current - metric.previous
        if metric.absolute_change is not None:
            # Deliberately far tighter than `ai_manager_number_tolerance`, which
            # exists to let prose round a figure for readability (1234.56 as
            # "1,235"). A stated change is an assertion about an exact
            # relationship, and 5% of a large change is hundreds of rupees of
            # slack — enough for a wrong conclusion to pass as a rounded one.
            if abs(metric.absolute_change - expected_change) > max(
                ARITHMETIC_ABSOLUTE_EPSILON, abs(expected_change) * ARITHMETIC_RELATIVE_EPSILON
            ):
                return (
                    f"{metric.name}: stated change {metric.absolute_change} does not "
                    f"match {metric.current} - {metric.previous}"
                )

        if metric.percent_change is not None:
            if metric.previous == 0:
                return (
                    f"{metric.name}: a percentage change from zero is undefined, "
                    "not a number"
                )
            expected_percent = expected_change / abs(metric.previous) * 100
            # Half a point of slack covers rounding to one decimal; the relative
            # term covers float noise on large percentages, not disagreement.
            if abs(metric.percent_change - expected_percent) > max(
                PERCENT_ABSOLUTE_EPSILON, abs(expected_percent) * ARITHMETIC_RELATIVE_EPSILON
            ):
                return (
                    f"{metric.name}: stated {metric.percent_change}% does not match "
                    f"the {expected_percent:.1f}% the figures give"
                )

    return None


def check_causal_language(finding: AIFinding) -> str | None:
    """Keep measured claims and explanations apart.

    `body` is presented to an owner as what the data shows, so a causal claim
    there is a measurement the platform never made. `interpretation` is allowed
    to explain, but must say so as a possibility — an unhedged cause in either
    field is the failure that makes a wrong analysis most convincing.
    """

    body = (finding.body or "").casefold()
    for marker in CAUSAL_MARKERS:
        if marker in body:
            return (
                f"the observed claim asserts cause ({marker!r}); causes belong in "
                "interpretation, and nothing here measures them"
            )

    interpretation = (finding.interpretation or "").casefold()
    if interpretation and any(marker in interpretation for marker in CAUSAL_MARKERS):
        if not any(hedge in interpretation for hedge in HEDGE_MARKERS):
            return (
                "the interpretation states a cause as fact; it must read as a "
                "possibility"
            )

    return None


def check_unsupported_domain(text: str) -> str | None:
    """Refuse an explanation that reaches outside the data entirely.

    Hedging makes a causal claim honest about being a guess; it does not make a
    guess about unmeasured data into analysis. "This may be due to a successful
    marketing campaign" is unfalsifiable here — there is no marketing table, no
    spend, no campaign — so it reads as insight while carrying none.
    """

    lowered = (text or "").casefold()
    for domain, markers in UNSUPPORTED_DOMAINS.items():
        for marker in markers:
            if marker in lowered:
                return (
                    f"refers to {domain}, which this platform holds no data about; "
                    "an explanation that cannot be checked against anything is a "
                    "guess, not an interpretation"
                )
    return None


# "from 2,459.65 to 1,578.92" and the like: the pair a prose claim rests on.
FROM_TO_PATTERN = re.compile(
    r"from\s+(?:[^\d\-+]{0,3})(-?[\d,]+(?:\.\d+)?)\s+to\s+(?:[^\d\-+]{0,3})(-?[\d,]+(?:\.\d+)?)",
    re.IGNORECASE,
)
PERCENT_PATTERN = re.compile(r"(-?[\d,]+(?:\.\d+)?)\s*%")
BY_AMOUNT_PATTERN = re.compile(
    r"\b(?:by|of)\s+(?:[^\d\-+]{0,3})(-?[\d,]+(?:\.\d+)?)", re.IGNORECASE
)


def _as_float(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def check_prose_arithmetic(text: str) -> str | None:
    """Verify the relationships a sentence asserts between its own numbers.

    The metric gate only checks arithmetic the model chose to declare. Most
    claims are not declared — they are written in the sentence, as "revenue fell
    from A to B, down C (N%)" — and until now those figures were only checked
    for membership. Membership cannot catch a true A and a true B joined by a
    false C.

    Deliberately conservative: it fires only on sentences containing an explicit
    "from A to B", and only against a change or percentage stated in the same
    sentence. Anything it cannot parse confidently, it passes.
    """

    for sentence in re.split(r"(?<=[.;])\s+", text or ""):
        pair = FROM_TO_PATTERN.search(sentence)
        if pair is None:
            continue
        start = _as_float(pair.group(1))
        end = _as_float(pair.group(2))
        if start is None or end is None:
            continue

        expected_change = end - start
        remainder = sentence[: pair.start()] + sentence[pair.end() :]

        for match in BY_AMOUNT_PATTERN.finditer(remainder):
            stated = _as_float(match.group(1))
            if stated is None:
                continue
            if abs(abs(stated) - abs(expected_change)) > max(
                ARITHMETIC_ABSOLUTE_EPSILON, abs(expected_change) * ARITHMETIC_RELATIVE_EPSILON
            ):
                return (
                    f"states a change of {stated} between {start} and {end}, "
                    f"which differ by {expected_change:.2f}"
                )

        if start:
            expected_percent = expected_change / abs(start) * 100
            for match in PERCENT_PATTERN.finditer(remainder):
                stated = _as_float(match.group(1))
                if stated is None:
                    continue
                if abs(abs(stated) - abs(expected_percent)) > max(
                    PERCENT_ABSOLUTE_EPSILON, abs(expected_percent) * ARITHMETIC_RELATIVE_EPSILON
                ):
                    return (
                        f"states {stated}% between {start} and {end}, "
                        f"which is {expected_percent:.1f}%"
                    )

    return None


def clamp_severity(finding: AIFinding) -> tuple[OwnerInsightSeverity, bool]:
    """Hold a finding to the severity its money justifies.

    Reuses the rules engine's own ceiling, so an analyst finding and a rule
    finding about the same movement cannot disagree about how loud it is.
    """

    claimed = SEVERITY_BY_NAME.get(finding.severity, OwnerInsightSeverity.LOW)

    money_amounts = [
        abs(metric.absolute_change if metric.absolute_change is not None else metric.current)
        for metric in finding.metrics
        if metric.unit == "money"
    ]
    if not money_amounts:
        # Nothing monetary to justify a loud finding, so it cannot exceed LOW.
        ceiling = OwnerInsightSeverity.LOW
    else:
        ceiling = _severity_for(
            100.0,
            settings.insight_item_contribution_percent,
            money_amount=max(money_amounts),
        )

    if SEVERITY_ORDER[claimed] > SEVERITY_ORDER[ceiling]:
        return ceiling, True
    return claimed, False


def check_action_safety(
    recommendation: AIRecommendation,
) -> tuple[OwnerActionType | None, bool, str | None]:
    """Whether a recommendation may be proposed as executable.

    Returns (action_type, is_executable, reason_it_was_downgraded). Downgrading
    is always safe: an advisory proposal creates nothing at all, so an
    unrecognised or over-cap request costs the owner a suggestion, never money.
    """

    raw = (recommendation.requested_action_type or "").strip().upper()
    if not raw:
        return None, False, None

    try:
        action_type = OwnerActionType(raw)
    except ValueError:
        return None, False, f"unknown action type {raw!r}"

    if action_type not in EXECUTABLE_ACTION_TYPES:
        # OPERATIONAL_REVIEW and PROTECT_SUPPLY are advisory by design.
        return action_type, False, None

    discount = recommendation.discount_percent
    if discount is None:
        return action_type, False, "no discount was specified"
    if discount <= 0:
        return action_type, False, f"discount {discount} is not positive"
    if discount > float(settings.ai_max_percentage_discount):
        return (
            action_type,
            False,
            f"discount {discount}% exceeds the {settings.ai_max_percentage_discount}% cap",
        )

    minimum = recommendation.minimum_order_amount
    if minimum is None:
        return action_type, False, "no minimum order was specified"
    if minimum < float(settings.ai_min_order_threshold):
        return (
            action_type,
            False,
            f"minimum order {minimum} is below the "
            f"{settings.ai_min_order_threshold} threshold",
        )

    return action_type, True, None


# --- the pass ---------------------------------------------------------------


def validate_verdict(
    verdict: AnalysisVerdict,
    *,
    ledger: FactLedger,
    coverage: CoverageContext,
) -> ValidationOutcome:
    """Run every gate over one generated analysis."""

    outcome = ValidationOutcome(insufficient_data=not coverage.is_sufficient)

    if not coverage.is_sufficient:
        # The backend decides this, not the model. A run over four trading days
        # must not produce confident conclusions however confidently they are
        # written, and "I don't have enough data" is the correct answer rather
        # than a failure.
        for finding in verdict.findings:
            outcome.rejections.append(
                Rejection(
                    kind="finding",
                    gate="coverage",
                    title=finding.title,
                    detail=(
                        f"only {coverage.orders} orders across "
                        f"{coverage.trading_days} trading days; the window does "
                        "not support conclusions"
                    ),
                )
            )
        for recommendation in verdict.recommendations:
            outcome.rejections.append(
                Rejection(
                    kind="recommendation",
                    gate="coverage",
                    title=recommendation.title,
                    detail="not enough trade in the window to recommend against",
                )
            )
        return outcome

    for finding in verdict.findings:
        call_ids, evidence_error = check_evidence(finding.evidence, ledger)
        if evidence_error is not None:
            outcome.rejections.append(
                Rejection("finding", "evidence", finding.title, evidence_error)
            )
            continue

        prose = " ".join(
            part for part in (finding.title, finding.body, finding.interpretation) if part
        )
        number_error = check_numbers(prose, call_ids, ledger)
        if number_error is not None:
            outcome.rejections.append(
                Rejection("finding", "numbers", finding.title, number_error)
            )
            continue

        arithmetic_error = check_arithmetic(finding, ledger, call_ids)
        if arithmetic_error is not None:
            outcome.rejections.append(
                Rejection("finding", "arithmetic", finding.title, arithmetic_error)
            )
            continue

        causal_error = check_causal_language(finding)
        if causal_error is not None:
            outcome.rejections.append(
                Rejection("finding", "causality", finding.title, causal_error)
            )
            continue

        severity, clamped = clamp_severity(finding)
        outcome.findings.append(
            ValidatedFinding(
                finding=finding,
                severity=severity,
                confidence=CONFIDENCE_BY_NAME.get(
                    finding.confidence, AnalysisConfidence.LOW
                ),
                evidence={
                    "call_ids": call_ids,
                    "calls": [
                        entry.to_payload()
                        for entry in ledger.entries
                        if entry.call_id in set(call_ids)
                    ],
                },
                clamped=clamped,
            )
        )

    for recommendation in verdict.recommendations:
        call_ids, evidence_error = check_evidence(recommendation.evidence, ledger)
        if evidence_error is not None:
            outcome.rejections.append(
                Rejection("recommendation", "evidence", recommendation.title, evidence_error)
            )
            continue

        prose = f"{recommendation.title} {recommendation.rationale} " + (
            recommendation.expected_impact_basis or ""
        )
        number_error = check_numbers(prose, call_ids, ledger)
        if number_error is not None:
            outcome.rejections.append(
                Rejection("recommendation", "numbers", recommendation.title, number_error)
            )
            continue

        if recommendation.expected_impact_amount is not None:
            impact_error = check_numbers(
                str(recommendation.expected_impact_amount), call_ids, ledger
            )
            if impact_error is not None:
                # An impact estimate is a promise about money. One that does not
                # come from the data is exactly the claim not to let through.
                outcome.rejections.append(
                    Rejection(
                        "recommendation",
                        "numbers",
                        recommendation.title,
                        f"expected impact is not supported: {impact_error}",
                    )
                )
                continue

        action_type, is_executable, downgraded = check_action_safety(recommendation)
        outcome.recommendations.append(
            ValidatedRecommendation(
                recommendation=recommendation,
                action_type=action_type,
                is_executable=is_executable,
                priority=Decimal(str(round(recommendation.priority, 2))),
                confidence=CONFIDENCE_BY_NAME.get(
                    recommendation.confidence, AnalysisConfidence.LOW
                ),
                evidence={"call_ids": call_ids},
                downgraded_reason=downgraded,
            )
        )
        if downgraded is not None:
            outcome.rejections.append(
                Rejection(
                    "recommendation",
                    "safety",
                    recommendation.title,
                    f"downgraded to advisory: {downgraded}",
                )
            )

    return outcome


__all__ = [
    "ARITHMETIC_ABSOLUTE_EPSILON",
    "ARITHMETIC_RELATIVE_EPSILON",
    "CONFIDENCE_BY_NAME",
    "PERCENT_ABSOLUTE_EPSILON",
    "CoverageContext",
    "EXECUTABLE_ACTION_TYPES",
    "Rejection",
    "SEVERITY_BY_NAME",
    "ValidatedFinding",
    "ValidatedRecommendation",
    "ValidationOutcome",
    "check_action_safety",
    "CAUSAL_MARKERS",
    "HEDGE_MARKERS",
    "UNSUPPORTED_DOMAINS",
    "check_arithmetic",
    "check_prose_arithmetic",
    "check_unsupported_domain",
    "check_causal_language",
    "check_evidence",
    "check_numbers",
    "clamp_severity",
    "validate_verdict",
]

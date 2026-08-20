"""Adversarial tests for the Phase 8B ledger and validator.

Every test here is a generated analysis that a careless reader would accept.
None of them involve a model: the outputs are hand-written to be exactly as
wrong as a real failure would be, because the point of the validator is that it
does not need the model to cooperate.

The failures worth catching, roughly in order of how convincing they look:

* a figure that never appeared in the data
* a figure that did appear, cited from a call that never returned it
* true numbers combined into a false change or percentage
* a confident conclusion drawn from four orders
* a discount past the platform cap, arriving as a recommendation
* an evidence list that is empty, fabricated, or points at a failed call
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.config import get_settings
from app.models.enums import (
    AnalysisConfidence,
    OwnerActionType,
    OwnerInsightSeverity,
)
from app.services.insights.analyst.ledger import FactLedger, collect_numbers
from app.services.insights.analyst.output import (
    AIFinding,
    AIRecommendation,
    AnalysisVerdict,
    MetricClaim,
)
from app.services.insights.analyst.schemas import ToolResult
from app.services.insights.analyst.validation import (
    CoverageContext,
    check_action_safety,
    check_arithmetic,
    check_evidence,
    clamp_severity,
    validate_verdict,
)

settings = get_settings()


def ledger_with(*results: ToolResult) -> FactLedger:
    ledger = FactLedger()
    for result in results:
        ledger.record(result)
    return ledger


def ok_result(tool: str, data: dict) -> ToolResult:
    return ToolResult(tool=tool, args={}, ok=True, data=data)


def failed_result(tool: str, error: str = "tool_failed") -> ToolResult:
    return ToolResult(tool=tool, args={}, ok=False, error=error)


def healthy_coverage() -> CoverageContext:
    return CoverageContext(
        orders=120, trading_days=28, days_in_window=30, sufficient_volume=True
    )


def thin_coverage() -> CoverageContext:
    return CoverageContext(
        orders=4, trading_days=2, days_in_window=30, sufficient_volume=False
    )


def finding(**overrides) -> AIFinding:
    base = {
        "category": "payments",
        "title": "Payment failures cost 4000",
        "body": "Orders worth 4000 were lost at the payment step.",
        "severity": "LOW",
        "confidence": "MEDIUM",
        "evidence": ["call_1"],
        "metrics": [],
    }
    base.update(overrides)
    return AIFinding(**base)


def recommendation(**overrides) -> AIRecommendation:
    base = {
        "title": "Recover failed payments",
        "rationale": "Orders worth 4000 never completed payment.",
        "evidence": ["call_1"],
    }
    base.update(overrides)
    return AIRecommendation(**base)


# --- the ledger ------------------------------------------------------------


class LedgerTests(unittest.TestCase):
    def test_numbers_are_collected_from_nested_results(self) -> None:
        values: set[float] = set()
        collect_numbers({"a": [{"b": 12.5}], "c": {"d": [3, 4]}}, values)
        self.assertEqual(values, {12.5, 3.0, 4.0})

    def test_booleans_are_not_collected_as_numbers(self) -> None:
        # `True` is not the number 1. Collecting it would silently authorise "1"
        # for any result that happens to contain a flag.
        values: set[float] = set()
        collect_numbers({"is_open": True, "is_active": False}, values)
        self.assertEqual(values, set())

    def test_iso_dates_contribute_their_parts(self) -> None:
        values: set[float] = set()
        collect_numbers({"start_date": "2026-08-13"}, values)
        self.assertEqual(values, {13.0, 8.0, 2026.0})

    def test_failed_calls_are_recorded_with_no_values(self) -> None:
        ledger = ledger_with(failed_result("get_branch_status"))
        entry = ledger.entry("call_1")
        self.assertIsNotNone(entry)
        self.assertFalse(entry.ok)
        self.assertEqual(entry.values, set())
        self.assertEqual(ledger.successful_call_ids(), set())

    def test_allowed_numbers_are_scoped_to_the_cited_calls(self) -> None:
        # A finding about payments must not be able to borrow a figure from an
        # unrelated menu query it never cited.
        ledger = ledger_with(
            ok_result("get_payment_failures", {"lost_value": 4000.0}),
            ok_result("get_menu_health", {"unavailable_count": 77.0}),
        )
        self.assertIn(4000.0, ledger.allowed_numbers(["call_1"]))
        self.assertNotIn(77.0, ledger.allowed_numbers(["call_1"]))
        self.assertIn(77.0, ledger.allowed_numbers(["call_1", "call_2"]))

    def test_rounded_forms_of_a_value_are_allowed(self) -> None:
        ledger = ledger_with(ok_result("get_period_metrics", {"revenue": 1234.56}))
        allowed = ledger.allowed_numbers(["call_1"])
        self.assertIn(1235.0, allowed)
        self.assertIn(1234.6, allowed)
        self.assertNotIn(1400.0, allowed)


# --- evidence --------------------------------------------------------------


class EvidenceGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = ledger_with(
            ok_result("get_period_metrics", {"revenue": 4000.0}),
            failed_result("get_stockouts"),
        )

    def test_a_real_citation_passes(self) -> None:
        call_ids, error = check_evidence(["call_1"], self.ledger)
        self.assertIsNone(error)
        self.assertEqual(call_ids, ["call_1"])

    def test_a_fabricated_citation_is_rejected(self) -> None:
        # A plausible-looking id is worse than none: it reads as traceable.
        _ids, error = check_evidence(["call_9"], self.ledger)
        self.assertIsNotNone(error)
        self.assertIn("never made", error)

    def test_citing_only_a_failed_call_is_rejected(self) -> None:
        # Citing a call that errored is citing an absence of data.
        _ids, error = check_evidence(["call_2"], self.ledger)
        self.assertIsNotNone(error)
        self.assertIn("failed", error)

    def test_a_failed_call_alongside_a_good_one_is_dropped(self) -> None:
        call_ids, error = check_evidence(["call_1", "call_2"], self.ledger)
        self.assertIsNone(error)
        self.assertEqual(call_ids, ["call_1"])

    def test_empty_evidence_is_rejected(self) -> None:
        _ids, error = check_evidence([], self.ledger)
        self.assertIsNotNone(error)


# --- numbers ---------------------------------------------------------------


class NumberGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = ledger_with(
            ok_result("get_payment_failures", {"lost_value": 4000.0, "lost_orders": 12}),
            ok_result("get_menu_health", {"unavailable_count": 77}),
        )
        self.coverage = healthy_coverage()

    def test_a_supported_figure_survives(self) -> None:
        outcome = validate_verdict(
            AnalysisVerdict(findings=[finding()]),
            ledger=self.ledger,
            coverage=self.coverage,
        )
        self.assertEqual(outcome.accepted_count, 1)
        self.assertEqual(outcome.rejections, [])

    def test_an_invented_figure_discards_the_whole_finding(self) -> None:
        outcome = validate_verdict(
            AnalysisVerdict(
                findings=[
                    finding(body="Orders worth 4000 were lost, up from 2500 last month.")
                ]
            ),
            ledger=self.ledger,
            coverage=self.coverage,
        )
        self.assertEqual(outcome.accepted_count, 0)
        self.assertEqual(outcome.rejections[0].gate, "numbers")

    def test_a_figure_from_an_uncited_call_is_rejected(self) -> None:
        # 77 is real, and in the ledger — but not in the call this finding cites.
        outcome = validate_verdict(
            AnalysisVerdict(
                findings=[finding(body="77 dishes are switched off.", evidence=["call_1"])]
            ),
            ledger=self.ledger,
            coverage=self.coverage,
        )
        self.assertEqual(outcome.accepted_count, 0)
        self.assertEqual(outcome.rejections[0].gate, "numbers")

    def test_the_interpretation_is_checked_too(self) -> None:
        # An explanation is where a model is most tempted to reach for a number
        # nobody measured.
        outcome = validate_verdict(
            AnalysisVerdict(
                findings=[finding(interpretation="This is 63% of your weekly revenue.")]
            ),
            ledger=self.ledger,
            coverage=self.coverage,
        )
        self.assertEqual(outcome.accepted_count, 0)


# --- arithmetic ------------------------------------------------------------


class ArithmeticGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = ledger_with(
            ok_result("get_period_metrics", {"current": 800.0, "previous": 1000.0})
        )

    def _check(self, metric: MetricClaim) -> str | None:
        return check_arithmetic(finding(metrics=[metric]), self.ledger, ["call_1"])

    def test_correct_arithmetic_passes(self) -> None:
        self.assertIsNone(
            self._check(
                MetricClaim(
                    name="revenue",
                    current=800.0,
                    previous=1000.0,
                    absolute_change=-200.0,
                    percent_change=-20.0,
                    unit="money",
                )
            )
        )

    def test_a_false_change_between_true_numbers_is_caught(self) -> None:
        # The dangerous case: every figure is real, the relationship is not.
        error = self._check(
            MetricClaim(
                name="revenue", current=800.0, previous=1000.0, absolute_change=-500.0
            )
        )
        self.assertIsNotNone(error)
        self.assertIn("does not match", error)

    def test_a_false_percentage_is_caught(self) -> None:
        error = self._check(
            MetricClaim(
                name="revenue", current=800.0, previous=1000.0, percent_change=-80.0
            )
        )
        self.assertIsNotNone(error)
        self.assertIn("%", error)

    def test_a_percentage_from_zero_is_refused(self) -> None:
        # "Down 100% from nothing" is the growth-from-zero mistake the Phase 7
        # tiles already refuse to draw.
        ledger = ledger_with(ok_result("m", {"current": 500.0, "previous": 0.0}))
        error = check_arithmetic(
            finding(
                metrics=[
                    MetricClaim(
                        name="revenue", current=500.0, previous=0.0, percent_change=100.0
                    )
                ]
            ),
            ledger,
            ["call_1"],
        )
        self.assertIsNotNone(error)
        self.assertIn("undefined", error)

    def test_a_metric_value_not_in_the_data_is_caught(self) -> None:
        error = self._check(MetricClaim(name="revenue", current=810.0, previous=1000.0))
        self.assertIsNotNone(error)
        self.assertIn("not in the cited data", error)


# --- coverage --------------------------------------------------------------


class CoverageGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = ledger_with(ok_result("get_data_coverage", {"orders": 4}))

    def test_thin_data_rejects_every_finding(self) -> None:
        outcome = validate_verdict(
            AnalysisVerdict(
                findings=[finding(body="Orders worth 4 were lost.", confidence="HIGH")],
                recommendations=[recommendation(rationale="Only 4 orders.")],
            ),
            ledger=self.ledger,
            coverage=thin_coverage(),
        )
        self.assertEqual(outcome.accepted_count, 0)
        self.assertEqual(outcome.recommendations, [])
        self.assertTrue(outcome.insufficient_data)
        self.assertEqual({r.gate for r in outcome.rejections}, {"coverage"})

    def test_the_backend_decides_sufficiency_not_the_model(self) -> None:
        # A model claiming the data is fine does not make it fine.
        outcome = validate_verdict(
            AnalysisVerdict(insufficient_data=False, findings=[finding(body="Lost 4.")]),
            ledger=self.ledger,
            coverage=thin_coverage(),
        )
        self.assertTrue(outcome.insufficient_data)
        self.assertEqual(outcome.accepted_count, 0)

    def test_enough_orders_on_too_few_days_is_still_insufficient(self) -> None:
        # 200 orders in one day is not a period anyone should draw a weekday or
        # daypart conclusion from.
        coverage = CoverageContext(
            orders=200, trading_days=1, days_in_window=30, sufficient_volume=True
        )
        self.assertFalse(coverage.is_sufficient)

    def test_healthy_coverage_is_sufficient(self) -> None:
        self.assertTrue(healthy_coverage().is_sufficient)


# --- severity --------------------------------------------------------------


class SeverityClampTests(unittest.TestCase):
    def test_a_loud_claim_over_small_money_is_clamped(self) -> None:
        severity, clamped = clamp_severity(
            finding(
                severity="HIGH",
                metrics=[MetricClaim(name="revenue", current=300.0, unit="money")],
            )
        )
        self.assertTrue(clamped)
        self.assertEqual(severity, OwnerInsightSeverity.LOW)

    def test_large_money_may_be_loud(self) -> None:
        severity, clamped = clamp_severity(
            finding(
                severity="HIGH",
                metrics=[MetricClaim(name="revenue", current=99000.0, unit="money")],
            )
        )
        self.assertFalse(clamped)
        self.assertEqual(severity, OwnerInsightSeverity.HIGH)

    def test_a_finding_with_no_money_cannot_be_loud(self) -> None:
        severity, clamped = clamp_severity(
            finding(severity="HIGH", metrics=[MetricClaim(name="orders", current=9.0)])
        )
        self.assertTrue(clamped)
        self.assertEqual(severity, OwnerInsightSeverity.LOW)

    def test_a_quiet_claim_is_left_alone(self) -> None:
        severity, clamped = clamp_severity(finding(severity="INFO"))
        self.assertFalse(clamped)
        self.assertEqual(severity, OwnerInsightSeverity.INFO)


# --- action safety ---------------------------------------------------------


class ActionSafetyTests(unittest.TestCase):
    def test_a_valid_offer_request_may_be_executable(self) -> None:
        action_type, executable, reason = check_action_safety(
            recommendation(
                requested_action_type="PROMOTE_ITEM",
                discount_percent=10.0,
                minimum_order_amount=float(settings.ai_min_order_threshold) + 10,
            )
        )
        self.assertEqual(action_type, OwnerActionType.PROMOTE_ITEM)
        self.assertTrue(executable)
        self.assertIsNone(reason)

    def test_an_over_cap_discount_is_downgraded_not_rejected(self) -> None:
        # Downgrading is always safe: an advisory proposal creates nothing, so a
        # greedy request costs a suggestion rather than money.
        _type, executable, reason = check_action_safety(
            recommendation(
                requested_action_type="PROMOTE_ITEM",
                discount_percent=95.0,
                minimum_order_amount=float(settings.ai_min_order_threshold) + 10,
            )
        )
        self.assertFalse(executable)
        self.assertIn("cap", reason)

    def test_a_below_threshold_minimum_order_is_downgraded(self) -> None:
        _type, executable, reason = check_action_safety(
            recommendation(
                requested_action_type="PROMOTE_ITEM",
                discount_percent=10.0,
                minimum_order_amount=0.0,
            )
        )
        self.assertFalse(executable)
        self.assertIn("threshold", reason)

    def test_an_invented_action_type_is_downgraded(self) -> None:
        action_type, executable, reason = check_action_safety(
            recommendation(requested_action_type="DELETE_ALL_ORDERS")
        )
        self.assertIsNone(action_type)
        self.assertFalse(executable)
        self.assertIn("unknown action type", reason)

    def test_advisory_types_are_never_executable(self) -> None:
        for name in ("OPERATIONAL_REVIEW", "PROTECT_SUPPLY"):
            with self.subTest(action=name):
                action_type, executable, _reason = check_action_safety(
                    recommendation(
                        requested_action_type=name,
                        discount_percent=10.0,
                        minimum_order_amount=999.0,
                    )
                )
                self.assertEqual(action_type, OwnerActionType(name))
                self.assertFalse(executable)

    def test_an_offer_with_no_discount_is_advisory(self) -> None:
        _type, executable, reason = check_action_safety(
            recommendation(requested_action_type="WINBACK_INACTIVE")
        )
        self.assertFalse(executable)
        self.assertIn("no discount", reason)


# --- whole verdicts --------------------------------------------------------


class VerdictTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = ledger_with(
            ok_result(
                "get_payment_failures",
                {"lost_value": 4000.0, "lost_orders": 12, "share": 16.0},
            )
        )
        self.coverage = healthy_coverage()

    def test_a_bad_finding_does_not_take_a_good_one_with_it(self) -> None:
        outcome = validate_verdict(
            AnalysisVerdict(
                findings=[
                    finding(title="Real", body="4000 was lost across 12 orders."),
                    finding(title="Invented", body="Revenue fell by 7777."),
                ]
            ),
            ledger=self.ledger,
            coverage=self.coverage,
        )
        self.assertEqual(outcome.accepted_count, 1)
        self.assertEqual(outcome.findings[0].finding.title, "Real")
        self.assertEqual(len(outcome.rejections), 1)

    def test_false_arithmetic_is_caught_through_the_whole_pass(self) -> None:
        # The gate is also exercised directly, but a check that only works when
        # called on its own is not a gate — it has to fire from validate_verdict.
        outcome = validate_verdict(
            AnalysisVerdict(
                findings=[
                    finding(
                        body="Lost value was 4000 across 12 orders.",
                        metrics=[
                            MetricClaim(
                                name="lost_value",
                                current=4000.0,
                                previous=12.0,
                                absolute_change=4000.0,
                                unit="money",
                            )
                        ],
                    )
                ]
            ),
            ledger=self.ledger,
            coverage=self.coverage,
        )
        self.assertEqual(outcome.accepted_count, 0)
        self.assertEqual(outcome.rejections[0].gate, "arithmetic")

    def test_an_unsupported_impact_estimate_is_rejected(self) -> None:
        # An impact figure is a promise about money; one the data does not
        # support is exactly the claim not to let through.
        outcome = validate_verdict(
            AnalysisVerdict(
                recommendations=[
                    recommendation(
                        rationale="4000 was lost at payment.",
                        expected_impact_amount=31000.0,
                    )
                ]
            ),
            ledger=self.ledger,
            coverage=self.coverage,
        )
        self.assertEqual(outcome.recommendations, [])
        self.assertIn("expected impact", outcome.rejections[0].detail)

    def test_a_downgrade_is_recorded_as_well_as_applied(self) -> None:
        outcome = validate_verdict(
            AnalysisVerdict(
                recommendations=[
                    recommendation(
                        requested_action_type="PROMOTE_ITEM",
                        discount_percent=99.0,
                        minimum_order_amount=999.0,
                    )
                ]
            ),
            ledger=self.ledger,
            coverage=self.coverage,
        )
        self.assertEqual(len(outcome.recommendations), 1)
        self.assertFalse(outcome.recommendations[0].is_executable)
        self.assertEqual(outcome.rejections[0].gate, "safety")

    def test_confidence_is_carried_through(self) -> None:
        outcome = validate_verdict(
            AnalysisVerdict(findings=[finding(confidence="HIGH")]),
            ledger=self.ledger,
            coverage=self.coverage,
        )
        self.assertEqual(outcome.findings[0].confidence, AnalysisConfidence.HIGH)

    def test_evidence_is_kept_with_the_finding(self) -> None:
        outcome = validate_verdict(
            AnalysisVerdict(findings=[finding()]),
            ledger=self.ledger,
            coverage=self.coverage,
        )
        evidence = outcome.findings[0].evidence
        self.assertEqual(evidence["call_ids"], ["call_1"])
        self.assertEqual(evidence["calls"][0]["tool"], "get_payment_failures")

    def test_every_rejection_names_its_gate(self) -> None:
        # The rejection rate per gate is the go/no-go metric for 8C, so an
        # unlabelled rejection is a hole in the evidence.
        outcome = validate_verdict(
            AnalysisVerdict(
                findings=[
                    finding(title="No evidence", evidence=["call_77"]),
                    finding(title="Invented", body="Revenue fell by 7777."),
                ]
            ),
            ledger=self.ledger,
            coverage=self.coverage,
        )
        self.assertEqual(
            {rejection.gate for rejection in outcome.rejections}, {"evidence", "numbers"}
        )
        for rejection in outcome.rejections:
            self.assertTrue(rejection.detail)


# --- schema hardening ------------------------------------------------------


class OutputSchemaTests(unittest.TestCase):
    def test_a_finding_without_evidence_cannot_be_constructed(self) -> None:
        # Enforced at the type level, so no code path can produce one.
        with self.assertRaises(Exception):
            AIFinding(category="x", title="t", body="b", evidence=[])

    def test_unknown_fields_are_refused(self) -> None:
        with self.assertRaises(Exception):
            AIFinding(
                category="x",
                title="t",
                body="b",
                evidence=["call_1"],
                sql="SELECT * FROM orders",
            )

    def test_an_over_long_body_is_refused(self) -> None:
        with self.assertRaises(Exception):
            AIFinding(category="x", title="t", body="b" * 5000, evidence=["call_1"])

    def test_the_number_of_findings_is_bounded(self) -> None:
        with self.assertRaises(Exception):
            AnalysisVerdict(findings=[finding() for _ in range(20)])


if __name__ == "__main__":
    unittest.main()

"""Tests for Phase 8E additive mode.

The property under test is ownership. The rules engine states the facts and
ranks them; the model may say what they might mean and nothing else. Every test
here is a way the model might try to take back a decision that is not its own —
adding a finding, restating a number, ranking, or explaining the period with
data this platform has never held.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.models.enums import OwnerInsightSeverity, OwnerInsightType
from app.schemas.insights import (
    AnomalyReportResponse,
    DiagnosticsSnapshotResponse,
    InsightsDataQuality,
    InsightsPeriod,
    InsightsScopeResponse,
    MetricDeltaResponse,
)
from app.services.insights.analyst.additive import (
    brief_ledger,
    build_brief,
    build_commentary_prompt,
    validate_commentary,
)
from app.services.insights.analyst.output import AnalystCommentary
from app.services.insights.analyst.validation import (
    CoverageContext,
    check_prose_arithmetic,
    check_unsupported_domain,
)
from app.services.insights.rules import CandidateInsight
import uuid


def coverage() -> CoverageContext:
    return CoverageContext(
        orders=30, trading_days=8, days_in_window=60, sufficient_volume=True
    )


def snapshot() -> DiagnosticsSnapshotResponse:
    period = InsightsPeriod(
        start_date=date(2026, 6, 18),
        end_date=date(2026, 8, 16),
        day_count=60,
        label="18 Jun - 16 Aug 2026",
    )
    previous = InsightsPeriod(
        start_date=date(2026, 4, 19),
        end_date=date(2026, 6, 17),
        day_count=60,
        label="19 Apr - 17 Jun 2026",
    )
    return DiagnosticsSnapshotResponse(
        scope=InsightsScopeResponse(
            restaurant_id=uuid.uuid4(), restaurant_location_id=None, timezone="Asia/Kolkata"
        ),
        current_period=period,
        previous_period=previous,
        generated_at="2026-08-17T00:00:00+00:00",
        data_quality=InsightsDataQuality(
            sufficient_volume=True,
            weekday_aligned=True,
            includes_partial_day=False,
            counted_order_statuses=["DELIVERED"],
            notes=[],
            trading_days=8,
            days_in_window=60,
        ),
        headline=[
            MetricDeltaResponse(
                metric="gross_revenue",
                current=1578.92,
                previous=2459.65,
                absolute_change=-880.73,
                percent_change=-35.81,
                direction="down",
                sufficient_data=True,
            )
        ],
        breakdowns=[],
        anomalies=AnomalyReportResponse(
            evaluated=False, baseline_days=0, baseline_median_orders=0.0, note=None, points=[]
        ),
    )


def candidates() -> list[CandidateInsight]:
    return [
        CandidateInsight(
            insight_type=OwnerInsightType.LOCATION_DECLINE,
            severity=OwnerInsightSeverity.MEDIUM,
            score=Decimal("2197"),
            title="Bangkok Bowl Ellisbridge revenue is down",
            body="Ellisbridge brought in 230.55, down 2197.25 from 2427.80.",
            dedupe_key="LOCATION_DECLINE:ellisbridge",
            dimension="location",
            subject="Bangkok Bowl Ellisbridge",
            facts={"current": 230.55, "previous": 2427.80, "absolute_change": -2197.25},
        ),
        CandidateInsight(
            insight_type=OwnerInsightType.DAYPART_WEAKNESS,
            severity=OwnerInsightSeverity.LOW,
            score=Decimal("875"),
            title="Lunch trade has weakened",
            body="Lunch revenue fell from 1178.0 to 303.0.",
            dedupe_key="DAYPART_WEAKNESS:lunch",
            dimension="daypart",
            subject="Lunch",
            facts={"current": 303.0, "previous": 1178.0, "absolute_change": -875.0},
        ),
    ]


def brief_fixture():
    return build_brief(snapshot(), candidates(), coverage())


def commentary(**overrides) -> AnalystCommentary:
    payload = {
        "interpretations": [
            {
                "finding_ref": 1,
                "text": "The branch may have stopped trading; worth checking whether it is open.",
                "confidence": "MEDIUM",
            }
        ],
        "connections": [],
        "context": None,
    }
    payload.update(overrides)
    return AnalystCommentary(**payload)


class BriefTests(unittest.TestCase):
    def test_the_brief_carries_the_rules_ranking(self) -> None:
        brief = brief_fixture()
        self.assertEqual([row["ref"] for row in brief.findings], [1, 2])
        self.assertEqual(brief.findings[0]["severity"], "MEDIUM")
        self.assertEqual(brief.findings[0]["subject"], "Bangkok Bowl Ellisbridge")

    def test_the_prompt_forbids_re_ranking_and_invention(self) -> None:
        prompt = build_commentary_prompt(brief_fixture())
        for instruction in ("already ranked", "re-rank", "never invent a finding"):
            self.assertIn(instruction, prompt)

    def test_the_prompt_is_compact(self) -> None:
        # One generation is the whole latency budget in this mode, and prompt
        # length is part of it. The exploring mode's conclude prompt was ~5.4KB.
        self.assertLess(len(build_commentary_prompt(brief_fixture())), 4000)

    def test_the_ledger_holds_only_the_brief(self) -> None:
        brief = brief_fixture()
        ledger = brief_ledger(brief)
        allowed = ledger.allowed_numbers(["call_1"])
        self.assertIn(2197.25, allowed)
        self.assertIn(230.55, allowed)
        # A real figure from elsewhere in the business was never shown, so it is
        # not sayable.
        self.assertNotIn(31.85, allowed)


class CommentaryValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.brief = brief_fixture()
        self.ledger = brief_ledger(self.brief)

    def validate(self, payload: AnalystCommentary):
        return validate_commentary(payload, brief=self.brief, ledger=self.ledger)

    def test_a_hedged_interpretation_survives(self) -> None:
        result = self.validate(commentary())
        self.assertEqual(len(result.interpretations), 1)
        self.assertEqual(result.rejections, [])

    def test_a_reference_to_a_finding_that_does_not_exist_is_rejected(self) -> None:
        # The model cannot add a finding by commenting on one.
        result = self.validate(
            commentary(interpretations=[{"finding_ref": 9, "text": "This may matter."}])
        )
        self.assertEqual(result.interpretations, [])
        self.assertEqual(result.rejections[0].gate, "reference")

    def test_an_invented_number_is_rejected(self) -> None:
        result = self.validate(
            commentary(
                interpretations=[
                    {"finding_ref": 1, "text": "This may have cost around 5000 in lost sales."}
                ]
            )
        )
        self.assertEqual(result.interpretations, [])
        self.assertEqual(result.rejections[0].gate, "numbers")

    def test_false_arithmetic_in_prose_is_rejected(self) -> None:
        """The 8D gap, and the exact shape that made it dangerous.

        Every figure here is real and present in the brief — 2427.8 and 230.55
        from the branch finding, 875.0 from the lunch one. Only the relationship
        between them is invented, which a membership check cannot see.
        """

        result = self.validate(
            commentary(
                interpretations=[
                    {
                        "finding_ref": 1,
                        "text": "Revenue may be affected: it fell from 2427.8 to 230.55, a drop of 875.0.",
                    }
                ]
            )
        )
        self.assertEqual(result.interpretations, [])
        self.assertEqual(result.rejections[0].gate, "arithmetic")

    def test_correct_arithmetic_in_prose_survives(self) -> None:
        result = self.validate(
            commentary(
                interpretations=[
                    {
                        "finding_ref": 1,
                        "text": "The fall from 2427.8 to 230.55 may be worth checking.",
                    }
                ]
            )
        )
        self.assertEqual(len(result.interpretations), 1)

    def test_speculation_about_unheld_data_is_rejected(self) -> None:
        # Every 8D run explained the period with marketing. The platform has no
        # marketing data at all, so the claim cannot be checked against anything.
        for text in (
            "This might suggest a successful marketing campaign.",
            "Competitors may have taken share.",
            "This could be due to seasonal weather.",
            "Staff shortages may explain it.",
            "This may indicate falling customer demand.",
        ):
            with self.subTest(text=text):
                result = self.validate(
                    commentary(interpretations=[{"finding_ref": 1, "text": text}])
                )
                self.assertEqual(result.interpretations, [])
                self.assertEqual(result.rejections[0].gate, "domain")

    def test_an_explanation_from_held_data_survives(self) -> None:
        # The contrast that makes the domain gate worth having: same shape of
        # sentence, but about something the database can confirm or refute.
        result = self.validate(
            commentary(
                interpretations=[
                    {
                        "finding_ref": 2,
                        "text": "Lunch may be weak at the branch that stopped trading; worth checking its hours.",
                    }
                ]
            )
        )
        self.assertEqual(len(result.interpretations), 1)

    def test_an_unhedged_cause_is_rejected(self) -> None:
        result = self.validate(
            commentary(
                interpretations=[
                    {"finding_ref": 1, "text": "Revenue fell because the branch closed."}
                ]
            )
        )
        self.assertEqual(result.interpretations, [])
        self.assertEqual(result.rejections[0].gate, "causality")

    def test_a_connection_between_real_findings_survives(self) -> None:
        # The thing rules cannot do: each rule sees one dimension, so none of
        # them can notice these two findings are one event.
        result = self.validate(
            commentary(
                interpretations=[],
                connections=[
                    {
                        "refs": [1, 2],
                        "text": "The lunch fall may be the same trade as the branch fall, counted twice.",
                        "confidence": "MEDIUM",
                    }
                ],
            )
        )
        self.assertEqual(len(result.connections), 1)

    def test_a_connection_to_a_missing_finding_is_rejected(self) -> None:
        result = self.validate(
            commentary(
                interpretations=[],
                connections=[{"refs": [1, 7], "text": "These may be related."}],
            )
        )
        self.assertEqual(result.connections, [])
        self.assertEqual(result.rejections[0].gate, "reference")

    def test_one_bad_comment_does_not_discard_a_good_one(self) -> None:
        result = self.validate(
            commentary(
                interpretations=[
                    {"finding_ref": 1, "text": "The branch may be closed; worth checking."},
                    {"finding_ref": 1, "text": "A marketing push may have failed."},
                ]
            )
        )
        self.assertEqual(len(result.interpretations), 1)
        self.assertEqual(len(result.rejections), 1)

    def test_the_model_cannot_change_severity_or_order(self) -> None:
        # There is no field for either. Asserted so the shape cannot be widened
        # without someone deciding to.
        fields = set(AnalystCommentary.model_fields)
        self.assertEqual(fields, {"interpretations", "connections", "context"})
        from app.services.insights.analyst.output import AIInterpretation

        self.assertEqual(
            set(AIInterpretation.model_fields), {"finding_ref", "text", "confidence"}
        )


class ProseArithmeticTests(unittest.TestCase):
    """The 8D gap, closed: figures in a sentence are recomputed, not just matched."""

    def test_a_correct_sentence_passes(self) -> None:
        self.assertIsNone(
            check_prose_arithmetic("Revenue fell from 2459.65 to 1578.92, down by 880.73.")
        )

    def test_a_false_change_is_caught(self) -> None:
        error = check_prose_arithmetic(
            "Revenue fell from 2459.65 to 1578.92, down by 1500.00."
        )
        self.assertIsNotNone(error)

    def test_a_false_percentage_is_caught(self) -> None:
        error = check_prose_arithmetic("Revenue fell from 2459.65 to 1578.92, a 70% drop.")
        self.assertIsNotNone(error)

    def test_a_correct_percentage_passes(self) -> None:
        self.assertIsNone(
            check_prose_arithmetic("Revenue fell from 2459.65 to 1578.92, a 35.8% drop.")
        )

    def test_a_sentence_with_no_pair_is_left_alone(self) -> None:
        # Conservative by design: no parseable relationship, no claim to check.
        self.assertIsNone(check_prose_arithmetic("Revenue was down sharply this period."))


class UnsupportedDomainTests(unittest.TestCase):
    def test_held_data_passes(self) -> None:
        for text in (
            "The branch is marked closed.",
            "Lunch orders fell to zero.",
            "Two orders were cancelled at the payment step.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(check_unsupported_domain(text))

    def test_unheld_domains_are_named_in_the_refusal(self) -> None:
        error = check_unsupported_domain("a competitor may have opened nearby")
        self.assertIn("competitors", error)


if __name__ == "__main__":
    unittest.main()

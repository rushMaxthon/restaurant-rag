"""Tests for fact packs, the numeric guardrail, and narration fallback.

The guardrail is the load-bearing part: an AI advisor that states a revenue
figure the data does not support is worse than no advisor, so every failure mode
here must end at the deterministic template rather than reach an owner.
"""

from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import httpx

from app.main import app  # noqa: F401  (imported first to settle import order)
from app.config import get_settings
from app.models.enums import (
    InsightNarrationSource,
    OwnerInsightSeverity,
    OwnerInsightType,
)
from app.services.insights import narrator as narrator_module
from app.services.insights.facts import (
    FactPack,
    allowed_numbers,
    build_fact_pack,
    extract_numbers,
    unsupported_numbers,
)
from app.services.insights.narrator import (
    MAX_NARRATIVE_CHARS,
    Narration,
    build_prompt,
    narrate,
)
from app.services.insights.rules import CandidateInsight, evaluate_rules
from tests.test_insights_rules import breakdown, contribution, delta, snapshot

settings = get_settings()


def sample_candidate() -> CandidateInsight:
    return CandidateInsight(
        insight_type=OwnerInsightType.ITEM_DECLINE,
        severity=OwnerInsightSeverity.MEDIUM,
        score=Decimal("1000"),
        title="Margherita Pizza sales are falling",
        body="Margherita Pizza brought in ₹2,500, down ₹1,000 from ₹3,500.",
        dedupe_key="ITEM_DECLINE:margherita-pizza",
        dimension="item",
        subject="Margherita Pizza",
        facts={"current": 2500.0, "previous": 3500.0, "absolute_change": -1000.0},
    )


def sample_pack() -> FactPack:
    return FactPack(
        period_label="09 Mar - 15 Mar 2026",
        previous_period_label="02 Mar - 08 Mar 2026",
        timezone="Asia/Kolkata",
        headline={
            "gross_revenue": {
                "current": 4600.0,
                "previous": 5600.0,
                "change": -1000.0,
                "percent_change": -17.9,
                "direction": "down",
            }
        },
        insights=[
            {
                "type": "ITEM_DECLINE",
                "severity": "MEDIUM",
                "subject": "Margherita Pizza",
                "statement": "Margherita Pizza fell.",
                "numbers": {"current": 2500.0, "previous": 3500.0, "absolute_change": -1000.0},
            }
        ],
        notes=[],
    )


class NumberExtractionTests(unittest.TestCase):
    def test_reads_figures_out_of_prose(self) -> None:
        values = extract_numbers("Revenue fell to ₹4,600 from ₹5,600, down 17.9%.")
        self.assertEqual(values, [4600.0, 5600.0, 17.9])

    def test_ignores_text_without_digits(self) -> None:
        self.assertEqual(extract_numbers("Sales were down sharply."), [])


class AllowedNumberTests(unittest.TestCase):
    def test_absolute_and_rounded_forms_are_permitted(self) -> None:
        pack = sample_pack()
        allowed = allowed_numbers(pack)
        # A change of -1000 may be written as "down 1,000".
        self.assertIn(1000.0, allowed)
        self.assertIn(4600.0, allowed)
        # 17.9 rounds to 18 in prose.
        self.assertIn(18.0, allowed)

    def test_period_dates_are_permitted(self) -> None:
        allowed = allowed_numbers(sample_pack(), period_dates=(date(2026, 3, 9),))
        self.assertIn(9.0, allowed)
        self.assertIn(2026.0, allowed)


class GuardrailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.allowed = allowed_numbers(sample_pack())

    def test_supported_text_passes(self) -> None:
        text = "Revenue fell to ₹4,600 from ₹5,600. Margherita Pizza dropped ₹1,000."
        self.assertEqual(unsupported_numbers(text, self.allowed), [])

    def test_invented_figure_is_caught(self) -> None:
        # 7,200 appears nowhere in the data.
        text = "Revenue fell to ₹4,600 from ₹7,200."
        self.assertEqual(unsupported_numbers(text, self.allowed), [7200.0])

    def test_plausible_near_miss_is_still_caught(self) -> None:
        # 4,800 is close to the real 4,600 and would read as credible, which is
        # exactly why it must not survive.
        text = "Revenue was ₹4,800 this week."
        self.assertEqual(unsupported_numbers(text, self.allowed), [4800.0])

    def test_rounding_is_tolerated(self) -> None:
        text = "Revenue is down 18% this week."
        self.assertEqual(unsupported_numbers(text, self.allowed), [])

    def test_words_without_numbers_always_pass(self) -> None:
        text = "Revenue fell noticeably, driven by one dish."
        self.assertEqual(unsupported_numbers(text, self.allowed), [])


class PromptTests(unittest.TestCase):
    def test_prompt_carries_the_facts_and_forbids_invention(self) -> None:
        prompt = build_prompt(sample_pack())
        self.assertIn("4600", prompt.replace(",", ""))
        self.assertIn("never estimate, extrapolate, or invent", prompt)


class TemplateNarrationTests(unittest.TestCase):
    def test_template_used_when_narration_is_disabled(self) -> None:
        result = narrate(sample_pack(), [sample_candidate()], enabled=False)
        self.assertEqual(result.source, InsightNarrationSource.TEMPLATE)
        self.assertIn("4,600", result.narrative)
        self.assertIsNone(result.fallback_reason)

    def test_template_numbers_pass_their_own_guardrail(self) -> None:
        # The fallback must never be the thing that states an unsupported figure.
        # Period dates count as supported because the template quotes the window
        # label, which is exactly what `narrate` passes through in production.
        pack = sample_pack()
        period_dates = (date(2026, 3, 9), date(2026, 3, 15), date(2026, 3, 2), date(2026, 3, 8))
        result = narrate(pack, [sample_candidate()], enabled=False, period_dates=period_dates)
        allowed = allowed_numbers(pack, period_dates=period_dates)
        self.assertEqual(
            unsupported_numbers(f"{result.headline} {result.narrative}", allowed), []
        )

    def test_template_handles_a_period_with_no_findings(self) -> None:
        result = narrate(sample_pack(), [], enabled=False)
        self.assertIn("Nothing else moved enough", result.narrative)


class LLMNarrationTests(unittest.TestCase):
    def _reply(self, payload: dict) -> str:
        return json.dumps(payload)

    def test_valid_generation_is_accepted(self) -> None:
        reply = self._reply(
            {
                "headline": "Revenue is down 18%",
                "narrative": (
                    "Revenue was ₹4,600, down ₹1,000 from ₹5,600. "
                    "Margherita Pizza carried most of the fall."
                ),
            }
        )
        with patch.object(narrator_module, "_call_model", return_value=reply):
            result = narrate(sample_pack(), [sample_candidate()], enabled=True)
        self.assertEqual(result.source, InsightNarrationSource.LLM)
        self.assertEqual(result.headline, "Revenue is down 18%")

    def test_invented_number_falls_back_to_template(self) -> None:
        reply = self._reply(
            {
                "headline": "Revenue is down",
                "narrative": "Revenue was ₹4,600, and delivery costs rose to ₹9,900.",
            }
        )
        with patch.object(narrator_module, "_call_model", return_value=reply):
            result = narrate(sample_pack(), [sample_candidate()], enabled=True)
        self.assertEqual(result.source, InsightNarrationSource.TEMPLATE)
        self.assertIn("9900.0", result.fallback_reason or "")

    def test_timeout_falls_back_to_template(self) -> None:
        with patch.object(
            narrator_module,
            "_call_model",
            side_effect=httpx.ReadTimeout("timed out"),
        ):
            result = narrate(sample_pack(), [sample_candidate()], enabled=True)
        self.assertEqual(result.source, InsightNarrationSource.TEMPLATE)
        self.assertIn("timed out", result.fallback_reason or "")

    def test_connection_failure_falls_back_to_template(self) -> None:
        with patch.object(
            narrator_module,
            "_call_model",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            result = narrate(sample_pack(), [sample_candidate()], enabled=True)
        self.assertEqual(result.source, InsightNarrationSource.TEMPLATE)

    def test_malformed_json_falls_back_to_template(self) -> None:
        with patch.object(narrator_module, "_call_model", return_value="not json at all"):
            result = narrate(sample_pack(), [sample_candidate()], enabled=True)
        self.assertEqual(result.source, InsightNarrationSource.TEMPLATE)

    def test_missing_field_falls_back_to_template(self) -> None:
        with patch.object(
            narrator_module, "_call_model", return_value=self._reply({"headline": "x"})
        ):
            result = narrate(sample_pack(), [sample_candidate()], enabled=True)
        self.assertEqual(result.source, InsightNarrationSource.TEMPLATE)

    def test_overlong_narrative_falls_back_to_template(self) -> None:
        reply = self._reply(
            {"headline": "Revenue is down", "narrative": "word " * (MAX_NARRATIVE_CHARS)}
        )
        with patch.object(narrator_module, "_call_model", return_value=reply):
            result = narrate(sample_pack(), [sample_candidate()], enabled=True)
        self.assertEqual(result.source, InsightNarrationSource.TEMPLATE)
        self.assertIn("length", result.fallback_reason or "")

    def test_json_wrapped_in_prose_is_recovered(self) -> None:
        reply = (
            'Here is your briefing: {"headline": "Revenue is down", '
            '"narrative": "Revenue was 4600."} Hope that helps.'
        )
        with patch.object(narrator_module, "_call_model", return_value=reply):
            result = narrate(sample_pack(), [sample_candidate()], enabled=True)
        self.assertEqual(result.source, InsightNarrationSource.LLM)

    def test_model_call_disables_thinking_tokens(self) -> None:
        captured: dict = {}

        class FakeResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"response": '{"headline": "a", "narrative": "b"}'}

        def fake_post(url: str, json: dict) -> FakeResponse:  # noqa: A002
            captured.update(json)
            return FakeResponse()

        with patch.object(narrator_module.GENERATE_CLIENT, "post", fake_post):
            narrate(sample_pack(), [sample_candidate()], enabled=True)

        self.assertIs(captured["think"], False)
        self.assertEqual(captured["format"], "json")
        self.assertFalse(captured["stream"])


class FactPackBuildTests(unittest.TestCase):
    def test_pack_is_built_from_a_snapshot_and_its_findings(self) -> None:
        source = snapshot(
            headline=[
                delta("gross_revenue", 8800.0, 10000.0),
                delta("orders", 90.0, 100.0),
            ],
            breakdowns=[
                breakdown(
                    "item",
                    -1200.0,
                    [contribution("pizza", "Margherita Pizza", 2500.0, 3500.0, share=90.0)],
                    basis="item_revenue",
                )
            ],
        )
        candidates = evaluate_rules(source)
        pack = build_fact_pack(source, candidates)

        self.assertEqual(pack.period_label, "09 Mar - 15 Mar 2026")
        self.assertEqual(pack.headline["gross_revenue"]["current"], 8800.0)
        self.assertTrue(pack.insights)

        # Every figure the rules stated must be usable by narration.
        allowed = allowed_numbers(pack)
        for candidate in candidates:
            self.assertEqual(unsupported_numbers(candidate.body, allowed), [])


if __name__ == "__main__":
    unittest.main()

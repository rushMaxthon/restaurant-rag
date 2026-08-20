"""Tests for the recommendation playbooks.

No database: playbooks map findings onto proposals, so every mapping, impact
estimate, and honesty guard is checked in isolation.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401  (imported first to settle import order)
from app.config import get_settings
from app.models.enums import (
    OwnerActionType,
    OwnerInsightSeverity,
    OwnerInsightType,
    PersonalizedOfferAudience,
    PersonalizedOfferType,
)
from app.services.insights.playbooks import ComboOpportunity, build_proposals
from app.services.insights.rules import CandidateInsight
from tests.test_insights_rules import SettingsOverride

settings = get_settings()

MENU_ITEM_ID = uuid.uuid4()


def insight(
    insight_type: OwnerInsightType,
    *,
    subject: str | None = None,
    facts: dict | None = None,
    severity: OwnerInsightSeverity = OwnerInsightSeverity.MEDIUM,
) -> CandidateInsight:
    return CandidateInsight(
        insight_type=insight_type,
        severity=severity,
        score=Decimal("1000"),
        title=f"{insight_type.value} title",
        body=f"{insight_type.value} body",
        dedupe_key=f"{insight_type.value}:{subject or 'total'}",
        subject=subject,
        facts=facts or {"absolute_change": -1000.0, "current": 2000.0, "previous": 3000.0},
    )


def resolver_hit(_name: str) -> uuid.UUID:
    return MENU_ITEM_ID


def resolver_miss(_name: str) -> None:
    return None


def by_type(proposals) -> dict[OwnerActionType, object]:
    return {proposal.action_type: proposal for proposal in proposals}


class ItemPlaybookTests(unittest.TestCase):
    def test_declining_item_becomes_an_offer_on_that_item(self) -> None:
        proposals = build_proposals(
            [insight(OwnerInsightType.ITEM_DECLINE, subject="Margherita Pizza")],
            resolve_menu_item=resolver_hit,
        )
        proposal = by_type(proposals)[OwnerActionType.PROMOTE_ITEM]

        self.assertTrue(proposal.is_executable)
        self.assertEqual(proposal.action_payload["applicable_item_id"], str(MENU_ITEM_ID))
        self.assertEqual(
            proposal.action_payload["offer_type"], PersonalizedOfferType.FAVORITE_ITEM.value
        )
        self.assertIn("Margherita Pizza", proposal.title)

    def test_unresolvable_dish_produces_nothing(self) -> None:
        # Attaching an offer to a guessed menu item would discount the wrong dish.
        proposals = build_proposals(
            [insight(OwnerInsightType.ITEM_DECLINE, subject="Ghost Dish")],
            resolve_menu_item=resolver_miss,
        )
        self.assertEqual(proposals, [])

    def test_no_resolver_produces_nothing(self) -> None:
        proposals = build_proposals(
            [insight(OwnerInsightType.ITEM_DECLINE, subject="Margherita Pizza")]
        )
        self.assertEqual(proposals, [])


class ImpactEstimateTests(unittest.TestCase):
    def test_impact_is_a_share_of_what_was_lost(self) -> None:
        with SettingsOverride(action_recovery_rate=0.5):
            proposals = build_proposals(
                [
                    insight(
                        OwnerInsightType.CATEGORY_DECLINE,
                        subject="Pizza",
                        facts={"absolute_change": -2000.0},
                    )
                ]
            )
        proposal = by_type(proposals)[OwnerActionType.PROMOTE_CATEGORY]
        self.assertEqual(proposal.expected_impact_amount, Decimal("1000.00"))

    def test_impact_is_labelled_an_estimate(self) -> None:
        # An owner must never read this as a promise.
        proposals = build_proposals(
            [insight(OwnerInsightType.CATEGORY_DECLINE, subject="Pizza")]
        )
        proposal = by_type(proposals)[OwnerActionType.PROMOTE_CATEGORY]
        self.assertIn("Estimate only", proposal.expected_impact_basis)

    def test_recovery_rate_is_configurable(self) -> None:
        with SettingsOverride(action_recovery_rate=0.25):
            proposals = build_proposals(
                [
                    insight(
                        OwnerInsightType.CATEGORY_DECLINE,
                        subject="Pizza",
                        facts={"absolute_change": -2000.0},
                    )
                ]
            )
        proposal = by_type(proposals)[OwnerActionType.PROMOTE_CATEGORY]
        self.assertEqual(proposal.expected_impact_amount, Decimal("500.00"))


class CohortPlaybookTests(unittest.TestCase):
    def test_returning_decline_targets_inactive_customers(self) -> None:
        proposals = build_proposals(
            [insight(OwnerInsightType.RETURNING_CUSTOMER_DECLINE, subject="Returning customers")]
        )
        proposal = by_type(proposals)[OwnerActionType.WINBACK_INACTIVE]
        self.assertEqual(
            proposal.action_payload["audience_type"],
            PersonalizedOfferAudience.INACTIVE_USERS.value,
        )

    def test_new_customer_decline_creates_a_welcome_offer(self) -> None:
        proposals = build_proposals(
            [insight(OwnerInsightType.NEW_CUSTOMER_DECLINE, subject="New customers")]
        )
        proposal = by_type(proposals)[OwnerActionType.WELCOME_NEW_CUSTOMERS]
        self.assertEqual(
            proposal.action_payload["offer_type"],
            PersonalizedOfferType.WELCOME_FIRST_ORDER.value,
        )


class AdvisoryPlaybookTests(unittest.TestCase):
    def test_cancellation_spike_creates_nothing_executable(self) -> None:
        # The data does not record why orders were cancelled, so inventing a
        # discount for it would be guesswork.
        proposals = build_proposals(
            [
                insight(
                    OwnerInsightType.CANCELLATION_SPIKE,
                    facts={
                        "cancelled_orders": 10,
                        "cancellation_rate": 12.0,
                        "cancelled_value": 5000.0,
                    },
                )
            ]
        )
        proposal = by_type(proposals)[OwnerActionType.OPERATIONAL_REVIEW]
        self.assertFalse(proposal.is_executable)
        self.assertEqual(proposal.action_payload, {})
        self.assertIsNone(proposal.expected_impact_amount)

    def test_item_surge_advises_protecting_stock(self) -> None:
        proposals = build_proposals(
            [
                insight(
                    OwnerInsightType.ITEM_SURGE,
                    subject="Margherita Pizza",
                    facts={"absolute_change": 3000.0},
                )
            ]
        )
        proposal = by_type(proposals)[OwnerActionType.PROTECT_SUPPLY]
        self.assertFalse(proposal.is_executable)

    def test_revenue_drop_alone_produces_no_action(self) -> None:
        # A headline with no dimension attached offers nothing to act on; the
        # per-dimension findings carry the recommendations.
        proposals = build_proposals([insight(OwnerInsightType.REVENUE_DROP)])
        self.assertEqual(proposals, [])


class DaypartPlaybookTests(unittest.TestCase):
    def test_daypart_offer_declares_it_is_not_time_restricted(self) -> None:
        # The offer engine has no hour-of-day rule. An owner who believed this
        # was dinner-only would be discounting lunch as well.
        proposals = build_proposals(
            [insight(OwnerInsightType.DAYPART_WEAKNESS, subject="Dinner")]
        )
        proposal = by_type(proposals)[OwnerActionType.DAYPART_OFFER]

        self.assertTrue(proposal.is_executable)
        self.assertIn("all-day", proposal.title.lower())
        self.assertIn("all hours", proposal.rationale.lower())
        self.assertFalse(proposal.action_payload["business_rules"]["time_restriction_enforced"])

    def test_daypart_hours_are_recorded_for_context(self) -> None:
        proposals = build_proposals(
            [insight(OwnerInsightType.DAYPART_WEAKNESS, subject="Dinner")]
        )
        proposal = by_type(proposals)[OwnerActionType.DAYPART_OFFER]
        self.assertEqual(proposal.action_payload["business_rules"]["daypart_hours"], [18, 23])


class CrossSellTests(unittest.TestCase):
    def _combo(self, **overrides) -> ComboOpportunity:
        defaults = dict(
            combo_id=uuid.uuid4(),
            combo_name="Pizza + Coke",
            order_count=25,
            unique_user_count=12,
            confidence_score=Decimal("9.00"),
            original_total_price=Decimal("600.00"),
            suggested_combo_price=Decimal("540.00"),
        )
        defaults.update(overrides)
        return ComboOpportunity(**defaults)

    def test_confident_combo_becomes_a_bundle_offer(self) -> None:
        proposals = build_proposals([], combos=[self._combo()])
        proposal = by_type(proposals)[OwnerActionType.CROSS_SELL_COMBO]

        self.assertTrue(proposal.is_executable)
        # 60 off 600 is a 10% bundle discount.
        self.assertEqual(proposal.action_payload["discount_value"], "10.00")
        self.assertEqual(proposal.source_facts["order_count"], 25)

    def test_low_confidence_combo_is_skipped(self) -> None:
        with SettingsOverride(action_combo_min_confidence=Decimal("5.00")):
            proposals = build_proposals(
                [], combos=[self._combo(confidence_score=Decimal("1.00"))]
            )
        self.assertEqual(proposals, [])

    def test_combo_without_a_saving_is_skipped(self) -> None:
        proposals = build_proposals(
            [], combos=[self._combo(suggested_combo_price=Decimal("600.00"))]
        )
        self.assertEqual(proposals, [])

    def test_combo_offers_no_invented_impact_figure(self) -> None:
        proposals = build_proposals([], combos=[self._combo()])
        proposal = by_type(proposals)[OwnerActionType.CROSS_SELL_COMBO]
        self.assertIsNone(proposal.expected_impact_amount)
        self.assertIn("No estimate", proposal.expected_impact_basis)


class RankingTests(unittest.TestCase):
    def test_executable_proposals_outrank_advisories(self) -> None:
        proposals = build_proposals(
            [
                insight(
                    OwnerInsightType.CANCELLATION_SPIKE,
                    facts={
                        "cancelled_orders": 20,
                        "cancellation_rate": 20.0,
                        "cancelled_value": 90000.0,
                    },
                ),
                insight(
                    OwnerInsightType.CATEGORY_DECLINE,
                    subject="Pizza",
                    facts={"absolute_change": -1000.0},
                ),
            ]
        )
        # The advisory involves far more money, but only one of these can be
        # acted on today.
        self.assertEqual(proposals[0].action_type, OwnerActionType.PROMOTE_CATEGORY)

    def test_limit_truncates_after_ranking(self) -> None:
        proposals = build_proposals(
            [
                insight(OwnerInsightType.CATEGORY_DECLINE, subject="Pizza"),
                insight(OwnerInsightType.RETURNING_CUSTOMER_DECLINE, subject="Returning"),
                insight(OwnerInsightType.NEW_CUSTOMER_DECLINE, subject="New"),
            ],
            limit=2,
        )
        self.assertEqual(len(proposals), 2)

    def test_dedupe_keys_are_unique_and_stable(self) -> None:
        findings = [
            insight(OwnerInsightType.CATEGORY_DECLINE, subject="Pizza"),
            insight(OwnerInsightType.RETURNING_CUSTOMER_DECLINE, subject="Returning"),
        ]
        first = build_proposals(findings)
        second = build_proposals(findings)

        keys = [row.dedupe_key for row in first]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(keys, [row.dedupe_key for row in second])

    def test_proposals_carry_their_source_insight(self) -> None:
        finding = insight(OwnerInsightType.CATEGORY_DECLINE, subject="Pizza")
        proposals = build_proposals([finding])
        self.assertEqual(proposals[0].insight_dedupe_key, finding.dedupe_key)


class PayloadSafetyTests(unittest.TestCase):
    def test_generated_payloads_stay_within_platform_discount_caps(self) -> None:
        from app.services.insights.actions import validate_payload

        findings = [
            insight(OwnerInsightType.CATEGORY_DECLINE, subject="Pizza"),
            insight(OwnerInsightType.RETURNING_CUSTOMER_DECLINE, subject="Returning"),
            insight(OwnerInsightType.NEW_CUSTOMER_DECLINE, subject="New"),
            insight(OwnerInsightType.DAYPART_WEAKNESS, subject="Dinner"),
        ]
        for proposal in build_proposals(findings):
            if not proposal.is_executable:
                continue
            with self.subTest(action=proposal.action_type.value):
                # Must parse as a real offer request and survive the caps.
                validate_payload(proposal.action_payload)


if __name__ == "__main__":
    unittest.main()

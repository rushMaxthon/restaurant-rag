"""Metrics and diagnostics layer for the AI Restaurant Manager.

Deterministic SQL and Python only. No LLM lives here — this package computes the
facts a later narration step will be allowed to describe.
"""

from app.services.insights.diagnostics import (
    AnomalyPoint,
    AnomalyReport,
    Contribution,
    ContributionBreakdown,
    MetricDelta,
    build_contributions,
    build_delta,
    detect_anomalies,
    fill_daily_series,
    has_sufficient_volume,
)
from app.services.insights.actions import (
    ActionValidationError,
    approve_proposal,
    reject_proposal,
)
from app.services.insights.chat import ChatTurn, answer_question, stream_answer
from app.services.insights.facts import FactPack, build_fact_pack, unsupported_numbers
from app.services.insights.generation import (
    GenerationResult,
    RunSummary,
    generate_all_briefings,
    generate_for_restaurant,
)
from app.services.insights.narrator import Narration, narrate
from app.services.insights.periods import (
    AnalysisPeriod,
    PeriodComparison,
    baseline_period,
    build_period,
    previous_period,
    resolve_period_comparison,
)
from app.services.insights.playbooks import ActionProposal, ComboOpportunity, build_proposals
from app.services.insights.router import RoutedQuestion, route_question
from app.services.insights.rules import CandidateInsight, evaluate_rules
from app.services.insights.skills import SkillParams, SkillResult, run_skill
from app.services.insights.scope import InsightsScope, resolve_insights_scope
from app.services.insights.service import (
    build_diagnostics_snapshot,
    get_diagnostics_snapshot,
    invalidate_insights_caches,
)

__all__ = [
    "ActionProposal",
    "ActionValidationError",
    "AnalysisPeriod",
    "AnomalyPoint",
    "AnomalyReport",
    "CandidateInsight",
    "ComboOpportunity",
    "ChatTurn",
    "RoutedQuestion",
    "SkillParams",
    "SkillResult",
    "Contribution",
    "ContributionBreakdown",
    "FactPack",
    "GenerationResult",
    "InsightsScope",
    "MetricDelta",
    "Narration",
    "PeriodComparison",
    "RunSummary",
    "baseline_period",
    "build_contributions",
    "answer_question",
    "approve_proposal",
    "build_delta",
    "build_diagnostics_snapshot",
    "build_fact_pack",
    "build_period",
    "build_proposals",
    "detect_anomalies",
    "evaluate_rules",
    "fill_daily_series",
    "generate_all_briefings",
    "generate_for_restaurant",
    "get_diagnostics_snapshot",
    "has_sufficient_volume",
    "invalidate_insights_caches",
    "narrate",
    "previous_period",
    "reject_proposal",
    "resolve_insights_scope",
    "resolve_period_comparison",
    "route_question",
    "run_skill",
    "stream_answer",
    "unsupported_numbers",
]

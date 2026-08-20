"""Tests for the analyst audit trail and the switches that keep it invisible.

The important property is negative: with 8B's shipped configuration, a run can
produce findings, be recorded in full, and still put nothing in front of an
owner. Both the write path and the read path are checked, because either one on
its own is a single point of failure for something that must not leak.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.config import get_settings
from app.models.base import Base
from app.models.enums import (
    AnalysisRunStatus,
    InsightOrigin,
    OwnerActionStatus,
    OwnerInsightSeverity,
    OwnerInsightStatus,
    OwnerInsightType,
    UserRole,
)
from app.models.owner_action import OwnerActionProposal
from app.models.owner_analysis_run import OwnerAnalysisRun
from app.models.owner_insight import OwnerInsight
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.services.insights.actions import list_proposals
from app.services.insights.analyst.ledger import FactLedger
from app.services.insights.analyst.output import AIFinding, AIRecommendation, AnalysisVerdict
from app.services.insights.analyst.persistence import (
    persist_outcome,
    record_run,
    run_summary,
    visible_origins,
)
from app.services.insights.analyst.schemas import ToolResult
from app.services.insights.analyst.validation import CoverageContext, validate_verdict
from app.services.insights.generation import list_insights
from app.services.insights.periods import resolve_period_comparison
from app.services.insights.scope import InsightsScope
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

settings = get_settings()

TEST_DB_NAME = os.environ.get("ANALYST_PERSIST_TEST_DB", "restaurant_rag_analyst_persist_test")


def _admin_url() -> str:
    return (
        f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_server}:{settings.postgres_port}/postgres"
    )


def _test_url() -> str:
    return (
        f"postgresql+psycopg://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_server}:{settings.postgres_port}/{TEST_DB_NAME}"
    )


def postgres_available() -> bool:
    engine = None
    try:
        engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with engine.connect():
            return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:  # noqa: BLE001
                pass


def _verdict() -> AnalysisVerdict:
    return AnalysisVerdict(
        summary="Payment failures are the largest recoverable loss.",
        findings=[
            AIFinding(
                category="payments",
                title="Payment failures cost 4000",
                body="Orders worth 4000 were lost at the payment step across 12 orders.",
                severity="LOW",
                confidence="MEDIUM",
                interpretation="This looks like a checkout problem rather than lost demand.",
                subject="payments",
                evidence=["call_1"],
            )
        ],
        recommendations=[
            AIRecommendation(
                title="Review the payment flow",
                rationale="Orders worth 4000 never completed payment.",
                requested_action_type="OPERATIONAL_REVIEW",
                priority=4000.0,
                confidence="MEDIUM",
                evidence=["call_1"],
            )
        ],
    )


def _ledger() -> FactLedger:
    ledger = FactLedger()
    ledger.record(
        ToolResult(
            tool="get_payment_failures",
            args={"window_days": 30},
            ok=True,
            data={"lost_value": 4000.0, "lost_orders": 12},
        )
    )
    return ledger


@unittest.skipUnless(postgres_available(), "Postgres is not reachable")
class AnalystPersistenceTests(unittest.TestCase):
    engine = None
    session_factory = None

    @classmethod
    def setUpClass(cls) -> None:
        admin_engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
            connection.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin_engine.dispose()

        cls.engine = create_engine(_test_url())
        with cls.engine.connect() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            connection.commit()
        Base.metadata.create_all(cls.engine)
        cls.session_factory = sessionmaker(bind=cls.engine, expire_on_commit=False)

        with cls.session_factory() as session:
            owner = User(
                id=uuid.uuid4(),
                app_client_id=None,
                full_name="Owner",
                email="analyst-owner@example.com",
                hashed_password="x",
                role=UserRole.OWNER,
            )
            session.add(owner)
            session.flush()
            restaurant = Restaurant(
                id=uuid.uuid4(),
                owner_id=owner.id,
                name="Ledger Diner",
                slug="ledger-diner",
                cuisine_type="Thai",
                address_line_1="1 Test Street",
                city="Bengaluru",
                state="Karnataka",
                postal_code="560001",
                is_approved=True,
                is_active=True,
            )
            session.add(restaurant)
            session.flush()
            session.add(
                RestaurantLocation(
                    id=uuid.uuid4(),
                    restaurant_id=restaurant.id,
                    branch_name="Ledger Diner Main",
                    address_line_1="1 Test Street",
                    city="Bengaluru",
                    state="Karnataka",
                    postal_code="560001",
                )
            )
            session.commit()
            cls.restaurant_id = restaurant.id

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.engine is not None:
            cls.engine.dispose()
        admin_engine = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
        admin_engine.dispose()

    def setUp(self) -> None:
        self._shadow = settings.ai_manager_analyst_shadow_mode
        self._visible = settings.enable_ai_manager_ai_findings

    def tearDown(self) -> None:
        settings.ai_manager_analyst_shadow_mode = self._shadow
        settings.enable_ai_manager_ai_findings = self._visible
        with self.session_factory() as session:
            session.query(OwnerActionProposal).delete()
            session.query(OwnerInsight).delete()
            session.query(OwnerAnalysisRun).delete()
            session.commit()

    def scope(self) -> InsightsScope:
        return InsightsScope(restaurant_id=self.restaurant_id)

    def _run(self, session: Session, *, status=AnalysisRunStatus.COMPLETED):
        ledger = _ledger()
        comparison = resolve_period_comparison(window_days=30)
        outcome = validate_verdict(
            _verdict(),
            ledger=ledger,
            coverage=CoverageContext(
                orders=120, trading_days=25, days_in_window=30, sufficient_volume=True
            ),
        )
        run = record_run(
            session,
            scope=self.scope(),
            comparison=comparison,
            ledger=ledger,
            outcome=outcome,
            coverage=CoverageContext(
                orders=120, trading_days=25, days_in_window=30, sufficient_volume=True
            ),
            status=status,
            started_at=datetime.now(UTC),
            elapsed_ms=1234,
            model_name="qwen3:8b",
        )
        return run, outcome, comparison

    # -- the audit trail --------------------------------------------------

    def test_a_run_is_recorded_with_its_transcript(self) -> None:
        with self.session_factory() as session:
            run, _outcome, _comparison = self._run(session)
            stored = session.get(OwnerAnalysisRun, run.id)

        self.assertEqual(stored.restaurant_id, self.restaurant_id)
        self.assertEqual(stored.tool_call_count, 1)
        self.assertEqual(stored.model_name, "qwen3:8b")
        self.assertEqual(stored.transcript["calls"][0]["tool"], "get_payment_failures")
        self.assertIn("coverage", stored.transcript)

    def test_rejections_are_recorded_with_the_run(self) -> None:
        # A run whose findings were thrown out is the most informative row in
        # this table, so the reasons have to survive.
        ledger = _ledger()
        verdict = AnalysisVerdict(
            findings=[
                AIFinding(
                    category="revenue",
                    title="Invented",
                    body="Revenue fell by 9999.",
                    evidence=["call_1"],
                )
            ]
        )
        outcome = validate_verdict(
            verdict,
            ledger=ledger,
            coverage=CoverageContext(
                orders=120, trading_days=25, days_in_window=30, sufficient_volume=True
            ),
        )
        with self.session_factory() as session:
            run = record_run(
                session,
                scope=self.scope(),
                comparison=resolve_period_comparison(window_days=30),
                ledger=ledger,
                outcome=outcome,
                coverage=CoverageContext(
                    orders=120, trading_days=25, days_in_window=30, sufficient_volume=True
                ),
                status=AnalysisRunStatus.REJECTED,
                started_at=datetime.now(UTC),
                elapsed_ms=10,
            )
            stored = session.get(OwnerAnalysisRun, run.id)

        self.assertEqual(stored.findings_accepted, 0)
        self.assertEqual(stored.findings_rejected, 1)
        self.assertEqual(stored.rejection_reasons[0]["gate"], "numbers")
        self.assertEqual(run_summary(stored)["rejection_rate"], 1.0)

    def test_a_failed_run_is_still_recorded(self) -> None:
        with self.session_factory() as session:
            run, _outcome, _comparison = self._run(session, status=AnalysisRunStatus.FAILED)
            stored = session.get(OwnerAnalysisRun, run.id)
        self.assertEqual(stored.status, AnalysisRunStatus.FAILED)

    # -- shadow mode ------------------------------------------------------

    def test_shadow_mode_writes_no_findings_at_all(self) -> None:
        settings.ai_manager_analyst_shadow_mode = True
        with self.session_factory() as session:
            run, outcome, comparison = self._run(session)
            self.assertEqual(outcome.accepted_count, 1)  # it did produce one
            insights, proposals = persist_outcome(
                session,
                scope=self.scope(),
                comparison=comparison,
                outcome=outcome,
                run=run,
            )
            self.assertEqual((insights, proposals), (0, 0))
            self.assertEqual(session.scalar(select(func.count(OwnerInsight.id))), 0)
            self.assertEqual(session.scalar(select(func.count(OwnerActionProposal.id))), 0)

    def test_leaving_shadow_mode_writes_ai_rows(self) -> None:
        settings.ai_manager_analyst_shadow_mode = False
        with self.session_factory() as session:
            run, outcome, comparison = self._run(session)
            insights, proposals = persist_outcome(
                session,
                scope=self.scope(),
                comparison=comparison,
                outcome=outcome,
                run=run,
                model_name="qwen3:8b",
            )
            self.assertEqual((insights, proposals), (1, 1))

            insight = session.scalars(select(OwnerInsight)).one()
            self.assertEqual(insight.origin, InsightOrigin.AI)
            self.assertEqual(insight.insight_type, OwnerInsightType.AI_DISCOVERED)
            self.assertEqual(insight.ai_category, "payments")
            self.assertEqual(insight.analysis_run_id, run.id)
            self.assertEqual(insight.evidence["call_ids"], ["call_1"])
            # The explanation is stored apart from the observation, so a guess is
            # never shown in the voice of a measurement.
            self.assertIn("checkout problem", insight.root_cause)

            proposal = session.scalars(select(OwnerActionProposal)).one()
            self.assertEqual(proposal.origin, InsightOrigin.AI)
            self.assertEqual(proposal.status, OwnerActionStatus.PROPOSED)
            self.assertFalse(proposal.is_executable)
            # No generated payload is ever persisted; the backend builds it.
            self.assertEqual(proposal.action_payload, {})

    # -- visibility -------------------------------------------------------

    def test_ai_rows_are_invisible_to_the_feed_while_disabled(self) -> None:
        settings.ai_manager_analyst_shadow_mode = False
        settings.enable_ai_manager_ai_findings = False
        with self.session_factory() as session:
            run, outcome, comparison = self._run(session)
            persist_outcome(
                session,
                scope=self.scope(),
                comparison=comparison,
                outcome=outcome,
                run=run,
            )
            self.assertEqual(session.scalar(select(func.count(OwnerInsight.id))), 1)

            # Written, and still not reachable through the read path.
            self.assertEqual(list_insights(session, scope=self.scope()), [])
            self.assertEqual(list_proposals(session, scope=self.scope()), [])
            self.assertEqual(visible_origins(), (InsightOrigin.RULES,))

    def test_rule_findings_are_unaffected_by_the_filter(self) -> None:
        settings.enable_ai_manager_ai_findings = False
        with self.session_factory() as session:
            session.add(
                OwnerInsight(
                    id=uuid.uuid4(),
                    restaurant_id=self.restaurant_id,
                    insight_type=OwnerInsightType.REVENUE_DROP,
                    severity=OwnerInsightSeverity.LOW,
                    status=OwnerInsightStatus.NEW,
                    dedupe_key="RULES:test",
                    score=Decimal("1"),
                    title="Revenue is down",
                    body="Measured by the rules engine.",
                    period_start=date(2026, 8, 1),
                    period_end=date(2026, 8, 7),
                    generated_at=datetime.now(UTC),
                )
            )
            session.commit()
            rows = list_insights(session, scope=self.scope())

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].origin, InsightOrigin.RULES)

    def test_enabling_visibility_reveals_ai_rows(self) -> None:
        settings.ai_manager_analyst_shadow_mode = False
        settings.enable_ai_manager_ai_findings = True
        with self.session_factory() as session:
            run, outcome, comparison = self._run(session)
            persist_outcome(
                session,
                scope=self.scope(),
                comparison=comparison,
                outcome=outcome,
                run=run,
            )
            rows = list_insights(session, scope=self.scope())

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].origin, InsightOrigin.AI)

    def test_defaults_ship_disabled(self) -> None:
        # The configuration 8B is meant to ship in, asserted rather than assumed.
        fresh = type(settings)()
        self.assertFalse(fresh.enable_ai_manager_analyst)
        self.assertTrue(fresh.ai_manager_analyst_shadow_mode)
        self.assertFalse(fresh.enable_ai_manager_ai_findings)


if __name__ == "__main__":
    unittest.main()

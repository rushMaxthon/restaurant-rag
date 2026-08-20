from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import (
    AnalysisConfidence,
    InsightNarrationSource,
    InsightOrigin,
    OwnerInsightSeverity,
    OwnerInsightStatus,
    OwnerInsightType,
)

if TYPE_CHECKING:
    from app.models.restaurant import Restaurant
    from app.models.restaurant_location import RestaurantLocation


class OwnerBriefing(TimestampMixin, Base):
    """One narrative summary of a restaurant's period, per generation run.

    `snapshot` stores the full diagnostics payload the narrative was built from,
    so a claim in the text can always be traced back to the numbers that
    produced it.
    """

    __tablename__ = "owner_briefings"
    __table_args__ = (
        Index(
            "ix_owner_briefings_scope_period",
            "restaurant_id",
            "period_end",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    restaurant_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurant_locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    previous_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    previous_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    headline: Mapped[str] = mapped_column(String(255), nullable=False)
    narrative: Mapped[str] = mapped_column(Text, nullable=False)
    narration_source: Mapped[InsightNarrationSource] = mapped_column(
        Enum(InsightNarrationSource, name="insight_narration_source"),
        nullable=False,
        default=InsightNarrationSource.TEMPLATE,
        server_default=InsightNarrationSource.TEMPLATE.value,
        index=True,
    )
    # Why the deterministic template was used instead of the model: a timeout, a
    # validation failure, or a number the model invented.
    fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    insight_count: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    restaurant: Mapped["Restaurant"] = relationship()
    restaurant_location: Mapped["RestaurantLocation | None"] = relationship()


class OwnerInsight(TimestampMixin, Base):
    """One ranked finding about a restaurant's period.

    `facts` is the complete set of numbers this insight is allowed to state.
    Narration is checked against it, so nothing reaches an owner that the data
    did not support.
    """

    __tablename__ = "owner_insights"
    __table_args__ = (
        Index("ix_owner_insights_scope_status", "restaurant_id", "status"),
        Index("ix_owner_insights_dedupe", "restaurant_id", "dedupe_key", "generated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    briefing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("owner_briefings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    restaurant_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurant_locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    insight_type: Mapped[OwnerInsightType] = mapped_column(
        Enum(OwnerInsightType, name="owner_insight_type"),
        nullable=False,
        index=True,
    )
    severity: Mapped[OwnerInsightSeverity] = mapped_column(
        Enum(OwnerInsightSeverity, name="owner_insight_severity"),
        nullable=False,
        default=OwnerInsightSeverity.INFO,
        server_default=OwnerInsightSeverity.INFO.value,
        index=True,
    )
    status: Mapped[OwnerInsightStatus] = mapped_column(
        Enum(OwnerInsightStatus, name="owner_insight_status"),
        nullable=False,
        default=OwnerInsightStatus.NEW,
        server_default=OwnerInsightStatus.NEW.value,
        index=True,
    )
    # Stable identity for "the same finding", used to suppress a repeat while a
    # slump continues rather than raising an identical card every night.
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    score: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        default=Decimal("0.0000"),
        server_default="0.0000",
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    dimension: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # The run's own timestamp rather than the row's `created_at`. Cooldown
    # decisions compare against the clock the run was given, so a backfill over
    # historical periods suppresses repeats the same way a live run does.
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    # Why this happened, where the operational history supports an
    # explanation. Null when nothing in the data explains it — which is the
    # honest answer far more often than not.
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Phase 8B: provenance -------------------------------------------
    #
    # `origin` separates a measured finding from a generated one. It defaults to
    # RULES so every existing row keeps the meaning it was written with.
    origin: Mapped[InsightOrigin] = mapped_column(
        Enum(InsightOrigin, name="insight_origin"),
        nullable=False,
        default=InsightOrigin.RULES,
        server_default=InsightOrigin.RULES.value,
        index=True,
    )
    confidence: Mapped[AnalysisConfidence | None] = mapped_column(
        Enum(AnalysisConfidence, name="analysis_confidence"), nullable=True
    )
    # The analyst's own name for what it found, when the fixed type enum has no
    # word for it. Null for rule findings.
    ai_category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # The tool calls each claim rests on, so any figure can be traced back.
    evidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    analysis_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("owner_analysis_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)

    facts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    briefing: Mapped["OwnerBriefing | None"] = relationship()
    restaurant: Mapped["Restaurant"] = relationship()
    restaurant_location: Mapped["RestaurantLocation | None"] = relationship()


__all__ = ["OwnerBriefing", "OwnerInsight"]

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import (
    AnalysisConfidence,
    InsightOrigin,
    OwnerActionStatus,
    OwnerActionType,
)

if TYPE_CHECKING:
    from app.models.owner_insight import OwnerInsight
    from app.models.personalized_offer import PersonalizedOffer
    from app.models.restaurant import Restaurant
    from app.models.restaurant_location import RestaurantLocation
    from app.models.user import User


class OwnerActionProposal(TimestampMixin, Base):
    """A recommended action awaiting an owner's decision.

    Approving one of these can create a live offer and therefore cost real
    money, so three things are deliberate:

    * `action_payload` is frozen at proposal time. Approval executes exactly
      what the owner read, never a freshly regenerated version.
    * `executed_offer_id` doubles as the idempotency guard — once set, the
      proposal cannot execute again.
    * `expected_impact` is an arithmetic estimate derived from `source_facts`,
      not a forecast, and is stored alongside the assumption that produced it.
    """

    __tablename__ = "owner_action_proposals"
    __table_args__ = (
        Index("ix_owner_action_proposals_scope_status", "restaurant_id", "status"),
        Index(
            "ix_owner_action_proposals_dedupe",
            "restaurant_id",
            "dedupe_key",
            "generated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "restaurants.id",
            ondelete="CASCADE",
            name="fk_owner_action_proposals_restaurant",
        ),
        nullable=False,
        index=True,
    )
    restaurant_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "restaurant_locations.id",
            ondelete="SET NULL",
            name="fk_owner_action_proposals_location",
        ),
        nullable=True,
        index=True,
    )
    insight_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "owner_insights.id",
            ondelete="SET NULL",
            name="fk_owner_action_proposals_insight",
        ),
        nullable=True,
        index=True,
    )
    briefing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "owner_briefings.id",
            ondelete="SET NULL",
            name="fk_owner_action_proposals_briefing",
        ),
        nullable=True,
        index=True,
    )
    action_type: Mapped[OwnerActionType] = mapped_column(
        Enum(OwnerActionType, name="owner_action_type"),
        nullable=False,
        index=True,
    )
    status: Mapped[OwnerActionStatus] = mapped_column(
        Enum(OwnerActionStatus, name="owner_action_status"),
        nullable=False,
        default=OwnerActionStatus.PROPOSED,
        server_default=OwnerActionStatus.PROPOSED.value,
        index=True,
    )
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    priority: Mapped[Decimal] = mapped_column(
        Numeric(12, 4),
        nullable=False,
        default=Decimal("0.0000"),
        server_default="0.0000",
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    # True when approving creates something. Advisory proposals are read-only
    # observations the data cannot safely automate.
    is_executable: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false", index=True
    )
    expected_impact_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    expected_impact_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    source_facts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "users.id",
            ondelete="SET NULL",
            name="fk_owner_action_proposals_decided_by",
        ),
        nullable=True,
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "personalized_offers.id",
            ondelete="SET NULL",
            name="fk_owner_action_proposals_offer",
        ),
        nullable=True,
        index=True,
    )
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

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


    restaurant: Mapped["Restaurant"] = relationship()
    restaurant_location: Mapped["RestaurantLocation | None"] = relationship()
    insight: Mapped["OwnerInsight | None"] = relationship()
    decided_by_user: Mapped["User | None"] = relationship()
    executed_offer: Mapped["PersonalizedOffer | None"] = relationship()


__all__ = ["OwnerActionProposal"]

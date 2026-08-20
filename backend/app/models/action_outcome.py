from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import ActionOutcomeVerdict

if TYPE_CHECKING:
    from app.models.owner_action import OwnerActionProposal
    from app.models.personalized_offer import PersonalizedOffer
    from app.models.restaurant import Restaurant


class ActionOutcome(TimestampMixin, Base):
    """What was observed after an approved recommendation ran.

    This closes the loop the manager previously left open: it could propose an
    action and create the offer, but never look back to see what happened.

    Read it as observation, not proof. There is no holdout group and no control,
    so these figures describe what occurred in the window after the offer went
    live — they cannot show that the offer *caused* it. Seasonality, a festival,
    or an unrelated menu change would all land in the same numbers. The wording
    surfaced to owners is chosen to keep that distinction.
    """

    __tablename__ = "action_outcomes"
    __table_args__ = (
        Index("ix_action_outcomes_scope_measured", "restaurant_id", "measured_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "owner_action_proposals.id",
            ondelete="CASCADE",
            name="fk_action_outcomes_proposal",
        ),
        nullable=False,
        # One outcome per proposal: re-measuring updates the row rather than
        # appending, so the feed cannot fill with repeated verdicts.
        unique=True,
        index=True,
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE", name="fk_action_outcomes_restaurant"),
        nullable=False,
        index=True,
    )
    offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "personalized_offers.id", ondelete="SET NULL", name="fk_action_outcomes_offer"
        ),
        nullable=True,
        index=True,
    )
    verdict: Mapped[ActionOutcomeVerdict] = mapped_column(
        Enum(ActionOutcomeVerdict, name="action_outcome_verdict"),
        nullable=False,
        index=True,
    )
    # The window measured: from the day the offer went live to the day measured.
    window_start: Mapped[date] = mapped_column(Date, nullable=False)
    window_end: Mapped[date] = mapped_column(Date, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    attributed_orders: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    attributed_customers: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    attributed_revenue: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    discount_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    net_revenue: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"), server_default="0.00"
    )
    # What the proposal estimated at the time, kept alongside so the two can be
    # compared without re-deriving an assumption that may since have changed.
    estimated_impact: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # Plain-English summary, written deterministically. No model involved.
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    measured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    proposal: Mapped["OwnerActionProposal"] = relationship()
    restaurant: Mapped["Restaurant"] = relationship()
    offer: Mapped["PersonalizedOffer | None"] = relationship()


__all__ = ["ActionOutcome"]

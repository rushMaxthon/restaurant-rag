"""The audit trail for one analyst run.

Every run is recorded whether or not anything survived validation, and the
rejections are recorded with it. That is the point: a run that produced four
findings and had three thrown out for inventing numbers is the single most
useful signal for deciding whether this is fit to show anyone, and it only
exists if failures are written down as carefully as successes.

Nothing here is user-facing. It is an operator's record.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import AnalysisRunStatus


class OwnerAnalysisRun(TimestampMixin, Base):
    """One end-to-end analyst pass over one restaurant's data."""

    __tablename__ = "owner_analysis_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    restaurant_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurant_locations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    status: Mapped[AnalysisRunStatus] = mapped_column(
        Enum(AnalysisRunStatus, name="analysis_run_status"),
        nullable=False,
        index=True,
    )
    # True while output is written but deliberately not shown to anyone.
    shadow_mode: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    model_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(40), nullable=True)

    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    findings_proposed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    findings_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    findings_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    recommendations_proposed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    recommendations_accepted: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The tool calls made and what they returned, so a finding can be replayed.
    transcript: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # One entry per discarded finding, with the gate that discarded it. The
    # rejection rate computed from these is the go/no-go metric for 8C.
    rejection_reasons: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    restaurant: Mapped["Restaurant"] = relationship()  # noqa: F821
    restaurant_location: Mapped["RestaurantLocation | None"] = relationship()  # noqa: F821


__all__ = ["OwnerAnalysisRun"]

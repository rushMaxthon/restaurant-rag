"""Analyst run audit table, and the enum labels Phase 8B will need.

Split deliberately from 0047, which adds the columns that *use* these labels.
Postgres refuses to use an enum label in the transaction that added it, and
`alembic upgrade head` runs the whole chain in one transaction on a fresh
database. `analysis_run_status` is a brand new type, so creating and using it
here is safe; `AI_DISCOVERED` is added to an existing type and is deliberately
not referenced by any migration.

Revision ID: 0046_analysis_runs
Revises: 0045_location_insight_type
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0046_analysis_runs"
down_revision = "0045_location_insight_type"
branch_labels = None
depends_on = None


analysis_run_status_enum = postgresql.ENUM(
    "COMPLETED",
    "FAILED",
    "REJECTED",
    "SKIPPED",
    name="analysis_run_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    analysis_run_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "owner_analysis_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "restaurant_location_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurant_locations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("status", analysis_run_status_enum, nullable=False),
        sa.Column(
            "shadow_mode", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=True),
        sa.Column("prompt_version", sa.String(length=40), nullable=True),
        sa.Column("tool_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("findings_proposed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("findings_accepted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("findings_rejected", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "recommendations_proposed", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "recommendations_accepted", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "transcript",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "rejection_reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_owner_analysis_runs_restaurant_id", "owner_analysis_runs", ["restaurant_id"]
    )
    op.create_index(
        "ix_owner_analysis_runs_restaurant_location_id",
        "owner_analysis_runs",
        ["restaurant_location_id"],
    )
    op.create_index("ix_owner_analysis_runs_status", "owner_analysis_runs", ["status"])
    op.create_index(
        "ix_owner_analysis_runs_period_end", "owner_analysis_runs", ["period_end"]
    )

    # Added here, used only at runtime. See the module docstring.
    op.execute(
        "ALTER TYPE owner_insight_type ADD VALUE IF NOT EXISTS 'AI_DISCOVERED'"
    )


def downgrade() -> None:
    op.drop_index("ix_owner_analysis_runs_period_end", table_name="owner_analysis_runs")
    op.drop_index("ix_owner_analysis_runs_status", table_name="owner_analysis_runs")
    op.drop_index(
        "ix_owner_analysis_runs_restaurant_location_id", table_name="owner_analysis_runs"
    )
    op.drop_index(
        "ix_owner_analysis_runs_restaurant_id", table_name="owner_analysis_runs"
    )
    op.drop_table("owner_analysis_runs")
    analysis_run_status_enum.drop(op.get_bind(), checkfirst=True)
    # The AI_DISCOVERED label stays: Postgres cannot drop one label, and
    # rebuilding the type would mean rewriting every dependent column.

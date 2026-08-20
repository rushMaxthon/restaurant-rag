"""Action outcomes: what was observed after an approved recommendation ran

Revision ID: 0043_action_outcomes
Revises: 0042_operational_events
Create Date: 2026-08-14 17:30:00.000000

The manager could propose an action and create the offer, but never looked back
to see what happened. `owner_action_proposals.executed_offer_id` was written and
never read; this table is what reads it.

One row per proposal (enforced by a unique constraint), so re-measuring updates
the existing verdict rather than appending a new one.

These figures are observations, not proof of cause. There is no holdout group,
so the numbers describe what happened in the window after the offer went live —
seasonality or an unrelated change would land in them identically.

Every step is guarded so re-running is a no-op.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0043_action_outcomes"
down_revision = "0042_operational_events"
branch_labels = None
depends_on = None


action_outcome_verdict_enum = postgresql.ENUM(
    "NO_UPTAKE",
    "BELOW_ESTIMATE",
    "MET_ESTIMATE",
    "ABOVE_ESTIMATE",
    "NOT_MEASURABLE",
    name="action_outcome_verdict",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    action_outcome_verdict_enum.create(bind, checkfirst=True)

    if "action_outcomes" in set(sa.inspect(bind).get_table_names()):
        return

    op.create_table(
        "action_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("proposal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("offer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("verdict", action_outcome_verdict_enum, nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attributed_orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attributed_customers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "attributed_revenue",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column(
            "discount_cost",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column(
            "net_revenue",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0.00",
        ),
        sa.Column("estimated_impact", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["owner_action_proposals.id"],
            name="fk_action_outcomes_proposal",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_id"],
            ["restaurants.id"],
            name="fk_action_outcomes_restaurant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["offer_id"],
            ["personalized_offers.id"],
            name="fk_action_outcomes_offer",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_action_outcomes"),
        # One outcome per proposal: measuring again updates rather than appends.
        sa.UniqueConstraint("proposal_id", name="uq_action_outcomes_proposal_id"),
    )

    for column in ("proposal_id", "restaurant_id", "offer_id", "verdict", "measured_at"):
        op.create_index(f"ix_action_outcomes_{column}", "action_outcomes", [column])
    op.create_index(
        "ix_action_outcomes_scope_measured",
        "action_outcomes",
        ["restaurant_id", "measured_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "action_outcomes" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("action_outcomes")
    action_outcome_verdict_enum.drop(bind, checkfirst=True)

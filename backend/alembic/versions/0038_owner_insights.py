"""AI Restaurant Manager: persisted owner briefings and insights

Revision ID: 0038_owner_insights
Revises: 0037_stripe_payments
Create Date: 2026-08-14 12:00:00.000000

Adds the two tables the insight generation phase writes to:

* ``owner_briefings`` - one narrative summary per restaurant per generation run,
  keeping the diagnostics snapshot it was written from so any claim in the text
  can be traced back to the numbers behind it.
* ``owner_insights`` - the individual ranked findings, each carrying the exact
  set of numbers it is allowed to state.

All four enum types are created fresh rather than extended, so the Postgres
restriction on using a label in the same transaction that added it (see
``0037_stripe_payments``) does not apply here.

Every step is guarded so re-running is a no-op.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0038_owner_insights"
down_revision = "0037_stripe_payments"
branch_labels = None
depends_on = None


owner_insight_type_enum = postgresql.ENUM(
    "REVENUE_DROP",
    "REVENUE_SPIKE",
    "ITEM_DECLINE",
    "ITEM_SURGE",
    "CATEGORY_DECLINE",
    "DAYPART_WEAKNESS",
    "WEEKDAY_WEAKNESS",
    "RETURNING_CUSTOMER_DECLINE",
    "NEW_CUSTOMER_DECLINE",
    "CANCELLATION_SPIKE",
    "AOV_DROP",
    "ANOMALY_DAY",
    name="owner_insight_type",
    create_type=False,
)

owner_insight_severity_enum = postgresql.ENUM(
    "INFO",
    "LOW",
    "MEDIUM",
    "HIGH",
    name="owner_insight_severity",
    create_type=False,
)

owner_insight_status_enum = postgresql.ENUM(
    "NEW",
    "SEEN",
    "DISMISSED",
    name="owner_insight_status",
    create_type=False,
)

insight_narration_source_enum = postgresql.ENUM(
    "TEMPLATE",
    "LLM",
    name="insight_narration_source",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    owner_insight_type_enum.create(bind, checkfirst=True)
    owner_insight_severity_enum.create(bind, checkfirst=True)
    owner_insight_status_enum.create(bind, checkfirst=True)
    insight_narration_source_enum.create(bind, checkfirst=True)

    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "owner_briefings" not in existing_tables:
        op.create_table(
            "owner_briefings",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("restaurant_location_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("previous_period_start", sa.Date(), nullable=False),
            sa.Column("previous_period_end", sa.Date(), nullable=False),
            sa.Column("headline", sa.String(length=255), nullable=False),
            sa.Column("narrative", sa.Text(), nullable=False),
            sa.Column(
                "narration_source",
                insight_narration_source_enum,
                nullable=False,
                server_default="TEMPLATE",
            ),
            sa.Column("fallback_reason", sa.Text(), nullable=True),
            sa.Column("insight_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "facts",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
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
                ["restaurant_id"],
                ["restaurants.id"],
                name="fk_owner_briefings_restaurant_id_restaurants",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["restaurant_location_id"],
                ["restaurant_locations.id"],
                name="fk_owner_briefings_restaurant_location_id_restaurant_locations",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_owner_briefings"),
        )
        op.create_index(
            "ix_owner_briefings_restaurant_id", "owner_briefings", ["restaurant_id"]
        )
        op.create_index(
            "ix_owner_briefings_restaurant_location_id",
            "owner_briefings",
            ["restaurant_location_id"],
        )
        op.create_index("ix_owner_briefings_period_end", "owner_briefings", ["period_end"])
        op.create_index(
            "ix_owner_briefings_narration_source", "owner_briefings", ["narration_source"]
        )
        op.create_index(
            "ix_owner_briefings_scope_period",
            "owner_briefings",
            ["restaurant_id", "period_end"],
        )

    if "owner_insights" not in existing_tables:
        op.create_table(
            "owner_insights",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("briefing_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("restaurant_location_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("insight_type", owner_insight_type_enum, nullable=False),
            sa.Column(
                "severity",
                owner_insight_severity_enum,
                nullable=False,
                server_default="INFO",
            ),
            sa.Column(
                "status", owner_insight_status_enum, nullable=False, server_default="NEW"
            ),
            sa.Column("dedupe_key", sa.String(length=255), nullable=False),
            sa.Column(
                "score", sa.Numeric(precision=12, scale=4), nullable=False, server_default="0.0000"
            ),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("dimension", sa.String(length=64), nullable=True),
            sa.Column("subject", sa.String(length=255), nullable=True),
            sa.Column("period_start", sa.Date(), nullable=False),
            sa.Column("period_end", sa.Date(), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "facts",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
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
                ["briefing_id"],
                ["owner_briefings.id"],
                name="fk_owner_insights_briefing_id_owner_briefings",
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["restaurant_id"],
                ["restaurants.id"],
                name="fk_owner_insights_restaurant_id_restaurants",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["restaurant_location_id"],
                ["restaurant_locations.id"],
                name="fk_owner_insights_restaurant_location_id_restaurant_locations",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_owner_insights"),
        )
        op.create_index("ix_owner_insights_briefing_id", "owner_insights", ["briefing_id"])
        op.create_index("ix_owner_insights_restaurant_id", "owner_insights", ["restaurant_id"])
        op.create_index(
            "ix_owner_insights_restaurant_location_id",
            "owner_insights",
            ["restaurant_location_id"],
        )
        op.create_index("ix_owner_insights_insight_type", "owner_insights", ["insight_type"])
        op.create_index("ix_owner_insights_severity", "owner_insights", ["severity"])
        op.create_index("ix_owner_insights_status", "owner_insights", ["status"])
        op.create_index("ix_owner_insights_dedupe_key", "owner_insights", ["dedupe_key"])
        op.create_index("ix_owner_insights_score", "owner_insights", ["score"])
        op.create_index("ix_owner_insights_period_end", "owner_insights", ["period_end"])
        op.create_index("ix_owner_insights_generated_at", "owner_insights", ["generated_at"])
        op.create_index(
            "ix_owner_insights_scope_status", "owner_insights", ["restaurant_id", "status"]
        )
        op.create_index(
            "ix_owner_insights_dedupe",
            "owner_insights",
            ["restaurant_id", "dedupe_key", "generated_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "owner_insights" in existing_tables:
        op.drop_table("owner_insights")
    if "owner_briefings" in existing_tables:
        op.drop_table("owner_briefings")

    owner_insight_type_enum.drop(bind, checkfirst=True)
    owner_insight_severity_enum.drop(bind, checkfirst=True)
    owner_insight_status_enum.drop(bind, checkfirst=True)
    insight_narration_source_enum.drop(bind, checkfirst=True)

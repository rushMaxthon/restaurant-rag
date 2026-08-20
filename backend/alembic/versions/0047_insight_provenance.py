"""Provenance columns on insights and proposals.

`insight_origin` and `analysis_confidence` are new types, so creating and using
them in this migration is safe — the restriction that shaped 0045 and 0046
applies only to labels added to a type that already existed.

Every existing row is backfilled to RULES, which is what it is: produced by the
deterministic rules engine. Nothing is retroactively attributed to a model.

Revision ID: 0047_insight_provenance
Revises: 0046_analysis_runs
Create Date: 2026-08-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0047_insight_provenance"
down_revision = "0046_analysis_runs"
branch_labels = None
depends_on = None

TABLES = ("owner_insights", "owner_action_proposals")

insight_origin_enum = postgresql.ENUM(
    "RULES", "AI", name="insight_origin", create_type=False
)
analysis_confidence_enum = postgresql.ENUM(
    "LOW", "MEDIUM", "HIGH", name="analysis_confidence", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    insight_origin_enum.create(bind, checkfirst=True)
    analysis_confidence_enum.create(bind, checkfirst=True)

    for table in TABLES:
        op.add_column(
            table,
            sa.Column(
                "origin",
                insight_origin_enum,
                nullable=False,
                server_default="RULES",
            ),
        )
        op.add_column(
            table, sa.Column("confidence", analysis_confidence_enum, nullable=True)
        )
        op.add_column(table, sa.Column("ai_category", sa.String(length=120), nullable=True))
        op.add_column(
            table,
            sa.Column(
                "evidence",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="{}",
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "analysis_run_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("owner_analysis_runs.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.add_column(table, sa.Column("model_name", sa.String(length=120), nullable=True))

        op.create_index(f"ix_{table}_origin", table, ["origin"])
        op.create_index(f"ix_{table}_analysis_run_id", table, ["analysis_run_id"])

        # Explicit, even though the server default already covers existing rows:
        # a column added with a default is one migration away from someone
        # removing the default and leaving nulls behind.
        op.execute(sa.text(f"UPDATE {table} SET origin = 'RULES' WHERE origin IS NULL"))


def downgrade() -> None:
    for table in TABLES:
        op.drop_index(f"ix_{table}_analysis_run_id", table_name=table)
        op.drop_index(f"ix_{table}_origin", table_name=table)
        for column in (
            "model_name",
            "analysis_run_id",
            "evidence",
            "ai_category",
            "confidence",
            "origin",
        ):
            op.drop_column(table, column)

    bind = op.get_bind()
    analysis_confidence_enum.drop(bind, checkfirst=True)
    insight_origin_enum.drop(bind, checkfirst=True)

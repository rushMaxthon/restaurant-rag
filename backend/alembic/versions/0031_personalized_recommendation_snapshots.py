"""add personalized recommendation snapshots

Revision ID: 0031_personalized_recommendation_snapshots
Revises: 0030_generated_combo_live_status
Create Date: 2026-06-24 12:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0031_personalized_recommendation_snapshots"
down_revision = "0030_generated_combo_live_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personalized_recommendation_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("generation_status", sa.String(length=32), server_default="PENDING", nullable=False),
        sa.Column("candidate_snapshot_hash", sa.String(length=128), nullable=True),
        sa.Column("candidate_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ranked_recommendation_keys", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("ai_collection_title", sa.String(length=255), nullable=True),
        sa.Column("ai_insight", sa.Text(), nullable=True),
        sa.Column("item_metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("ai_model", sa.String(length=120), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_personalized_recommendation_snapshots_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_personalized_recommendation_snapshots")),
        sa.UniqueConstraint("user_id", name=op.f("uq_personalized_recommendation_snapshots_user_id")),
    )
    op.create_index(
        op.f("ix_personalized_recommendation_snapshots_candidate_snapshot_hash"),
        "personalized_recommendation_snapshots",
        ["candidate_snapshot_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_personalized_recommendation_snapshots_user_id"),
        "personalized_recommendation_snapshots",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_personalized_recommendation_snapshots_user_id"),
        table_name="personalized_recommendation_snapshots",
    )
    op.drop_index(
        op.f("ix_personalized_recommendation_snapshots_candidate_snapshot_hash"),
        table_name="personalized_recommendation_snapshots",
    )
    op.drop_table("personalized_recommendation_snapshots")

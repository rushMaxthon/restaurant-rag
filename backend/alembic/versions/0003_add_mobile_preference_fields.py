"""add mobile preference fields

Revision ID: 0003_mobile_pref_fields
Revises: 0002_enforce_owner_one_to_one
Create Date: 2026-05-06 00:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0003_mobile_pref_fields"
down_revision = "0002_enforce_owner_one_to_one"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_preferences",
        sa.Column("spice_level", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "user_preferences",
        sa.Column("budget_tier", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "user_preferences",
        sa.Column(
            "favorite_items",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("user_preferences", "favorite_items")
    op.drop_column("user_preferences", "budget_tier")
    op.drop_column("user_preferences", "spice_level")

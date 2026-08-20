"""rename generated combo published status to live and add manual override

Revision ID: 0030_generated_combo_live_status
Revises: 0029_generated_combo_lifecycle
Create Date: 2026-06-18 19:55:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0030_generated_combo_live_status"
down_revision = "0029_generated_combo_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generated_combos",
        sa.Column("manual_status_override", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE generated_combos
        SET status = 'LIVE'
        WHERE status = 'PUBLISHED'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE generated_combos
        SET status = 'PUBLISHED'
        WHERE status = 'LIVE'
        """
    )
    op.drop_column("generated_combos", "manual_status_override")

"""add welcome first-order personalized offer type

Revision ID: 0013_offer_welcome
Revises: 0012_offer_audience
Create Date: 2026-05-21 09:45:00.000000
"""

from __future__ import annotations

from alembic import op


# revision identifiers, used by Alembic.
revision = "0013_offer_welcome"
down_revision = "0012_offer_audience"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE personalized_offer_type ADD VALUE IF NOT EXISTS 'WELCOME_FIRST_ORDER'")


def downgrade() -> None:
    # PostgreSQL enum values are intentionally left in place on downgrade.
    pass

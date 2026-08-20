"""Add free delivery discount type for manual offers

Revision ID: 0014_offer_free_delivery
Revises: 0013_offer_welcome
Create Date: 2026-05-21 12:00:00.000000
"""

from __future__ import annotations

from alembic import op


revision = "0014_offer_free_delivery"
down_revision = "0013_offer_welcome"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE personalized_offer_discount_type ADD VALUE IF NOT EXISTS 'FREE_DELIVERY'")


def downgrade() -> None:
    # PostgreSQL enum value removal is intentionally skipped.
    pass

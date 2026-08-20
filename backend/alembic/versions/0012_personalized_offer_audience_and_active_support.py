"""add personalized offer audience targeting and active-user support

Revision ID: 0012_offer_audience
Revises: 0011_personalized_offers
Create Date: 2026-05-20 20:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0012_offer_audience"
down_revision = "0011_personalized_offers"
branch_labels = None
depends_on = None


personalized_offer_audience = postgresql.ENUM(
    "ACTIVE_USERS",
    "INACTIVE_USERS",
    "ALL_CUSTOMERS",
    name="personalized_offer_audience",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("ALTER TYPE personalized_offer_type ADD VALUE IF NOT EXISTS 'PREFERENCE_MATCH'")
    op.execute("ALTER TYPE personalized_offer_type ADD VALUE IF NOT EXISTS 'ORDER_HISTORY_MATCH'")
    op.execute("ALTER TYPE personalized_offer_type ADD VALUE IF NOT EXISTS 'NEW_ITEM_MATCH'")

    personalized_offer_audience.create(bind, checkfirst=True)

    op.add_column(
        "personalized_offers",
        sa.Column(
            "audience_type",
            personalized_offer_audience,
            nullable=False,
            server_default=sa.text("'INACTIVE_USERS'"),
        ),
    )
    op.create_index(
        op.f("ix_personalized_offers_audience_type"),
        "personalized_offers",
        ["audience_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_personalized_offers_audience_type"), table_name="personalized_offers")
    op.drop_column("personalized_offers", "audience_type")

    bind = op.get_bind()
    personalized_offer_audience.drop(bind, checkfirst=True)

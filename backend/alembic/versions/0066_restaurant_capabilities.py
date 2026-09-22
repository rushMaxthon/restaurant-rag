"""features switched on for one restaurant

Revision ID: 0066_restaurant_capabilities
Revises: 0065_restaurant_currency
Create Date: 2026-09-18 00:00:00.000000

"Build something for one restaurant and have it live only for them" without a
fork, a branch or a second deployment.

An allowlist like this existed here before, as a module constant, and was
deleted for becoming a permanent unexplained split. What is different is not
discipline: it is that a row has a writer, an actor, a timestamp and a screen,
and a module constant has none of those.

Empty on every restaurant, forever, unless somebody decides otherwise. No row
means the catalog default, so this migration changes nothing for any existing
tenant and onboarding a new one needs zero rows.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0066_restaurant_capabilities"
down_revision = "0065_restaurant_currency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "restaurant_capabilities" in sa.inspect(bind).get_table_names():
        return

    op.create_table(
        "restaurant_capabilities",
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("capability_key", sa.String(length=64), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("granted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"),
        # SET NULL: a grant outlives the admin account that made it, and
        # losing the record along with a departed colleague's login would
        # defeat the point of storing who granted it.
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("restaurant_id", "capability_key"),
    )
    # "Who has Ask AI" is a question the platform matrix asks directly, and it
    # is the wrong shape for the primary key.
    op.create_index(
        "ix_restaurant_capabilities_key",
        "restaurant_capabilities",
        ["capability_key"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "restaurant_capabilities" in sa.inspect(bind).get_table_names():
        op.drop_index("ix_restaurant_capabilities_key", table_name="restaurant_capabilities")
        op.drop_table("restaurant_capabilities")

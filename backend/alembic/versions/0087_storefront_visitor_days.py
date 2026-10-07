"""Storefront traffic: one row per visitor, per restaurant, per day.

Read by the admin's Traffic page (`services/traffic.py`): who is online now,
daily unique visitors, new against returning, devices, busiest hours and how
many visitors ordered. Purely additive; nothing reads it until the storefront
starts sending its heartbeat. RLS on in the migration itself, as `0070` set
the pattern - the backend owns the table and bypasses it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0087_storefront_visitor_days"
down_revision = "0086_platform_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "storefront_visitor_days" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "storefront_visitor_days",
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("visit_date", sa.Date(), primary_key=True),
        sa.Column("visitor_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("device", sa.String(8), nullable=False),
        sa.Column("is_new", sa.Boolean(), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hours_mask", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_storefront_visitor_days_restaurant_last_seen",
        "storefront_visitor_days",
        ["restaurant_id", "last_seen_at"],
    )
    op.create_index(
        "ix_storefront_visitor_days_restaurant_visitor",
        "storefront_visitor_days",
        ["restaurant_id", "visitor_id"],
    )
    op.execute("ALTER TABLE public.storefront_visitor_days ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("storefront_visitor_days")

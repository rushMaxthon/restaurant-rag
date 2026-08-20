"""add fulfillment scheduling settings and order schedule fields

Revision ID: 0018_fulfillment_scheduling
Revises: 0017_default_location_slots
Create Date: 2026-05-27 20:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0018_fulfillment_scheduling"
down_revision = "0017_default_location_slots"
branch_labels = None
depends_on = None


order_schedule_type = postgresql.ENUM(
    "ASAP",
    "SCHEDULED",
    name="order_schedule_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    order_schedule_type.create(bind, checkfirst=True)

    op.add_column(
        "restaurant_locations",
        sa.Column("future_order_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "restaurant_locations",
        sa.Column("max_future_days", sa.Integer(), nullable=False, server_default="7"),
    )
    op.add_column(
        "restaurant_locations",
        sa.Column("slot_interval_minutes", sa.Integer(), nullable=False, server_default="15"),
    )

    op.add_column(
        "orders",
        sa.Column(
            "schedule_type",
            order_schedule_type,
            nullable=False,
            server_default=sa.text("'ASAP'"),
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(op.f("ix_orders_schedule_type"), "orders", ["schedule_type"], unique=False)
    op.create_index(op.f("ix_orders_scheduled_at"), "orders", ["scheduled_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_orders_scheduled_at"), table_name="orders")
    op.drop_index(op.f("ix_orders_schedule_type"), table_name="orders")
    op.drop_column("orders", "scheduled_at")
    op.drop_column("orders", "schedule_type")

    op.drop_column("restaurant_locations", "slot_interval_minutes")
    op.drop_column("restaurant_locations", "max_future_days")
    op.drop_column("restaurant_locations", "future_order_enabled")

    bind = op.get_bind()
    order_schedule_type.drop(bind, checkfirst=True)

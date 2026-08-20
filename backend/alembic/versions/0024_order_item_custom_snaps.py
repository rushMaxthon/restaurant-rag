"""store order item customization snapshots

Revision ID: 0024_order_item_custom_snaps
Revises: 0023_menu_item_customizations
Create Date: 2026-06-09 20:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0024_order_item_custom_snaps"
down_revision = "0023_menu_item_customizations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "order_items",
        sa.Column("menu_item_size_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("size_name_snapshot", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column(
            "base_unit_price",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="0.00",
        ),
    )
    op.add_column(
        "order_items",
        sa.Column(
            "customization_total_price",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="0.00",
        ),
    )
    op.add_column(
        "order_items",
        sa.Column(
            "selected_options_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.execute(
        "UPDATE order_items "
        "SET base_unit_price = unit_price, customization_total_price = 0.00, selected_options_snapshot = '[]'::jsonb"
    )
    op.alter_column("order_items", "base_unit_price", server_default=None)
    op.alter_column("order_items", "customization_total_price", server_default=None)
    op.alter_column("order_items", "selected_options_snapshot", server_default=None)


def downgrade() -> None:
    op.drop_column("order_items", "selected_options_snapshot")
    op.drop_column("order_items", "customization_total_price")
    op.drop_column("order_items", "base_unit_price")
    op.drop_column("order_items", "size_name_snapshot")
    op.drop_column("order_items", "menu_item_size_id")

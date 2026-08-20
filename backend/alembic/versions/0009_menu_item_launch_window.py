"""add menu item launch timestamp support for new-item recommendations

Revision ID: 0009_menu_item_launch_window
Revises: 0008_restaurant_locations
Create Date: 2026-05-18 17:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0009_menu_item_launch_window"
down_revision = "0008_restaurant_locations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "menu_items",
        sa.Column(
            "launched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
    )
    op.create_index(
        op.f("ix_menu_items_launched_at"),
        "menu_items",
        ["launched_at"],
        unique=False,
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE menu_items "
            "SET launched_at = COALESCE(created_at, now()) "
            "WHERE launched_at IS NULL"
        )
    )

    op.alter_column("menu_items", "launched_at", nullable=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_menu_items_launched_at"), table_name="menu_items")
    op.drop_column("menu_items", "launched_at")

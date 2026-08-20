"""add manual new-launch flag for menu items

Revision ID: 0010_menu_item_new_launch_flag
Revises: 0009_menu_item_launch_window
Create Date: 2026-05-19 18:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0010_menu_item_new_launch_flag"
down_revision = "0009_menu_item_launch_window"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "menu_items",
        sa.Column(
            "is_new_launch",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_index(
        op.f("ix_menu_items_is_new_launch"),
        "menu_items",
        ["is_new_launch"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_menu_items_is_new_launch"), table_name="menu_items")
    op.drop_column("menu_items", "is_new_launch")

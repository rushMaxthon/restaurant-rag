"""add is_countable column to menu_item_customization_options

Migration 0023 was applied before is_countable was added to the schema.
This migration patches the existing table to add the missing column.

Revision ID: 0025_add_is_countable_to_options
Revises: 0024_order_item_custom_snaps
Create Date: 2026-06-10 06:15:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0025_add_is_countable_to_options"
down_revision = "0024_order_item_custom_snaps"
branch_labels = None
depends_on = None


def _has_is_countable() -> bool:
    inspector = sa.inspect(op.get_bind())
    return "is_countable" in {
        column["name"]
        for column in inspector.get_columns("menu_item_customization_options")
    }


def upgrade() -> None:
    # 0023 now creates this column itself, so on a fresh database it already
    # exists by the time this patch revision runs. Only older databases, where
    # 0023 predated the column, still need it added.
    if not _has_is_countable():
        op.add_column(
            "menu_item_customization_options",
            sa.Column(
                "is_countable",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    # Remove the server default so it behaves like the model definition
    op.alter_column(
        "menu_item_customization_options",
        "is_countable",
        server_default=None,
    )


def downgrade() -> None:
    if _has_is_countable():
        op.drop_column("menu_item_customization_options", "is_countable")

"""add menu item size and customization support

Revision ID: 0023_menu_item_customizations
Revises: 0022_push_notification_campaigns
Create Date: 2026-06-09 10:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0023_menu_item_customizations"
down_revision = "0022_push_notification_campaigns"
branch_labels = None
depends_on = None


menu_item_customization_selection_type = postgresql.ENUM(
    "SINGLE",
    "MULTI",
    name="menu_item_customization_selection_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    menu_item_customization_selection_type.create(bind, checkfirst=True)

    op.add_column(
        "menu_items",
        sa.Column("has_sizes", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "menu_items",
        sa.Column(
            "has_customizations",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "menu_item_sizes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("menu_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["menu_item_id"], ["menu_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_menu_item_sizes_menu_item_id", "menu_item_sizes", ["menu_item_id"], unique=False)

    op.create_table(
        "menu_item_customization_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("menu_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("menu_item_size_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column(
            "selection_type",
            menu_item_customization_selection_type,
            nullable=False,
            server_default=sa.text("'MULTI'"),
        ),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("min_selection", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_selection", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["menu_item_id"], ["menu_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["menu_item_size_id"], ["menu_item_sizes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_menu_item_customization_groups_menu_item_id",
        "menu_item_customization_groups",
        ["menu_item_id"],
        unique=False,
    )
    op.create_index(
        "ix_menu_item_customization_groups_menu_item_size_id",
        "menu_item_customization_groups",
        ["menu_item_size_id"],
        unique=False,
    )

    op.create_table(
        "menu_item_customization_options",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("extra_price", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_countable", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["group_id"], ["menu_item_customization_groups.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_menu_item_customization_options_group_id",
        "menu_item_customization_options",
        ["group_id"],
        unique=False,
    )

    op.alter_column("menu_items", "has_sizes", server_default=None)
    op.alter_column("menu_items", "has_customizations", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_menu_item_customization_options_group_id", table_name="menu_item_customization_options")
    op.drop_table("menu_item_customization_options")

    op.drop_index(
        "ix_menu_item_customization_groups_menu_item_size_id",
        table_name="menu_item_customization_groups",
    )
    op.drop_index(
        "ix_menu_item_customization_groups_menu_item_id",
        table_name="menu_item_customization_groups",
    )
    op.drop_table("menu_item_customization_groups")

    op.drop_index("ix_menu_item_sizes_menu_item_id", table_name="menu_item_sizes")
    op.drop_table("menu_item_sizes")

    op.drop_column("menu_items", "has_customizations")
    op.drop_column("menu_items", "has_sizes")

    bind = op.get_bind()
    menu_item_customization_selection_type.drop(bind, checkfirst=True)

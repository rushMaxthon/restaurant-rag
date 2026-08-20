"""add generated combo tables

Revision ID: 0006_generated_combos
Revises: 0005_remove_rating_review_flow
Create Date: 2026-05-13 11:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0006_generated_combos"
down_revision = "0005_remove_rating_review_flow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generated_combos",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("restaurant_id", sa.UUID(), nullable=False),
        sa.Column("signature", sa.String(length=255), nullable=False),
        sa.Column("combo_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("order_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unique_user_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("confidence_score", sa.Numeric(precision=10, scale=2), server_default="0.00", nullable=False),
        sa.Column("original_total_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("suggested_combo_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("generated_from_orders", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["restaurant_id"],
            ["restaurants.id"],
            name=op.f("fk_generated_combos_restaurant_id_restaurants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_combos")),
    )
    op.create_index(op.f("ix_generated_combos_combo_name"), "generated_combos", ["combo_name"], unique=False)
    op.create_index(op.f("ix_generated_combos_is_active"), "generated_combos", ["is_active"], unique=False)
    op.create_index(op.f("ix_generated_combos_restaurant_id"), "generated_combos", ["restaurant_id"], unique=False)
    op.create_index(op.f("ix_generated_combos_signature"), "generated_combos", ["signature"], unique=True)

    op.create_table(
        "generated_combo_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("combo_id", sa.UUID(), nullable=False),
        sa.Column("menu_item_id", sa.UUID(), nullable=False),
        sa.Column("quantity", sa.Integer(), server_default="1", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["combo_id"],
            ["generated_combos.id"],
            name=op.f("fk_generated_combo_items_combo_id_generated_combos"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["menu_item_id"],
            ["menu_items.id"],
            name=op.f("fk_generated_combo_items_menu_item_id_menu_items"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_combo_items")),
        sa.UniqueConstraint("combo_id", "menu_item_id", name=op.f("uq_generated_combo_items_combo_id_menu_item_id")),
    )
    op.create_index(op.f("ix_generated_combo_items_combo_id"), "generated_combo_items", ["combo_id"], unique=False)
    op.create_index(op.f("ix_generated_combo_items_menu_item_id"), "generated_combo_items", ["menu_item_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_generated_combo_items_menu_item_id"), table_name="generated_combo_items")
    op.drop_index(op.f("ix_generated_combo_items_combo_id"), table_name="generated_combo_items")
    op.drop_table("generated_combo_items")

    op.drop_index(op.f("ix_generated_combos_signature"), table_name="generated_combos")
    op.drop_index(op.f("ix_generated_combos_restaurant_id"), table_name="generated_combos")
    op.drop_index(op.f("ix_generated_combos_is_active"), table_name="generated_combos")
    op.drop_index(op.f("ix_generated_combos_combo_name"), table_name="generated_combos")
    op.drop_table("generated_combos")

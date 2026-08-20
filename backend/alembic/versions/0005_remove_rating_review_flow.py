"""remove rating and review flow

Revision ID: 0005_remove_rating_review_flow
Revises: 0004_chat_perf_indexes
Create Date: 2026-05-12 10:15:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0005_remove_rating_review_flow"
down_revision = "0004_chat_perf_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_menu_items_restaurant_available_popularity")

    op.execute("ALTER TABLE order_items DROP CONSTRAINT IF EXISTS ck_order_items_order_items_rating_range")
    op.execute("ALTER TABLE order_items DROP CONSTRAINT IF EXISTS ck_order_items_ck_order_items_order_items_rating_range")
    op.drop_column("order_items", "review_text")
    op.drop_column("order_items", "rating")

    op.drop_column("menu_items", "total_ratings")
    op.drop_column("menu_items", "average_rating")

    op.drop_column("restaurants", "total_ratings")
    op.drop_column("restaurants", "average_rating")

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_menu_items_restaurant_available_popularity
        ON menu_items (
            restaurant_id,
            is_available,
            popularity_score DESC,
            created_at DESC
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_menu_items_restaurant_available_popularity")

    op.add_column("restaurants", sa.Column("average_rating", sa.Numeric(precision=3, scale=2), server_default="0.00", nullable=False))
    op.add_column("restaurants", sa.Column("total_ratings", sa.Integer(), server_default="0", nullable=False))

    op.add_column("menu_items", sa.Column("average_rating", sa.Numeric(precision=3, scale=2), server_default="0.00", nullable=False))
    op.add_column("menu_items", sa.Column("total_ratings", sa.Integer(), server_default="0", nullable=False))

    op.add_column("order_items", sa.Column("rating", sa.Integer(), nullable=True))
    op.add_column("order_items", sa.Column("review_text", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_order_items_order_items_rating_range",
        "order_items",
        "rating IS NULL OR (rating >= 1 AND rating <= 5)",
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_menu_items_restaurant_available_popularity
        ON menu_items (
            restaurant_id,
            is_available,
            popularity_score DESC,
            total_ratings DESC,
            average_rating DESC
        )
        """
    )

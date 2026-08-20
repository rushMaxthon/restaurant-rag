"""add chat performance indexes

Revision ID: 0004_chat_perf_indexes
Revises: 0003_mobile_pref_fields
Create Date: 2026-05-11 11:05:00.000000
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_chat_perf_indexes"
down_revision = "0003_mobile_pref_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_menu_embeddings_embedding_ivfflat
        ON menu_embeddings
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_restaurants_active_approved
        ON restaurants (is_active, is_approved, id)
        """
    )
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
    op.execute("DROP INDEX IF EXISTS ix_restaurants_active_approved")
    op.execute("DROP INDEX IF EXISTS ix_menu_embeddings_embedding_ivfflat")

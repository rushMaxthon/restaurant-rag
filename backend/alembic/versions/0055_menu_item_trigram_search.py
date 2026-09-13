"""Enable trigram search on menu item names, so a typo still finds the dish.

Keyword retrieval is an ILIKE substring match, which is all-or-nothing: "pad
thai" finds Pad Thai and "padd thai" finds nothing at all. Vector search rescues
some misspellings because the embedding of a near-miss lands close enough, but
it is unreliable about it — measured over 20 common misspellings it caught
"biriyani", "marghrita" and "chiken" while missing "padd thai", "margarita
pizza", "noodels" and "cofee", which fell through to the generic popular
fallback and answered a question the customer had not asked.

pg_trgm gives a real edit-distance-like score to fall back on. The GIN index
keeps `%` and `similarity()` off a sequential scan as the menu grows.

Revision ID: 0055_menu_item_trigram_search
Revises: 0054_offer_type_custom
"""

from alembic import op

revision = "0055_menu_item_trigram_search"
down_revision = "0054_offer_type_custom"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_menu_items_name_trgm "
        "ON menu_items USING gin (name gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_menu_items_name_trgm")
    # The extension is left installed: other work may have come to depend on it,
    # and dropping it would take those indexes with it.

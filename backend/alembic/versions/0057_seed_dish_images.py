"""Give every dish and restaurant a picture.

172 of 189 menu items had no `image_url`, so the customer app fell back to an
initials tile — 91% of the menu rendered as "TC" and "MP" boxes, which is the
first thing anyone notices and the hardest to take seriously. Every restaurant
was missing its cover and logo too.

These are category images, not per-dish photography: the picture says what KIND
of dish it is, which is honest and far better than two letters on a coloured
square. A dish that already has its own photo keeps it — the WHERE clause only
fills blanks, so re-running this never overwrites real photography, and adding
real photos later simply supersedes it.

Every URL here was fetched and confirmed to return 200 with an image
content-type before being written down. A dead image is worse than the tile it
replaces.

Revision ID: 0057_seed_dish_images
Revises: 0056_disable_cash_on_delivery
"""

from alembic import op
import sqlalchemy as sa

revision = "0057_seed_dish_images"
down_revision = "0056_disable_cash_on_delivery"
branch_labels = None
depends_on = None


CATEGORY_IMAGES = {
    "Beverages": "https://images.unsplash.com/photo-1544145945-f90425340c7e?w=800&q=80",
    "Main Course": "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=800&q=80",
    # A spread, not a pizza. Combo shared the Pizza image at first, so a Thai
    # combo box rendered as a pizza — a wrong picture is worse than a generic
    # one, because the customer believes it.
    "Combo": "https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=800&q=80",
    "Appetizer": "https://images.unsplash.com/photo-1541014741259-de529411b96a?w=800&q=80",
    "Momos": "https://images.unsplash.com/photo-1534422298391-e4f8c172dddb?w=800&q=80",
    "Burger": "https://images.unsplash.com/photo-1568901346375-23c9450c58cd?w=800&q=80",
    "Pizza": "https://images.unsplash.com/photo-1513104890138-7c749659a591?w=800&q=80",
    "Rice": "https://images.unsplash.com/photo-1596797038530-2c107229654b?w=800&q=80",
    "Pasta": "https://images.unsplash.com/photo-1551183053-bf91a1d81141?w=800&q=80",
    "Noodles": "https://images.unsplash.com/photo-1585032226651-759b368d7246?w=800&q=80",
    "Soup": "https://images.unsplash.com/photo-1547592166-23ac45744acd?w=800&q=80",
    "Curry": "https://images.unsplash.com/photo-1455619452474-d2be8b1e70cd?w=800&q=80",
    "Dessert": "https://images.unsplash.com/photo-1488477181946-6428a0291777?w=800&q=80",
    "Breads": "https://images.unsplash.com/photo-1509440159596-0249088772ff?w=800&q=80",
    "Sides": "https://images.unsplash.com/photo-1573080496219-bb080dd4f877?w=800&q=80",
    "Dim Sum": "https://images.unsplash.com/photo-1496116218417-1a781b1c416c?w=800&q=80",
    "Non-Veg": "https://images.unsplash.com/photo-1432139555190-58524dae6a55?w=800&q=80",
    "Bao": "https://images.unsplash.com/photo-1563245372-f21724e3856d?w=800&q=80",
    "Rolls": "https://images.unsplash.com/photo-1562967914-608f82629710?w=800&q=80",
    "Healthy Bowls": "https://images.unsplash.com/photo-1512621776951-a57141f2eefd?w=800&q=80",
    "Salads": "https://images.unsplash.com/photo-1540420773420-3366772f4999?w=800&q=80",
}

# Falls back to this when a dish's category is not in the map above, so no item
# can come out of this migration still holding a blank.
GENERIC_DISH_IMAGE = "https://images.unsplash.com/photo-1546069901-ba9599a7e63c?w=800&q=80"

CUISINE_COVERS = {
    "Indian": "https://images.unsplash.com/photo-1585937421612-70a008356fbe?w=1200&q=80",
    "Italian": "https://images.unsplash.com/photo-1498579150354-977475b7ea0b?w=1200&q=80",
    "Chinese": "https://images.unsplash.com/photo-1525755662778-989d0524087e?w=1200&q=80",
    "Thai": "https://images.unsplash.com/photo-1552465011-b4e21bf6e79a?w=1200&q=80",
    "American": "https://images.unsplash.com/photo-1550547660-d9450f859349?w=1200&q=80",
    "Tibetan": "https://images.unsplash.com/photo-1626804475297-41608ea09aeb?w=1200&q=80",
}

GENERIC_COVER = "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?w=1200&q=80"


def upgrade() -> None:
    connection = op.get_bind()

    for category, url in CATEGORY_IMAGES.items():
        connection.execute(
            sa.text(
                "UPDATE menu_items SET image_url = :url "
                "WHERE category = :category AND (image_url IS NULL OR image_url = '')"
            ),
            {"url": url, "category": category},
        )

    connection.execute(
        sa.text(
            "UPDATE menu_items SET image_url = :url WHERE image_url IS NULL OR image_url = ''"
        ),
        {"url": GENERIC_DISH_IMAGE},
    )

    for cuisine, url in CUISINE_COVERS.items():
        connection.execute(
            sa.text(
                "UPDATE restaurants SET cover_image_url = :url "
                "WHERE cuisine_type = :cuisine AND (cover_image_url IS NULL OR cover_image_url = '')"
            ),
            {"url": url, "cuisine": cuisine},
        )

    connection.execute(
        sa.text(
            "UPDATE restaurants SET cover_image_url = :url "
            "WHERE cover_image_url IS NULL OR cover_image_url = ''"
        ),
        {"url": GENERIC_COVER},
    )
    # The logo falls back to the cover rather than a second lookup: a wrong logo
    # is more noticeable than a repeated one.
    connection.execute(
        sa.text(
            "UPDATE restaurants SET logo_image_url = cover_image_url "
            "WHERE logo_image_url IS NULL OR logo_image_url = ''"
        )
    )


def downgrade() -> None:
    # Deliberately not clearing image_url: by the time anyone downgrades, real
    # photography may have been added on top and there is no way to tell it
    # apart from what this migration wrote.
    pass

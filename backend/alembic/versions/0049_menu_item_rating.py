"""Ratings on a menu item.

The storefront wants a star beside the price and had nowhere to read one from.
The only alternative to a column was deriving a number from `popularity_score`
and presenting it as if diners had given it.

`rating` is nullable because a dish nobody has rated has no rating — which is a
different fact from a rating of zero, and has to render differently.
`rating_count` is not, because "no ratings yet" is honestly zero.

Additive and empty by default, so every existing dish keeps working and simply
shows no star until it has one.
"""

from alembic import op
import sqlalchemy as sa

revision = "0049_menu_item_rating"
down_revision = "0048_restaurant_theme"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("menu_items", sa.Column("rating", sa.Numeric(2, 1), nullable=True))
    op.add_column(
        "menu_items",
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("menu_items", "rating_count")
    op.drop_column("menu_items", "rating")

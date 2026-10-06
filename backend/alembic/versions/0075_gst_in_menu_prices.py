"""A branch can sell at prices that already contain 18% GST.

One switch on the branch, and beside every price the figure the owner typed.

`price` keeps its meaning — what the customer pays — because about ninety
places read it and three clients add a cart up from it. With the switch on it
is rewritten as the typed figure plus 18%, by `services/menu_pricing.py`, when
an item is saved or the switch is flipped. The typed figure has to be kept
somewhere or switching back off would have nothing to return to, and dividing
118 by 1.18 does not always land on the paisa it started from.

**The base columns are nullable and are NOT backfilled.** NULL means "what is
in `price` is what was typed", which is true of every row that exists today —
the switch defaults off, so no price here has ever been marked up. Leaving them
NULL is what makes the first relist safe: it records the base from the price
exactly once.

Numbered 0075 because `0074_print_agents` exists on the print branch. Both
name `0073_restaurant_brand` as their parent, so merging the two branches gives
two heads: re-point this one at `0074_print_agents` when that happens, the way
`0069_order_deliveries` was re-pointed.

Guarded, like `0072`: the shared database may be given these columns by hand
before this revision can be reached from its stamp.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0075_gst_in_menu_prices"
# Re-pointed from 0073 when feat/print-agent was merged (2026-10-05): both
# branches had continued from 0073, and the shared database carries both
# halves. Re-pointed rather than renumbered, for the reason 0063/0064 were -
# Supabase is stamped with an id downstream of this one.
down_revision = "0074_print_agents"
branch_labels = None
depends_on = None

_BASE_COLUMNS = (
    ("menu_items", "base_price"),
    ("menu_item_sizes", "base_price"),
    ("menu_item_customization_options", "base_extra_price"),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    branch = {c["name"] for c in inspector.get_columns("restaurant_locations")}
    if "gst_in_menu_prices" not in branch:
        op.add_column(
            "restaurant_locations",
            sa.Column(
                "gst_in_menu_prices",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    for table, column in _BASE_COLUMNS:
        existing = {c["name"] for c in inspector.get_columns(table)}
        if column not in existing:
            op.add_column(table, sa.Column(column, sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    # A branch with the switch on is selling at marked-up prices. Dropping the
    # base would leave those as the only record, so put the typed figures back
    # first.
    op.execute(
        "UPDATE menu_items SET price = base_price WHERE base_price IS NOT NULL"
    )
    op.execute(
        "UPDATE menu_item_sizes SET price = base_price WHERE base_price IS NOT NULL"
    )
    op.execute(
        "UPDATE menu_item_customization_options SET extra_price = base_extra_price "
        "WHERE base_extra_price IS NOT NULL"
    )
    for table, column in reversed(_BASE_COLUMNS):
        op.drop_column(table, column)
    op.drop_column("restaurant_locations", "gst_in_menu_prices")

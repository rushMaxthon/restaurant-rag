"""The GST switch stops changing prices, and the second price column goes.

`0075` built the switch backwards. An owner who turned it on was saying "my
menu prices already contain GST"; what it did was ADD 18% to every price they
had typed and keep the typed figure in `base_price`. The switch now means what
the owner meant: on, the typed price is what the customer pays and no tax on
food is added at checkout; off, `tax_percent` is added on the bill. Nothing
rewrites a price.

Two things follow, in this order.

**Prices that were marked up go back to what was typed.** Any branch that had
the switch on is selling at typed-plus-18%. `base_price` is the typed figure —
it was stamped on every save and every flip — so the restore is a copy, not a
division: 116.82 / 1.18 does not land back on 99.00. A row with a NULL base
was never marked up and is left alone. The switch itself is NOT turned off:
those owners did say their prices include GST, and leaving it on is what
keeps tax off their bills.

**Then the base columns are dropped.** With no markup there is one price, and
a second column that nothing writes would go stale the first time an item was
edited — and the admin editor used to load it in preference to `price`.

Not reversible in the sense that matters: the downgrade brings the columns
back empty, which under 0075's own rule ("NULL means what is in `price` is
what was typed") is a correct state. It does not re-apply a markup.

Guarded, like `0075`: the shared database may have been changed by hand.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0076_gst_switch_keeps_prices"
down_revision = "0075_gst_in_menu_prices"
branch_labels = None
depends_on = None

#: (table, the price a customer pays, the typed figure kept beside it)
_COLUMNS = (
    ("menu_items", "price", "base_price"),
    ("menu_item_sizes", "price", "base_price"),
    ("menu_item_customization_options", "extra_price", "base_extra_price"),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, price, base in _COLUMNS:
        existing = {c["name"] for c in inspector.get_columns(table)}
        if base not in existing:
            continue
        op.execute(
            f"UPDATE {table} SET {price} = {base} "
            f"WHERE {base} IS NOT NULL AND {base} <> {price}"
        )
        op.drop_column(table, base)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, _price, base in reversed(_COLUMNS):
        existing = {c["name"] for c in inspector.get_columns(table)}
        if base not in existing:
            op.add_column(table, sa.Column(base, sa.Numeric(10, 2), nullable=True))

"""The platform's commission goes into the menu price.

One rate on the branch, `commission_percent`, 10 by default. The owner types
what they want for a dish and the customer is shown that plus the rate: typed
100 is 110 on the menu. `services/menu_pricing.py` rewrites `price` whenever
an item is saved or the rate is changed.

`price` keeps its meaning — what the customer pays — because about ninety
places read it and three clients add a cart up from it. The typed figure has
to be kept somewhere or a change of rate would have nothing to start from, and
dividing 54.95 by 1.10 does not land on the 49.95 it came from. So the three
base columns that `0076` dropped come back, for a different reason than the
one `0075` first added them for. That one was a misreading of the GST switch,
and the switch still changes no price.

**Every price that exists today is marked up, here.** A branch that has the
default rate and a menu still at typed prices would be two figures for one
dish in waiting: the first item an owner edited would go up 10% and its
neighbours would not. So the upgrade records what is in `price` as the typed
figure and raises it by the branch's rate, in SQL, with the same rounding
`menu_pricing._money` uses — Postgres rounds a numeric half away from zero,
which for a price is ROUND_HALF_UP. Only rows with no base are touched, so a
second run, or a run after the columns were added by hand, changes nothing.

Orders already placed are not touched: an order line carries its own copy of
the price it was sold at.

The downgrade puts the typed figures back before it drops where they are kept.

Guarded, like `0075` and `0076`: the shared database may be changed by hand
before this revision can be reached from its stamp.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0077_commission_percent"
down_revision = "0076_gst_switch_keeps_prices"
branch_labels = None
depends_on = None

#: (table, the price a customer pays, the typed figure kept beside it, how to
#: reach the row's menu item)
_COLUMNS = (
    ("menu_items", "price", "base_price", "t.id"),
    ("menu_item_sizes", "price", "base_price", "t.menu_item_id"),
    (
        "menu_item_customization_options",
        "extra_price",
        "base_extra_price",
        "(SELECT g.menu_item_id FROM menu_item_customization_groups g WHERE g.id = t.group_id)",
    ),
)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    branch = {c["name"] for c in inspector.get_columns("restaurant_locations")}
    if "commission_percent" not in branch:
        op.add_column(
            "restaurant_locations",
            sa.Column(
                "commission_percent",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="10.00",
            ),
        )

    for table, price, base, menu_item_id in _COLUMNS:
        existing = {c["name"] for c in inspector.get_columns(table)}
        if base not in existing:
            op.add_column(table, sa.Column(base, sa.Numeric(10, 2), nullable=True))
        op.execute(
            f"""
            UPDATE {table} AS t
            SET {base} = t.{price},
                {price} = round(t.{price} * (100 + l.commission_percent) / 100, 2)
            FROM menu_items m
            JOIN restaurant_locations l ON l.id = m.restaurant_location_id
            WHERE m.id = {menu_item_id}
              AND t.{base} IS NULL
            """
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, price, base, _menu_item_id in reversed(_COLUMNS):
        existing = {c["name"] for c in inspector.get_columns(table)}
        if base in existing:
            op.execute(f"UPDATE {table} SET {price} = {base} WHERE {base} IS NOT NULL")
            op.drop_column(table, base)
    branch = {c["name"] for c in inspector.get_columns("restaurant_locations")}
    if "commission_percent" in branch:
        op.drop_column("restaurant_locations", "commission_percent")

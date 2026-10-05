"""Stock: by hand, by size, and refilled each morning.

Three things `0078` could not say.

* `menu_items.out_of_stock` - marked out of stock by hand. On the menu, cannot
  be added. For the owner who counts nothing and has just sold the last one.
* `menu_item_sizes.stock_quantity` - a size's own count, for a dish whose
  sizes come off different trays. NULL means the size draws on the dish's
  count, which is what every size did before this, so nothing changes until
  an owner types a number against one.
* `stock_daily_quantity` on both - what the count is set back to each morning
  by `stock.restock_daily`. NULL means it is restocked by hand.

And `order_items.stock_reserved_size`, so a cancelled order's stock goes back
to the count it came from.

Everything is additive and defaults to "as before". Guarded, like `0075` to
`0079`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0080_stock_sizes_manual_daily"
down_revision = "0079_order_commission"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _checks(table: str) -> set[str]:
    return {check["name"] for check in sa.inspect(op.get_bind()).get_check_constraints(table)}


def _check(table: str, name: str, condition: str) -> None:
    # The bare name: the naming convention adds `ck_<table>_` itself.
    if f"ck_{table}_{name}" not in _checks(table):
        op.create_check_constraint(name, table, condition)


def upgrade() -> None:
    items = _columns("menu_items")
    if "out_of_stock" not in items:
        op.add_column(
            "menu_items",
            sa.Column("out_of_stock", sa.Boolean(), nullable=False, server_default="false"),
        )
    if "stock_daily_quantity" not in items:
        op.add_column("menu_items", sa.Column("stock_daily_quantity", sa.Integer(), nullable=True))
    _check(
        "menu_items",
        "stock_daily_quantity_not_negative",
        "stock_daily_quantity IS NULL OR stock_daily_quantity >= 0",
    )

    sizes = _columns("menu_item_sizes")
    if "stock_quantity" not in sizes:
        op.add_column("menu_item_sizes", sa.Column("stock_quantity", sa.Integer(), nullable=True))
    if "stock_daily_quantity" not in sizes:
        op.add_column(
            "menu_item_sizes", sa.Column("stock_daily_quantity", sa.Integer(), nullable=True)
        )
    _check(
        "menu_item_sizes",
        "stock_quantity_not_negative",
        "stock_quantity IS NULL OR stock_quantity >= 0",
    )
    _check(
        "menu_item_sizes",
        "stock_daily_quantity_not_negative",
        "stock_daily_quantity IS NULL OR stock_daily_quantity >= 0",
    )

    if "stock_reserved_size" not in _columns("order_items"):
        op.add_column(
            "order_items",
            sa.Column("stock_reserved_size", sa.Boolean(), nullable=False, server_default="false"),
        )


def downgrade() -> None:
    if "stock_reserved_size" in _columns("order_items"):
        op.drop_column("order_items", "stock_reserved_size")

    for name in ("stock_daily_quantity_not_negative", "stock_quantity_not_negative"):
        if f"ck_menu_item_sizes_{name}" in _checks("menu_item_sizes"):
            op.drop_constraint(name, "menu_item_sizes", type_="check")
    sizes = _columns("menu_item_sizes")
    for column in ("stock_daily_quantity", "stock_quantity"):
        if column in sizes:
            op.drop_column("menu_item_sizes", column)

    if "ck_menu_items_stock_daily_quantity_not_negative" in _checks("menu_items"):
        op.drop_constraint("stock_daily_quantity_not_negative", "menu_items", type_="check")
    items = _columns("menu_items")
    for column in ("stock_daily_quantity", "out_of_stock"):
        if column in items:
            op.drop_column("menu_items", column)

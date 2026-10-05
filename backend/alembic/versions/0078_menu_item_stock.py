"""A dish can be counted: how many are left to sell.

`menu_items.stock_quantity`, nullable. NULL is "nobody is counting", which is
every row that exists today, so this changes no menu. A number is how many can
still be sold; `services/stock.py` subtracts from it when an order is created
and adds back when one is cancelled.

`order_items.stock_reserved` records that a line subtracted from the count. A
cancellation gives back only what is marked, so an order placed before an
owner started counting returns nothing it never took.

The CHECK is the last line of defence, not the rule. The rule is the UPDATE in
`stock.reserve`, which refuses to go below zero by matching no row. The CHECK
is there for the day somebody writes a second path that subtracts.

Guarded, like `0075` to `0077`: the shared database may be changed by hand
before this revision can be reached from its stamp.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0078_menu_item_stock"
down_revision = "0077_commission_percent"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _checks(table: str) -> set[str]:
    return {check["name"] for check in sa.inspect(op.get_bind()).get_check_constraints(table)}


def upgrade() -> None:
    if "stock_quantity" not in _columns("menu_items"):
        op.add_column("menu_items", sa.Column("stock_quantity", sa.Integer(), nullable=True))
    if "ck_menu_items_stock_quantity_not_negative" not in _checks("menu_items"):
        # The bare name: the naming convention adds `ck_menu_items_` itself,
        # on a CREATE and on a DROP alike.
        op.create_check_constraint(
            "stock_quantity_not_negative",
            "menu_items",
            "stock_quantity IS NULL OR stock_quantity >= 0",
        )
    if "stock_reserved" not in _columns("order_items"):
        op.add_column(
            "order_items",
            sa.Column("stock_reserved", sa.Boolean(), nullable=False, server_default="false"),
        )


def downgrade() -> None:
    if "stock_reserved" in _columns("order_items"):
        op.drop_column("order_items", "stock_reserved")
    if "ck_menu_items_stock_quantity_not_negative" in _checks("menu_items"):
        op.drop_constraint("stock_quantity_not_negative", "menu_items", type_="check")
    if "stock_quantity" in _columns("menu_items"):
        op.drop_column("menu_items", "stock_quantity")

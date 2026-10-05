"""An order records the commission it earned.

`orders.commission_percent` is the branch's rate when the order was placed,
and `orders.commission_amount` is what that rate put inside the subtotal.
`services/commission.py` writes both in `create_order` and reads them for the
admin's commission report.

Both nullable, and left NULL on every order that already exists. The rate is
a dial: an order from last month cannot honestly be costed at today's
setting, so the report counts from the first order that carries a figure and
says when that was.

Guarded, like `0075` to `0078`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0079_order_commission"
down_revision = "0078_menu_item_stock"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    existing = _columns("orders")
    if "commission_percent" not in existing:
        op.add_column("orders", sa.Column("commission_percent", sa.Numeric(5, 2), nullable=True))
    if "commission_amount" not in existing:
        op.add_column("orders", sa.Column("commission_amount", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    existing = _columns("orders")
    if "commission_amount" in existing:
        op.drop_column("orders", "commission_amount")
    if "commission_percent" in existing:
        op.drop_column("orders", "commission_percent")

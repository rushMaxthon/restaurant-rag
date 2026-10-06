"""Where the rider goes, and who is carrying the order.

Found on the first live order, 2026-10-06:

- `orders.delivery_latitude` / `delivery_longitude`: the rooftop the customer
  picked at checkout. The order was priced from it and then it was dropped,
  so the courier was sent the address text alone and geocoded it itself.
- `order_deliveries.network_name` / `network_order_id` / `allocated_at`:
  Pidge hands a trip to a partner network with its own order reference, the
  one to quote when a delivery goes wrong. It was only inside `raw`.

Additive and nullable or defaulted, guarded like 0075-0083, so the code on
Render before this deploy keeps working against it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0084_delivery_point_and_network"
down_revision = "0083_restaurant_payouts"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    orders = _columns("orders")
    if "delivery_latitude" not in orders:
        op.add_column("orders", sa.Column("delivery_latitude", sa.Float(), nullable=True))
    if "delivery_longitude" not in orders:
        op.add_column("orders", sa.Column("delivery_longitude", sa.Float(), nullable=True))
    deliveries = _columns("order_deliveries")
    if "network_name" not in deliveries:
        op.add_column("order_deliveries", sa.Column("network_name", sa.String(120), nullable=False, server_default=""))
    if "network_order_id" not in deliveries:
        op.add_column(
            "order_deliveries", sa.Column("network_order_id", sa.String(128), nullable=False, server_default="")
        )
    if "allocated_at" not in deliveries:
        op.add_column("order_deliveries", sa.Column("allocated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    deliveries = _columns("order_deliveries")
    for name in ("allocated_at", "network_order_id", "network_name"):
        if name in deliveries:
            op.drop_column("order_deliveries", name)
    orders = _columns("orders")
    for name in ("delivery_longitude", "delivery_latitude"):
        if name in orders:
            op.drop_column("orders", name)

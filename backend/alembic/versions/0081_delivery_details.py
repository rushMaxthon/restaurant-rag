"""A delivery keeps what the courier told it, in columns a screen can read.

Pidge's status response carries the pickup and drop ETAs, the moment each
happened, its own charge for the trip, every step with a remark and the
rider's position, and why a trip failed. All of it was in `raw` and none of
it was read: the fields the code looked for (`picked_up_at`,
`delivered_at`) are not ones Pidge sends. These columns hold the parts the
admin, the live board and the customer's order page show.

`attempt` counts bookings for one order. A failed or cancelled trip can be
re-booked; Pidge refuses a reference it has seen, so the attempt number goes
into it.

All nullable or defaulted, so existing deliveries are untouched. Guarded,
like `0075` to `0080`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0081_delivery_details"
down_revision = "0080_stock_sizes_manual_daily"
branch_labels = None
depends_on = None

_COLUMNS = (
    ("pickup_eta", lambda: sa.Column("pickup_eta", sa.DateTime(timezone=True), nullable=True)),
    ("drop_eta", lambda: sa.Column("drop_eta", sa.DateTime(timezone=True), nullable=True)),
    ("courier_charge", lambda: sa.Column("courier_charge", sa.Numeric(10, 2), nullable=True)),
    ("rider_latitude", lambda: sa.Column("rider_latitude", sa.Float(), nullable=True)),
    ("rider_longitude", lambda: sa.Column("rider_longitude", sa.Float(), nullable=True)),
    ("rider_location_at", lambda: sa.Column("rider_location_at", sa.DateTime(timezone=True), nullable=True)),
    ("failure_reason", lambda: sa.Column("failure_reason", sa.Text(), nullable=False, server_default="")),
    ("timeline", lambda: sa.Column("timeline", postgresql.JSONB(), nullable=True)),
    ("attempt", lambda: sa.Column("attempt", sa.Integer(), nullable=False, server_default="1")),
)


def _existing() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("order_deliveries")}


def upgrade() -> None:
    existing = _existing()
    for name, column in _COLUMNS:
        if name not in existing:
            op.add_column("order_deliveries", column())


def downgrade() -> None:
    existing = _existing()
    for name, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("order_deliveries", name)

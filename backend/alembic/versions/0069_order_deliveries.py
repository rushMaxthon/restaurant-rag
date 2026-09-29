"""what a courier is doing with one order

Revision ID: 0069_order_deliveries
Revises: 0068_payment_transaction_payment_id
Create Date: 2026-09-29 00:00:00.000000

A courier's story and a restaurant's story are not the same story, and the
part that costs money is the part that does not fit. `orders.status` is
strictly linear and ends at DELIVERED or CANCELLED; a rider who collects the
food, cannot hand it over and brings it back is neither. Folding that into
CANCELLED would erase the difference between an order nobody started and an
order that was cooked, dispatched and wasted — which is exactly the case
somebody has to pay for.

So the delivery keeps its own state here, and only the states that genuinely
correspond are allowed to move the order.

`order_id` is UNIQUE: one live delivery per order. The dispatch path checks
for an existing row before calling the courier, and this constraint is what
makes that check safe when two workers run it at once rather than merely
likely to work. A retried task cannot put a second rider on the same food.

Empty on every existing order, and nothing reads it until
`ENABLE_DELIVERY_DISPATCH` is on — so this changes nothing on its own.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0069_order_deliveries"
down_revision = "0068_payment_transaction_payment_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded because the table may already be there. The shared development
    # database is on another branch's chain (it reads 0071 while this branch
    # ends at 0068), so the table was created on it directly rather than by
    # this migration. An unguarded `create_table` would then fail the first
    # time the chains are reconciled and this revision finally runs — turning
    # a merge into an outage for the sake of a table that already exists.
    #
    # The RLS statement below is repeated for the same reason: it is what the
    # direct creation also did, and enabling it twice is a no-op.
    inspector = sa.inspect(op.get_bind())
    if "order_deliveries" in inspector.get_table_names():
        op.execute("ALTER TABLE public.order_deliveries ENABLE ROW LEVEL SECURITY")
        return

    op.create_table(
        "order_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("orders.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("provider", sa.String(length=50), nullable=False),
        # Empty until the courier accepts it. A row with no id records a
        # dispatch that was attempted and refused, which is the difference
        # between "we never tried" and "they would not take it".
        sa.Column("provider_order_id", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("provider_status", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("rider_name", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("rider_mobile", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("tracking_url", sa.Text(), nullable=False, server_default=""),
        sa.Column("distance_metres", sa.Float(), nullable=True),
        sa.Column("picked_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    # How a webhook finds its order: the courier names its own id, not ours.
    op.create_index(
        "ix_order_deliveries_provider_order_id",
        "order_deliveries",
        ["provider", "provider_order_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_order_deliveries_provider_order_id", table_name="order_deliveries")
    op.drop_table("order_deliveries")

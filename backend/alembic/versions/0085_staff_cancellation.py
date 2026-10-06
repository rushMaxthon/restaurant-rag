"""Staff may cancel an order; a prepaid one is refunded.

Five new `order_cancellation_reason` values for a person's cancellation, and
three columns on `orders`: the note beside the reason, and where the refund
stands. Additive and nullable, so the code on Render before this deploy keeps
working against it.

The enum values are added inside `autocommit_block`, for the reason `0071`
gives: Postgres will not let a value added in a transaction be used before
that transaction commits, and Alembic runs every pending revision in one.
`ADD VALUE IF NOT EXISTS` makes a re-run harmless. A downgrade cannot remove
an enum value in Postgres, so it drops the columns and leaves the values.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0085_staff_cancellation"
down_revision = "0084_delivery_point_and_network"
branch_labels = None
depends_on = None

REASONS = ("OUT_OF_STOCK", "KITCHEN_UNAVAILABLE", "CUSTOMER_REQUEST", "DUPLICATE_OR_TEST", "OTHER_BY_STAFF")


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for value in REASONS:
            op.execute(f"ALTER TYPE order_cancellation_reason ADD VALUE IF NOT EXISTS '{value}'")
    columns = _columns("orders")
    if "cancellation_note" not in columns:
        op.add_column("orders", sa.Column("cancellation_note", sa.Text(), nullable=True))
    if "refund_status" not in columns:
        op.add_column("orders", sa.Column("refund_status", sa.String(16), nullable=True))
    if "refund_error" not in columns:
        op.add_column("orders", sa.Column("refund_error", sa.Text(), nullable=True))


def downgrade() -> None:
    columns = _columns("orders")
    for name in ("refund_error", "refund_status", "cancellation_note"):
        if name in columns:
            op.drop_column("orders", name)

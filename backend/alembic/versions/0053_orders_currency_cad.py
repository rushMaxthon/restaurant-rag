"""Move the orders currency to CAD, in the column default and in existing rows.

Every price in both web apps is now rendered in Canadian dollars and
`payment_currency` is "cad", but `orders.currency` still defaulted to 'INR' at
the database level and 30 existing rows still carried it. The Stripe intent is
built from `order.currency`, not from the setting — so a row left at INR would
have quoted a customer CAD on screen and charged them the same number in
rupees.

Backfilling historical rows is safe here and would not always be: at the time
of writing `payment_transactions` is empty, so no row being rewritten has ever
been part of a real charge. If that is not true in your environment, drop the
UPDATE and correct only the default — rewriting the currency of a settled
payment falsifies a financial record.

Revision ID: 0053_orders_currency_cad
Revises: 0052_enable_row_level_security
"""

from alembic import op
import sqlalchemy as sa

revision = "0053_orders_currency_cad"
down_revision = "0052_enable_row_level_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "orders",
        "currency",
        existing_type=sa.String(length=10),
        existing_nullable=False,
        server_default="CAD",
    )
    op.execute("UPDATE orders SET currency = 'CAD' WHERE currency = 'INR'")


def downgrade() -> None:
    op.alter_column(
        "orders",
        "currency",
        existing_type=sa.String(length=10),
        existing_nullable=False,
        server_default="INR",
    )
    op.execute("UPDATE orders SET currency = 'INR' WHERE currency = 'CAD'")

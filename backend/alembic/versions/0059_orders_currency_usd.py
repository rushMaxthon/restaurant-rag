"""Move the orders currency default to USD. Existing rows are left alone.

`8f4d050` switched every customer- and owner-facing price to US dollars, but
three places still disagreed about what the number meant:

    display (formatMoney)     USD
    .env PAYMENT_CURRENCY     INR
    settings default          CAD
    orders.currency default   CAD

`orders.currency` is not cosmetic. Orders stamp it at creation and the Stripe
intent is built from the ROW, not from the setting — so a row carrying a
currency the screen never showed charges the customer in it.

**No backfill, deliberately.** 0053 moved this column INR -> CAD and rewrote its
existing rows, and said exactly when that is allowed:

    "Backfilling historical rows is safe here and would not always be: at the
    time of writing `payment_transactions` is empty, so no row being rewritten
    has ever been part of a real charge. If that is not true in your
    environment, drop the UPDATE and correct only the default — rewriting the
    currency of a settled payment falsifies a financial record."

That condition no longer holds. `payment_transactions` has 132 rows, 61 of them
PAID against the stripe provider. So the 162 existing CAD orders keep their
currency: whatever was charged, was charged in what the row says.

The effect is a database that holds both, which is correct rather than untidy —
`orders.currency` exists precisely so a historical order can be read in the
currency it was placed in. Every order from here is USD.

Revision ID: 0059_orders_currency_usd
Revises: 0058_order_contact_details
"""

from alembic import op
import sqlalchemy as sa

revision = "0059_orders_currency_usd"
down_revision = "0058_order_contact_details"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "orders",
        "currency",
        existing_type=sa.String(length=10),
        existing_nullable=False,
        server_default="USD",
    )


def downgrade() -> None:
    op.alter_column(
        "orders",
        "currency",
        existing_type=sa.String(length=10),
        existing_nullable=False,
        server_default="CAD",
    )

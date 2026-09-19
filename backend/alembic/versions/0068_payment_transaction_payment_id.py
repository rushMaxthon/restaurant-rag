"""the gateway's id for the money that actually moved

Revision ID: 0068_payment_transaction_payment_id
Revises: 0067_restaurant_payment_accounts
Create Date: 2026-09-19 00:00:00.000000

`payment_transactions` records what this app ASKED the gateway for —
`provider_intent_id` is a Stripe PaymentIntent, a Razorpay order, or (since
chat ordering) a Razorpay payment link. None of those is what a refund is
issued against.

Razorpay refunds `POST /payments/{payment_id}/refund`, and that payment id
arrives in the `payment_link.paid` webhook, in `payload.payment.entity.id` —
where it was read, used to nothing, and dropped. So a Razorpay payment could
not be refunded from this system at all: somebody had to open the Razorpay
dashboard and find the payment by hand.

Nullable, and not backfilled. Every row written before this has genuinely
lost the id, and inventing one would be worse than admitting it — a refund
path can say "this payment predates the id being recorded" and send the
operator to the dashboard, which is what they are doing today anyway.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0068_payment_transaction_payment_id"
down_revision = "0067_restaurant_payment_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("payment_transactions")}

    if "provider_payment_id" not in existing:
        op.add_column(
            "payment_transactions",
            sa.Column("provider_payment_id", sa.String(length=255), nullable=True),
        )

    indexes = {index["name"] for index in inspector.get_indexes("payment_transactions")}
    if "ix_payment_transactions_provider_payment_id" not in indexes:
        # A refund webhook names the payment, not the intent, so this is the
        # column that has to be searchable to match one back to an order.
        op.create_index(
            "ix_payment_transactions_provider_payment_id",
            "payment_transactions",
            ["provider_payment_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    indexes = {index["name"] for index in inspector.get_indexes("payment_transactions")}
    if "ix_payment_transactions_provider_payment_id" in indexes:
        op.drop_index(
            "ix_payment_transactions_provider_payment_id",
            table_name="payment_transactions",
        )

    existing = {column["name"] for column in inspector.get_columns("payment_transactions")}
    if "provider_payment_id" in existing:
        op.drop_column("payment_transactions", "provider_payment_id")

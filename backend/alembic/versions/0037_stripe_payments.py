"""stripe payments: payment-pending order states, transactions and webhook events

Revision ID: 0037_stripe_payments
Revises: 0036_user_token_version
Create Date: 2026-08-13 10:00:00.000000

Adds what a real card payment needs, on top of the previously mocked flow:

* ``OrderStatus.PAYMENT_PENDING`` — a card order exists but is unpaid, so the
  kitchen must not see it — and ``OrderStatus.CANCELLED`` for orders abandoned
  before payment.
* ``PaymentStatus.CANCELLED`` for a dismissed payment sheet.
* ``payment_transactions`` — one row per payment attempt, since an order can be
  retried after a decline.
* ``payment_webhook_events`` — every provider event seen, uniquely keyed so
  redelivered webhooks are idempotent.

New enum labels are added with ``ALTER TYPE ... ADD VALUE IF NOT EXISTS``. They
are never *used* inside this migration: Postgres forbids using a label added in
the same transaction that created it.

Every step is guarded so re-running is a no-op.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0037_stripe_payments"
down_revision = "0036_user_token_version"
branch_labels = None
depends_on = None


payment_status_enum = postgresql.ENUM(
    "PENDING",
    "PAID",
    "FAILED",
    "COD",
    "REFUNDED",
    "CANCELLED",
    name="payment_status",
    create_type=False,
)

NEW_ORDER_STATUSES = ("PAYMENT_PENDING", "CANCELLED")
NEW_PAYMENT_STATUSES = ("CANCELLED",)


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return table in _inspector().get_table_names()


def upgrade() -> None:
    for label in NEW_ORDER_STATUSES:
        op.execute(f"ALTER TYPE order_status ADD VALUE IF NOT EXISTS '{label}'")
    for label in NEW_PAYMENT_STATUSES:
        op.execute(f"ALTER TYPE payment_status ADD VALUE IF NOT EXISTS '{label}'")

    if not _has_table("payment_transactions"):
        op.create_table(
            "payment_transactions",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("order_id", sa.UUID(), nullable=False),
            sa.Column("provider", sa.String(length=50), nullable=False),
            sa.Column("provider_intent_id", sa.String(length=255), nullable=False),
            sa.Column("status", payment_status_enum, server_default="PENDING", nullable=False),
            sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
            sa.Column("currency", sa.String(length=10), server_default="INR", nullable=False),
            sa.Column("failure_code", sa.String(length=100), nullable=True),
            sa.Column("failure_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(
                ["order_id"],
                ["orders.id"],
                name="fk_payment_transactions_order_id_orders",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_payment_transactions"),
        )
        op.create_index(
            "ix_payment_transactions_order_id",
            "payment_transactions",
            ["order_id"],
        )
        op.create_index(
            "ix_payment_transactions_provider_intent_id",
            "payment_transactions",
            ["provider_intent_id"],
            unique=True,
        )
        op.create_index(
            "ix_payment_transactions_status",
            "payment_transactions",
            ["status"],
        )

    if not _has_table("payment_webhook_events"):
        op.create_table(
            "payment_webhook_events",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("provider", sa.String(length=50), nullable=False),
            sa.Column("provider_event_id", sa.String(length=255), nullable=False),
            sa.Column("event_type", sa.String(length=100), nullable=False),
            sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_payment_webhook_events"),
        )
        op.create_index(
            "ix_payment_webhook_events_provider",
            "payment_webhook_events",
            ["provider"],
        )
        op.create_index(
            "ix_payment_webhook_events_provider_event_id",
            "payment_webhook_events",
            ["provider_event_id"],
            unique=True,
        )


def downgrade() -> None:
    """Drops the payment tables.

    The enum labels are intentionally left in place: Postgres cannot remove a
    label from an enum type, and orders may already be stamped with them.
    """

    if _has_table("payment_webhook_events"):
        op.drop_table("payment_webhook_events")
    if _has_table("payment_transactions"):
        op.drop_table("payment_transactions")

"""the gateway's own payment id on a transaction — RECONSTRUCTED

Revision ID: 0068_payment_transaction_payment_id
Revises: 0067_restaurant_payment_accounts
Create Date: 2026-09-21 00:00:00.000000

A reconstruction. See `0065_app_client_push_credentials` for why these four
revisions exist.

**This id matters more than the other three.** It is what the shared database
is actually stamped with, read from `alembic_version` on 2026-09-21. Alembic
resolves a database's current position by looking that string up among the
revision files it can see; with no file carrying this id, `alembic current`
and `alembic upgrade` both fail outright, which is why nothing could be
deployed. This file is what makes the stamp resolvable, and therefore what
unblocks every migration after it.

The column: `payment_transactions.provider_intent_id` records the intent we
created, and this records the payment the gateway settled it into — two
different identifiers that a refund or a dispute needs to tell apart.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0068_payment_transaction_payment_id"
down_revision = "0067_restaurant_payment_accounts"
branch_labels = None
depends_on = None


TABLE = "payment_transactions"
COLUMN = "provider_payment_id"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if TABLE not in inspector.get_table_names():
        return
    if COLUMN in {column["name"] for column in inspector.get_columns(TABLE)}:
        return

    # Nullable: every transaction that existed before the gateway told us a
    # payment id, and every one that never reached a settled payment.
    op.add_column(TABLE, sa.Column(COLUMN, sa.String(255), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return
    if COLUMN in {column["name"] for column in inspector.get_columns(TABLE)}:
        op.drop_column(TABLE, COLUMN)

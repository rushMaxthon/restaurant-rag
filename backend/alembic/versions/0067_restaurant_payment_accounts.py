"""per-restaurant gateway keys — RECONSTRUCTED from the shared database

Revision ID: 0067_restaurant_payment_accounts
Revises: 0066_restaurant_capabilities
Create Date: 2026-09-21 00:00:00.000000

A reconstruction. See `0065_app_client_push_credentials` for why these four
revisions exist and what they can and cannot be trusted to represent.

**This id is not a guess.** It is the revision CLAUDE.md recorded the shared
database as being stamped with, and the one every previous session found
unresolvable. The database has since moved on to
`0068_payment_transaction_payment_id`, but this id is still the one named in
the failure everybody hit, so it is reproduced exactly.

The table: Stripe or Razorpay credentials per restaurant, so each tenant is
paid into its own account rather than the platform's. The secret columns are
named `_encrypted` and are 1024 characters — wide enough for a ciphertext
rather than a key — so whatever wrote them encrypted them at the application
layer. Nothing in this repository reads this table; the code that does is in
the same unpushed branch as the original migration.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0067_restaurant_payment_accounts"
down_revision = "0066_restaurant_capabilities"
branch_labels = None
depends_on = None


TABLE = "restaurant_payment_accounts"

gateway = postgresql.ENUM(
    "STRIPE", "RAZORPAY", name="payment_gateway", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    gateway.create(bind, checkfirst=True)

    if TABLE in inspector.get_table_names():
        return

    op.create_table(
        TABLE,
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # One account per gateway per restaurant: a tenant may hold both a
        # Stripe and a Razorpay account, and which is used is a separate
        # decision from which exist.
        sa.Column("gateway", gateway, primary_key=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("public_key", sa.String(255), nullable=False),
        sa.Column("secret_key_encrypted", sa.String(1024), nullable=False),
        sa.Column("webhook_secret_encrypted", sa.String(1024), nullable=True),
        # The last four characters, so an owner can recognise which key is
        # stored without it ever being shown or returned.
        sa.Column("secret_last4", sa.String(8), nullable=True),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE in inspector.get_table_names():
        op.drop_table(TABLE)
    gateway.drop(bind, checkfirst=True)

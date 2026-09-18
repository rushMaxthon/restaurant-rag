"""each restaurant's own gateway account

Revision ID: 0067_restaurant_payment_accounts
Revises: 0066_restaurant_capabilities
Create Date: 2026-09-18 00:00:00.000000

One deployment serves every tenant, and every charge currently settles into
the platform's single Stripe account. That is not a payments arrangement a
restaurant would agree to: the money is theirs.

A row per restaurant per gateway, so a kitchen in Surat can take UPI through
its own Razorpay account while one in Toronto takes cards through its own
Stripe account, on the same deployment and the same release.

Secrets are Fernet ciphertext from `services/secrets.py`, which refuses to
store plaintext rather than degrading to it. `public_key` is deliberately not
encrypted — it is in the page source of every checkout that uses it.

Empty on every restaurant. Nothing is migrated from the platform's own keys:
those stay where they are and keep settling the restaurants that have not
been given their own account yet, so this changes nothing until a row exists.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0067_restaurant_payment_accounts"
down_revision = "0066_restaurant_capabilities"
branch_labels = None
depends_on = None


payment_gateway = postgresql.ENUM("STRIPE", "RAZORPAY", name="payment_gateway", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    payment_gateway.create(bind, checkfirst=True)

    if "restaurant_payment_accounts" in sa.inspect(bind).get_table_names():
        return

    op.create_table(
        "restaurant_payment_accounts",
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("gateway", payment_gateway, nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("public_key", sa.String(length=255), nullable=False),
        sa.Column("secret_key_encrypted", sa.String(length=1024), nullable=False),
        sa.Column("webhook_secret_encrypted", sa.String(length=1024), nullable=True),
        sa.Column("secret_last4", sa.String(length=8), nullable=True),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"),
        # SET NULL: who last touched a gateway's keys outlives their account.
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("restaurant_id", "gateway"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "restaurant_payment_accounts" in sa.inspect(bind).get_table_names():
        op.drop_table("restaurant_payment_accounts")
    payment_gateway.drop(bind, checkfirst=True)

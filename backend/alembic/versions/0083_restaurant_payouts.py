"""Restaurant payouts through Razorpay Route.

Two tables, `restaurant_payout_accounts` (a restaurant's linked account) and
`restaurant_payouts` (one row per order), plus
`payment_transactions.on_platform_account`. Additive, and guarded like
`0075`-`0082` so a schema created by hand is not created twice. RLS is enabled
here, not by hand, so a fresh environment comes up closed (CLAUDE.md).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0083_restaurant_payouts"
down_revision = "0082_restaurant_is_demo"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    tables = _tables()
    if "restaurant_payout_accounts" not in tables:
        op.create_table(
            "restaurant_payout_accounts",
            sa.Column("restaurant_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("restaurants.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("razorpay_account_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("stakeholder_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("product_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("status", sa.String(32), nullable=False, server_default="DRAFT"),
            sa.Column("legal_business_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("business_type", sa.String(32), nullable=False, server_default="proprietorship"),
            sa.Column("pan", sa.String(10), nullable=False, server_default=""),
            sa.Column("contact_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("email", sa.String(255), nullable=False, server_default=""),
            sa.Column("phone", sa.String(32), nullable=False, server_default=""),
            sa.Column("street", sa.String(255), nullable=False, server_default=""),
            sa.Column("city", sa.String(120), nullable=False, server_default=""),
            sa.Column("state", sa.String(120), nullable=False, server_default=""),
            sa.Column("postal_code", sa.String(10), nullable=False, server_default=""),
            sa.Column("bank_account_number_encrypted", sa.String(1024), nullable=True),
            sa.Column("bank_account_last4", sa.String(4), nullable=False, server_default=""),
            sa.Column("ifsc", sa.String(11), nullable=False, server_default=""),
            sa.Column("beneficiary_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("requirements", postgresql.JSONB(), nullable=False, server_default="[]"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    if "restaurant_payouts" not in tables:
        op.create_table(
            "restaurant_payouts",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("order_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("restaurant_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("payment_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("restaurant_share", sa.Numeric(10, 2), nullable=False),
            sa.Column("platform_keeps", sa.Numeric(10, 2), nullable=False),
            sa.Column("currency", sa.String(10), nullable=False, server_default="INR"),
            sa.Column("status", sa.String(32), nullable=False),
            sa.Column("transfer_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("settlement_id", sa.String(64), nullable=False, server_default=""),
            sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_restaurant_payouts_restaurant_id", "restaurant_payouts", ["restaurant_id"])
        op.create_index("ix_restaurant_payouts_status", "restaurant_payouts", ["status"])
        op.create_index("ix_restaurant_payouts_transfer_id", "restaurant_payouts", ["transfer_id"])
    if "on_platform_account" not in _columns("payment_transactions"):
        op.add_column(
            "payment_transactions",
            sa.Column("on_platform_account", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    op.execute("ALTER TABLE public.restaurant_payout_accounts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE public.restaurant_payouts ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    if "on_platform_account" in _columns("payment_transactions"):
        op.drop_column("payment_transactions", "on_platform_account")
    tables = _tables()
    if "restaurant_payouts" in tables:
        op.drop_table("restaurant_payouts")
    if "restaurant_payout_accounts" in tables:
        op.drop_table("restaurant_payout_accounts")

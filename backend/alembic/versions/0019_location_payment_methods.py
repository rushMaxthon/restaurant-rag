"""add location payment methods and order payment method

Revision ID: 0019_location_payment_methods
Revises: 0018_fulfillment_scheduling
Create Date: 2026-05-29 16:10:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0019_location_payment_methods"
down_revision = "0018_fulfillment_scheduling"
branch_labels = None
depends_on = None


payment_method_enum = sa.Enum(
    "GOOGLE_PAY",
    "RAZORPAY",
    "CARD",
    "COD",
    name="payment_method",
)


def upgrade() -> None:
    op.add_column(
        "restaurant_locations",
        sa.Column(
            "google_pay_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "restaurant_locations",
        sa.Column(
            "razorpay_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "restaurant_locations",
        sa.Column(
            "card_payment_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "restaurant_locations",
        sa.Column(
            "cash_on_delivery_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.execute("ALTER TYPE payment_status ADD VALUE IF NOT EXISTS 'COD'")
    payment_method_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "orders",
        sa.Column(
            "payment_method",
            payment_method_enum,
            nullable=False,
            server_default="COD",
        ),
    )
    op.create_index("ix_orders_payment_method", "orders", ["payment_method"])


def downgrade() -> None:
    op.drop_index("ix_orders_payment_method", table_name="orders")
    op.drop_column("orders", "payment_method")
    payment_method_enum.drop(op.get_bind(), checkfirst=True)
    op.drop_column("restaurant_locations", "cash_on_delivery_enabled")
    op.drop_column("restaurant_locations", "card_payment_enabled")
    op.drop_column("restaurant_locations", "razorpay_enabled")
    op.drop_column("restaurant_locations", "google_pay_enabled")

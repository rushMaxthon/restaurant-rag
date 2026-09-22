"""what a restaurant charges in

Revision ID: 0065_restaurant_currency
Revises: 0064_restaurant_storefront
Create Date: 2026-09-18 00:00:00.000000

`payment_currency` has been one global setting since the platform served one
restaurant. It stopped being true the moment a Surat dhokla shop was onboarded
beside a Bangkok noodle bar: the menu is priced in rupees and every price
rendered as "$35.00" — the right number under the wrong symbol, which reads as
a price a customer could agree to.

Backfilled from the deployment's existing `payment_currency` rather than left
null, so every restaurant that exists today keeps charging exactly what it
charged yesterday. A restaurant onboarded after this inherits the same default
until an administrator changes it.

`orders.currency` is untouched. It is stamped per order and read by every
payment path already, which is what makes a currency change safe: old orders
keep the currency they were actually charged in.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0065_restaurant_currency"
down_revision = "0064_restaurant_storefront"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("restaurants")}

    if "currency" not in existing:
        op.add_column(
            "restaurants",
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="USD"),
        )
        # Whatever this deployment has been charging, so nothing reprices.
        from app.config import get_settings

        current = (get_settings().payment_currency or "USD").strip().upper()[:3] or "USD"
        op.execute(sa.text("UPDATE restaurants SET currency = :code").bindparams(code=current))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "currency" in {column["name"] for column in inspector.get_columns("restaurants")}:
        op.drop_column("restaurants", "currency")

"""Turn cash on delivery off at every location: this product is card-only.

`restaurant_locations.cash_on_delivery_enabled` defaulted to true and every one
of the 18 rows carried it, which disagreed with the business — there is no cash
option — and with the new `enable_cash_on_delivery` setting. Two sources of
truth pointing opposite ways is how a customer ends up offered a payment method
the restaurant will not honour.

Revision ID: 0056_disable_cash_on_delivery
Revises: 0055_menu_item_trigram_search
"""

from alembic import op
import sqlalchemy as sa

revision = "0056_disable_cash_on_delivery"
down_revision = "0055_menu_item_trigram_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "restaurant_locations",
        "cash_on_delivery_enabled",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.false(),
    )
    op.execute("UPDATE restaurant_locations SET cash_on_delivery_enabled = false")


def downgrade() -> None:
    op.alter_column(
        "restaurant_locations",
        "cash_on_delivery_enabled",
        existing_type=sa.Boolean(),
        existing_nullable=False,
        server_default=sa.true(),
    )
    op.execute("UPDATE restaurant_locations SET cash_on_delivery_enabled = true")

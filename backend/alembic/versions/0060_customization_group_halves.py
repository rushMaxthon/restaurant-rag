"""Let a customization group be split across halves of an item.

Half-and-half pizza: pepperoni on one side, mushroom on the other. The choice
of WHICH half lives on the order line, not here; this flag is the owner saying
the kitchen can split this group at all.

Off by default, and deliberately so. Most groups have no halves — a spice
level, a crust, a drink size — and a kitchen that cannot split an item must not
be sent an order claiming it can. Every existing group therefore keeps exactly
the behaviour it has today until someone turns this on.

Revision ID: 0060_customization_group_halves
Revises: 0059_orders_currency_usd
"""

from alembic import op
import sqlalchemy as sa

revision = "0060_customization_group_halves"
down_revision = "0059_orders_currency_usd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "menu_item_customization_groups",
        sa.Column(
            "supports_halves",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("menu_item_customization_groups", "supports_halves")

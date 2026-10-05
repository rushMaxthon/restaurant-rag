"""Demo restaurants: kept, and left out of what the platform admin reads.

`restaurants.is_demo`. The shared database carries seven restaurants seeded on
2026-09-13 to develop against, priced in Canadian dollars, beside the real
Indian kitchens. Deleting them would break the Bangkok Bowl app client and its
WhatsApp setup, which still point at one; leaving them in made every platform
total add dollars to rupees under a "$". The flag lets the admin's
cross-restaurant views leave them out while anything that names one still
answers.

Additive, false by default, guarded like `0075` to `0081`. Which restaurants
are demo is data, not schema, so it is set by hand rather than here: a fresh
environment has no seeded demo and should mark none.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0082_restaurant_is_demo"
down_revision = "0081_delivery_details"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    if "is_demo" not in _columns("restaurants"):
        op.add_column(
            "restaurants",
            sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    if "is_demo" in _columns("restaurants"):
        op.drop_column("restaurants", "is_demo")

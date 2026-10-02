"""what a restaurant says about itself, beyond a hero line

Revision ID: 0073_restaurant_brand
Revises: 0072_order_charges
Create Date: 2026-10-02 00:00:00.000000

A storefront for a single restaurant is that restaurant's website, and a
website that opens on a menu and ends at a menu is a form. What is missing is
the part a customer reads to decide whether to trust a kitchen they have not
ordered from: who this is, what they are known for, what they will and will not
do, and the handful of questions everybody asks before a first order.

That content is structured rather than a sentence — headed sections, and a list
of questions with answers — so it does not fit `restaurants.storefront`, which
is a flat map of capped strings.

**It gets its own column rather than a new key in that one**, and the reason is
worth stating because the shortcut looks safe. `resolve_storefront` rebuilds
what it stores from an allowlist: any key it does not know about is dropped on
the next save. Brand content parked in that JSONB would survive until the
first time an owner edited their page title on another screen, and then vanish
with no error — the same class of silent whole-object loss that
`PATCH /profile/me` was just fixed for. A separate column cannot be reached by
that code path at all.

Empty is the normal state and stays empty. Unlike the copy in `storefront`,
nothing here is derived from the restaurant's name or city: a platform-written
"Commitment to Quality" paragraph published under a real business's name is a
claim nobody at that business made. The storefront renders nothing until the
owner writes something.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0073_restaurant_brand"
down_revision = "0072_order_charges"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    # Guarded like 0069-0072: the shared development database follows another
    # branch's chain and may already carry this.
    columns = {column["name"] for column in inspector.get_columns("restaurants")}
    if "brand" in columns:
        return

    op.add_column(
        "restaurants",
        sa.Column(
            "brand",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("restaurants")}
    if "brand" not in columns:
        return
    op.drop_column("restaurants", "brand")

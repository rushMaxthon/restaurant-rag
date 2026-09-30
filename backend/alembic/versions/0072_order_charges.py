"""what a customer is actually charged, itemised

Revision ID: 0072_order_charges
Revises: 0071_branch_geocode_confidence
Create Date: 2026-09-30 00:00:00.000000

The bill was a subtotal, a delivery fee and a flat 5% tax written into
`services/orders.py`. That is a placeholder rather than a bill, and it was wrong
in both directions: a restaurant that packages its food paid for the boxes out
of its margin, and the platform earned nothing per order.

Four figures move onto the branch, beside the delivery fee and minimum order
that already live there, and an operator sets them.

**Every default reproduces exactly what was charged before** — 5% on food,
nothing else — so this changes no existing restaurant's prices until somebody
deliberately edits them. `tax_percent` defaults to 5.00 for that reason and not
because five is right anywhere in particular.

The order gains its own copies, because a bill has to keep saying the same thing
a year later. Reading today's rates off the branch to re-render a past receipt
would silently restate it every time the restaurant changed a number.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0072_order_charges"
down_revision = "0071_branch_geocode_confidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    # Guarded like 0069-0071: the shared development database follows another
    # branch's chain, so these may already exist.
    branch = {c["name"] for c in inspector.get_columns("restaurant_locations")}
    for name, default in (
        # The restaurant's charge for boxes and bags. Flat, not per item: it is
        # what the restaurant says it costs, not something to be derived.
        ("packaging_fee", "0.00"),
        # What the platform takes per order. Inclusive of its own tax, so it is
        # never taxed again downstream.
        ("platform_fee", "0.00"),
    ):
        if name not in branch:
            op.add_column(
                "restaurant_locations",
                sa.Column(
                    name, sa.Numeric(10, 2), nullable=False, server_default=default
                ),
            )
    # Percent, not a fraction: an operator types 5 and 18, which is how the
    # rates are written on every invoice they will compare this against.
    if "tax_percent" not in branch:
        op.add_column(
            "restaurant_locations",
            sa.Column("tax_percent", sa.Numeric(5, 2), nullable=False, server_default="5.00"),
        )
    if "delivery_tax_percent" not in branch:
        op.add_column(
            "restaurant_locations",
            sa.Column(
                "delivery_tax_percent", sa.Numeric(5, 2), nullable=False, server_default="0.00"
            ),
        )

    # The order keeps its own copies. `tax_amount` already exists and keeps its
    # meaning — everything that is neither the food nor the delivery — so these
    # are the parts of it, not additions to the total.
    order = {c["name"] for c in inspector.get_columns("orders")}
    for name in ("packaging_fee", "platform_fee", "food_tax_amount", "delivery_tax_amount"):
        if name not in order:
            op.add_column(
                "orders",
                sa.Column(name, sa.Numeric(10, 2), nullable=False, server_default="0.00"),
            )


def downgrade() -> None:
    for name in ("delivery_tax_amount", "food_tax_amount", "platform_fee", "packaging_fee"):
        op.drop_column("orders", name)
    for name in ("delivery_tax_percent", "tax_percent", "platform_fee", "packaging_fee"):
        op.drop_column("restaurant_locations", name)

"""a restaurant's own words on its own website

Revision ID: 0064_restaurant_storefront
Revises: 0063_app_client_lifecycle_note
Create Date: 2026-09-18 00:00:00.000000

Page title, meta description and hero copy were string literals in the
customer web app, so every tenant onboarded inherited Bangkok Bowl's
marketing — including in their search-engine listings.

Beside `restaurants.theme` and for the same reason: a restaurant's copy is its
own and its owner writes it, where `app_clients.branding` is the build
configuration an administrator set up.

Empty on every existing row on purpose. `read_storefront` derives every key
from the restaurant's own name, cuisine and city, so this migration changes
what is rendered without backfilling a single string — and a restaurant
onboarded after it reads correctly with no rows written at all.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0064_restaurant_storefront"
down_revision = "0063_app_client_lifecycle_note"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("restaurants")}

    if "storefront" not in existing:
        op.add_column(
            "restaurants",
            sa.Column(
                "storefront",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="{}",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("restaurants")}

    if "storefront" in existing:
        op.drop_column("restaurants", "storefront")

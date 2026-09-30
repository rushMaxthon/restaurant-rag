"""how much a branch's stored coordinate is worth

Revision ID: 0071_branch_geocode_confidence
Revises: 0070_geocoding
Create Date: 2026-09-30 00:00:00.000000

`restaurant_locations.latitude`/`longitude` have existed for a long time and
said nothing about where the numbers came from. That was fine while nobody read
them and became a problem the moment a courier started pricing deliveries from
them: a coordinate typed by an owner who pointed at their own front door and a
coordinate derived from a PIN code that spans several kilometres are not the
same fact, and they were indistinguishable.

So the precision is recorded beside the point.

Empty is deliberately NOT "unknown, assume the worst". An empty confidence with
coordinates present means a person put them there by hand, which is the most
trustworthy source available — better than any geocoder — and that is how every
existing row got its values. Only a lookup writes a confidence, and it writes
what the provider actually said.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0071_branch_geocode_confidence"
down_revision = "0070_geocoding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Guarded like 0069 and 0070: the shared development database is on another
    # branch's chain, so this column may already be there.
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("restaurant_locations")}
    if "geocode_confidence" not in columns:
        op.add_column(
            "restaurant_locations",
            sa.Column(
                "geocode_confidence",
                sa.String(length=16),
                nullable=False,
                server_default="",
            ),
        )


def downgrade() -> None:
    op.drop_column("restaurant_locations", "geocode_confidence")

"""where addresses actually are

Revision ID: 0070_geocoding
Revises: 0069_order_deliveries
Create Date: 2026-09-30 00:00:00.000000

A courier prices a trip between two POINTS. Until now this app had no way to
turn an address into one: branches have `latitude`/`longitude` columns that
nobody fills in, and a customer's address was free text with nowhere to put a
coordinate at all. So every delivery quote priced the same stand-in trip — a
real price for a journey nobody was taking.

Two things land here.

`user_saved_addresses` gains coordinates and a confidence. Filled when the
customer picks their address from the autocomplete, which means the point is
the one the map provider holds for that building rather than an interpretation
of typed text. This is the row that makes a repeat order cost nothing: the
coordinate is already there, and no geocoder is called at all.

`geocode_cache` remembers every other lookup. A geocode result does not change,
so a repeat call is wasted — paid, with Google, and a step toward a block under
OpenStreetMap's usage policy, which requires caching outright. A NULL latitude
in that table is a remembered MISS rather than an empty row, because an address
that would not resolve today will not resolve on the next page load either, and
re-asking every time is how a quota disappears quietly.

Both are additive and nullable. Nothing reads them until an address has been
located, so this changes no existing order.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0070_geocoding"
down_revision = "0069_order_deliveries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    # Guarded the same way 0069 is, and for the same reason: the shared
    # development database is on another branch's chain, so these objects may
    # have been created on it directly. An unguarded statement would turn the
    # eventual `alembic merge` into an outage over a column that already
    # exists.
    saved = {column["name"] for column in inspector.get_columns("user_saved_addresses")}
    if "latitude" not in saved:
        op.add_column("user_saved_addresses", sa.Column("latitude", sa.Float(), nullable=True))
    if "longitude" not in saved:
        op.add_column("user_saved_addresses", sa.Column("longitude", sa.Float(), nullable=True))
    if "geocode_confidence" not in saved:
        op.add_column(
            "user_saved_addresses",
            sa.Column(
                "geocode_confidence",
                sa.String(length=16),
                nullable=False,
                server_default="",
            ),
        )

    if "geocode_cache" not in inspector.get_table_names():
        op.create_table(
            "geocode_cache",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            # Truncated SHA-256 of the normalised address text, not the text
            # itself: this column is indexed and an address can be 300 chars.
            sa.Column("fingerprint", sa.String(length=32), nullable=False, unique=True),
            # Kept so the table can be read by eye when a quote looks wrong.
            sa.Column("query_text", sa.String(length=500), nullable=False, server_default=""),
            # NULL means "looked up, nothing found" — see the note above.
            sa.Column("latitude", sa.Float(), nullable=True),
            sa.Column("longitude", sa.Float(), nullable=True),
            sa.Column("confidence", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("provider", sa.String(length=32), nullable=False, server_default=""),
            sa.Column("matched", sa.String(length=500), nullable=False, server_default=""),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        op.create_index("ix_geocode_cache_fingerprint", "geocode_cache", ["fingerprint"])

    # Deny by default, matching every other table in this database. This one
    # holds no personal data on its own, but an address plus a coordinate is
    # exactly the pair worth not publishing, and the anon key is inside every
    # client app. The FastAPI backend connects as the table owner and is
    # unaffected.
    op.execute("ALTER TABLE public.geocode_cache ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_geocode_cache_fingerprint", table_name="geocode_cache")
    op.drop_table("geocode_cache")
    op.drop_column("user_saved_addresses", "geocode_confidence")
    op.drop_column("user_saved_addresses", "longitude")
    op.drop_column("user_saved_addresses", "latitude")

"""how a restaurant reaches each channel, and how a public post gets credit

Revision ID: 0070_channel_connections
Revises: 0069_campaign_recipients
Create Date: 2026-09-21 00:00:00.000000

Two additions, both required before any channel but push can send.

**`restaurant_channel_connections`.** Everything a send needs that is not the
campaign: the WhatsApp number to send from, the Instagram account to post as,
the sender id the telecom operator approved. Per restaurant, because it *is*
per restaurant — two brands on this platform send from two different numbers
and a settings value cannot hold both.

Absence of a row means the channel is not connected, so there is no
NOT_CONNECTED status: a status column that can disagree with the existence of
the row it sits on is a bug waiting to be written. Push gets no row at all —
its credentials are the platform's Firebase service account, shared by every
restaurant, and a per-restaurant connection for it would let an owner
disconnect the channel their order notifications ride on.

`credentials` is ordinary JSONB, not encrypted at rest. It is excluded from
every response schema, the database is reachable only by the backend, and RLS
denies the anon key — the same posture as every other secret here. A
deployment needing envelope encryption adds it in one place.

**`orders.marketing_promo_code`.** The only thing that can attribute a public
post to an order. A push writes a recipient row and the window is measured
from it; an Instagram post is seen by people this platform has no identity
for, so there is nothing to join on. The code the customer types at checkout
is that join. No foreign key: a campaign may be deleted and the order must
keep the fact that a code was used.

RLS is enabled on the new table here rather than by hand. Every other table in
this database had it applied out of band, which is why three tables are open
right now; doing it in the migration is the only way a fresh environment comes
up closed. The backend connects as `postgres`, which owns the table and
therefore bypasses RLS — this denies the published anon key, nothing else.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0070_channel_connections"
down_revision = "0069_campaign_recipients"
branch_labels = None
depends_on = None


TABLE = "restaurant_channel_connections"

connection_status = postgresql.ENUM(
    "CONNECTED",
    "DISABLED",
    "ERROR",
    name="channel_connection_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    connection_status.create(bind, checkfirst=True)

    if TABLE not in inspector.get_table_names():
        op.create_table(
            TABLE,
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()"),
            ),
            sa.Column(
                "restaurant_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            # VARCHAR rather than a Postgres enum, matching `campaigns.goal`:
            # the channel list grows with the product, and a VARCHAR makes
            # that a code change instead of an ALTER TYPE.
            sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("status", connection_status, nullable=False, server_default="CONNECTED"),
            sa.Column(
                "config",
                postgresql.JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "credentials",
                postgresql.JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
            # Distinct from `connected_at`: a token that worked in March is
            # not a token that works today, and the owner should be told
            # which one they have.
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
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
        op.create_unique_constraint(
            "uq_channel_connection_restaurant_channel", TABLE, ["restaurant_id", "channel"]
        )
        # Every read is "this restaurant's connections", usually all of them
        # at once for the channel picker.
        op.create_index(f"ix_{TABLE}_restaurant", TABLE, ["restaurant_id"])
        op.create_index(f"ix_{TABLE}_channel", TABLE, ["channel"])
        op.create_index(f"ix_{TABLE}_status", TABLE, ["status"])

    # Deny-by-default, in the migration rather than by hand. Postgres only.
    if bind.dialect.name == "postgresql":
        op.execute(f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY")

    order_columns = {column["name"] for column in inspector.get_columns("orders")}
    if "marketing_promo_code" not in order_columns:
        op.add_column(
            "orders", sa.Column("marketing_promo_code", sa.String(32), nullable=True)
        )
        # The attribution query is "orders for this restaurant with this code
        # in this window", so the code is the selective half of it.
        op.create_index(
            "ix_orders_marketing_promo_code", "orders", ["marketing_promo_code"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    order_columns = {column["name"] for column in inspector.get_columns("orders")}
    if "marketing_promo_code" in order_columns:
        op.drop_index("ix_orders_marketing_promo_code", table_name="orders")
        op.drop_column("orders", "marketing_promo_code")

    if TABLE in inspector.get_table_names():
        op.drop_table(TABLE)
    connection_status.drop(bind, checkfirst=True)

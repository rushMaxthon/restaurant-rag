"""per-app Firebase credentials — RECONSTRUCTED from the shared database

Revision ID: 0065_app_client_push_credentials
Revises: 0064_marketing_campaign_fields
Create Date: 2026-09-21 00:00:00.000000

**This file is a reconstruction, not the original.** The shared Supabase
database carries three tables and one column from a lineage that exists in no
branch of this repository, and until now that made the whole chain
unresolvable: `alembic current` could not find the revision the database is
stamped with, so neither `current` nor `upgrade` could run against it at all,
and no new migration could be deployed.

The four revisions 0065-0068 were rebuilt by introspecting the live schema on
2026-09-21 — columns, types, defaults, primary keys, foreign keys, indexes and
enum labels — and each one creates its table only if it is missing. On the
shared database every one of them is therefore a no-op, and the point of them
is simply that the chain can be walked. On a fresh environment they reproduce
what the shared database already has, which is the first time those two things
have matched.

What this cannot reconstruct is intent: the original author's reasons, and
anything they did that left no trace in the schema (a data backfill, a
constraint later dropped). Treat these four as a bridge, not as history.

**If the real 0065-0068 are ever pushed**, alembic will refuse to start on the
duplicate revision ids for `0067_restaurant_payment_accounts` and
`0068_payment_transaction_payment_id` — loudly, which is the point. Delete
these reconstructions at that moment and keep theirs.

The table itself: one Firebase project per app client, so a white-label
restaurant app can send push from its own project rather than the
marketplace's. `credential_ref` is a pointer — a path or a secret name — and
not the service account itself, which is why it is only 500 characters and
why nothing here is encrypted.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0065_app_client_push_credentials"
down_revision = "0064_marketing_campaign_fields"
branch_labels = None
depends_on = None


TABLE = "app_client_push_credentials"

provider = postgresql.ENUM("FCM", name="push_credential_provider", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    provider.create(bind, checkfirst=True)

    if TABLE in inspector.get_table_names():
        # Already present on the shared database, which is the whole reason
        # this file exists. Nothing to do.
        return

    op.create_table(
        TABLE,
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "app_client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("app_clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", provider, nullable=False, server_default="FCM"),
        sa.Column("project_id", sa.String(255), nullable=True),
        sa.Column("credential_ref", sa.String(500), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
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
    op.create_index(f"ix_{TABLE}_app_client_id", TABLE, ["app_client_id"])
    op.create_unique_constraint(
        f"uq_{TABLE}_app_client_id_provider", TABLE, ["app_client_id", "provider"]
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE in inspector.get_table_names():
        op.drop_table(TABLE)
    provider.drop(bind, checkfirst=True)

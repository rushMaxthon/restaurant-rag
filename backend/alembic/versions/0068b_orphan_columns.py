"""five columns from the unpushed lineage — RECONSTRUCTED

Revision ID: 0068b_orphan_columns
Revises: 0068_payment_transaction_payment_id
Create Date: 2026-09-21 00:00:00.000000

The last of the reconciliation. See `0065_app_client_push_credentials` for why
these bridge revisions exist.

Comparing the shared database against a database built from this chain turned
up three tables, one column on `payment_transactions`, and then these five —
which the table-level comparison had missed entirely, because they are columns
on tables both sides already had. None of the five appears in any model in
this repository, so nothing here reads them; they belong to the same unpushed
branch as everything else in 0065-0068.

The id carries a letter rather than a number on purpose. 0069 and 0070 were
already taken by this repository's own migrations, and renumbering those a
second time to make room for a revision that only exists to paper over
somebody else's would be churn for its own sake. A non-numeric suffix also
reads correctly: this is a bridge, not a place anybody's work actually sat.

Every column is added only if absent, so this is a no-op against the shared
database and a catch-up on a fresh one.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0068b_orphan_columns"
down_revision = "0068_payment_transaction_payment_id"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    app_client_columns = _columns(inspector, "app_clients")

    # Who suspended a tenant, when, and why. All nullable: an app client that
    # has never had its status changed has nothing to record, and that is
    # different from a change with no note.
    if "status_changed_at" not in app_client_columns:
        op.add_column(
            "app_clients",
            sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "status_changed_by_user_id" not in app_client_columns:
        op.add_column(
            "app_clients",
            sa.Column(
                "status_changed_by_user_id",
                postgresql.UUID(as_uuid=True),
                # SET NULL rather than CASCADE: the fact that the status
                # changed outlives the admin who changed it.
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if "status_note" not in app_client_columns:
        op.add_column("app_clients", sa.Column("status_note", sa.String(500), nullable=True))

    restaurant_columns = _columns(inspector, "restaurants")

    # Per-restaurant currency, defaulted so every existing row has one. The
    # orders table has carried its own currency since 0059; this is the brand
    # level, which is what a storefront prices in before an order exists.
    if "currency" not in restaurant_columns:
        op.add_column(
            "restaurants",
            sa.Column(
                "currency", sa.String(3), nullable=False, server_default=sa.text("'USD'")
            ),
        )
    # Storefront presentation as one JSONB blob rather than a column per
    # setting, on the same reasoning as `campaigns.data_payload`: it is read
    # and written whole and never joined against.
    if "storefront" not in restaurant_columns:
        op.add_column(
            "restaurants",
            sa.Column(
                "storefront",
                postgresql.JSONB,
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table, column in (
        ("app_clients", "status_note"),
        ("app_clients", "status_changed_by_user_id"),
        ("app_clients", "status_changed_at"),
        ("restaurants", "storefront"),
        ("restaurants", "currency"),
    ):
        if column in _columns(inspector, table):
            op.drop_column(table, column)

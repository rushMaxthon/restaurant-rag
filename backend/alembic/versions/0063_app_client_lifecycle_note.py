"""who suspended a tenant, when, and why

Revision ID: 0063_app_client_lifecycle_note
Revises: 0062_app_client_domains
Create Date: 2026-09-18 00:00:00.000000

`app_clients.status` has existed since `0032` and nothing has ever written it
after creation — there was no endpoint. Adding one makes it possible to take a
paying restaurant's storefront off the air from a browser, and a status that
can change needs to carry its own provenance or the answer to "why is Dragon
Wok down" lives only in somebody's memory.

Three columns rather than an audit table. The question this has to answer is
"what state is this tenant in and why", which is about the current state, not
about its history; a full trail of every lifecycle event is a different
feature and would be read by nobody today.

`status_changed_by_user_id` is ON DELETE SET NULL: a suspension outlives the
admin account that made it, and losing the note along with a departed
colleague's login would defeat the point of storing it.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0063_app_client_lifecycle_note"
down_revision = "0062_app_client_domains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("app_clients")}

    if "status_note" not in existing:
        op.add_column("app_clients", sa.Column("status_note", sa.String(length=500), nullable=True))
    if "status_changed_at" not in existing:
        op.add_column(
            "app_clients",
            sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "status_changed_by_user_id" not in existing:
        op.add_column(
            "app_clients",
            sa.Column(
                "status_changed_by_user_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("app_clients")}

    for column in ("status_changed_by_user_id", "status_changed_at", "status_note"):
        if column in existing:
            op.drop_column("app_clients", column)

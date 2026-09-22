"""per-restaurant feature switches — RECONSTRUCTED from the shared database

Revision ID: 0066_restaurant_capabilities
Revises: 0065_app_client_push_credentials
Create Date: 2026-09-21 00:00:00.000000

A reconstruction. See `0065_app_client_push_credentials` for why these four
revisions exist and what they can and cannot be trusted to represent.

The table: one row per restaurant per capability, keyed on the pair, so a
platform admin can switch a feature on for one tenant without a deploy.
`granted_by_user_id` is SET NULL rather than CASCADE — who granted it is
useful history, and losing the row because that admin left the company would
make the audit trail worse than useless.

This revision's id is a guess. The shared database does not record it — only
the revision it is stamped at, which is 0068 — so the number is inferred from
its position between two revisions whose ids are known. Nothing depends on
the guess being right: the stamp resolves regardless.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0066_restaurant_capabilities"
down_revision = "0065_app_client_push_credentials"
branch_labels = None
depends_on = None


TABLE = "restaurant_capabilities"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE in inspector.get_table_names():
        return

    op.create_table(
        TABLE,
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("capability_key", sa.String(64), primary_key=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "granted_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.String(500), nullable=True),
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
    # "Who has this capability" is asked across tenants, so the key leads.
    op.create_index(f"ix_{TABLE}_key", TABLE, ["capability_key"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE in inspector.get_table_names():
        op.drop_table(TABLE)

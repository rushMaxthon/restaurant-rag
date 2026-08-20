"""add push notification device tokens

Revision ID: 0021_push_notifications
Revises: 0020_user_saved_addresses
Create Date: 2026-06-05 18:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0021_push_notifications"
down_revision = "0020_user_saved_addresses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_device_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("installation_id", sa.String(length=128), nullable=False),
        sa.Column("fcm_token", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("device_name", sa.String(length=255), nullable=True),
        sa.Column("app_version", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "installation_id", name="uq_user_device_tokens_user_installation"),
    )
    op.create_index("ix_user_device_tokens_user_id", "user_device_tokens", ["user_id"], unique=False)
    op.create_index("ix_user_device_tokens_user_active", "user_device_tokens", ["user_id", "is_active"], unique=False)
    op.create_index("ix_user_device_tokens_fcm_token", "user_device_tokens", ["fcm_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_user_device_tokens_fcm_token", table_name="user_device_tokens")
    op.drop_index("ix_user_device_tokens_user_active", table_name="user_device_tokens")
    op.drop_index("ix_user_device_tokens_user_id", table_name="user_device_tokens")
    op.drop_table("user_device_tokens")

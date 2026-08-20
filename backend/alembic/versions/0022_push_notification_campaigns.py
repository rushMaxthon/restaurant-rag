"""add push notification campaigns and delivery events

Revision ID: 0022_push_notification_campaigns
Revises: 0021_push_notifications
Create Date: 2026-06-05 18:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0022_push_notification_campaigns"
down_revision = "0021_push_notifications"
branch_labels = None
depends_on = None


notification_delivery_type = postgresql.ENUM(
    "INSTANT",
    "SCHEDULED",
    name="notification_delivery_type",
    create_type=False,
)
notification_audience = postgresql.ENUM(
    "ALL_USERS",
    "CUSTOMERS",
    "OWNERS",
    "ADMINS",
    "SPECIFIC_USER",
    name="notification_audience",
    create_type=False,
)
notification_campaign_status = postgresql.ENUM(
    "DRAFT",
    "SCHEDULED",
    "SENDING",
    "SENT",
    "FAILED",
    "CANCELLED",
    name="notification_campaign_status",
    create_type=False,
)
notification_event_type = postgresql.ENUM(
    "SENT",
    "DELIVERED",
    "OPENED",
    "FAILED",
    name="notification_event_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    notification_audience.create(bind, checkfirst=True)
    notification_delivery_type.create(bind, checkfirst=True)
    notification_campaign_status.create(bind, checkfirst=True)
    notification_event_type.create(bind, checkfirst=True)

    op.create_table(
        "push_notification_campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("specific_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("audience", notification_audience, nullable=False),
        sa.Column(
            "delivery_type",
            notification_delivery_type,
            nullable=False,
            server_default=sa.text("'INSTANT'"),
        ),
        sa.Column(
            "status",
            notification_campaign_status,
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column("template_key", sa.String(length=64), nullable=True),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("deep_link", sa.String(length=255), nullable=True),
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'Asia/Kolkata'"),
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("estimated_recipient_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opened_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("data_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["specific_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_push_notification_campaigns_created_by_user_id", "push_notification_campaigns", ["created_by_user_id"], unique=False)
    op.create_index("ix_push_notification_campaigns_specific_user_id", "push_notification_campaigns", ["specific_user_id"], unique=False)
    op.create_index("ix_push_notification_campaigns_restaurant_id", "push_notification_campaigns", ["restaurant_id"], unique=False)
    op.create_index("ix_push_notification_campaigns_audience", "push_notification_campaigns", ["audience"], unique=False)
    op.create_index("ix_push_notification_campaigns_status", "push_notification_campaigns", ["status"], unique=False)

    op.create_table(
        "push_notification_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("installation_id", sa.String(length=128), nullable=True),
        sa.Column("message_id", sa.String(length=255), nullable=True),
        sa.Column("event_type", notification_event_type, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["campaign_id"], ["push_notification_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_push_notification_events_campaign_id", "push_notification_events", ["campaign_id"], unique=False)
    op.create_index("ix_push_notification_events_user_id", "push_notification_events", ["user_id"], unique=False)
    op.create_index("ix_push_notification_events_event_type", "push_notification_events", ["event_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_push_notification_events_event_type", table_name="push_notification_events")
    op.drop_index("ix_push_notification_events_user_id", table_name="push_notification_events")
    op.drop_index("ix_push_notification_events_campaign_id", table_name="push_notification_events")
    op.drop_table("push_notification_events")

    op.drop_index("ix_push_notification_campaigns_status", table_name="push_notification_campaigns")
    op.drop_index("ix_push_notification_campaigns_audience", table_name="push_notification_campaigns")
    op.drop_index("ix_push_notification_campaigns_restaurant_id", table_name="push_notification_campaigns")
    op.drop_index("ix_push_notification_campaigns_specific_user_id", table_name="push_notification_campaigns")
    op.drop_index("ix_push_notification_campaigns_created_by_user_id", table_name="push_notification_campaigns")
    op.drop_table("push_notification_campaigns")

    bind = op.get_bind()
    notification_event_type.drop(bind, checkfirst=True)
    notification_campaign_status.drop(bind, checkfirst=True)
    notification_delivery_type.drop(bind, checkfirst=True)
    notification_audience.drop(bind, checkfirst=True)

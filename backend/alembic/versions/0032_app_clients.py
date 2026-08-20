"""add app clients for bundle-id based multi-app support

Revision ID: 0032_app_clients
Revises: 0031_personalized_recommendation_snapshots
Create Date: 2026-08-07 12:00:00.000000

This migration is idempotent. The app client tables already exist in some
environments, so every object is created only when it is missing.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0032_app_clients"
down_revision = "0031_personalized_recommendation_snapshots"
branch_labels = None
depends_on = None


app_mode = postgresql.ENUM(
    "MARKETPLACE",
    "SINGLE_RESTAURANT",
    name="app_mode",
    create_type=False,
)
app_client_status = postgresql.ENUM(
    "ACTIVE",
    "SUSPENDED",
    "OFFBOARDED",
    name="app_client_status",
    create_type=False,
)
app_client_platform = postgresql.ENUM(
    "IOS",
    "ANDROID",
    name="app_client_platform",
    create_type=False,
)
app_client_environment = postgresql.ENUM(
    "PROD",
    "STAGING",
    name="app_client_environment",
    create_type=False,
)
push_credential_provider = postgresql.ENUM(
    "FCM",
    name="push_credential_provider",
    create_type=False,
)

ENUM_TYPES = (
    app_mode,
    app_client_status,
    app_client_platform,
    app_client_environment,
    push_credential_provider,
)


def _existing_tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in ENUM_TYPES:
        enum_type.create(bind, checkfirst=True)

    existing_tables = _existing_tables()

    if "app_clients" not in existing_tables:
        op.create_table(
            "app_clients",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=False),
            sa.Column("app_mode", app_mode, nullable=False),
            sa.Column("restaurant_id", sa.UUID(), nullable=True),
            sa.Column("status", app_client_status, server_default="ACTIVE", nullable=False),
            sa.Column("order_number_prefix", sa.String(length=8), server_default="MP", nullable=False),
            sa.Column(
                "branding",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="{}",
                nullable=False,
            ),
            sa.Column(
                "config",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="{}",
                nullable=False,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(
                ["restaurant_id"],
                ["restaurants.id"],
                name=op.f("fk_app_clients_restaurant_id_restaurants"),
                ondelete="RESTRICT",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_app_clients")),
        )
        op.create_index(op.f("ix_app_clients_key"), "app_clients", ["key"], unique=True)
        op.create_index(op.f("ix_app_clients_app_mode"), "app_clients", ["app_mode"], unique=False)
        op.create_index(op.f("ix_app_clients_status"), "app_clients", ["status"], unique=False)
        op.create_index(op.f("ix_app_clients_restaurant_id"), "app_clients", ["restaurant_id"], unique=False)

    if "app_client_identifiers" not in existing_tables:
        op.create_table(
            "app_client_identifiers",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("app_client_id", sa.UUID(), nullable=False),
            sa.Column("platform", app_client_platform, nullable=False),
            sa.Column("identifier", sa.String(length=255), nullable=False),
            sa.Column("environment", app_client_environment, server_default="PROD", nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(
                ["app_client_id"],
                ["app_clients.id"],
                name=op.f("fk_app_client_identifiers_app_client_id_app_clients"),
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_app_client_identifiers")),
            sa.UniqueConstraint(
                "platform",
                "identifier",
                "environment",
                name="uq_app_client_identifiers_platform_identifier_environment",
            ),
        )
        op.create_index(
            op.f("ix_app_client_identifiers_app_client_id"),
            "app_client_identifiers",
            ["app_client_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_app_client_identifiers_identifier"),
            "app_client_identifiers",
            ["identifier"],
            unique=False,
        )

    if "app_client_order_sequences" not in existing_tables:
        op.create_table(
            "app_client_order_sequences",
            sa.Column("app_client_id", sa.UUID(), nullable=False),
            sa.Column("last_value", sa.BigInteger(), server_default="0", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(
                ["app_client_id"],
                ["app_clients.id"],
                name=op.f("fk_app_client_order_sequences_app_client_id_app_clients"),
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("app_client_id", name=op.f("pk_app_client_order_sequences")),
        )

    if "app_client_push_credentials" not in existing_tables:
        op.create_table(
            "app_client_push_credentials",
            sa.Column("id", sa.UUID(), nullable=False),
            sa.Column("app_client_id", sa.UUID(), nullable=False),
            sa.Column("provider", push_credential_provider, server_default="FCM", nullable=False),
            sa.Column("project_id", sa.String(length=255), nullable=True),
            sa.Column("credential_ref", sa.String(length=500), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.ForeignKeyConstraint(
                ["app_client_id"],
                ["app_clients.id"],
                name=op.f("fk_app_client_push_credentials_app_client_id_app_clients"),
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_app_client_push_credentials")),
            sa.UniqueConstraint(
                "app_client_id",
                "provider",
                name="uq_app_client_push_credentials_app_client_id_provider",
            ),
        )
        op.create_index(
            op.f("ix_app_client_push_credentials_app_client_id"),
            "app_client_push_credentials",
            ["app_client_id"],
            unique=False,
        )


def downgrade() -> None:
    existing_tables = _existing_tables()

    for table_name in (
        "app_client_push_credentials",
        "app_client_order_sequences",
        "app_client_identifiers",
        "app_clients",
    ):
        if table_name in existing_tables:
            op.drop_table(table_name)

    bind = op.get_bind()
    for enum_type in ENUM_TYPES:
        enum_type.drop(bind, checkfirst=True)

"""scope user identity by app client, and add per-app columns to user-owned tables

Revision ID: 0036_user_token_version
Revises: 0032_app_clients
Create Date: 2026-08-08 12:00:00.000000

This revision deliberately carries the id ``0036_user_token_version`` while
following ``0032_app_clients``.

Some databases were migrated by a branch whose revisions 0033-0035 never reached
this repository; those databases are stamped ``0036_user_token_version``, so every
alembic command against them fails with "Can't locate revision identified by
'0036_user_token_version'". Alembic stores only the head, so the intermediate ids
are unrecoverable. Owning that id here is what makes repo and database consistent
again, and it collapses the missing revisions into this single one.

Consequence to be aware of: if the other branch is ever merged back, its 0033-0036
files would collide with this revision id and break alembic again. They must not be.

Every step is individually guarded, because the objects already exist in the
databases described above while a fresh database has none of them. Running this
twice is a no-op.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0036_user_token_version"
down_revision = "0032_app_clients"
branch_labels = None
depends_on = None


push_credential_provider = postgresql.ENUM(
    "FCM",
    name="push_credential_provider",
    create_type=False,
)

# Tables that gained an ``app_client_id``. The second element is the column
# referencing ``users.id``, or None when the table has no user column and so
# needs no composite foreign key.
APP_CLIENT_SCOPED_TABLES: tuple[tuple[str, str | None], ...] = (
    ("chat_history", "user_id"),
    ("favorites", "user_id"),
    ("generated_offer_user_matches", "user_id"),
    ("generated_offers", None),
    ("orders", "customer_id"),
    ("personalized_offer_events", "user_id"),
    ("personalized_recommendation_snapshots", "user_id"),
    ("push_notification_campaigns", None),
    ("push_notification_events", None),
    ("user_device_tokens", "user_id"),
    ("user_preferences", "user_id"),
    ("user_saved_addresses", "user_id"),
)

# Postgres truncates identifiers at 63 characters; this one is stored truncated,
# so it is spelled out rather than generated to keep fresh databases identical.
TRUNCATED_FK_NAMES = {
    "personalized_recommendation_snapshots": (
        "fk_personalized_recommendation_snapshots_app_client_id__12a8"
    ),
}

DEFAULT_APP_CLIENT_KEY = "marketplace"


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _has_table(table: str) -> bool:
    return table in _inspector().get_table_names()


def _has_column(table: str, column: str) -> bool:
    if not _has_table(table):
        return False
    return column in {col["name"] for col in _inspector().get_columns(table)}


def _has_index(table: str, index: str) -> bool:
    if not _has_table(table):
        return False
    return index in {ix["name"] for ix in _inspector().get_indexes(table)}


def _has_constraint(table: str, name: str) -> bool:
    """True when any constraint of that name exists on the table."""

    if not _has_table(table):
        return False
    bind = op.get_bind()
    return bool(
        bind.scalar(
            sa.text(
                """
                SELECT 1
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                WHERE rel.relname = :table AND con.conname = :name
                """
            ),
            {"table": table, "name": name},
        )
    )


def _app_client_fk_name(table: str) -> str:
    return TRUNCATED_FK_NAMES.get(table, f"fk_{table}_app_client_id_app_clients")


def upgrade() -> None:
    bind = op.get_bind()
    push_credential_provider.create(bind, checkfirst=True)

    # --- per-app push credentials -----------------------------------------
    if not _has_table("app_client_push_credentials"):
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
                name="fk_app_client_push_credentials_app_client_id_app_clients",
                ondelete="CASCADE",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_app_client_push_credentials"),
            sa.UniqueConstraint(
                "app_client_id",
                "provider",
                name="uq_app_client_push_credentials_app_client_id_provider",
            ),
        )
        op.create_index(
            "ix_app_client_push_credentials_app_client_id",
            "app_client_push_credentials",
            ["app_client_id"],
        )

    # --- users: identity columns ------------------------------------------
    if not _has_column("users", "app_client_id"):
        op.add_column("users", sa.Column("app_client_id", sa.UUID(), nullable=True))
    if not _has_column("users", "token_version"):
        op.add_column(
            "users",
            sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
        )

    # --- guarantee a marketplace app client to own existing customers ------
    # Nothing else in the codebase creates one, and a fresh database would
    # otherwise have no app client for customer identity to resolve to.
    marketplace_id = bind.scalar(
        sa.text("SELECT id FROM app_clients WHERE key = :key"),
        {"key": DEFAULT_APP_CLIENT_KEY},
    )
    if marketplace_id is None:
        marketplace_id = bind.scalar(
            sa.text(
                """
                INSERT INTO app_clients
                    (id, key, display_name, app_mode, restaurant_id, status,
                     order_number_prefix, branding, config, created_at, updated_at)
                VALUES
                    (gen_random_uuid(), :key, 'QuickBite', 'MARKETPLACE', NULL, 'ACTIVE',
                     'MP', '{}'::jsonb, '{}'::jsonb, now(), now())
                RETURNING id
                """
            ),
            {"key": DEFAULT_APP_CLIENT_KEY},
        )
        op.execute(
            sa.text(
                """
                INSERT INTO app_client_order_sequences (app_client_id, last_value, created_at, updated_at)
                VALUES (:app_client_id, 0, now(), now())
                ON CONFLICT (app_client_id) DO NOTHING
                """
            ).bindparams(app_client_id=marketplace_id)
        )

    # --- backfill before constraining --------------------------------------
    op.execute(
        sa.text(
            "UPDATE users SET app_client_id = :app_client_id "
            "WHERE role = 'CUSTOMER' AND app_client_id IS NULL"
        ).bindparams(app_client_id=marketplace_id)
    )
    op.execute("UPDATE users SET app_client_id = NULL WHERE role <> 'CUSTOMER'")

    # --- users: replace platform-wide uniqueness with per-app uniqueness ----
    for legacy in ("users_email_key", "uq_users_email", "users_phone_number_key", "uq_users_phone_number"):
        if _has_constraint("users", legacy):
            op.drop_constraint(legacy, "users", type_="unique")

    # ix_users_email was created UNIQUE by 0001; it must become a plain index.
    if _has_index("users", "ix_users_email"):
        unique_email_index = bind.scalar(
            sa.text(
                "SELECT indexdef LIKE 'CREATE UNIQUE%' FROM pg_indexes "
                "WHERE tablename = 'users' AND indexname = 'ix_users_email'"
            )
        )
        if unique_email_index:
            op.drop_index("ix_users_email", table_name="users")
            op.create_index("ix_users_email", "users", ["email"], unique=False)
    else:
        op.create_index("ix_users_email", "users", ["email"], unique=False)

    if not _has_constraint("users", "uq_users_id_app_client_id"):
        op.create_unique_constraint("uq_users_id_app_client_id", "users", ["id", "app_client_id"])

    if not _has_constraint("users", "fk_users_app_client_id_app_clients"):
        op.create_foreign_key(
            "fk_users_app_client_id_app_clients",
            "users",
            "app_clients",
            ["app_client_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    if not _has_constraint("users", "ck_users_app_client_scope_matches_role"):
        op.create_check_constraint(
            "app_client_scope_matches_role",
            "users",
            "(role = 'CUSTOMER' AND app_client_id IS NOT NULL) "
            "OR (role <> 'CUSTOMER' AND app_client_id IS NULL)",
        )

    if not _has_index("users", "ix_users_app_client_id"):
        op.create_index("ix_users_app_client_id", "users", ["app_client_id"])

    # Partial and expression indexes cannot be expressed via op.create_index.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_app_client_id_email_customer "
        "ON users (app_client_id, lower(email)) WHERE role = 'CUSTOMER'"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_app_client_id_phone_number_customer "
        "ON users (app_client_id, phone_number) "
        "WHERE role = 'CUSTOMER' AND phone_number IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_email_platform "
        "ON users (lower(email)) WHERE role IN ('ADMIN', 'OWNER')"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_phone_number_platform "
        "ON users (phone_number) "
        "WHERE role IN ('ADMIN', 'OWNER') AND phone_number IS NOT NULL"
    )

    # --- user-owned tables gain the owning app client ----------------------
    for table, user_column in APP_CLIENT_SCOPED_TABLES:
        if not _has_table(table):
            continue

        if not _has_column(table, "app_client_id"):
            op.add_column(table, sa.Column("app_client_id", sa.UUID(), nullable=True))

        index_name = f"ix_{table}_app_client_id"
        if not _has_index(table, index_name):
            op.create_index(index_name, table, ["app_client_id"])

        fk_name = _app_client_fk_name(table)
        if not _has_constraint(table, fk_name):
            op.create_foreign_key(
                fk_name,
                table,
                "app_clients",
                ["app_client_id"],
                ["id"],
                ondelete="RESTRICT",
            )

        # The composite key is what stops a row referencing a user from another
        # app. It is MATCH SIMPLE, so rows with a NULL app_client_id are exempt.
        if user_column is not None:
            composite_name = f"fk_{table}_{'customer' if user_column == 'customer_id' else 'user'}_app_client_users"
            if not _has_constraint(table, composite_name):
                op.create_foreign_key(
                    composite_name,
                    table,
                    "users",
                    [user_column, "app_client_id"],
                    ["id", "app_client_id"],
                    ondelete="CASCADE",
                )

    # --- per-app order numbering ------------------------------------------
    if _has_table("orders"):
        if not _has_column("orders", "order_number"):
            op.add_column("orders", sa.Column("order_number", sa.String(length=32), nullable=True))
        if not _has_index("orders", "ix_orders_order_number"):
            op.create_index("ix_orders_order_number", "orders", ["order_number"])
        # A unique constraint rather than a bare unique index, to match the
        # databases that already ran the original revisions.
        if not _has_constraint("orders", "uq_orders_app_client_id_order_number"):
            op.create_unique_constraint(
                "uq_orders_app_client_id_order_number",
                "orders",
                ["app_client_id", "order_number"],
            )


def downgrade() -> None:
    """Guarded teardown.

    Dropping ``users.app_client_id`` discards which app every customer belongs
    to, and that mapping cannot be reconstructed. Only run this on a database
    you are willing to lose per-app identity on.
    """

    if _has_constraint("orders", "uq_orders_app_client_id_order_number"):
        op.drop_constraint("uq_orders_app_client_id_order_number", "orders", type_="unique")
    if _has_index("orders", "ix_orders_order_number"):
        op.drop_index("ix_orders_order_number", table_name="orders")
    if _has_column("orders", "order_number"):
        op.drop_column("orders", "order_number")

    for table, user_column in APP_CLIENT_SCOPED_TABLES:
        if not _has_table(table):
            continue
        if user_column is not None:
            composite_name = f"fk_{table}_{'customer' if user_column == 'customer_id' else 'user'}_app_client_users"
            if _has_constraint(table, composite_name):
                op.drop_constraint(composite_name, table, type_="foreignkey")
        fk_name = _app_client_fk_name(table)
        if _has_constraint(table, fk_name):
            op.drop_constraint(fk_name, table, type_="foreignkey")
        index_name = f"ix_{table}_app_client_id"
        if _has_index(table, index_name):
            op.drop_index(index_name, table_name=table)
        if _has_column(table, "app_client_id"):
            op.drop_column(table, "app_client_id")

    for index_name in (
        "uq_users_app_client_id_email_customer",
        "uq_users_app_client_id_phone_number_customer",
        "uq_users_email_platform",
        "uq_users_phone_number_platform",
    ):
        op.execute(f"DROP INDEX IF EXISTS {index_name}")

    if _has_index("users", "ix_users_app_client_id"):
        op.drop_index("ix_users_app_client_id", table_name="users")
    if _has_constraint("users", "ck_users_app_client_scope_matches_role"):
        op.drop_constraint("ck_users_app_client_scope_matches_role", "users", type_="check")
    if _has_constraint("users", "fk_users_app_client_id_app_clients"):
        op.drop_constraint("fk_users_app_client_id_app_clients", "users", type_="foreignkey")
    if _has_constraint("users", "uq_users_id_app_client_id"):
        op.drop_constraint("uq_users_id_app_client_id", "users", type_="unique")

    if _has_index("users", "ix_users_email"):
        op.drop_index("ix_users_email", table_name="users")
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    if _has_column("users", "token_version"):
        op.drop_column("users", "token_version")
    if _has_column("users", "app_client_id"):
        op.drop_column("users", "app_client_id")

    if _has_table("app_client_push_credentials"):
        op.drop_table("app_client_push_credentials")
    push_credential_provider.drop(op.get_bind(), checkfirst=True)

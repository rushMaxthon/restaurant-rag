"""marketing consent, opt-out by default

Revision ID: 0063_marketing_consent
Revises: 0062_app_client_domains
Create Date: 2026-09-19 00:00:00.000000

Consent is opt-out: the column defaults true and every existing customer
backfills to true. That is a deliberate product decision, not a convenience.
The alternative - defaulting false and treating the whole existing base as
unreachable - would have made the Marketing Hub ship into a platform where
every campaign fails its "nobody in this audience can be reached" check on day
one, and it would have discarded a consent posture customers were already
signed up under.

`marketing_opt_in_changed_at` stays null on the backfill on purpose. Null means
"never expressed a preference", which is a different fact from an explicit
opt-in and is the first thing anyone auditing consent will ask for. Writing
now() here would have manufactured a decision nobody made.

Transactional pushes do not read either column.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0063_marketing_consent"
down_revision = "0062_app_client_domains"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = {column["name"] for column in sa.inspect(bind).get_columns("users")}

    if "marketing_opt_in" not in existing:
        op.add_column(
            "users",
            sa.Column(
                "marketing_opt_in",
                sa.Boolean(),
                nullable=False,
                server_default="true",
            ),
        )

    if "marketing_opt_in_changed_at" not in existing:
        op.add_column(
            "users",
            sa.Column(
                "marketing_opt_in_changed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )

    # Reach estimation runs this predicate on every campaign draft, against the
    # whole customer base of a tenant, while the owner is still typing. The
    # partial index covers only the rows a marketing send can ever touch.
    existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("users")}
    if "ix_users_marketing_reachable" not in existing_indexes:
        op.create_index(
            "ix_users_marketing_reachable",
            "users",
            ["app_client_id"],
            unique=False,
            postgresql_where=sa.text(
                "marketing_opt_in = true AND is_active = true AND role = 'CUSTOMER'"
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("users")}
    if "ix_users_marketing_reachable" in existing_indexes:
        op.drop_index("ix_users_marketing_reachable", table_name="users")

    existing = {column["name"] for column in sa.inspect(bind).get_columns("users")}
    if "marketing_opt_in_changed_at" in existing:
        op.drop_column("users", "marketing_opt_in_changed_at")
    if "marketing_opt_in" in existing:
        op.drop_column("users", "marketing_opt_in")

"""a kitchen account, pinned to the restaurant and branch it cooks for

Revision ID: 0071_kitchen_staff
Revises: 0070_channel_connections
Create Date: 2026-09-22 00:00:00.000000

The order board needed a login that is not the owner's.

Advancing an order was `require_owner`, so the only way to put a screen in a
kitchen was to leave the owner signed in on it — the same token that edits the
menu, spends money on marketing campaigns and reads revenue, on a tablet on a
wall that anyone walking past can pick up. This adds the narrow role instead.

**KITCHEN is platform staff.** `ck_users_app_client_scope_matches_role` reads
`role <> 'CUSTOMER' AND app_client_id IS NULL`, so the new role lands on the
staff side of it with no change. That is correct: a cook belongs to a
restaurant, not to one of its consumer apps.

**But the uniqueness indexes did need changing.** `uq_users_email_platform`
and `uq_users_phone_number_platform` were `WHERE role IN ('ADMIN', 'OWNER')`,
so a KITCHEN account would have had no uniqueness on its email at ALL — two
of them could share one address and `authenticate_user` would have had two
rows to choose between. They are recreated here to include the new role.

**The assignment is two columns, and the database enforces the pairing.**
`staff_restaurant_id` is where the account works; `staff_restaurant_location_id`
is the single branch it sees, or NULL for all of them.
`ck_users_kitchen_assignment` makes both halves exhaustive — a KITCHEN row
without a restaurant is rejected, and so is any other role carrying either
column. The alternative was a nullable column and a service-layer check, and
a kitchen account that had somehow lost its restaurant would then have read
every order on the platform.

The branch is tied to the restaurant by a COMPOSITE foreign key onto
`(id, restaurant_id)` rather than a plain one onto `id`, which is why
`uq_restaurant_locations_id_restaurant_id` is created first. A plain key would
happily accept a branch belonging to somebody else's restaurant; this one
cannot. It still permits `staff_restaurant_location_id IS NULL`, because a
composite foreign key with any NULL column is satisfied by default (MATCH
SIMPLE) — which is exactly the "every branch" case.

**Why `autocommit_block`.** `alembic/env.py` does not set
`transaction_per_migration`, so an `alembic upgrade` runs every pending
revision inside ONE transaction. Postgres allows `ALTER TYPE ... ADD VALUE`
inside a transaction but refuses to let the new value be USED until that
transaction commits — and the CHECK constraint below names 'KITCHEN'. Without
the autocommit block this migration fails with `unsafe use of new value
"KITCHEN"`, and splitting it into two revisions would not help, because they
would share the same transaction too.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0071_kitchen_staff"
down_revision = "0070_channel_connections"
branch_labels = None
depends_on = None


PLATFORM_ROLES = "'ADMIN', 'OWNER', 'KITCHEN'"

KITCHEN_ASSIGNMENT_CHECK = (
    "(role = 'KITCHEN' AND staff_restaurant_id IS NOT NULL) "
    "OR (role <> 'KITCHEN' "
    "AND staff_restaurant_id IS NULL "
    "AND staff_restaurant_location_id IS NULL)"
)


def _constraint_names(inspector, table: str) -> set[str]:
    names = {c["name"] for c in inspector.get_check_constraints(table)}
    names |= {c["name"] for c in inspector.get_foreign_keys(table)}
    names |= {c["name"] for c in (inspector.get_unique_constraints(table) or [])}
    return {name for name in names if name}


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # Committed before anything below can name 'KITCHEN'. See the module
    # docstring — this is the whole reason the block exists.
    if is_postgres:
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'KITCHEN'")
            # Without this the audit log records every advance a cook makes as
            # SYSTEM, because `actor_for_user` has no branch to fall into.
            op.execute("ALTER TYPE order_event_actor ADD VALUE IF NOT EXISTS 'KITCHEN'")

    inspector = sa.inspect(bind)

    # The target of the composite foreign key below. `id` is already the
    # primary key, so this constraint adds no real restriction — it exists
    # only because Postgres requires a unique constraint on exactly the
    # referenced column pair.
    location_constraints = _constraint_names(inspector, "restaurant_locations")
    if "uq_restaurant_locations_id_restaurant_id" not in location_constraints:
        op.create_unique_constraint(
            "uq_restaurant_locations_id_restaurant_id",
            "restaurant_locations",
            ["id", "restaurant_id"],
        )

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "staff_restaurant_id" not in user_columns:
        op.add_column(
            "users",
            sa.Column("staff_restaurant_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),
        )
    if "staff_restaurant_location_id" not in user_columns:
        op.add_column(
            "users",
            sa.Column(
                "staff_restaurant_location_id",
                sa.dialects.postgresql.UUID(as_uuid=True),
                nullable=True,
            ),
        )

    inspector = sa.inspect(bind)
    user_constraints = _constraint_names(inspector, "users")
    user_indexes = {index["name"] for index in inspector.get_indexes("users")}

    if "fk_users_staff_restaurant_id_restaurants" not in user_constraints:
        op.create_foreign_key(
            "fk_users_staff_restaurant_id_restaurants",
            "users",
            "restaurants",
            ["staff_restaurant_id"],
            ["id"],
            # RESTRICT, not CASCADE: deleting a restaurant that still has cooks
            # signed into it should fail loudly rather than silently widen
            # their scope by nulling the column the CHECK depends on.
            ondelete="RESTRICT",
        )

    if "fk_users_staff_location_matches_restaurant" not in user_constraints:
        op.create_foreign_key(
            "fk_users_staff_location_matches_restaurant",
            "users",
            "restaurant_locations",
            ["staff_restaurant_location_id", "staff_restaurant_id"],
            ["id", "restaurant_id"],
            ondelete="RESTRICT",
        )

    if "ck_users_kitchen_assignment" not in user_constraints:
        op.create_check_constraint(
            "kitchen_assignment",
            "users",
            KITCHEN_ASSIGNMENT_CHECK,
        )

    if "ix_users_staff_restaurant_id" not in user_indexes:
        op.create_index("ix_users_staff_restaurant_id", "users", ["staff_restaurant_id"])
    if "ix_users_staff_restaurant_location_id" not in user_indexes:
        op.create_index(
            "ix_users_staff_restaurant_location_id",
            "users",
            ["staff_restaurant_location_id"],
        )

    # Recreated rather than altered: Postgres has no ALTER INDEX ... SET WHERE.
    # A kitchen account had no uniqueness on its email until this ran.
    if is_postgres:
        op.execute("DROP INDEX IF EXISTS uq_users_email_platform")
        op.execute(
            "CREATE UNIQUE INDEX uq_users_email_platform "
            f"ON users (lower(email)) WHERE role IN ({PLATFORM_ROLES})"
        )
        op.execute("DROP INDEX IF EXISTS uq_users_phone_number_platform")
        op.execute(
            "CREATE UNIQUE INDEX uq_users_phone_number_platform "
            "ON users (phone_number) "
            f"WHERE role IN ({PLATFORM_ROLES}) AND phone_number IS NOT NULL"
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    inspector = sa.inspect(bind)
    user_constraints = _constraint_names(inspector, "users")
    user_indexes = {index["name"] for index in inspector.get_indexes("users")}

    if is_postgres:
        op.execute("DROP INDEX IF EXISTS uq_users_email_platform")
        op.execute(
            "CREATE UNIQUE INDEX uq_users_email_platform "
            "ON users (lower(email)) WHERE role IN ('ADMIN', 'OWNER')"
        )
        op.execute("DROP INDEX IF EXISTS uq_users_phone_number_platform")
        op.execute(
            "CREATE UNIQUE INDEX uq_users_phone_number_platform "
            "ON users (phone_number) "
            "WHERE role IN ('ADMIN', 'OWNER') AND phone_number IS NOT NULL"
        )

    if "ix_users_staff_restaurant_location_id" in user_indexes:
        op.drop_index("ix_users_staff_restaurant_location_id", table_name="users")
    if "ix_users_staff_restaurant_id" in user_indexes:
        op.drop_index("ix_users_staff_restaurant_id", table_name="users")

    if "ck_users_kitchen_assignment" in user_constraints:
        # The bare name, because alembic applies the metadata's
        # "ck_%(table_name)s_%(constraint_name)s" convention to a DROP as well
        # as to a CREATE. Passing the full name here asks Postgres to drop
        # `ck_users_ck_users_kitchen_assignment`, which does not exist.
        op.drop_constraint("kitchen_assignment", "users", type_="check")
    if "fk_users_staff_location_matches_restaurant" in user_constraints:
        op.drop_constraint("fk_users_staff_location_matches_restaurant", "users", type_="foreignkey")
    if "fk_users_staff_restaurant_id_restaurants" in user_constraints:
        op.drop_constraint("fk_users_staff_restaurant_id_restaurants", "users", type_="foreignkey")

    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "staff_restaurant_location_id" in user_columns:
        op.drop_column("users", "staff_restaurant_location_id")
    if "staff_restaurant_id" in user_columns:
        op.drop_column("users", "staff_restaurant_id")

    location_constraints = _constraint_names(inspector, "restaurant_locations")
    if "uq_restaurant_locations_id_restaurant_id" in location_constraints:
        op.drop_constraint(
            "uq_restaurant_locations_id_restaurant_id",
            "restaurant_locations",
            type_="unique",
        )

    # 'KITCHEN' is deliberately left in both enum types. Postgres cannot remove
    # a value from an enum, and the only route — recreating the type and
    # rewriting every column that uses it — would rewrite `users` and
    # `order_status_events` wholesale to undo something no row is required to
    # use. Any KITCHEN account must be deleted or re-roled before downgrading;
    # the dropped CHECK is what would otherwise have stopped it.

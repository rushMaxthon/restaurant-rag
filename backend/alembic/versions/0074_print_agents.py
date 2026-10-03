"""a print agent, its printers, and a queue of tickets

Revision ID: 0074_print_agents
Revises: 0073_restaurant_brand
Create Date: 2026-10-03 20:00:00.000000

Three tables so a kitchen printer can produce a ticket the moment a paid order
arrives, with no browser open and nobody signed in.

**`print_agents`.** One installed copy of the Windows agent. A device, not a
person, which is why it is not a `users` row: its credential sits unattended
on a PC in a restaurant for years, and it must be revocable without ending any
cook's session. Hashed token, its own `token_version`, and it can do exactly
two things over the API - read the jobs queued for its own printers and say
whether they printed.

The branch is NOT NULL here, unlike a KITCHEN account's. A null location on
`users` means "every branch of that restaurant" and is a real answer for a
cook who covers two kitchens; a printer is a physical object in one room. The
branch is tied to the restaurant by a composite foreign key onto
`(id, restaurant_id)` rather than a plain one onto `id`, for the reason
`ck_users_kitchen_assignment` gives: an agent pinned to somebody else's branch
becomes unrepresentable rather than merely unlikely.

**`printers`.** One row per printer an agent can reach, because one PC
commonly drives two - a docket printer on the kitchen wall and a bill printer
at the counter. `docket_kinds` is the routing rule and it is data, so nothing
in the agent branches on which printer it is talking to.

The transport CHECK is exhaustive: TCP demands a host and a port, WINDOWS
demands a queue name, and neither may carry the other's columns. Without it a
row could claim TCP and hold no address, and the failure would surface on the
agent at the moment an order arrived rather than when somebody saved the form.

**`print_jobs`.** The queue, which is the whole feature. An agent printing
straight off a realtime event would reprint its history on every reconnect -
the clients report a reconnect as "anything may have changed" - lose a ticket
outright whenever the printer was out of paper, and have no way to tell a
redelivery from a second order. A row per ticket answers all three.

`uq_print_jobs_auto_once` is the idempotency guarantee, and it is a database
constraint rather than service logic on purpose: a double-firing enqueue, a
replayed payment webhook or a retried Celery task physically cannot write a
second docket. Scoped to AUTO so a reprint - whose entire purpose is a second
copy - is unconstrained, and excluding FAILED so a ticket that did not print
can be queued again.

`document` holds the rendered ticket rather than being re-derived at print
time. That is deliberate and it is an audit property: a reprint reproduces
exactly what the kitchen saw, even if the order, the menu or the branch's
prices have changed since. Rendering again would quietly produce a different
ticket for the same order, and nobody would know which one the cook worked
from.

RLS is enabled on all three here rather than by hand, which `0070` established
as the only way a fresh environment comes up closed. The backend connects as
`postgres`, which owns the tables and therefore bypasses it; this denies the
published anon key and nothing else.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0074_print_agents"
down_revision = "0073_restaurant_brand"
branch_labels = None
depends_on = None


AGENTS = "print_agents"
PRINTERS = "printers"
JOBS = "print_jobs"

TRANSPORT_CHECK = (
    "(transport = 'TCP' AND host IS NOT NULL AND port IS NOT NULL"
    " AND windows_printer_name IS NULL)"
    " OR (transport = 'WINDOWS' AND windows_printer_name IS NOT NULL"
    " AND host IS NULL AND port IS NULL)"
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    is_postgres = bind.dialect.name == "postgresql"

    # Guarded for the same reason every migration here is: the shared Supabase
    # database has had tables created by hand before now, and a migration that
    # cannot be re-run against a database that already has its table is a
    # migration that strands the stamp.
    if AGENTS not in existing:
        op.create_table(
            AGENTS,
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()") if is_postgres else None,
            ),
            sa.Column(
                "restaurant_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("restaurants.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("restaurant_location_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("agent_version", sa.String(40), nullable=True),
            sa.Column("hostname", sa.String(120), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
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
            # The branch belongs to the restaurant, enforced rather than
            # trusted. See the module docstring.
            sa.ForeignKeyConstraint(
                ["restaurant_location_id", "restaurant_id"],
                ["restaurant_locations.id", "restaurant_locations.restaurant_id"],
                name="fk_print_agents_location_matches_restaurant",
                ondelete="RESTRICT",
            ),
        )
        op.create_index(f"ix_{AGENTS}_restaurant_id", AGENTS, ["restaurant_id"])
        op.create_index(
            f"ix_{AGENTS}_restaurant_location_id", AGENTS, ["restaurant_location_id"]
        )

    if PRINTERS not in existing:
        op.create_table(
            PRINTERS,
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()") if is_postgres else None,
            ),
            sa.Column(
                "print_agent_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey(f"{AGENTS}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column(
                "transport",
                sa.Enum("TCP", "WINDOWS", name="printer_transport"),
                nullable=False,
            ),
            sa.Column("host", sa.String(255), nullable=True),
            sa.Column("port", sa.Integer(), nullable=True),
            sa.Column("windows_printer_name", sa.String(255), nullable=True),
            sa.Column(
                "paper_width_chars", sa.SmallInteger(), nullable=False, server_default="48"
            ),
            sa.Column("copies", sa.SmallInteger(), nullable=False, server_default="1"),
            sa.Column(
                "docket_kinds",
                postgresql.ARRAY(sa.String(32)) if is_postgres else sa.JSON(),
                nullable=False,
                server_default="{}" if is_postgres else "[]",
            ),
            sa.Column(
                "is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
            ),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("last_printed_at", sa.DateTime(timezone=True), nullable=True),
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
            sa.CheckConstraint(TRANSPORT_CHECK, name="transport_is_exhaustive"),
            # 32 is 58mm, 48 is 80mm, 42 is the other common 80mm font. A
            # wrong column count is not subtle: every line wraps and the
            # docket becomes mush.
            sa.CheckConstraint(
                "paper_width_chars IN (32, 42, 48)", name="paper_width_is_known"
            ),
            sa.CheckConstraint("copies BETWEEN 1 AND 5", name="copies_are_sane"),
        )
        op.create_index(f"ix_{PRINTERS}_print_agent_id", PRINTERS, ["print_agent_id"])

    if JOBS not in existing:
        op.create_table(
            JOBS,
            sa.Column(
                "id",
                postgresql.UUID(as_uuid=True),
                primary_key=True,
                server_default=sa.text("gen_random_uuid()") if is_postgres else None,
            ),
            sa.Column(
                "printer_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey(f"{PRINTERS}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            # Null for a TEST print, which belongs to no order.
            sa.Column(
                "order_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("orders.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "kind",
                sa.Enum(
                    "KITCHEN_DOCKET",
                    "CUSTOMER_BILL",
                    "VOID_SLIP",
                    "TEST",
                    name="print_job_kind",
                ),
                nullable=False,
            ),
            sa.Column(
                "source",
                sa.Enum("AUTO", "MANUAL", name="print_job_source"),
                nullable=False,
                server_default="AUTO",
            ),
            sa.Column(
                "status",
                sa.Enum(
                    "QUEUED", "CLAIMED", "PRINTED", "FAILED", name="print_job_status"
                ),
                nullable=False,
                server_default="QUEUED",
            ),
            sa.Column(
                "document",
                postgresql.JSONB() if is_postgres else sa.JSON(),
                nullable=False,
            ),
            sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("printed_at", sa.DateTime(timezone=True), nullable=True),
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
        op.create_index(
            f"ix_{JOBS}_printer_status", JOBS, ["printer_id", "status", "created_at"]
        )
        op.create_index(f"ix_{JOBS}_order_id", JOBS, ["order_id"])

        if is_postgres:
            # The idempotency guarantee. Raw SQL because alembic cannot express
            # a partial unique index with a predicate over enum columns, and
            # because this is the one line in the migration worth reading
            # literally.
            op.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS uq_print_jobs_auto_once "
                f"ON {JOBS} (printer_id, order_id, kind) "
                f"WHERE source = 'AUTO' AND status <> 'FAILED'"
            )

    # Deny-by-default, in the migration. See the module docstring.
    if is_postgres:
        for table in (AGENTS, PRINTERS, JOBS):
            op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())
    is_postgres = bind.dialect.name == "postgresql"

    # Dropped children first: `printers` references `print_agents` and
    # `print_jobs` references `printers`.
    for table in (JOBS, PRINTERS, AGENTS):
        if table in existing:
            op.drop_table(table)

    if is_postgres:
        # The enum types outlive their tables and would block a re-upgrade
        # with "type already exists".
        for enum_name in (
            "print_job_status",
            "print_job_source",
            "print_job_kind",
            "printer_transport",
        ):
            op.execute(f"DROP TYPE IF EXISTS {enum_name}")

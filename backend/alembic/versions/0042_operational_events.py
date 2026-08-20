"""Operational history: order status events, availability events, cancellation reasons

Revision ID: 0042_operational_events
Revises: 0041_owner_chat_messages
Create Date: 2026-08-14 17:00:00.000000

Until now the platform recorded only *current* state: an order's status, a
dish's availability. That made a whole class of owner question unanswerable —
how long orders take to be accepted, where they stall, and whether a dish sold
nothing because demand fell or because it was switched off.

This adds the history:

* ``order_status_events`` — one row per transition, written at the four places
  order status is set (creation, owner transitions, the payment webhook, the
  unpaid-order reaper).
* ``menu_item_availability_events`` — when a dish was switched off and back on.
* ``orders.cancellation_reason`` / ``cancelled_by`` / ``cancelled_at``.

On cancellation reasons: the platform has no human cancellation flow —
``ORDER_STATUS_FLOW`` is strictly linear and refuses anything else — so every
cancellation is system-derived and the reason is always knowable. Existing
cancelled orders are therefore backfillable: a cancelled order whose payment was
also cancelled is provably the reaper's work.

No backfill is possible for the two event tables. That history was never
recorded, so they improve analysis from this migration forward rather than
retroactively.

Every step is guarded so re-running is a no-op.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0042_operational_events"
down_revision = "0041_owner_chat_messages"
branch_labels = None
depends_on = None


order_cancellation_reason_enum = postgresql.ENUM(
    "PAYMENT_NOT_COMPLETED",
    "PAYMENT_ABANDONED",
    "PAYMENT_FAILED",
    "UNKNOWN",
    name="order_cancellation_reason",
    create_type=False,
)

order_event_actor_enum = postgresql.ENUM(
    "OWNER",
    "ADMIN",
    "CUSTOMER",
    "SYSTEM",
    "PAYMENT_PROVIDER",
    name="order_event_actor",
    create_type=False,
)

# Reused, not recreated: defined by the original orders migration.
order_status_enum = postgresql.ENUM(
    "PAYMENT_PENDING",
    "PLACED",
    "ACCEPTED",
    "PREPARING",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "CANCELLED",
    name="order_status",
    create_type=False,
)


def _columns(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()

    order_cancellation_reason_enum.create(bind, checkfirst=True)
    order_event_actor_enum.create(bind, checkfirst=True)

    # --- cancellation columns on orders -----------------------------------
    order_columns = _columns(bind, "orders")
    if "cancellation_reason" not in order_columns:
        op.add_column(
            "orders",
            sa.Column("cancellation_reason", order_cancellation_reason_enum, nullable=True),
        )
        op.create_index(
            "ix_orders_cancellation_reason", "orders", ["cancellation_reason"]
        )
    if "cancelled_by" not in order_columns:
        op.add_column("orders", sa.Column("cancelled_by", order_event_actor_enum, nullable=True))
    if "cancelled_at" not in order_columns:
        op.add_column(
            "orders", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True)
        )

    existing_tables = set(sa.inspect(bind).get_table_names())

    # --- order status events ----------------------------------------------
    if "order_status_events" not in existing_tables:
        op.create_table(
            "order_status_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("restaurant_location_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("from_status", order_status_enum, nullable=True),
            sa.Column("to_status", order_status_enum, nullable=False),
            sa.Column(
                "actor", order_event_actor_enum, nullable=False, server_default="SYSTEM"
            ),
            sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column(
                "cancellation_reason", order_cancellation_reason_enum, nullable=True
            ),
            sa.Column("note", sa.String(length=255), nullable=True),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "metadata",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["order_id"],
                ["orders.id"],
                name="fk_order_status_events_order",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["restaurant_id"],
                ["restaurants.id"],
                name="fk_order_status_events_restaurant",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["restaurant_location_id"],
                ["restaurant_locations.id"],
                name="fk_order_status_events_location",
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["actor_user_id"],
                ["users.id"],
                name="fk_order_status_events_actor",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_order_status_events"),
        )
        for column in (
            "order_id",
            "restaurant_id",
            "restaurant_location_id",
            "to_status",
            "actor",
            "occurred_at",
        ):
            op.create_index(
                f"ix_order_status_events_{column}", "order_status_events", [column]
            )
        op.create_index(
            "ix_order_status_events_order_created",
            "order_status_events",
            ["order_id", "created_at"],
        )
        op.create_index(
            "ix_order_status_events_scope_created",
            "order_status_events",
            ["restaurant_id", "created_at"],
        )

    # --- menu availability events -----------------------------------------
    if "menu_item_availability_events" not in existing_tables:
        op.create_table(
            "menu_item_availability_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("menu_item_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("restaurant_location_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("is_available", sa.Boolean(), nullable=False),
            sa.Column("item_name_snapshot", sa.String(length=255), nullable=False),
            sa.Column(
                "actor", order_event_actor_enum, nullable=False, server_default="SYSTEM"
            ),
            sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.ForeignKeyConstraint(
                ["menu_item_id"],
                ["menu_items.id"],
                name="fk_menu_availability_item",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["restaurant_id"],
                ["restaurants.id"],
                name="fk_menu_availability_restaurant",
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["restaurant_location_id"],
                ["restaurant_locations.id"],
                name="fk_menu_availability_location",
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["actor_user_id"],
                ["users.id"],
                name="fk_menu_availability_actor",
                ondelete="SET NULL",
            ),
            sa.PrimaryKeyConstraint("id", name="pk_menu_item_availability_events"),
        )
        for column in (
            "menu_item_id",
            "restaurant_id",
            "restaurant_location_id",
            "is_available",
            "occurred_at",
        ):
            op.create_index(
                f"ix_menu_availability_{column}", "menu_item_availability_events", [column]
            )
        op.create_index(
            "ix_menu_availability_item_created",
            "menu_item_availability_events",
            ["menu_item_id", "created_at"],
        )
        op.create_index(
            "ix_menu_availability_scope_created",
            "menu_item_availability_events",
            ["restaurant_id", "created_at"],
        )

    _backfill_cancellation_reasons(bind)


def _backfill_cancellation_reasons(bind) -> None:
    """Label existing cancellations, which are all system-derived.

    A cancelled order whose payment was also cancelled is the unpaid-order
    reaper's work. Anything else cancelled predates reason tracking with no
    inferable path, so it is marked UNKNOWN rather than guessed at.

    Only rows with no reason yet are touched, so this is safe to re-run.

    Statuses are compared as text rather than as enum literals. `CANCELLED` was
    added to both enums by migration 0037, and Postgres refuses to *use* an enum
    label added in the same transaction — which is exactly what happens when a
    fresh database runs the whole chain in one `alembic upgrade head`.
    """

    bind.execute(
        sa.text(
            """
            UPDATE orders
            SET cancellation_reason = 'PAYMENT_NOT_COMPLETED',
                cancelled_by = 'SYSTEM',
                cancelled_at = COALESCE(cancelled_at, updated_at)
            WHERE status::text = 'CANCELLED'
              AND cancellation_reason IS NULL
              AND payment_status::text = 'CANCELLED'
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE orders
            SET cancellation_reason = 'UNKNOWN',
                cancelled_by = 'SYSTEM',
                cancelled_at = COALESCE(cancelled_at, updated_at)
            WHERE status::text = 'CANCELLED'
              AND cancellation_reason IS NULL
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())

    if "menu_item_availability_events" in existing_tables:
        op.drop_table("menu_item_availability_events")
    if "order_status_events" in existing_tables:
        op.drop_table("order_status_events")

    order_columns = _columns(bind, "orders")
    if "cancelled_at" in order_columns:
        op.drop_column("orders", "cancelled_at")
    if "cancelled_by" in order_columns:
        op.drop_column("orders", "cancelled_by")
    if "cancellation_reason" in order_columns:
        op.drop_index("ix_orders_cancellation_reason", table_name="orders")
        op.drop_column("orders", "cancellation_reason")

    order_cancellation_reason_enum.drop(bind, checkfirst=True)
    order_event_actor_enum.drop(bind, checkfirst=True)

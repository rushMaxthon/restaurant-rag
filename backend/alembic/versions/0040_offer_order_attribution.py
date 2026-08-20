"""Offer to order attribution: link an order to the offer that produced it

Revision ID: 0040_offer_order_attribution
Revises: 0039_owner_action_proposals
Create Date: 2026-08-14 15:00:00.000000

Until now the only record of "this offer produced this order" was a string
inside ``personalized_offer_events.metadata`` (the model calls it
``event_metadata``):

    {"order_id": "…"}

That cannot be joined, indexed, or trusted, so the question an owner actually
cares about — did this promotion pay for itself? — was unanswerable.

This migration adds real foreign keys:

* ``orders.applied_offer_id`` / ``applied_generated_offer_id`` /
  ``applied_offer_user_match_id`` — who to credit for the revenue. The cost was
  already recorded in ``orders.discount_amount``.
* ``personalized_offer_events.order_id`` — the same link on the event itself.

Existing rows are then backfilled from the JSONB metadata, so historical
conversions become measurable instead of starting from zero. The backfill:

* only touches rows whose metadata holds a well-formed UUID that matches a real
  order, so malformed values and orders since deleted are skipped rather than
  failing the migration;
* never overwrites a value already set, so it is safe to re-run;
* leaves ``event_metadata`` untouched, so anything still reading the old key
  keeps working.

Every column is nullable: orders placed without an offer, and every order that
existed before today, simply carry no link.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0040_offer_order_attribution"
down_revision = "0039_owner_action_proposals"
branch_labels = None
depends_on = None


ORDER_COLUMNS = (
    ("applied_offer_id", "personalized_offers", "fk_orders_applied_offer"),
    ("applied_generated_offer_id", "generated_offers", "fk_orders_applied_generated_offer"),
    (
        "applied_offer_user_match_id",
        "generated_offer_user_matches",
        "fk_orders_applied_offer_match",
    ),
)


def _existing_columns(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()

    order_columns = _existing_columns(bind, "orders")
    for column_name, referred_table, constraint_name in ORDER_COLUMNS:
        if column_name in order_columns:
            continue
        op.add_column(
            "orders",
            sa.Column(column_name, postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            constraint_name,
            "orders",
            referred_table,
            [column_name],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"ix_orders_{column_name}", "orders", [column_name])

    event_columns = _existing_columns(bind, "personalized_offer_events")
    if "order_id" not in event_columns:
        op.add_column(
            "personalized_offer_events",
            sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        op.create_foreign_key(
            "fk_offer_events_order",
            "personalized_offer_events",
            "orders",
            ["order_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            "ix_personalized_offer_events_order_id",
            "personalized_offer_events",
            ["order_id"],
        )

    _backfill(bind)


def _backfill(bind) -> None:
    """Recover the historical links from the JSONB metadata.

    ``event_metadata->>'order_id'`` is validated against the uuid pattern before
    casting: a malformed value would otherwise abort the whole migration.
    """

    uuid_pattern = "'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'"

    # 1. Point each conversion event at its order.
    bind.execute(
        sa.text(
            f"""
            UPDATE personalized_offer_events AS e
            SET order_id = o.id
            FROM orders AS o
            WHERE e.order_id IS NULL
              AND e.event_type = 'CONVERTED'
              AND e."metadata" ->> 'order_id' ~ {uuid_pattern}
              AND o.id = (e."metadata" ->> 'order_id')::uuid
            """
        )
    )

    # 2. Copy the offer references from those events onto the orders. A single
    #    order can only carry one attribution, so the earliest conversion event
    #    wins if history somehow holds more than one.
    bind.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    e.order_id,
                    e.offer_id,
                    e.generated_offer_id,
                    e.generated_offer_user_match_id,
                    ROW_NUMBER() OVER (
                        PARTITION BY e.order_id ORDER BY e.created_at ASC, e.id ASC
                    ) AS position
                FROM personalized_offer_events AS e
                WHERE e.event_type = 'CONVERTED'
                  AND e.order_id IS NOT NULL
            )
            UPDATE orders AS o
            SET applied_offer_id = COALESCE(o.applied_offer_id, ranked.offer_id),
                applied_generated_offer_id = COALESCE(
                    o.applied_generated_offer_id, ranked.generated_offer_id
                ),
                applied_offer_user_match_id = COALESCE(
                    o.applied_offer_user_match_id, ranked.generated_offer_user_match_id
                )
            FROM ranked
            WHERE ranked.position = 1
              AND o.id = ranked.order_id
              AND (
                  o.applied_offer_id IS NULL
                  AND o.applied_generated_offer_id IS NULL
                  AND o.applied_offer_user_match_id IS NULL
              )
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()

    event_columns = _existing_columns(bind, "personalized_offer_events")
    if "order_id" in event_columns:
        op.drop_index(
            "ix_personalized_offer_events_order_id",
            table_name="personalized_offer_events",
        )
        op.drop_constraint(
            "fk_offer_events_order", "personalized_offer_events", type_="foreignkey"
        )
        op.drop_column("personalized_offer_events", "order_id")

    order_columns = _existing_columns(bind, "orders")
    for column_name, _referred_table, constraint_name in ORDER_COLUMNS:
        if column_name not in order_columns:
            continue
        op.drop_index(f"ix_orders_{column_name}", table_name="orders")
        op.drop_constraint(constraint_name, "orders", type_="foreignkey")
        op.drop_column("orders", column_name)

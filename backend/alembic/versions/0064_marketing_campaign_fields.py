"""the campaign columns the Marketing Hub needs, on the table that already was one

Revision ID: 0064_marketing_campaign_fields
Revises: 0063_marketing_consent
Create Date: 2026-09-19 00:00:00.000000

`push_notification_campaigns` was already a campaign table wearing a
notification's name: status (with exactly the six values the Hub's UI declares),
scheduled_for, timezone, deep_link, restaurant_id, data_payload and four
delivery counters all predate this. A separate `marketing_campaigns` table
would have duplicated the dispatch machinery, the event table's parent, and the
counters, to store a row this table nearly already holds.

So this is additive. Every column added is nullable or defaulted, and the
transactional `order_placed` path sets none of them — it writes the same row
after this migration as before it.

`kind` is the seam. It backfills to TRANSACTIONAL for every existing row, so
the Hub's campaign list starts empty rather than showing years of order
notifications, and the frequency cap cannot count an order update against a
customer's weekly marketing allowance.

Two enum types are widened rather than replaced:

* `notification_audience` gains SEGMENT — an audience computed per campaign
  rather than derived from a role.
* `notification_event_type` gains CLICKED and UNSUBSCRIBED — a tap that reached
  the deep link, and an opt-out attributed to the message that caused it.

ALTER TYPE ... ADD VALUE cannot run inside a transaction block on older
Postgres and cannot be rolled back, which is why the downgrade leaves both enum
types widened. Dropping an enum value would fail against any row using it, and
a widened enum with no writers is inert.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0064_marketing_campaign_fields"
down_revision = "0063_marketing_consent"
branch_labels = None
depends_on = None


TABLE = "push_notification_campaigns"

campaign_kind = postgresql.ENUM(
    "TRANSACTIONAL",
    "MARKETING",
    name="notification_campaign_kind",
    create_type=False,
)


def _existing_columns(bind) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(TABLE)}


def _enum_values(bind, type_name: str) -> set[str]:
    rows = bind.execute(
        sa.text(
            """
            SELECT e.enumlabel
            FROM pg_enum e
            JOIN pg_type t ON t.oid = e.enumtypid
            WHERE t.typname = :type_name
            """
        ),
        {"type_name": type_name},
    )
    return {row[0] for row in rows}


def upgrade() -> None:
    bind = op.get_bind()

    # --- widen the two existing enums --------------------------------------

    for value in ("SEGMENT",):
        if value not in _enum_values(bind, "notification_audience"):
            op.execute(
                sa.text(f"ALTER TYPE notification_audience ADD VALUE IF NOT EXISTS '{value}'")
            )

    for value in ("CLICKED", "UNSUBSCRIBED"):
        if value not in _enum_values(bind, "notification_event_type"):
            op.execute(
                sa.text(f"ALTER TYPE notification_event_type ADD VALUE IF NOT EXISTS '{value}'")
            )

    # --- the new kind enum and column ---------------------------------------

    campaign_kind.create(bind, checkfirst=True)

    existing = _existing_columns(bind)

    if "kind" not in existing:
        op.add_column(
            TABLE,
            sa.Column(
                "kind",
                campaign_kind,
                nullable=False,
                server_default="TRANSACTIONAL",
            ),
        )
        op.create_index(f"ix_{TABLE}_kind", TABLE, ["kind"])

    # --- marketing campaign fields ------------------------------------------

    additive_columns = [
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("goal", sa.String(32), nullable=True),
        sa.Column("segment_key", sa.String(32), nullable=True),
        sa.Column("branch_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("channels", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("last_step", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("clicked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unsubscribed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sending_progress", sa.Numeric(5, 4), nullable=True),
        sa.Column("attribution_window_days", sa.Integer(), nullable=False, server_default="7"),
    ]
    for column in additive_columns:
        if column.name not in existing:
            op.add_column(TABLE, column)

    if "offer_id" not in existing:
        op.add_column(
            TABLE,
            sa.Column("offer_id", postgresql.UUID(as_uuid=True), nullable=True),
        )
        # SET NULL rather than CASCADE: an expired offer being cleaned up must
        # never delete the record of a campaign that was actually sent to
        # customers. The report loses the discount link, not the send.
        op.create_foreign_key(
            f"fk_{TABLE}_offer",
            TABLE,
            "generated_offers",
            ["offer_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"ix_{TABLE}_offer_id", TABLE, ["offer_id"])

    # The Hub's list and dashboard both read "this restaurant's marketing
    # campaigns, newest first". Without this they are a sequential scan over
    # every push the platform has ever sent, most of them transactional.
    existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes(TABLE)}
    if f"ix_{TABLE}_marketing_listing" not in existing_indexes:
        op.create_index(
            f"ix_{TABLE}_marketing_listing",
            TABLE,
            ["restaurant_id", "created_at"],
            postgresql_where=sa.text("kind = 'MARKETING'"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = _existing_columns(bind)
    existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes(TABLE)}

    if f"ix_{TABLE}_marketing_listing" in existing_indexes:
        op.drop_index(f"ix_{TABLE}_marketing_listing", table_name=TABLE)

    if "offer_id" in existing:
        if f"ix_{TABLE}_offer_id" in existing_indexes:
            op.drop_index(f"ix_{TABLE}_offer_id", table_name=TABLE)
        op.drop_constraint(f"fk_{TABLE}_offer", TABLE, type_="foreignkey")
        op.drop_column(TABLE, "offer_id")

    for name in (
        "attribution_window_days",
        "sending_progress",
        "unsubscribed_count",
        "clicked_count",
        "last_step",
        "channels",
        "branch_ids",
        "segment_key",
        "goal",
        "name",
    ):
        if name in existing:
            op.drop_column(TABLE, name)

    if "kind" in existing:
        if f"ix_{TABLE}_kind" in existing_indexes:
            op.drop_index(f"ix_{TABLE}_kind", table_name=TABLE)
        op.drop_column(TABLE, "kind")

    campaign_kind.drop(bind, checkfirst=True)

    # notification_audience and notification_event_type keep their new values.
    # See the module docstring.

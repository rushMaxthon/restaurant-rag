"""backfill default pickup and delivery slots for all restaurant locations

Revision ID: 0017_default_location_slots
Revises: 0016_location_fulfillment
Create Date: 2026-05-27 18:20:00.000000
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, time, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0017_default_location_slots"
down_revision = "0016_location_fulfillment"
branch_labels = None
depends_on = None


DEFAULT_START_TIME = time(10, 30)
DEFAULT_END_TIME = time(22, 0)
DAY_SEQUENCE = (
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
)
FULFILLMENT_TYPES = ("PICKUP", "DELIVERY")


def upgrade() -> None:
    bind = op.get_bind()
    location_rows = bind.execute(sa.text("select id from restaurant_locations")).fetchall()
    existing_rows = bind.execute(
        sa.text(
            """
            select
              location_id,
              day_of_week,
              fulfillment_type,
              start_time,
              end_time
            from location_fulfillment_slots
            """
        )
    ).fetchall()
    existing_windows = {
        (
            row.location_id,
            row.day_of_week,
            row.fulfillment_type,
            row.start_time,
            row.end_time,
        )
        for row in existing_rows
    }

    slot_table = sa.table(
        "location_fulfillment_slots",
        sa.column("id", sa.Uuid()),
        sa.column("location_id", sa.Uuid()),
        sa.column(
            "day_of_week",
            postgresql.ENUM(
                *DAY_SEQUENCE,
                name="location_day_of_week",
                create_type=False,
            ),
        ),
        sa.column(
            "fulfillment_type",
            postgresql.ENUM(
                *FULFILLMENT_TYPES,
                name="order_fulfillment_type",
                create_type=False,
            ),
        ),
        sa.column("start_time", sa.Time()),
        sa.column("end_time", sa.Time()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    now = datetime.now(timezone.utc)
    rows_to_insert: list[dict[str, object]] = []
    for (location_id,) in location_rows:
        for day_of_week in DAY_SEQUENCE:
            for fulfillment_type in FULFILLMENT_TYPES:
                window_key = (
                    location_id,
                    day_of_week,
                    fulfillment_type,
                    DEFAULT_START_TIME,
                    DEFAULT_END_TIME,
                )
                if window_key in existing_windows:
                    continue
                rows_to_insert.append(
                    {
                        "id": uuid.uuid4(),
                        "location_id": location_id,
                        "day_of_week": day_of_week,
                        "fulfillment_type": fulfillment_type,
                        "start_time": DEFAULT_START_TIME,
                        "end_time": DEFAULT_END_TIME,
                        "is_active": True,
                        "created_at": now,
                        "updated_at": now,
                    }
                )
                existing_windows.add(window_key)

    if rows_to_insert:
        op.bulk_insert(slot_table, rows_to_insert)


def downgrade() -> None:
    # Intentionally preserve seeded/default slot data on downgrade.
    pass

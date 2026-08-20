"""enforce one owner to one restaurant

Revision ID: 0002_enforce_owner_one_to_one
Revises: 0001_initial_schema
Create Date: 2026-05-04 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0002_enforce_owner_one_to_one"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate_owner_rows: Sequence[tuple[object, int]] = connection.execute(
        sa.text(
            """
            SELECT owner_id, COUNT(*) AS restaurant_count
            FROM restaurants
            GROUP BY owner_id
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()

    if duplicate_owner_rows:
        duplicate_owner_ids = ", ".join(str(row[0]) for row in duplicate_owner_rows)
        raise RuntimeError(
            "Cannot enforce one-to-one owner mapping because multiple restaurants are linked to the same owner: "
            f"{duplicate_owner_ids}"
        )

    op.drop_index(op.f("ix_restaurants_owner_id"), table_name="restaurants")
    op.create_unique_constraint(op.f("uq_restaurants_owner_id"), "restaurants", ["owner_id"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_restaurants_owner_id"), "restaurants", type_="unique")
    op.create_index(op.f("ix_restaurants_owner_id"), "restaurants", ["owner_id"], unique=False)

"""add restaurant locations and backfill branch ownership

Revision ID: 0008_restaurant_locations
Revises: 0007_user_favorites
Create Date: 2026-05-15 15:35:00.000000
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0008_restaurant_locations"
down_revision = "0007_user_favorites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "restaurant_locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_name", sa.String(length=255), nullable=False),
        sa.Column("address_line_1", sa.String(length=255), nullable=False),
        sa.Column("address_line_2", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("state", sa.String(length=120), nullable=False),
        sa.Column("postal_code", sa.String(length=20), nullable=False),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("phone_number", sa.String(length=20), nullable=True),
        sa.Column("delivery_fee", sa.Numeric(10, 2), server_default="0.00", nullable=False),
        sa.Column("minimum_order_amount", sa.Numeric(10, 2), server_default="0.00", nullable=False),
        sa.Column("estimated_delivery_time", sa.Integer(), server_default="30", nullable=False),
        sa.Column("is_open", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("opening_time", sa.Time(), nullable=True),
        sa.Column("closing_time", sa.Time(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "restaurant_id",
            "branch_name",
            name="uq_restaurant_locations_restaurant_id_branch_name",
        ),
    )
    op.create_index(
        op.f("ix_restaurant_locations_restaurant_id"),
        "restaurant_locations",
        ["restaurant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_restaurant_locations_city"),
        "restaurant_locations",
        ["city"],
        unique=False,
    )

    op.add_column(
        "menu_items",
        sa.Column("restaurant_location_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_menu_items_restaurant_location_id"),
        "menu_items",
        ["restaurant_location_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_menu_items_restaurant_location_id",
        "menu_items",
        "restaurant_locations",
        ["restaurant_location_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.add_column(
        "orders",
        sa.Column("restaurant_location_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_orders_restaurant_location_id"),
        "orders",
        ["restaurant_location_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_orders_restaurant_location_id",
        "orders",
        "restaurant_locations",
        ["restaurant_location_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.add_column(
        "generated_combos",
        sa.Column("restaurant_location_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_generated_combos_restaurant_location_id"),
        "generated_combos",
        ["restaurant_location_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_generated_combos_restaurant_location_id",
        "generated_combos",
        "restaurant_locations",
        ["restaurant_location_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.add_column(
        "chat_history",
        sa.Column("restaurant_location_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        op.f("ix_chat_history_restaurant_location_id"),
        "chat_history",
        ["restaurant_location_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_chat_history_restaurant_location_id",
        "chat_history",
        "restaurant_locations",
        ["restaurant_location_id"],
        ["id"],
        ondelete="SET NULL",
    )

    bind = op.get_bind()
    restaurant_table = sa.table(
        "restaurants",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String()),
        sa.column("address_line_1", sa.String()),
        sa.column("address_line_2", sa.String()),
        sa.column("city", sa.String()),
        sa.column("state", sa.String()),
        sa.column("postal_code", sa.String()),
        sa.column("phone_number", sa.String()),
        sa.column("delivery_fee", sa.Numeric(10, 2)),
        sa.column("minimum_order_amount", sa.Numeric(10, 2)),
        sa.column("is_open", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    location_table = sa.table(
        "restaurant_locations",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("restaurant_id", postgresql.UUID(as_uuid=True)),
        sa.column("branch_name", sa.String()),
        sa.column("address_line_1", sa.String()),
        sa.column("address_line_2", sa.String()),
        sa.column("city", sa.String()),
        sa.column("state", sa.String()),
        sa.column("postal_code", sa.String()),
        sa.column("phone_number", sa.String()),
        sa.column("delivery_fee", sa.Numeric(10, 2)),
        sa.column("minimum_order_amount", sa.Numeric(10, 2)),
        sa.column("estimated_delivery_time", sa.Integer()),
        sa.column("is_open", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
        sa.column("opening_time", sa.Time()),
        sa.column("closing_time", sa.Time()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    restaurants: Sequence[sa.RowMapping] = bind.execute(sa.select(restaurant_table)).mappings().all()
    location_ids_by_restaurant: dict[uuid.UUID, uuid.UUID] = {}
    if restaurants:
        location_rows: list[dict[str, object]] = []
        for restaurant in restaurants:
            location_id = uuid.uuid4()
            location_ids_by_restaurant[restaurant["id"]] = location_id
            location_rows.append(
                {
                    "id": location_id,
                    "restaurant_id": restaurant["id"],
                    "branch_name": "Main Branch",
                    "address_line_1": restaurant["address_line_1"],
                    "address_line_2": restaurant["address_line_2"],
                    "city": restaurant["city"],
                    "state": restaurant["state"],
                    "postal_code": restaurant["postal_code"],
                    "phone_number": restaurant["phone_number"],
                    "delivery_fee": restaurant["delivery_fee"],
                    "minimum_order_amount": restaurant["minimum_order_amount"],
                    "estimated_delivery_time": 30,
                    "is_open": restaurant["is_open"],
                    "is_active": restaurant["is_active"],
                    "opening_time": None,
                    "closing_time": None,
                    "created_at": restaurant["created_at"],
                    "updated_at": restaurant["updated_at"],
                }
            )
        op.bulk_insert(location_table, location_rows)

    for restaurant_id, location_id in location_ids_by_restaurant.items():
        bind.execute(
            sa.text(
                "UPDATE menu_items SET restaurant_location_id = :location_id WHERE restaurant_id = :restaurant_id"
            ),
            {"location_id": location_id, "restaurant_id": restaurant_id},
        )
        bind.execute(
            sa.text(
                "UPDATE orders SET restaurant_location_id = :location_id WHERE restaurant_id = :restaurant_id"
            ),
            {"location_id": location_id, "restaurant_id": restaurant_id},
        )
        bind.execute(
            sa.text(
                "UPDATE generated_combos SET restaurant_location_id = :location_id WHERE restaurant_id = :restaurant_id"
            ),
            {"location_id": location_id, "restaurant_id": restaurant_id},
        )
        bind.execute(
            sa.text(
                "UPDATE chat_history SET restaurant_location_id = :location_id WHERE restaurant_id = :restaurant_id"
            ),
            {"location_id": location_id, "restaurant_id": restaurant_id},
        )

    op.alter_column("menu_items", "restaurant_location_id", nullable=False)
    op.alter_column("orders", "restaurant_location_id", nullable=False)
    op.alter_column("generated_combos", "restaurant_location_id", nullable=False)


def downgrade() -> None:
    op.drop_constraint("fk_chat_history_restaurant_location_id", "chat_history", type_="foreignkey")
    op.drop_index(op.f("ix_chat_history_restaurant_location_id"), table_name="chat_history")
    op.drop_column("chat_history", "restaurant_location_id")

    op.drop_constraint("fk_generated_combos_restaurant_location_id", "generated_combos", type_="foreignkey")
    op.drop_index(op.f("ix_generated_combos_restaurant_location_id"), table_name="generated_combos")
    op.drop_column("generated_combos", "restaurant_location_id")

    op.drop_constraint("fk_orders_restaurant_location_id", "orders", type_="foreignkey")
    op.drop_index(op.f("ix_orders_restaurant_location_id"), table_name="orders")
    op.drop_column("orders", "restaurant_location_id")

    op.drop_constraint("fk_menu_items_restaurant_location_id", "menu_items", type_="foreignkey")
    op.drop_index(op.f("ix_menu_items_restaurant_location_id"), table_name="menu_items")
    op.drop_column("menu_items", "restaurant_location_id")

    op.drop_index(op.f("ix_restaurant_locations_city"), table_name="restaurant_locations")
    op.drop_index(op.f("ix_restaurant_locations_restaurant_id"), table_name="restaurant_locations")
    op.drop_table("restaurant_locations")

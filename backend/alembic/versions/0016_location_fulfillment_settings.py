"""add location fulfillment settings and weekly slots

Revision ID: 0016_location_fulfillment
Revises: 0015_offer_generation_layer
Create Date: 2026-05-27 10:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0016_location_fulfillment"
down_revision = "0015_offer_generation_layer"
branch_labels = None
depends_on = None


order_fulfillment_type = postgresql.ENUM(
    "DELIVERY",
    "PICKUP",
    name="order_fulfillment_type",
    create_type=False,
)
location_day_of_week = postgresql.ENUM(
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
    name="location_day_of_week",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    order_fulfillment_type.create(bind, checkfirst=True)
    location_day_of_week.create(bind, checkfirst=True)

    op.add_column(
        "restaurant_locations",
        sa.Column("estimated_pickup_time", sa.Integer(), nullable=False, server_default="20"),
    )
    op.add_column(
        "restaurant_locations",
        sa.Column("delivery_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "restaurant_locations",
        sa.Column("pickup_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "restaurant_locations",
        sa.Column("temporary_closed_reason", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "restaurant_locations",
        sa.Column("preparation_time_minutes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "restaurant_locations",
        sa.Column("service_radius_km", sa.Numeric(6, 2), nullable=True),
    )

    op.add_column(
        "orders",
        sa.Column(
            "fulfillment_type",
            order_fulfillment_type,
            nullable=False,
            server_default=sa.text("'DELIVERY'"),
        ),
    )
    op.create_index(op.f("ix_orders_fulfillment_type"), "orders", ["fulfillment_type"], unique=False)

    op.create_table(
        "location_fulfillment_slots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day_of_week", location_day_of_week, nullable=False),
        sa.Column("fulfillment_type", order_fulfillment_type, nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["location_id"], ["restaurant_locations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "location_id",
            "day_of_week",
            "fulfillment_type",
            "start_time",
            "end_time",
            name="uq_location_fulfillment_slots_window",
        ),
    )
    op.create_index(
        op.f("ix_location_fulfillment_slots_location_id"),
        "location_fulfillment_slots",
        ["location_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_location_fulfillment_slots_day_of_week"),
        "location_fulfillment_slots",
        ["day_of_week"],
        unique=False,
    )
    op.create_index(
        op.f("ix_location_fulfillment_slots_fulfillment_type"),
        "location_fulfillment_slots",
        ["fulfillment_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_location_fulfillment_slots_fulfillment_type"),
        table_name="location_fulfillment_slots",
    )
    op.drop_index(
        op.f("ix_location_fulfillment_slots_day_of_week"),
        table_name="location_fulfillment_slots",
    )
    op.drop_index(
        op.f("ix_location_fulfillment_slots_location_id"),
        table_name="location_fulfillment_slots",
    )
    op.drop_table("location_fulfillment_slots")

    op.drop_index(op.f("ix_orders_fulfillment_type"), table_name="orders")
    op.drop_column("orders", "fulfillment_type")

    op.drop_column("restaurant_locations", "service_radius_km")
    op.drop_column("restaurant_locations", "preparation_time_minutes")
    op.drop_column("restaurant_locations", "temporary_closed_reason")
    op.drop_column("restaurant_locations", "pickup_enabled")
    op.drop_column("restaurant_locations", "delivery_enabled")
    op.drop_column("restaurant_locations", "estimated_pickup_time")

    bind = op.get_bind()
    location_day_of_week.drop(bind, checkfirst=True)
    order_fulfillment_type.drop(bind, checkfirst=True)

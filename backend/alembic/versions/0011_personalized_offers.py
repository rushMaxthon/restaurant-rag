"""add personalized offers and event tracking

Revision ID: 0011_personalized_offers
Revises: 0010_menu_item_new_launch_flag
Create Date: 2026-05-20 13:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0011_personalized_offers"
down_revision = "0010_menu_item_new_launch_flag"
branch_labels = None
depends_on = None


personalized_offer_type = postgresql.ENUM(
    "FAVORITE_ITEM",
    "FAVORITE_RESTAURANT",
    "TASTE_MATCH",
    "CUISINE_AFFINITY",
    "BUDGET_BEHAVIOR",
    "COMBO_AFFINITY",
    name="personalized_offer_type",
    create_type=False,
)
personalized_offer_state = postgresql.ENUM(
    "DRAFT",
    "ACTIVE",
    "PAUSED",
    "EXPIRED",
    "DISABLED",
    name="personalized_offer_state",
    create_type=False,
)
personalized_offer_discount_type = postgresql.ENUM(
    "NONE",
    "PERCENTAGE",
    "FLAT",
    name="personalized_offer_discount_type",
    create_type=False,
)
personalized_offer_event_type = postgresql.ENUM(
    "VIEWED",
    "CLICKED",
    "CONVERTED",
    name="personalized_offer_event_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    personalized_offer_type.create(bind, checkfirst=True)
    personalized_offer_state.create(bind, checkfirst=True)
    personalized_offer_discount_type.create(bind, checkfirst=True)
    personalized_offer_event_type.create(bind, checkfirst=True)

    op.create_table(
        "personalized_offers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("applicable_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("offer_type", personalized_offer_type, nullable=False),
        sa.Column("state", personalized_offer_state, nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column("discount_type", personalized_offer_discount_type, nullable=False, server_default=sa.text("'NONE'")),
        sa.Column("discount_value", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
        sa.Column("max_discount_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("minimum_order_amount", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
        sa.Column("inactivity_days", sa.Integer(), nullable=False, server_default="14"),
        sa.Column("cooldown_hours", sa.Integer(), nullable=False, server_default="48"),
        sa.Column("valid_for_days", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("applicable_category", sa.String(length=120), nullable=True),
        sa.Column("applicable_cuisine", sa.String(length=120), nullable=True),
        sa.Column("cta_label", sa.String(length=80), nullable=True),
        sa.Column("business_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["applicable_item_id"], ["menu_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["restaurant_location_id"], ["restaurant_locations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_personalized_offers")),
    )
    op.create_index(op.f("ix_personalized_offers_restaurant_id"), "personalized_offers", ["restaurant_id"], unique=False)
    op.create_index(op.f("ix_personalized_offers_restaurant_location_id"), "personalized_offers", ["restaurant_location_id"], unique=False)
    op.create_index(op.f("ix_personalized_offers_applicable_item_id"), "personalized_offers", ["applicable_item_id"], unique=False)
    op.create_index(op.f("ix_personalized_offers_name"), "personalized_offers", ["name"], unique=False)
    op.create_index(op.f("ix_personalized_offers_offer_type"), "personalized_offers", ["offer_type"], unique=False)
    op.create_index(op.f("ix_personalized_offers_state"), "personalized_offers", ["state"], unique=False)
    op.create_index(op.f("ix_personalized_offers_expires_at"), "personalized_offers", ["expires_at"], unique=False)

    op.create_table(
        "personalized_offer_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("offer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", personalized_offer_event_type, nullable=False),
        sa.Column("target_type", sa.String(length=40), nullable=True),
        sa.Column("target_id", sa.String(length=255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["offer_id"], ["personalized_offers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_personalized_offer_events")),
    )
    op.create_index(op.f("ix_personalized_offer_events_offer_id"), "personalized_offer_events", ["offer_id"], unique=False)
    op.create_index(op.f("ix_personalized_offer_events_user_id"), "personalized_offer_events", ["user_id"], unique=False)
    op.create_index(op.f("ix_personalized_offer_events_event_type"), "personalized_offer_events", ["event_type"], unique=False)
    op.create_index(op.f("ix_personalized_offer_events_target_type"), "personalized_offer_events", ["target_type"], unique=False)
    op.create_index(op.f("ix_personalized_offer_events_target_id"), "personalized_offer_events", ["target_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_personalized_offer_events_target_id"), table_name="personalized_offer_events")
    op.drop_index(op.f("ix_personalized_offer_events_target_type"), table_name="personalized_offer_events")
    op.drop_index(op.f("ix_personalized_offer_events_event_type"), table_name="personalized_offer_events")
    op.drop_index(op.f("ix_personalized_offer_events_user_id"), table_name="personalized_offer_events")
    op.drop_index(op.f("ix_personalized_offer_events_offer_id"), table_name="personalized_offer_events")
    op.drop_table("personalized_offer_events")

    op.drop_index(op.f("ix_personalized_offers_expires_at"), table_name="personalized_offers")
    op.drop_index(op.f("ix_personalized_offers_state"), table_name="personalized_offers")
    op.drop_index(op.f("ix_personalized_offers_offer_type"), table_name="personalized_offers")
    op.drop_index(op.f("ix_personalized_offers_name"), table_name="personalized_offers")
    op.drop_index(op.f("ix_personalized_offers_applicable_item_id"), table_name="personalized_offers")
    op.drop_index(op.f("ix_personalized_offers_restaurant_location_id"), table_name="personalized_offers")
    op.drop_index(op.f("ix_personalized_offers_restaurant_id"), table_name="personalized_offers")
    op.drop_table("personalized_offers")

    bind = op.get_bind()
    personalized_offer_event_type.drop(bind, checkfirst=True)
    personalized_offer_discount_type.drop(bind, checkfirst=True)
    personalized_offer_state.drop(bind, checkfirst=True)
    personalized_offer_type.drop(bind, checkfirst=True)

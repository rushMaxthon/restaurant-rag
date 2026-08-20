"""add generated offer campaigns and user matches

Revision ID: 0015_offer_generation_layer
Revises: 0014_offer_free_delivery
Create Date: 2026-05-21 21:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015_offer_generation_layer"
down_revision = "0014_offer_free_delivery"
branch_labels = None
depends_on = None


personalized_offer_source = postgresql.ENUM(
    "MANUAL_TEMPLATE",
    "AI_GENERATED",
    name="personalized_offer_source",
    create_type=False,
)
personalized_offer_generation_reason = postgresql.ENUM(
    "REPEATED_ORDER",
    "FAVORITE_RESTAURANT",
    "FIRST_ORDER",
    "INACTIVE_USER",
    "CUISINE_AFFINITY",
    "COMBO_AFFINITY",
    "BUDGET_BEHAVIOR",
    "GLOBAL_FALLBACK",
    name="personalized_offer_generation_reason",
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
personalized_offer_type = postgresql.ENUM(
    "FAVORITE_ITEM",
    "FAVORITE_RESTAURANT",
    "TASTE_MATCH",
    "CUISINE_AFFINITY",
    "BUDGET_BEHAVIOR",
    "COMBO_AFFINITY",
    "ORDER_HISTORY_MATCH",
    "PREFERENCE_MATCH",
    "NEW_ITEM_MATCH",
    "WELCOME_FIRST_ORDER",
    name="personalized_offer_type",
    create_type=False,
)
personalized_offer_audience = postgresql.ENUM(
    "ACTIVE_USERS",
    "INACTIVE_USERS",
    "ALL_CUSTOMERS",
    name="personalized_offer_audience",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    personalized_offer_source.create(bind, checkfirst=True)
    personalized_offer_generation_reason.create(bind, checkfirst=True)

    op.create_table(
        "generated_offers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_offer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("applicable_item_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("generated_combo_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", personalized_offer_source, nullable=False, server_default=sa.text("'AI_GENERATED'")),
        sa.Column("generation_reason", personalized_offer_generation_reason, nullable=False),
        sa.Column("state", personalized_offer_state, nullable=False, server_default=sa.text("'DRAFT'")),
        sa.Column("offer_type", personalized_offer_type, nullable=False),
        sa.Column("audience_type", personalized_offer_audience, nullable=False, server_default=sa.text("'ALL_CUSTOMERS'")),
        sa.Column("applicable_category", sa.String(length=120), nullable=True),
        sa.Column("applicable_cuisine", sa.String(length=120), nullable=True),
        sa.Column("generated_title", sa.String(length=255), nullable=False),
        sa.Column("generated_subtitle", sa.Text(), nullable=False),
        sa.Column("generated_badge", sa.String(length=80), nullable=True),
        sa.Column("generated_cta_label", sa.String(length=80), nullable=True),
        sa.Column("score", sa.Numeric(8, 2), nullable=False, server_default="0.00"),
        sa.Column("eligible_user_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("click_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversion_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("business_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["template_offer_id"], ["personalized_offers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["restaurant_location_id"], ["restaurant_locations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["applicable_item_id"], ["menu_items.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["generated_combo_id"], ["generated_combos.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_offers")),
    )
    op.create_index(op.f("ix_generated_offers_template_offer_id"), "generated_offers", ["template_offer_id"], unique=False)
    op.create_index(op.f("ix_generated_offers_restaurant_id"), "generated_offers", ["restaurant_id"], unique=False)
    op.create_index(op.f("ix_generated_offers_restaurant_location_id"), "generated_offers", ["restaurant_location_id"], unique=False)
    op.create_index(op.f("ix_generated_offers_applicable_item_id"), "generated_offers", ["applicable_item_id"], unique=False)
    op.create_index(op.f("ix_generated_offers_generated_combo_id"), "generated_offers", ["generated_combo_id"], unique=False)
    op.create_index(op.f("ix_generated_offers_source"), "generated_offers", ["source"], unique=False)
    op.create_index(op.f("ix_generated_offers_generation_reason"), "generated_offers", ["generation_reason"], unique=False)
    op.create_index(op.f("ix_generated_offers_state"), "generated_offers", ["state"], unique=False)
    op.create_index(op.f("ix_generated_offers_offer_type"), "generated_offers", ["offer_type"], unique=False)
    op.create_index(op.f("ix_generated_offers_audience_type"), "generated_offers", ["audience_type"], unique=False)
    op.create_index(op.f("ix_generated_offers_expires_at"), "generated_offers", ["expires_at"], unique=False)

    op.create_table(
        "generated_offer_user_matches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generated_offer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("matched_reason", personalized_offer_generation_reason, nullable=False),
        sa.Column("score", sa.Numeric(8, 2), nullable=False, server_default="0.00"),
        sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("target_type", sa.String(length=40), nullable=True),
        sa.Column("target_id", sa.String(length=255), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("click_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversion_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["generated_offer_id"], ["generated_offers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_generated_offer_user_matches")),
    )
    op.create_index(op.f("ix_generated_offer_user_matches_generated_offer_id"), "generated_offer_user_matches", ["generated_offer_id"], unique=False)
    op.create_index(op.f("ix_generated_offer_user_matches_user_id"), "generated_offer_user_matches", ["user_id"], unique=False)
    op.create_index(op.f("ix_generated_offer_user_matches_matched_reason"), "generated_offer_user_matches", ["matched_reason"], unique=False)
    op.create_index(op.f("ix_generated_offer_user_matches_is_current"), "generated_offer_user_matches", ["is_current"], unique=False)
    op.create_index(
        "uq_generated_offer_user_matches_offer_user",
        "generated_offer_user_matches",
        ["generated_offer_id", "user_id"],
        unique=True,
    )

    op.add_column("personalized_offer_events", sa.Column("generated_offer_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("personalized_offer_events", sa.Column("generated_offer_user_match_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_po_events_generated_offer",
        "personalized_offer_events",
        "generated_offers",
        ["generated_offer_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_po_events_generated_match",
        "personalized_offer_events",
        "generated_offer_user_matches",
        ["generated_offer_user_match_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_personalized_offer_events_generated_offer_id"), "personalized_offer_events", ["generated_offer_id"], unique=False)
    op.create_index(op.f("ix_personalized_offer_events_generated_offer_user_match_id"), "personalized_offer_events", ["generated_offer_user_match_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_personalized_offer_events_generated_offer_user_match_id"), table_name="personalized_offer_events")
    op.drop_index(op.f("ix_personalized_offer_events_generated_offer_id"), table_name="personalized_offer_events")
    op.drop_constraint(
        "fk_po_events_generated_match",
        "personalized_offer_events",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_po_events_generated_offer",
        "personalized_offer_events",
        type_="foreignkey",
    )
    op.drop_column("personalized_offer_events", "generated_offer_user_match_id")
    op.drop_column("personalized_offer_events", "generated_offer_id")

    op.drop_index("uq_generated_offer_user_matches_offer_user", table_name="generated_offer_user_matches")
    op.drop_index(op.f("ix_generated_offer_user_matches_is_current"), table_name="generated_offer_user_matches")
    op.drop_index(op.f("ix_generated_offer_user_matches_matched_reason"), table_name="generated_offer_user_matches")
    op.drop_index(op.f("ix_generated_offer_user_matches_user_id"), table_name="generated_offer_user_matches")
    op.drop_index(op.f("ix_generated_offer_user_matches_generated_offer_id"), table_name="generated_offer_user_matches")
    op.drop_table("generated_offer_user_matches")

    op.drop_index(op.f("ix_generated_offers_expires_at"), table_name="generated_offers")
    op.drop_index(op.f("ix_generated_offers_audience_type"), table_name="generated_offers")
    op.drop_index(op.f("ix_generated_offers_offer_type"), table_name="generated_offers")
    op.drop_index(op.f("ix_generated_offers_state"), table_name="generated_offers")
    op.drop_index(op.f("ix_generated_offers_generation_reason"), table_name="generated_offers")
    op.drop_index(op.f("ix_generated_offers_source"), table_name="generated_offers")
    op.drop_index(op.f("ix_generated_offers_generated_combo_id"), table_name="generated_offers")
    op.drop_index(op.f("ix_generated_offers_applicable_item_id"), table_name="generated_offers")
    op.drop_index(op.f("ix_generated_offers_restaurant_location_id"), table_name="generated_offers")
    op.drop_index(op.f("ix_generated_offers_restaurant_id"), table_name="generated_offers")
    op.drop_index(op.f("ix_generated_offers_template_offer_id"), table_name="generated_offers")
    op.drop_table("generated_offers")

    bind = op.get_bind()
    personalized_offer_generation_reason.drop(bind, checkfirst=True)
    personalized_offer_source.drop(bind, checkfirst=True)

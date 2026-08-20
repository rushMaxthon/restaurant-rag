"""create initial restaurant rag schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-05-01 00:00:00.000000

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


user_role = sa.Enum("ADMIN", "OWNER", "CUSTOMER", name="user_role")
order_status = sa.Enum(
    "PLACED",
    "ACCEPTED",
    "PREPARING",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    name="order_status",
)
payment_status = sa.Enum("PENDING", "PAID", "FAILED", "REFUNDED", name="payment_status")
chat_message_role = sa.Enum("USER", "ASSISTANT", name="chat_message_role")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")



    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("default_address", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)
    op.create_unique_constraint(op.f("uq_users_phone_number"), "users", ["phone_number"])

    op.create_table(
        "restaurants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cuisine_type", sa.String(length=120), nullable=False),
        sa.Column("address_line_1", sa.String(length=255), nullable=False),
        sa.Column("address_line_2", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("state", sa.String(length=120), nullable=False),
        sa.Column("country", sa.String(length=120), server_default="India", nullable=False),
        sa.Column("postal_code", sa.String(length=20), nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=True),
        sa.Column("average_rating", sa.Numeric(precision=3, scale=2), server_default="0.00", nullable=False),
        sa.Column("total_ratings", sa.Integer(), server_default="0", nullable=False),
        sa.Column("minimum_order_amount", sa.Numeric(precision=10, scale=2), server_default="0.00", nullable=False),
        sa.Column("delivery_fee", sa.Numeric(precision=10, scale=2), server_default="0.00", nullable=False),
        sa.Column("is_approved", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_open", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("logo_image_url", sa.String(length=500), nullable=True),
        sa.Column("cover_image_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], name=op.f("fk_restaurants_owner_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_restaurants")),
    )
    op.create_index(op.f("ix_restaurants_city"), "restaurants", ["city"], unique=False)
    op.create_index(op.f("ix_restaurants_cuisine_type"), "restaurants", ["cuisine_type"], unique=False)
    op.create_index(op.f("ix_restaurants_name"), "restaurants", ["name"], unique=False)
    op.create_index(op.f("ix_restaurants_owner_id"), "restaurants", ["owner_id"], unique=False)
    op.create_index(op.f("ix_restaurants_slug"), "restaurants", ["slug"], unique=True)

    op.create_table(
        "menu_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("restaurant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("cuisine_type", sa.String(length=120), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("is_veg", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_available", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_bestseller", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("average_rating", sa.Numeric(precision=3, scale=2), server_default="0.00", nullable=False),
        sa.Column("total_ratings", sa.Integer(), server_default="0", nullable=False),
        sa.Column("popularity_score", sa.Numeric(precision=6, scale=2), server_default="0.00", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], name=op.f("fk_menu_items_restaurant_id_restaurants"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_menu_items")),
    )
    op.create_index(op.f("ix_menu_items_category"), "menu_items", ["category"], unique=False)
    op.create_index(op.f("ix_menu_items_cuisine_type"), "menu_items", ["cuisine_type"], unique=False)
    op.create_index(op.f("ix_menu_items_name"), "menu_items", ["name"], unique=False)
    op.create_index(op.f("ix_menu_items_restaurant_id"), "menu_items", ["restaurant_id"], unique=False)

    op.create_table(
        "user_preferences",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("favorite_cuisines", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("disliked_cuisines", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("dietary_preferences", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("preferred_meal_times", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("price_sensitivity", sa.Numeric(precision=4, scale=2), server_default="1.00", nullable=False),
        sa.Column("average_budget", sa.Numeric(precision=10, scale=2), server_default="0.00", nullable=False),
        sa.Column("cuisine_affinity_scores", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("last_recalculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_user_preferences_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_preferences")),
        sa.UniqueConstraint("user_id", name=op.f("uq_user_preferences_user_id")),
    )
    op.create_index(op.f("ix_user_preferences_user_id"), "user_preferences", ["user_id"], unique=True)

    op.create_table(
        "orders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("restaurant_id", sa.UUID(), nullable=False),
        sa.Column("status", order_status, server_default="PLACED", nullable=False),
        sa.Column("payment_status", payment_status, server_default="PENDING", nullable=False),
        sa.Column("payment_provider", sa.String(length=50), server_default="mock", nullable=False),
        sa.Column("payment_reference", sa.String(length=255), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("delivery_fee", sa.Numeric(precision=10, scale=2), server_default="0.00", nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=10, scale=2), server_default="0.00", nullable=False),
        sa.Column("discount_amount", sa.Numeric(precision=10, scale=2), server_default="0.00", nullable=False),
        sa.Column("total_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=10), server_default="INR", nullable=False),
        sa.Column("special_instructions", sa.Text(), nullable=True),
        sa.Column("delivery_address", sa.Text(), nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"], name=op.f("fk_orders_customer_id_users"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], name=op.f("fk_orders_restaurant_id_restaurants"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
    )
    op.create_index(op.f("ix_orders_customer_id"), "orders", ["customer_id"], unique=False)
    op.create_index(op.f("ix_orders_payment_status"), "orders", ["payment_status"], unique=False)
    op.create_index(op.f("ix_orders_restaurant_id"), "orders", ["restaurant_id"], unique=False)
    op.create_index(op.f("ix_orders_status"), "orders", ["status"], unique=False)

    op.create_table(
        "chat_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("restaurant_id", sa.UUID(), nullable=True),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("role", chat_message_role, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context_payload", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["restaurant_id"], ["restaurants.id"], name=op.f("fk_chat_history_restaurant_id_restaurants"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_chat_history_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_history")),
    )
    op.create_index(op.f("ix_chat_history_restaurant_id"), "chat_history", ["restaurant_id"], unique=False)
    op.create_index(op.f("ix_chat_history_role"), "chat_history", ["role"], unique=False)
    op.create_index(op.f("ix_chat_history_session_id"), "chat_history", ["session_id"], unique=False)
    op.create_index(op.f("ix_chat_history_user_id"), "chat_history", ["user_id"], unique=False)

    op.create_table(
        "menu_embeddings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("menu_item_id", sa.UUID(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(dim=768), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["menu_item_id"], ["menu_items.id"], name=op.f("fk_menu_embeddings_menu_item_id_menu_items"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_menu_embeddings")),
        sa.UniqueConstraint("menu_item_id", name=op.f("uq_menu_embeddings_menu_item_id")),
    )
    op.create_index(op.f("ix_menu_embeddings_menu_item_id"), "menu_embeddings", ["menu_item_id"], unique=True)

    op.create_table(
        "order_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("order_id", sa.UUID(), nullable=False),
        sa.Column("menu_item_id", sa.UUID(), nullable=False),
        sa.Column("item_name_snapshot", sa.String(length=255), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("total_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("review_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_order_items_order_items_quantity_positive")),
        sa.CheckConstraint("rating IS NULL OR (rating >= 1 AND rating <= 5)", name=op.f("ck_order_items_order_items_rating_range")),
        sa.ForeignKeyConstraint(["menu_item_id"], ["menu_items.id"], name=op.f("fk_order_items_menu_item_id_menu_items"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], name=op.f("fk_order_items_order_id_orders"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_items")),
    )
    op.create_index(op.f("ix_order_items_menu_item_id"), "order_items", ["menu_item_id"], unique=False)
    op.create_index(op.f("ix_order_items_order_id"), "order_items", ["order_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_order_items_order_id"), table_name="order_items")
    op.drop_index(op.f("ix_order_items_menu_item_id"), table_name="order_items")
    op.drop_table("order_items")

    op.drop_index(op.f("ix_menu_embeddings_menu_item_id"), table_name="menu_embeddings")
    op.drop_table("menu_embeddings")

    op.drop_index(op.f("ix_chat_history_user_id"), table_name="chat_history")
    op.drop_index(op.f("ix_chat_history_session_id"), table_name="chat_history")
    op.drop_index(op.f("ix_chat_history_role"), table_name="chat_history")
    op.drop_index(op.f("ix_chat_history_restaurant_id"), table_name="chat_history")
    op.drop_table("chat_history")

    op.drop_index(op.f("ix_orders_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_restaurant_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_payment_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_customer_id"), table_name="orders")
    op.drop_table("orders")

    op.drop_index(op.f("ix_user_preferences_user_id"), table_name="user_preferences")
    op.drop_table("user_preferences")

    op.drop_index(op.f("ix_menu_items_restaurant_id"), table_name="menu_items")
    op.drop_index(op.f("ix_menu_items_name"), table_name="menu_items")
    op.drop_index(op.f("ix_menu_items_cuisine_type"), table_name="menu_items")
    op.drop_index(op.f("ix_menu_items_category"), table_name="menu_items")
    op.drop_table("menu_items")

    op.drop_index(op.f("ix_restaurants_slug"), table_name="restaurants")
    op.drop_index(op.f("ix_restaurants_owner_id"), table_name="restaurants")
    op.drop_index(op.f("ix_restaurants_name"), table_name="restaurants")
    op.drop_index(op.f("ix_restaurants_cuisine_type"), table_name="restaurants")
    op.drop_index(op.f("ix_restaurants_city"), table_name="restaurants")
    op.drop_table("restaurants")

    op.drop_constraint(op.f("uq_users_phone_number"), "users", type_="unique")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")



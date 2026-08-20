"""AI Restaurant Manager: owner chat history

Revision ID: 0041_owner_chat_messages
Revises: 0040_offer_order_attribution
Create Date: 2026-08-14 16:00:00.000000

Adds ``owner_chat_messages`` — the owner's conversation with the AI Restaurant
Manager. Kept separate from ``chat_history``, which serves the customer RAG
assistant and carries a nullable restaurant; every owner turn belongs to exactly
one restaurant, so the tenancy boundary is enforced by the schema rather than by
convention.

``facts`` stores the numbers each answer was allowed to state, so a reply can be
audited against its data afterwards.

The ``chat_message_role`` enum already exists (created in the original chat
history migration), so it is reused rather than recreated.

Every step is guarded so re-running is a no-op.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0041_owner_chat_messages"
down_revision = "0040_offer_order_attribution"
branch_labels = None
depends_on = None


chat_message_role_enum = postgresql.ENUM(
    "USER",
    "ASSISTANT",
    name="chat_message_role",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    # Reused, not recreated: the customer chat migration already defined it.
    chat_message_role_enum.create(bind, checkfirst=True)

    inspector = sa.inspect(bind)
    if "owner_chat_messages" in set(inspector.get_table_names()):
        return

    op.create_table(
        "owner_chat_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", chat_message_role_enum, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("skill", sa.String(length=64), nullable=True),
        sa.Column("answer_source", sa.String(length=32), nullable=True),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column(
            "facts",
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
            ["restaurant_id"],
            ["restaurants.id"],
            name="fk_owner_chat_restaurant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_location_id"],
            ["restaurant_locations.id"],
            name="fk_owner_chat_location",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_owner_chat_user",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_owner_chat_messages"),
    )

    for column in (
        "restaurant_id",
        "restaurant_location_id",
        "user_id",
        "session_id",
        "role",
        "skill",
    ):
        op.create_index(
            f"ix_owner_chat_messages_{column}", "owner_chat_messages", [column]
        )

    op.create_index(
        "ix_owner_chat_messages_scope_session",
        "owner_chat_messages",
        ["restaurant_id", "session_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "owner_chat_messages" in set(inspector.get_table_names()):
        op.drop_table("owner_chat_messages")

    # The enum is shared with `chat_history`, so it is deliberately left in place.

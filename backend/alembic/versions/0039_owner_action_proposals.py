"""AI Restaurant Manager: owner action proposals

Revision ID: 0039_owner_action_proposals
Revises: 0038_owner_insights
Create Date: 2026-08-14 14:00:00.000000

Adds ``owner_action_proposals`` — recommended actions awaiting an owner's
decision. Approving one can create a live offer, so the row stores the exact
payload that will execute, the facts that justified it, and the offer it
produced (which also serves as the idempotency guard).

Both enum types are created fresh rather than extended, so the Postgres
restriction on using a label in the same transaction that added it (see
``0037_stripe_payments``) does not apply here.

Every step is guarded so re-running is a no-op.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0039_owner_action_proposals"
down_revision = "0038_owner_insights"
branch_labels = None
depends_on = None


owner_action_type_enum = postgresql.ENUM(
    "PROMOTE_ITEM",
    "PROMOTE_CATEGORY",
    "DAYPART_OFFER",
    "WINBACK_INACTIVE",
    "WELCOME_NEW_CUSTOMERS",
    "CROSS_SELL_COMBO",
    "OPERATIONAL_REVIEW",
    "PROTECT_SUPPLY",
    name="owner_action_type",
    create_type=False,
)

owner_action_status_enum = postgresql.ENUM(
    "PROPOSED",
    "APPROVED",
    "EXECUTED",
    "REJECTED",
    "FAILED",
    "EXPIRED",
    name="owner_action_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    owner_action_type_enum.create(bind, checkfirst=True)
    owner_action_status_enum.create(bind, checkfirst=True)

    inspector = sa.inspect(bind)
    if "owner_action_proposals" in set(inspector.get_table_names()):
        return

    op.create_table(
        "owner_action_proposals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("restaurant_location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("insight_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("briefing_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_type", owner_action_type_enum, nullable=False),
        sa.Column(
            "status", owner_action_status_enum, nullable=False, server_default="PROPOSED"
        ),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column(
            "priority", sa.Numeric(precision=12, scale=4), nullable=False, server_default="0.0000"
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("is_executable", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("expected_impact_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("expected_impact_basis", sa.Text(), nullable=True),
        sa.Column(
            "action_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "source_facts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_offer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
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
            name="fk_owner_action_proposals_restaurant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["restaurant_location_id"],
            ["restaurant_locations.id"],
            name="fk_owner_action_proposals_location",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["insight_id"],
            ["owner_insights.id"],
            name="fk_owner_action_proposals_insight",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["briefing_id"],
            ["owner_briefings.id"],
            name="fk_owner_action_proposals_briefing",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name="fk_owner_action_proposals_decided_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["executed_offer_id"],
            ["personalized_offers.id"],
            name="fk_owner_action_proposals_offer",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_owner_action_proposals"),
    )

    for column in (
        "restaurant_id",
        "restaurant_location_id",
        "insight_id",
        "briefing_id",
        "action_type",
        "status",
        "dedupe_key",
        "priority",
        "is_executable",
        "generated_at",
        "expires_at",
        "executed_offer_id",
    ):
        op.create_index(
            f"ix_owner_action_proposals_{column}", "owner_action_proposals", [column]
        )

    op.create_index(
        "ix_owner_action_proposals_scope_status",
        "owner_action_proposals",
        ["restaurant_id", "status"],
    )
    op.create_index(
        "ix_owner_action_proposals_dedupe",
        "owner_action_proposals",
        ["restaurant_id", "dedupe_key", "generated_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "owner_action_proposals" in set(inspector.get_table_names()):
        op.drop_table("owner_action_proposals")

    owner_action_type_enum.drop(bind, checkfirst=True)
    owner_action_status_enum.drop(bind, checkfirst=True)

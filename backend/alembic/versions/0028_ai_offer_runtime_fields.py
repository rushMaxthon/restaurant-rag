"""add runtime fields for autonomous ai offers

Revision ID: 0028_ai_offer_runtime_fields
Revises: 0027_custom_offer_type
Create Date: 2026-06-16 18:20:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0028_ai_offer_runtime_fields"
down_revision = "0027_custom_offer_type"
branch_labels = None
depends_on = None


personalized_offer_discount_type = postgresql.ENUM(
    "NONE",
    "PERCENTAGE",
    "FLAT",
    "FREE_DELIVERY",
    name="personalized_offer_discount_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    personalized_offer_discount_type.create(bind, checkfirst=True)

    op.alter_column("generated_offers", "template_offer_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column("generated_offers", sa.Column("generated_for_user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column(
        "generated_offers",
        sa.Column(
            "discount_type",
            personalized_offer_discount_type,
            nullable=False,
            server_default=sa.text("'NONE'"),
        ),
    )
    op.add_column("generated_offers", sa.Column("discount_value", sa.Numeric(10, 2), nullable=False, server_default="0.00"))
    op.add_column("generated_offers", sa.Column("max_discount_amount", sa.Numeric(10, 2), nullable=True))
    op.add_column(
        "generated_offers",
        sa.Column("minimum_order_amount", sa.Numeric(10, 2), nullable=False, server_default="0.00"),
    )
    op.add_column("generated_offers", sa.Column("valid_for_days", sa.Integer(), nullable=False, server_default="7"))
    op.create_foreign_key(
        "fk_generated_offers_generated_for_user",
        "generated_offers",
        "users",
        ["generated_for_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_generated_offers_generated_for_user_id"), "generated_offers", ["generated_for_user_id"], unique=False)

    op.execute(
        """
        UPDATE generated_offers AS go
        SET
            discount_type = po.discount_type,
            discount_value = po.discount_value,
            max_discount_amount = po.max_discount_amount,
            minimum_order_amount = po.minimum_order_amount,
            valid_for_days = po.valid_for_days
        FROM personalized_offers AS po
        WHERE go.template_offer_id = po.id
        """
    )

    op.alter_column("personalized_offer_events", "offer_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)


def downgrade() -> None:
    op.alter_column("personalized_offer_events", "offer_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)

    op.drop_index(op.f("ix_generated_offers_generated_for_user_id"), table_name="generated_offers")
    op.drop_constraint("fk_generated_offers_generated_for_user", "generated_offers", type_="foreignkey")
    op.drop_column("generated_offers", "valid_for_days")
    op.drop_column("generated_offers", "minimum_order_amount")
    op.drop_column("generated_offers", "max_discount_amount")
    op.drop_column("generated_offers", "discount_value")
    op.drop_column("generated_offers", "discount_type")
    op.drop_column("generated_offers", "generated_for_user_id")
    op.alter_column("generated_offers", "template_offer_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)

"""add generated combo lifecycle fields

Revision ID: 0029_generated_combo_lifecycle
Revises: 0028_ai_offer_runtime_fields
Create Date: 2026-06-18 13:45:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0029_generated_combo_lifecycle"
down_revision = "0028_ai_offer_runtime_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generated_combos",
        sa.Column("status", sa.String(length=32), server_default="DRAFT", nullable=False),
    )
    op.add_column(
        "generated_combos",
        sa.Column("is_customer_visible", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index(op.f("ix_generated_combos_status"), "generated_combos", ["status"], unique=False)
    op.create_index(
        op.f("ix_generated_combos_is_customer_visible"),
        "generated_combos",
        ["is_customer_visible"],
        unique=False,
    )

    op.execute(
        """
        UPDATE generated_combos
        SET
            status = CASE
                WHEN is_active = true AND unique_user_count >= 3 THEN 'PUBLISHED'
                WHEN is_active = true THEN 'DRAFT'
                ELSE 'ARCHIVED'
            END,
            is_customer_visible = CASE
                WHEN is_active = true AND unique_user_count >= 3 THEN true
                ELSE false
            END
        """
    )

    op.alter_column("generated_combos", "status", server_default=None)
    op.alter_column("generated_combos", "is_customer_visible", server_default=None)


def downgrade() -> None:
    op.drop_index(op.f("ix_generated_combos_is_customer_visible"), table_name="generated_combos")
    op.drop_index(op.f("ix_generated_combos_status"), table_name="generated_combos")
    op.drop_column("generated_combos", "is_customer_visible")
    op.drop_column("generated_combos", "status")

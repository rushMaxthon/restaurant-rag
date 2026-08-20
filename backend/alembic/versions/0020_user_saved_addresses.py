"""add user saved addresses

Revision ID: 0020_user_saved_addresses
Revises: 0019_location_payment_methods
Create Date: 2026-06-01 16:30:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0020_user_saved_addresses"
down_revision = "0019_location_payment_methods"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.create_table(
        "user_saved_addresses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=24), nullable=False, server_default="OTHER"),
        sa.Column("address_line_1", sa.Text(), nullable=False),
        sa.Column("address_line_2", sa.Text(), nullable=True),
        sa.Column("landmark", sa.Text(), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("state", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("postal_code", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("phone_number", sa.String(length=20), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_user_saved_addresses_user_id",
        "user_saved_addresses",
        ["user_id"],
    )

    op.execute(
        """
        INSERT INTO user_saved_addresses (
            id,
            user_id,
            label,
            address_line_1,
            city,
            state,
            postal_code,
            phone_number,
            is_default,
            created_at,
            updated_at
        )
        SELECT
            gen_random_uuid(),
            users.id,
            'HOME',
            users.default_address,
            '',
            '',
            '',
            users.phone_number,
            true,
            NOW(),
            NOW()
        FROM users
        WHERE users.default_address IS NOT NULL
          AND btrim(users.default_address) <> ''
        """
    )


def downgrade() -> None:
    op.drop_index("ix_user_saved_addresses_user_id", table_name="user_saved_addresses")
    op.drop_table("user_saved_addresses")

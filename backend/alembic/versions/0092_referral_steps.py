"""Referral v2: milestone steps on each referral, a step number on each bonus.

Existing referrals become one step from their own columns; the money guard
becomes UNIQUE (referral_id, kind, step). Additive apart from that swap.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0092_referral_steps"
down_revision = "0091_rider_referrals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rider_referrals",
        sa.Column("steps", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.execute(
        """
        UPDATE rider_referrals
        SET steps = jsonb_build_array(jsonb_build_object(
            'deliveries', deliveries_required,
            'referrer_amount', referrer_amount::text,
            'joiner_amount', joiner_amount::text))
        WHERE steps = '[]'::jsonb
        """
    )
    op.add_column("rider_bonuses", sa.Column("step", sa.Integer(), nullable=False, server_default="0"))
    op.drop_constraint("uq_rider_bonuses_referral_kind", "rider_bonuses", type_="unique")
    op.create_unique_constraint(
        "uq_rider_bonuses_referral_kind_step", "rider_bonuses", ["referral_id", "kind", "step"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_rider_bonuses_referral_kind_step", "rider_bonuses", type_="unique")
    op.execute("DELETE FROM rider_bonuses WHERE step > 0")
    op.create_unique_constraint("uq_rider_bonuses_referral_kind", "rider_bonuses", ["referral_id", "kind"])
    op.drop_column("rider_bonuses", "step")
    op.drop_column("rider_referrals", "steps")

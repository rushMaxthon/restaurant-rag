"""Rider referrals: who referred whom on what terms, and the bonuses they pay.

Additive only. RLS is enabled on both new tables in the migration (0070+).
Constraint names are passed bare: the metadata naming convention is applied
to DROP as well as CREATE (CLAUDE.md, 0071).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0091_rider_referrals"
down_revision = "0090_rider_onboarding"
branch_labels = None
depends_on = None


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    postgresql.ENUM("WAITING", "IN_PROGRESS", "EARNED", "EXPIRED", "CANCELLED",
                    name="rider_referral_status").create(op.get_bind(), checkfirst=True)
    postgresql.ENUM("REFERRAL_REFERRER", "REFERRAL_JOINER", name="rider_bonus_kind").create(
        op.get_bind(), checkfirst=True
    )
    op.add_column("riders", sa.Column("referral_code", sa.String(16), nullable=True))
    op.create_unique_constraint("uq_riders_referral_code", "riders", ["referral_code"])

    op.create_table(
        "rider_referrals",
        sa.Column("referred_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("riders.user_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("referrer_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("riders.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("referrer_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("joiner_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("deliveries_required", sa.Integer(), nullable=False),
        sa.Column("days_allowed", sa.Integer(), nullable=False),
        sa.Column("status", _enum("rider_referral_status"), nullable=False, server_default="WAITING"),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("earned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("cancelled_by_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("referred_user_id <> referrer_user_id", name="not_self"),
    )
    op.create_index("ix_rider_referrals_referrer_user_id", "rider_referrals", ["referrer_user_id"])

    op.create_table(
        "rider_bonuses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("rider_user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("riders.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", _enum("rider_bonus_kind"), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("referral_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("rider_referrals.referred_user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("payout_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("rider_payouts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("earned_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("referral_id", "kind", name="uq_rider_bonuses_referral_kind"),
        sa.CheckConstraint("amount > 0", name="positive"),
    )
    op.create_index("ix_rider_bonuses_rider_user_id", "rider_bonuses", ["rider_user_id"])

    for table in ("rider_referrals", "rider_bonuses"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("rider_bonuses")
    op.drop_table("rider_referrals")
    op.drop_constraint("uq_riders_referral_code", "riders", type_="unique")
    op.drop_column("riders", "referral_code")
    op.execute("DROP TYPE IF EXISTS rider_bonus_kind")
    op.execute("DROP TYPE IF EXISTS rider_referral_status")

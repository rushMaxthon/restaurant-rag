"""Rider self sign-up: the application, its items, review events, phone codes.

* `riders.onboarding` defaults to APPROVED, so every existing rider - and
  every rider an admin creates - keeps working with no backfill. Only a rider
  who signed up in the app starts PENDING.
* `EV_SCOOTER` is added to `rider_vehicle_type` in an autocommit block, for
  the same reason 0089 did its values that way ("unsafe use of new value").
* RLS is enabled on every new table here, in the migration (0088).

Additive only. Applied to Supabase by the user (`alembic upgrade head`).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0090_rider_onboarding"
down_revision = "0089_own_fleet"
branch_labels = None
depends_on = None

ITEM_KINDS = (
    "PERSONAL", "VEHICLE_DETAILS", "BANK_DETAILS", "SELFIE", "RC", "AADHAAR_FRONT",
    "AADHAAR_BACK", "PAN", "LICENCE_FRONT", "LICENCE_BACK", "BANK_PROOF",
)
ENUMS = (
    ("rider_onboarding", ("PENDING", "APPROVED", "REJECTED")),
    ("rider_application_status", ("DRAFT", "SUBMITTED", "CHANGES_NEEDED", "APPROVED", "REJECTED")),
    ("rider_application_item_kind", ITEM_KINDS),
    ("rider_application_item_status", ("MISSING", "PENDING", "ACCEPTED", "NEEDS_CHANGE")),
    (
        "rider_application_action",
        ("SUBMITTED", "RESUBMITTED", "ITEM_ACCEPTED", "ITEM_FLAGGED", "SENT_BACK", "APPROVED", "REJECTED", "REOPENED"),
    ),
)
NEW_TABLES = ("rider_applications", "rider_application_items", "rider_application_events", "phone_verifications")


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _text(name: str, length: int | None = None) -> sa.Column:
    kind = sa.String(length) if length else sa.Text()
    return sa.Column(name, kind, nullable=False, server_default="")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE rider_vehicle_type ADD VALUE IF NOT EXISTS 'EV_SCOOTER'")

    bind = op.get_bind()
    for name, values in ENUMS:
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    uid = postgresql.UUID(as_uuid=True)
    existing = set(sa.inspect(bind).get_table_names())
    rider_columns = {c["name"] for c in sa.inspect(bind).get_columns("riders")}

    if "onboarding" not in rider_columns:
        op.add_column(
            "riders",
            sa.Column("onboarding", _enum("rider_onboarding"), nullable=False, server_default="APPROVED"),
        )

    if "rider_applications" not in existing:
        op.create_table(
            "rider_applications",
            sa.Column("rider_user_id", uid, sa.ForeignKey("riders.user_id", ondelete="CASCADE"), primary_key=True),
            sa.Column("status", _enum("rider_application_status"), nullable=False, server_default="DRAFT"),
            _text("full_name", 120),
            sa.Column("date_of_birth", sa.Date(), nullable=True),
            _text("city", 80),
            _text("address_line", 240),
            _text("pincode", 6),
            _text("emergency_name", 120),
            _text("emergency_phone", 20),
            sa.Column("vehicle_type", _enum("rider_vehicle_type"), nullable=True),
            _text("vehicle_number", 16),
            _text("aadhaar_last4", 4),
            _text("pan_encrypted"),
            _text("pan_last4", 4),
            _text("licence_number_encrypted"),
            _text("licence_last4", 4),
            sa.Column("licence_expiry", sa.Date(), nullable=True),
            _text("bank_holder", 120),
            _text("bank_account_encrypted"),
            _text("bank_account_last4", 4),
            _text("ifsc", 11),
            _text("upi_id", 80),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decided_by_user_id", uid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            _text("final_reason"),
            *_timestamps(),
        )
        op.create_index("ix_rider_applications_status", "rider_applications", ["status", "submitted_at"])

    if "rider_application_items" not in existing:
        op.create_table(
            "rider_application_items",
            sa.Column("id", uid, primary_key=True),
            sa.Column(
                "rider_user_id",
                uid,
                sa.ForeignKey("rider_applications.rider_user_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("kind", _enum("rider_application_item_kind"), nullable=False),
            sa.Column("status", _enum("rider_application_item_status"), nullable=False, server_default="MISSING"),
            _text("reason"),
            sa.Column("storage_path", sa.String(255), nullable=True),
            _text("content_type", 40),
            sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reviewed_by_user_id", uid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint("rider_user_id", "kind", name="uq_rider_application_items_kind"),
        )

    if "rider_application_events" not in existing:
        op.create_table(
            "rider_application_events",
            sa.Column("id", uid, primary_key=True),
            sa.Column(
                "rider_user_id",
                uid,
                sa.ForeignKey("rider_applications.rider_user_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("actor_user_id", uid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("action", _enum("rider_application_action"), nullable=False),
            sa.Column("item_kind", _enum("rider_application_item_kind"), nullable=True),
            _text("note"),
        )
        op.create_index("ix_rider_application_events_rider", "rider_application_events", ["rider_user_id", "at"])

    if "phone_verifications" not in existing:
        op.create_table(
            "phone_verifications",
            sa.Column("id", uid, primary_key=True),
            sa.Column("phone", sa.String(20), nullable=False),
            sa.Column("purpose", sa.String(20), nullable=False),
            sa.Column("code_hash", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        )
        op.create_index("ix_phone_verifications_phone", "phone_verifications", ["phone", "purpose", "created_at"])

    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in ("phone_verifications", "rider_application_events", "rider_application_items", "rider_applications"):
        op.drop_table(table)
    op.drop_column("riders", "onboarding")
    bind = op.get_bind()
    for name, _ in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
    # 'EV_SCOOTER' stays in rider_vehicle_type: Postgres cannot remove an enum
    # value. Re-type any EV_SCOOTER rider before downgrading.

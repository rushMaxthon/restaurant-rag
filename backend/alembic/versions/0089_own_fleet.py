"""The platform's own delivery fleet: riders, offers, trips, payouts, delivery OTP.

Three lessons from earlier migrations are applied here on purpose:

* RIDER is platform staff, so the two platform-uniqueness indexes are
  widened to name it (0071: a role missing from them has no uniqueness).
* The enum values are added in an autocommit block, because Postgres refuses
  to let a value added in this transaction be used by a later statement in it
  (0071, "unsafe use of new value").
* RLS is enabled on every new table here, in the migration, so a fresh
  environment comes up closed (0088).

Additive only. Applied to Supabase by the user (`alembic upgrade head`).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0089_own_fleet"
down_revision = "0088_rls_on_every_table"
branch_labels = None
depends_on = None

PLATFORM_ROLES = "'ADMIN', 'OWNER', 'KITCHEN', 'RIDER'"
OLD_PLATFORM_ROLES = "'ADMIN', 'OWNER', 'KITCHEN'"
NEW_TABLES = ("riders", "rider_payouts", "rider_offers", "rider_trips")
ENUMS = (
    ("rider_status", ("OFFLINE", "ONLINE", "ON_TRIP")),
    ("rider_vehicle_type", ("BIKE", "SCOOTER", "CYCLE")),
    ("rider_offer_outcome", ("PENDING", "ACCEPTED", "DECLINED", "EXPIRED", "WITHDRAWN")),
    (
        "rider_trip_end_reason",
        ("DELIVERED", "CANCELLED_BEFORE_PICKUP", "CANCELLED_AFTER_PICKUP", "CUSTOMER_UNAVAILABLE", "REASSIGNED"),
    ),
)


def _enum(name: str) -> postgresql.ENUM:
    return postgresql.ENUM(name=name, create_type=False)


def _uniqueness(roles: str) -> None:
    # Recreated rather than altered: Postgres has no ALTER INDEX ... SET WHERE.
    op.execute("DROP INDEX IF EXISTS uq_users_email_platform")
    op.execute(f"CREATE UNIQUE INDEX uq_users_email_platform ON users (lower(email)) WHERE role IN ({roles})")
    op.execute("DROP INDEX IF EXISTS uq_users_phone_number_platform")
    op.execute(
        "CREATE UNIQUE INDEX uq_users_phone_number_platform ON users (phone_number) "
        f"WHERE role IN ({roles}) AND phone_number IS NOT NULL"
    )


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'RIDER'")
        op.execute("ALTER TYPE order_event_actor ADD VALUE IF NOT EXISTS 'RIDER'")

    bind = op.get_bind()
    for name, values in ENUMS:
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)

    uid = postgresql.UUID(as_uuid=True)
    existing = set(sa.inspect(bind).get_table_names())

    if "riders" not in existing:
        op.create_table(
            "riders",
            sa.Column("user_id", uid, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("vehicle_type", _enum("rider_vehicle_type"), nullable=False),
            sa.Column("vehicle_number", sa.String(32), nullable=False, server_default=""),
            sa.Column("city", sa.String(80), nullable=False, server_default=""),
            sa.Column("status", _enum("rider_status"), nullable=False, server_default="OFFLINE"),
            sa.Column("status_at", sa.DateTime(timezone=True)),
            sa.Column("last_latitude", sa.Float()),
            sa.Column("last_longitude", sa.Float()),
            sa.Column("last_location_at", sa.DateTime(timezone=True)),
            sa.Column("fcm_token", sa.Text(), nullable=False, server_default=""),
            sa.Column("app_version", sa.String(32), nullable=False, server_default=""),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            *_timestamps(),
        )
        op.create_index("ix_riders_status", "riders", ["status"])

    if "rider_payouts" not in existing:
        op.create_table(
            "rider_payouts",
            sa.Column("id", uid, primary_key=True),
            sa.Column("rider_user_id", uid, sa.ForeignKey("riders.user_id", ondelete="RESTRICT"), nullable=False),
            sa.Column("period_from", sa.DateTime(timezone=True), nullable=False),
            sa.Column("period_to", sa.DateTime(timezone=True), nullable=False),
            sa.Column("amount", sa.Numeric(10, 2), nullable=False),
            sa.Column("trips", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reference", sa.String(120), nullable=False, server_default=""),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_by_user_id", uid, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
            *_timestamps(),
        )
        op.create_index("ix_rider_payouts_rider_user_id", "rider_payouts", ["rider_user_id"])

    if "rider_offers" not in existing:
        op.create_table(
            "rider_offers",
            sa.Column("id", uid, primary_key=True),
            sa.Column(
                "order_delivery_id", uid, sa.ForeignKey("order_deliveries.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("rider_user_id", uid, sa.ForeignKey("riders.user_id", ondelete="CASCADE"), nullable=False),
            sa.Column("offered_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("responded_at", sa.DateTime(timezone=True)),
            sa.Column("outcome", _enum("rider_offer_outcome"), nullable=False, server_default="PENDING"),
            sa.Column("distance_to_pickup_m", sa.Float()),
            *_timestamps(),
        )
        op.create_index(
            "uq_rider_offers_one_pending",
            "rider_offers",
            ["order_delivery_id"],
            unique=True,
            postgresql_where=sa.text("outcome = 'PENDING'"),
        )
        op.create_index("ix_rider_offers_rider", "rider_offers", ["rider_user_id", "outcome"])
        op.create_index("ix_rider_offers_delivery", "rider_offers", ["order_delivery_id"])

    if "rider_trips" not in existing:
        op.create_table(
            "rider_trips",
            sa.Column("id", uid, primary_key=True),
            sa.Column(
                "order_delivery_id", uid, sa.ForeignKey("order_deliveries.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("rider_user_id", uid, sa.ForeignKey("riders.user_id", ondelete="RESTRICT"), nullable=False),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("arrived_pickup_at", sa.DateTime(timezone=True)),
            sa.Column("picked_up_at", sa.DateTime(timezone=True)),
            sa.Column("arrived_drop_at", sa.DateTime(timezone=True)),
            sa.Column("delivered_at", sa.DateTime(timezone=True)),
            sa.Column("ended_at", sa.DateTime(timezone=True)),
            sa.Column("end_reason", _enum("rider_trip_end_reason")),
            sa.Column("call_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("distance_km", sa.Float()),
            sa.Column("earning_amount", sa.Numeric(10, 2)),
            sa.Column("earning_breakdown", postgresql.JSONB()),
            sa.Column("applied_actions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
            sa.Column("payout_id", uid, sa.ForeignKey("rider_payouts.id", ondelete="SET NULL")),
            *_timestamps(),
        )
        op.create_index(
            "uq_rider_trips_one_live",
            "rider_trips",
            ["order_delivery_id"],
            unique=True,
            postgresql_where=sa.text("ended_at IS NULL"),
        )
        op.create_index("ix_rider_trips_rider", "rider_trips", ["rider_user_id", "accepted_at"])

    delivery_columns = {c["name"] for c in sa.inspect(bind).get_columns("order_deliveries")}
    if "delivery_otp_hash" not in delivery_columns:
        op.add_column(
            "order_deliveries", sa.Column("delivery_otp_hash", sa.String(128), nullable=False, server_default="")
        )
    if "otp_attempts" not in delivery_columns:
        op.add_column("order_deliveries", sa.Column("otp_attempts", sa.Integer(), nullable=False, server_default="0"))
    if "otp_locked" not in delivery_columns:
        op.add_column(
            "order_deliveries", sa.Column("otp_locked", sa.Boolean(), nullable=False, server_default="false")
        )

    _uniqueness(PLATFORM_ROLES)

    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    _uniqueness(OLD_PLATFORM_ROLES)
    for column in ("otp_locked", "otp_attempts", "delivery_otp_hash"):
        op.drop_column("order_deliveries", column)
    for table in ("rider_trips", "rider_offers", "rider_payouts", "riders"):
        op.drop_table(table)
    bind = op.get_bind()
    for name, _ in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)
    # 'RIDER' stays in user_role and order_event_actor: Postgres cannot remove
    # an enum value. Delete or re-role every RIDER account before downgrading.

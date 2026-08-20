"""Add the LOCATION_DECLINE owner insight type.

Values only, deliberately. Postgres refuses to use an enum label inside the same
transaction that added it, and `alembic upgrade head` runs the whole chain in
one transaction on a fresh database — which is how migration 0042 passed when
run from its predecessor and failed from scratch. Nothing here reads or writes
the new label; the first use is at runtime, long after this has committed.

Revision ID: 0045_location_insight_type
Revises: 0044_insight_root_cause_chat_params
Create Date: 2026-08-14
"""

from __future__ import annotations

from alembic import op

revision = "0045_location_insight_type"
down_revision = "0044_insight_root_cause_chat_params"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE owner_insight_type ADD VALUE IF NOT EXISTS 'LOCATION_DECLINE'"
    )


def downgrade() -> None:
    # Postgres cannot drop a single enum label. Rebuilding the type to remove
    # one would mean rewriting every dependent column while rows may still
    # reference it, which is a far worse outcome than an unused label. The value
    # is left in place on the way down.
    pass

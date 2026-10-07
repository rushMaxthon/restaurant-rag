"""Platform-wide settings an administrator sets from the panel.

One table, `platform_settings`, keyed by name. Its first key is
"delivery_pricing": the delivery slabs, the furthest the platform delivers and
the GST on delivery, edited on the admin's Delivery pricing page and applied
to every restaurant (`services/delivery/slabs.py`).

Purely additive. With no row the code prices exactly as before, from the
settings defaults, so this can be applied before or after the deploy that
reads it. RLS on in the migration itself, as `0070` set the pattern: the
backend connects as the table owner and bypasses it; nobody else should read
the platform's prices through the anon key.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0086_platform_settings"
down_revision = "0085_staff_cancellation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "platform_settings" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column(
            "updated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute("ALTER TABLE public.platform_settings ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("platform_settings")

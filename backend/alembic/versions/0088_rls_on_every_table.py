"""Row-level security on every table, for a database built from scratch.

`0052` switched RLS on for every table that existed when it ran; each later
migration was supposed to do it for its own table, and these did not:
`app_client_domains` (0062), `restaurant_capabilities` (0066),
`restaurant_payment_accounts` (0067), `push_notification_campaign_recipients`
(0069). Supabase hands the `anon` role full read and write on `public`, and
the anon key ships inside client apps, so a fresh environment built from
these migrations started with those tables open to anyone holding it
(2026-10-07 security review) - including payment accounts and the domain map
that decides which storefront is which tenant.

The live Supabase project already has RLS on every table (checked
2026-10-07), so there this changes nothing; `ENABLE` on a table that has it
is a no-op. The backend connects as the table owner and is unaffected.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0088_rls_on_every_table"
down_revision = "0087_storefront_visitor_days"
branch_labels = None
depends_on = None

TABLES = (
    "app_client_domains",
    "restaurant_capabilities",
    "restaurant_payment_accounts",
    "push_notification_campaign_recipients",
    "app_client_push_credentials",
)


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in TABLES:
        if table in existing:
            op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Deliberately nothing: turning RLS off would reopen these tables.
    pass

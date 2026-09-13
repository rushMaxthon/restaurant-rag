"""Enable row level security on every table in the public schema.

RLS was turned on directly against the live database with no migration behind
it, so a freshly provisioned environment (a new dev box, a CI database, a
disaster-recovery restore) started with every tenant table readable and
writable by anyone holding the public anon key — the exact opposite of what
was already running in production. This migration is what makes that state
reproducible from a clean database instead of tribal knowledge.

This app does not use PostgREST: the FastAPI backend owns auth and every
business rule, and it connects as the table owner, which Postgres always lets
bypass RLS regardless of policy. So enabling RLS here with NO policies attached
is deny-by-default for any OTHER role that might reach these tables directly —
Supabase's anon/authenticated roles being the ones this closes the door on —
while changing nothing for the app itself. On a plain Postgres with no such
roles (a local dev database, a self-hosted deployment) `ENABLE ROW LEVEL
SECURITY` with nothing else touching the schema is inert: every existing
grant keeps working exactly as before.

Deliberately not `FORCE ROW LEVEL SECURITY`: that would also gate the table
owner, and the owner bypass above is load-bearing for how this backend
connects. Deliberately no policies: the goal is to deny every role this
migration doesn't already know about, not to reimplement the backend's
authorization logic in Postgres.

The table list is read at migration time rather than hardcoded, so this
correctly covers every table that exists in `public` when it runs — the same
reason `ENABLE ROW LEVEL SECURITY` is safe to run twice: Postgres treats
enabling (or disabling) it on a table where it is already enabled (or
disabled) as a no-op, so re-running this migration, or running it after RLS
was already turned on by hand, changes nothing.
"""

from alembic import op

revision = "0050_enable_row_level_security"
down_revision = "0049_menu_item_rating"
branch_labels = None
depends_on = None

_TOGGLE_RLS_SQL = """
DO $$
DECLARE
    target_table text;
BEGIN
    FOR target_table IN
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename <> 'alembic_version'
    LOOP
        EXECUTE format(
            'ALTER TABLE public.%I {command} ROW LEVEL SECURITY',
            target_table
        );
    END LOOP;
END
$$;
"""


def upgrade() -> None:
    # alembic_version is excluded: it is Alembic's own bookkeeping table, not
    # tenant data, and this backend is the only thing that ever touches it.
    op.execute(_TOGGLE_RLS_SQL.format(command="ENABLE"))


def downgrade() -> None:
    op.execute(_TOGGLE_RLS_SQL.format(command="DISABLE"))

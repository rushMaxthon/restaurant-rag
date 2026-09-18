"""the web address a tenant's storefront answers on

Revision ID: 0062_app_client_domains
Revises: 0061_customization_option_defaults
Create Date: 2026-09-18 00:00:00.000000

A mobile build identifies itself with a bundle id. A web build cannot: one
deployment serves every tenant and the only thing distinguishing requests is
the host. This table is that mapping, and `host` is globally unique so one
address can only ever resolve to one tenant.

Idempotent in the same style as `0032_app_clients`: some environments were
built by hand and already have parts of this.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0062_app_client_domains"
down_revision = "0061_customization_option_defaults"
branch_labels = None
depends_on = None


domain_kind = postgresql.ENUM(
    "PLATFORM_SUBDOMAIN",
    "CUSTOM",
    name="app_client_domain_kind",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    domain_kind.create(bind, checkfirst=True)

    if "app_client_domains" not in set(inspector.get_table_names()):
        op.create_table(
            "app_client_domains",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column(
                "app_client_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("app_clients.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("host", sa.String(255), nullable=False),
            sa.Column(
                "kind",
                domain_kind,
                nullable=False,
                server_default="PLATFORM_SUBDOMAIN",
            ),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("verification_token", sa.String(64), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
        # The whole safety property of this table: one address, one tenant,
        # decided by the database rather than by whichever query runs.
        op.create_unique_constraint(
            "uq_app_client_domains_host", "app_client_domains", ["host"]
        )
        op.create_index(
            "ix_app_client_domains_host", "app_client_domains", ["host"]
        )

    # Every single-restaurant client that has none gets its platform subdomain,
    # derived from the app key it already has. Nothing resolves by host until
    # this exists, so an environment upgraded without it would serve the
    # marketplace fallback to a tenant's own customers.
    bind.execute(
        sa.text(
            """
            INSERT INTO app_client_domains
                (id, app_client_id, host, kind, is_primary, is_verified, is_active,
                 created_at, updated_at)
            SELECT
                gen_random_uuid(),
                c.id,
                -- Hostnames cannot contain underscores and app keys can
                -- ('bangkok_bowl'), so the label is hyphenated the same way
                -- `_to_host_label` does it in the service.
                replace(lower(c.key), '_', '-') || '.' || :suffix,
                'PLATFORM_SUBDOMAIN',
                true,
                true,
                true,
                now(),
                now()
            FROM app_clients c
            WHERE c.app_mode = 'SINGLE_RESTAURANT'
              AND NOT EXISTS (
                  SELECT 1 FROM app_client_domains d WHERE d.app_client_id = c.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM app_client_domains d
                  WHERE d.host = replace(lower(c.key), '_', '-') || '.' || :suffix
              )
            """
        ),
        {"suffix": _platform_domain_suffix()},
    )


def _platform_domain_suffix() -> str:
    """The domain tenant subdomains hang off, from settings.

    Read at migration time rather than hardcoded, so a deployment that runs
    on its own domain backfills addresses that actually resolve.
    """

    try:
        from app.config import get_settings

        suffix = (get_settings().platform_domain or "").strip().lstrip(".")
    except Exception:  # noqa: BLE001 - a migration must not fail on config
        suffix = ""
    return suffix or "localhost"


def downgrade() -> None:
    bind = op.get_bind()
    if "app_client_domains" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("app_client_domains")
    domain_kind.drop(bind, checkfirst=True)

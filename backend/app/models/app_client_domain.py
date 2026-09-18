"""The web address a tenant's storefront answers on.

A mobile build says who it is with a bundle id, which the app store fixes at
release time. A web build cannot: one deployment serves every tenant, and the
only thing distinguishing one request from another is the host it arrived on.
So the host is the tenant's identifier, and this is where the mapping lives.

**Not a row in `app_client_identifiers`**, though the shape looks similar.
That table is keyed on `(platform, identifier, environment)`, which would let
a STAGING row and a PROD row both claim `bangkokbowl.example.com` — meaningless
for a host, since a request carries no environment. Its `platform` enum is also
load-bearing in a dozen places that assume exactly iOS and Android
(`ios_bundle_id`, `_new_prod_identifiers`, `_sync_prod_identifiers`,
`validate_app_client_identity_is_available`), each of which would grow a branch
for a value that is not a platform at all. And a domain needs state a bundle id
never has: which one is canonical, whether the tenant has proved they own it,
and whether it is ours to issue or theirs to point at us.

`host` is globally unique, which is the whole safety property: one address can
only ever resolve to one tenant, enforced by the database rather than by
whichever query happens to run.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import AppClientDomainKind

if TYPE_CHECKING:
    from app.models.app_client import AppClient


class AppClientDomain(TimestampMixin, Base):
    """One host that resolves to one app client."""

    __tablename__ = "app_client_domains"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Stored already normalised — lowercase, no port, no trailing dot, no
    # leading "www." — so the unique constraint means what it looks like it
    # means. `normalize_host` in `services/app_clients.py` is the one place
    # that decides what normalised is; nothing writes here without it.
    host: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    kind: Mapped[AppClientDomainKind] = mapped_column(
        Enum(AppClientDomainKind, name="app_client_domain_kind"),
        nullable=False,
        default=AppClientDomainKind.PLATFORM_SUBDOMAIN,
        server_default=AppClientDomainKind.PLATFORM_SUBDOMAIN.value,
    )
    # Which address the tenant's own links should use when there are several.
    # A tenant keeps their platform subdomain working after they point a
    # custom domain at us, but only one of them belongs in an email.
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    # A subdomain we issued is ours and needs no proving. A domain somebody
    # else owns does, or anyone could claim `mcdonalds.com` and be served
    # their storefront's branding.
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    verification_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    app_client: Mapped["AppClient"] = relationship(back_populates="domains")

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, Boolean, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import (
    AppClientEnvironment,
    AppClientPlatform,
    AppClientStatus,
    AppMode,
)

if TYPE_CHECKING:
    from app.models.restaurant import Restaurant

BRANDING_PRIMARY_COLOR_KEY = "primary_color"
CONFIG_MINIMUM_SUPPORTED_VERSION_KEY = "minimum_supported_version"


class AppClient(TimestampMixin, Base):
    """Per-app identity for a branded mobile build.

    A `SINGLE_RESTAURANT` client is linked to the restaurant it serves. A
    `MARKETPLACE` client has no `restaurant_id` and spans every restaurant.
    """

    __tablename__ = "app_clients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    app_mode: Mapped[AppMode] = mapped_column(
        Enum(AppMode, name="app_mode"),
        nullable=False,
        index=True,
    )
    restaurant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    status: Mapped[AppClientStatus] = mapped_column(
        Enum(AppClientStatus, name="app_client_status"),
        nullable=False,
        default=AppClientStatus.ACTIVE,
        server_default=AppClientStatus.ACTIVE.value,
        index=True,
    )
    order_number_prefix: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="MP",
        server_default="MP",
    )
    branding: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    restaurant: Mapped["Restaurant | None"] = relationship(back_populates="app_client")
    identifiers: Mapped[list["AppClientIdentifier"]] = relationship(
        back_populates="app_client",
        cascade="all, delete-orphan",
        order_by="AppClientIdentifier.platform.asc()",
    )
    order_sequence: Mapped["AppClientOrderSequence | None"] = relationship(
        back_populates="app_client",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @property
    def brand_primary_color(self) -> str | None:
        value = self.branding.get(BRANDING_PRIMARY_COLOR_KEY) if self.branding else None
        return value if isinstance(value, str) else None

    @property
    def minimum_supported_version(self) -> str | None:
        value = self.config.get(CONFIG_MINIMUM_SUPPORTED_VERSION_KEY) if self.config else None
        return value if isinstance(value, str) else None

    def _identifier_for(self, platform: AppClientPlatform) -> str | None:
        for identifier in self.identifiers:
            if identifier.platform == platform and identifier.environment == AppClientEnvironment.PROD:
                return identifier.identifier
        return None

    @property
    def ios_bundle_id(self) -> str | None:
        return self._identifier_for(AppClientPlatform.IOS)

    @property
    def android_package_name(self) -> str | None:
        return self._identifier_for(AppClientPlatform.ANDROID)


class AppClientIdentifier(TimestampMixin, Base):
    """Bundle id / package name for one platform and environment of an app client."""

    __tablename__ = "app_client_identifiers"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "identifier",
            "environment",
            name="uq_app_client_identifiers_platform_identifier_environment",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[AppClientPlatform] = mapped_column(
        Enum(AppClientPlatform, name="app_client_platform"),
        nullable=False,
    )
    identifier: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    environment: Mapped[AppClientEnvironment] = mapped_column(
        Enum(AppClientEnvironment, name="app_client_environment"),
        nullable=False,
        default=AppClientEnvironment.PROD,
        server_default=AppClientEnvironment.PROD.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    app_client: Mapped["AppClient"] = relationship(back_populates="identifiers")


class AppClientOrderSequence(TimestampMixin, Base):
    """Per-app order number counter, paired with `AppClient.order_number_prefix`."""

    __tablename__ = "app_client_order_sequences"

    app_client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_clients.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    app_client: Mapped["AppClient"] = relationship(back_populates="order_sequence")

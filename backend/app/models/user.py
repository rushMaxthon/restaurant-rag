from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.app_client import AppClient
    from app.models.chat_history import ChatHistory
    from app.models.favorite import Favorite
    from app.models.order import Order
    from app.models.personalized_recommendation_snapshot import PersonalizedRecommendationSnapshot
    from app.models.push_notification_campaign import PushNotificationCampaign
    from app.models.restaurant import Restaurant
    from app.models.user_device_token import UserDeviceToken
    from app.models.user_saved_address import UserSavedAddress
    from app.models.user_preferences import UserPreferences


class User(TimestampMixin, Base):
    """A person's account within one app.

    Identity is scoped by `app_client_id`: the same email or phone may exist once
    per app client, so a Bangkok Bowl customer and a Marketplace customer are
    separate accounts even when they are the same person. ADMIN and OWNER are
    platform staff and carry no app client at all.

    Uniqueness lives in partial indexes that SQLAlchemy cannot express, so they
    are defined in migration `0036_user_token_version` rather than here:

    * `uq_users_app_client_id_email_customer` - (app_client_id, lower(email)) for CUSTOMER
    * `uq_users_app_client_id_phone_number_customer` - (app_client_id, phone_number) for CUSTOMER
    * `uq_users_email_platform` / `uq_users_phone_number_platform` - global, for ADMIN/OWNER

    A CHECK constraint (`ck_users_app_client_scope_matches_role`) enforces the
    CUSTOMER/staff split, so `app_client_id` must be set explicitly on every
    insert; leaving it to the default fails at the database.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    app_client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_clients.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Not unique on its own: uniqueness is per app client for customers and
    # platform-wide for staff, via the partial indexes described above.
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    phone_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    default_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Bumped to invalidate every token already issued to this user.
    token_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    app_client: Mapped["AppClient | None"] = relationship(foreign_keys=[app_client_id])

    owned_restaurant: Mapped["Restaurant | None"] = relationship(
        back_populates="owner",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="Restaurant.owner_id",
    )
    customer_orders: Mapped[list["Order"]] = relationship(
        back_populates="customer",
        foreign_keys="Order.customer_id",
    )
    preferences: Mapped["UserPreferences | None"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    personalized_recommendation_snapshot: Mapped["PersonalizedRecommendationSnapshot | None"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    chat_messages: Mapped[list["ChatHistory"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    favorites: Mapped[list["Favorite"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    saved_addresses: Mapped[list["UserSavedAddress"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        order_by="desc(UserSavedAddress.is_default), desc(UserSavedAddress.updated_at)",
    )
    device_tokens: Mapped[list["UserDeviceToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    created_push_notification_campaigns: Mapped[list["PushNotificationCampaign"]] = relationship(
        foreign_keys="PushNotificationCampaign.created_by_user_id",
        back_populates="created_by_user",
    )
    targeted_push_notification_campaigns: Mapped[list["PushNotificationCampaign"]] = relationship(
        foreign_keys="PushNotificationCampaign.specific_user_id",
        back_populates="specific_user",
    )

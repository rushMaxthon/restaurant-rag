from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
)
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
    from app.models.restaurant_location import RestaurantLocation
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
    insert; leaving it to the default fails at the database. KITCHEN is staff
    for that constraint's purposes and so carries no app client either.
    """

    __tablename__ = "users"
    # Mirrors migration 0071. Declared here as well as there because the test
    # suites build their schema from `Base.metadata.create_all` and never run
    # a migration — without these a throwaway test database would accept a
    # kitchen account with no restaurant, which is the one state that would
    # let it read every order on the platform.
    #
    # `ck_users_app_client_scope_matches_role` is NOT repeated here: it
    # predates this pattern and stays migration-only, as its own docstring in
    # 0036 describes.
    __table_args__ = (
        CheckConstraint(
            "(role = 'KITCHEN' AND staff_restaurant_id IS NOT NULL) "
            "OR (role <> 'KITCHEN' "
            "AND staff_restaurant_id IS NULL "
            "AND staff_restaurant_location_id IS NULL)",
            # The metadata convention is "ck_%(table_name)s_%(constraint_name)s",
            # so this bare name is what produces `ck_users_kitchen_assignment` —
            # the same name migration 0071 creates. Spelling the full name here
            # yields `ck_users_ck_users_kitchen_assignment`.
            name="kitchen_assignment",
        ),
        # Composite, so the branch must belong to the restaurant named beside
        # it. A NULL location satisfies it by default (MATCH SIMPLE), which is
        # the "every branch of this restaurant" case.
        ForeignKeyConstraint(
            ["staff_restaurant_location_id", "staff_restaurant_id"],
            ["restaurant_locations.id", "restaurant_locations.restaurant_id"],
            name="fk_users_staff_location_matches_restaurant",
            ondelete="RESTRICT",
        ),
    )

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
    # Where a KITCHEN account works, and NULL for every other role.
    #
    # An OWNER reaches their restaurant through `Restaurant.owner_id` and an
    # ADMIN names one per request; a cook can do neither, so the assignment is
    # stored. `ck_users_kitchen_assignment` (migration 0072) makes the pairing
    # exhaustive: KITCHEN must have a restaurant, everyone else must have
    # neither column set. So "a kitchen account with no restaurant" — which
    # would read every order on the platform — cannot be written at all.
    staff_restaurant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # The one branch this account sees, or NULL for every branch of the
    # restaurant above. NULL is a real answer: a single-branch restaurant has
    # nothing to pin, and a head kitchen may legitimately watch all of them.
    #
    # There is no plain foreign key here. The composite one in 0072 points at
    # `(id, restaurant_id)`, so a branch belonging to a DIFFERENT restaurant
    # than `staff_restaurant_id` is rejected by the database rather than by a
    # check somebody has to remember to write.
    staff_restaurant_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    # Marketing consent, opt-out: true until the customer says otherwise.
    #
    # It lives on `users` rather than on `user_preferences` for two reasons.
    # `user_preferences` is a derived recommender profile - it is recalculated
    # by scoring jobs (`last_recalculated_at`) and a row may simply not exist
    # for a given user, both of which are disqualifying for a consent record
    # that must never be recomputed and must always have an answer. Second,
    # every reach query already filters `users` on `is_active`/`app_client_id`,
    # so keeping consent here costs no extra join on the hottest path.
    #
    # Transactional pushes ignore this flag entirely; suppressing an order
    # update because someone declined marketing would be a fault.
    marketing_opt_in: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    # Null means "never expressed a preference" and is meaningfully different
    # from an explicit opt-in: it is the difference between an assumption and a
    # decision, which is the first thing asked for if consent is ever queried.
    marketing_opt_in_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    app_client: Mapped["AppClient | None"] = relationship(foreign_keys=[app_client_id])

    owned_restaurant: Mapped["Restaurant | None"] = relationship(
        back_populates="owner",
        uselist=False,
        cascade="all, delete-orphan",
        foreign_keys="Restaurant.owner_id",
    )
    # Read-only views onto the assignment above. `viewonly` because the
    # composite foreign key spans two columns and SQLAlchemy must not try to
    # maintain either side of it from here.
    staff_restaurant: Mapped["Restaurant | None"] = relationship(
        foreign_keys=[staff_restaurant_id],
        viewonly=True,
    )
    staff_restaurant_location: Mapped["RestaurantLocation | None"] = relationship(
        primaryjoin="User.staff_restaurant_location_id == RestaurantLocation.id",
        foreign_keys=[staff_restaurant_location_id],
        viewonly=True,
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

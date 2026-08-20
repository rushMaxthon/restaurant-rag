from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import (
    PersonalizedOfferAudience,
    PersonalizedOfferDiscountType,
    PersonalizedOfferEventType,
    PersonalizedOfferGenerationReason,
    PersonalizedOfferSource,
    PersonalizedOfferState,
    PersonalizedOfferType,
)

if TYPE_CHECKING:
    from app.models.generated_combo import GeneratedCombo
    from app.models.menu_item import MenuItem
    from app.models.restaurant import Restaurant
    from app.models.restaurant_location import RestaurantLocation
    from app.models.user import User
    from app.models.generated_combo import GeneratedCombo


class PersonalizedOffer(TimestampMixin, Base):
    __tablename__ = "personalized_offers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    restaurant_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurant_locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    applicable_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menu_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    offer_type: Mapped[PersonalizedOfferType] = mapped_column(
        Enum(PersonalizedOfferType, name="personalized_offer_type"),
        nullable=False,
        index=True,
    )
    audience_type: Mapped[PersonalizedOfferAudience] = mapped_column(
        Enum(PersonalizedOfferAudience, name="personalized_offer_audience"),
        nullable=False,
        default=PersonalizedOfferAudience.INACTIVE_USERS,
        server_default=PersonalizedOfferAudience.INACTIVE_USERS.value,
        index=True,
    )
    state: Mapped[PersonalizedOfferState] = mapped_column(
        Enum(PersonalizedOfferState, name="personalized_offer_state"),
        nullable=False,
        default=PersonalizedOfferState.DRAFT,
        server_default=PersonalizedOfferState.DRAFT.value,
        index=True,
    )
    discount_type: Mapped[PersonalizedOfferDiscountType] = mapped_column(
        Enum(PersonalizedOfferDiscountType, name="personalized_offer_discount_type"),
        nullable=False,
        default=PersonalizedOfferDiscountType.NONE,
        server_default=PersonalizedOfferDiscountType.NONE.value,
    )
    discount_value: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    max_discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    minimum_order_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    inactivity_days: Mapped[int] = mapped_column(Integer, nullable=False, default=14, server_default="14")
    cooldown_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=48, server_default="48")
    valid_for_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    applicable_category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    applicable_cuisine: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cta_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    business_rules: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    restaurant: Mapped["Restaurant"] = relationship()
    restaurant_location: Mapped["RestaurantLocation | None"] = relationship()
    applicable_item: Mapped["MenuItem | None"] = relationship()
    events: Mapped[list["PersonalizedOfferEvent"]] = relationship(
        back_populates="offer",
        cascade="all, delete-orphan",
        order_by="PersonalizedOfferEvent.created_at.desc()",
    )
    generated_offers: Mapped[list["GeneratedOffer"]] = relationship(
        back_populates="template_offer",
        cascade="all, delete-orphan",
        order_by="GeneratedOffer.created_at.desc()",
    )


class GeneratedOffer(TimestampMixin, Base):
    __tablename__ = "generated_offers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    template_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personalized_offers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    generated_for_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    restaurant_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurant_locations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    applicable_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("menu_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generated_combo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generated_combos.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source: Mapped[PersonalizedOfferSource] = mapped_column(
        Enum(PersonalizedOfferSource, name="personalized_offer_source"),
        nullable=False,
        default=PersonalizedOfferSource.AI_GENERATED,
        server_default=PersonalizedOfferSource.AI_GENERATED.value,
        index=True,
    )
    generation_reason: Mapped[PersonalizedOfferGenerationReason] = mapped_column(
        Enum(PersonalizedOfferGenerationReason, name="personalized_offer_generation_reason"),
        nullable=False,
        index=True,
    )
    state: Mapped[PersonalizedOfferState] = mapped_column(
        Enum(PersonalizedOfferState, name="personalized_offer_state"),
        nullable=False,
        default=PersonalizedOfferState.DRAFT,
        server_default=PersonalizedOfferState.DRAFT.value,
        index=True,
    )
    offer_type: Mapped[PersonalizedOfferType] = mapped_column(
        Enum(PersonalizedOfferType, name="personalized_offer_type"),
        nullable=False,
        index=True,
    )
    audience_type: Mapped[PersonalizedOfferAudience] = mapped_column(
        Enum(PersonalizedOfferAudience, name="personalized_offer_audience"),
        nullable=False,
        default=PersonalizedOfferAudience.ALL_CUSTOMERS,
        server_default=PersonalizedOfferAudience.ALL_CUSTOMERS.value,
        index=True,
    )
    applicable_category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    applicable_cuisine: Mapped[str | None] = mapped_column(String(120), nullable=True)
    generated_title: Mapped[str] = mapped_column(String(255), nullable=False)
    generated_subtitle: Mapped[str] = mapped_column(Text, nullable=False)
    generated_badge: Mapped[str | None] = mapped_column(String(80), nullable=True)
    generated_cta_label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    discount_type: Mapped[PersonalizedOfferDiscountType] = mapped_column(
        Enum(PersonalizedOfferDiscountType, name="personalized_offer_discount_type"),
        nullable=False,
        default=PersonalizedOfferDiscountType.NONE,
        server_default=PersonalizedOfferDiscountType.NONE.value,
    )
    discount_value: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    max_discount_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    minimum_order_amount: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    valid_for_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7, server_default="7")
    score: Mapped[Decimal] = mapped_column(
        Numeric(8, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    eligible_user_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    click_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    conversion_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    business_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    template_offer: Mapped["PersonalizedOffer | None"] = relationship(back_populates="generated_offers")
    generated_for_user: Mapped["User | None"] = relationship()
    restaurant: Mapped["Restaurant"] = relationship()
    restaurant_location: Mapped["RestaurantLocation | None"] = relationship()
    applicable_item: Mapped["MenuItem | None"] = relationship()
    generated_combo: Mapped["GeneratedCombo | None"] = relationship()
    user_matches: Mapped[list["GeneratedOfferUserMatch"]] = relationship(
        back_populates="generated_offer",
        cascade="all, delete-orphan",
        order_by="GeneratedOfferUserMatch.created_at.desc()",
    )


class GeneratedOfferUserMatch(TimestampMixin, Base):
    __tablename__ = "generated_offer_user_matches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    generated_offer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generated_offers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    matched_reason: Mapped[PersonalizedOfferGenerationReason] = mapped_column(
        Enum(PersonalizedOfferGenerationReason, name="personalized_offer_generation_reason"),
        nullable=False,
        index=True,
    )
    score: Mapped[Decimal] = mapped_column(
        Numeric(8, 2),
        nullable=False,
        default=Decimal("0.00"),
        server_default="0.00",
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_current: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true", index=True)
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    click_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    conversion_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    match_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    generated_offer: Mapped["GeneratedOffer"] = relationship(back_populates="user_matches")
    user: Mapped["User"] = relationship()


class PersonalizedOfferEvent(TimestampMixin, Base):
    __tablename__ = "personalized_offer_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personalized_offers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[PersonalizedOfferEventType] = mapped_column(
        Enum(PersonalizedOfferEventType, name="personalized_offer_event_type"),
        nullable=False,
        index=True,
    )
    target_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    target_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # The order this conversion produced. Previously this lived only as a string
    # inside `event_metadata`, which could not be joined or indexed; that key is
    # still written for backwards compatibility.
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="SET NULL", name="fk_offer_events_order"),
        nullable=True,
        index=True,
    )
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generated_offer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generated_offers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    generated_offer_user_match_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("generated_offer_user_matches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    offer: Mapped["PersonalizedOffer | None"] = relationship(back_populates="events")
    user: Mapped["User"] = relationship()
    generated_offer: Mapped["GeneratedOffer | None"] = relationship()
    generated_offer_user_match: Mapped["GeneratedOfferUserMatch | None"] = relationship()

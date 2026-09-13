"""The preference questionnaire, as data.

Four tables:

* `PreferenceQuestion` - a question, global (``restaurant_id`` null) or owned by
  one restaurant.
* `PreferenceOption` - a choice under a question, carrying the metadata the
  scoring engine needs to interpret it.
* `PreferenceQuestionOverride` - how a restaurant hides a platform question
  without deleting it for anyone else.
* `UserPreferenceAnswer` - one row per selected option, or per free-text entry.

`user_preferences` is deliberately left alone. It stays as a projection of these
answers so the recommendation engine keeps reading exactly what it reads today.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin
from app.models.enums import PreferenceInputType, PreferenceSignalRole

if TYPE_CHECKING:
    from app.models.restaurant import Restaurant
    from app.models.user import User


class PreferenceQuestion(TimestampMixin, Base):
    __tablename__ = "preference_questions"
    __table_args__ = (
        Index(
            "uq_preference_questions_scope_key",
            "restaurant_id",
            "key",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_preference_questions_lookup",
            "restaurant_id",
            "is_active",
            "display_order",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    #: Null for a platform question every restaurant inherits.
    restaurant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=True,
    )
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt: Mapped[str] = mapped_column(String(255), nullable=False)
    help_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_type: Mapped[PreferenceInputType] = mapped_column(
        Enum(PreferenceInputType, name="preference_input_type"),
        nullable=False,
    )
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    min_selections: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    #: Null means unlimited.
    max_selections: Mapped[int | None] = mapped_column(Integer, nullable=True)
    allows_free_text: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    signal_role: Mapped[PreferenceSignalRole] = mapped_column(
        Enum(PreferenceSignalRole, name="preference_signal_role"),
        nullable=False,
        default=PreferenceSignalRole.NONE,
        server_default=PreferenceSignalRole.NONE.value,
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    restaurant: Mapped["Restaurant | None"] = relationship()
    options: Mapped[list["PreferenceOption"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="PreferenceOption.display_order",
    )
    overrides: Mapped[list["PreferenceQuestionOverride"]] = relationship(
        back_populates="question",
        cascade="all, delete-orphan",
    )

    @property
    def is_global(self) -> bool:
        return self.restaurant_id is None

    @property
    def is_live(self) -> bool:
        return self.is_active and self.deleted_at is None


class PreferenceOption(TimestampMixin, Base):
    __tablename__ = "preference_options"
    __table_args__ = (
        Index(
            "uq_preference_options_question_value",
            "question_id",
            "value",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_preference_options_lookup",
            "question_id",
            "is_active",
            "display_order",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("preference_questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    value: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    help_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Interpretation for the scoring engine, so an owner can add an option that
    #: actually affects ranking. `{"is_veg": true}` on a diet option;
    #: `{"amount": 420}` on a budget tier; `{"level": "HIGH"}` on spice.
    option_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    question: Mapped[PreferenceQuestion] = relationship(back_populates="options")

    @property
    def is_live(self) -> bool:
        return self.is_active and self.deleted_at is None


class PreferenceQuestionOverride(TimestampMixin, Base):
    """One restaurant's opt-out from a platform question.

    Deactivating the global row would remove the question from every tenant, so
    a restaurant that does not want it records the decision here instead. The
    global question stays exactly as it is for everyone else.
    """

    __tablename__ = "preference_question_overrides"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "question_id", name="uq_preference_question_overrides_scope"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("preference_questions.id", ondelete="CASCADE"),
        nullable=False,
    )
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
    #: Lets a restaurant reposition an inherited question without copying it.
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)

    question: Mapped[PreferenceQuestion] = relationship(back_populates="overrides")
    restaurant: Mapped["Restaurant"] = relationship()


class UserPreferenceAnswer(TimestampMixin, Base):
    """One selected option, or one free-text entry.

    Multi-select produces several rows. Nothing here is typed to a particular
    question, which is the point: a new preference costs a row, never a column.
    """

    __tablename__ = "user_preference_answers"
    __table_args__ = (
        CheckConstraint(
            "option_id IS NOT NULL OR free_text IS NOT NULL",
            name="ck_user_preference_answers_has_value",
        ),
        Index("ix_user_preference_answers_user", "user_id"),
        Index(
            "uq_user_preference_answers_option",
            "user_id",
            "question_id",
            "option_id",
            unique=True,
            postgresql_where=text("option_id IS NOT NULL"),
        ),
        # Postgres treats NULLs as distinct, so the index above does not stop a
        # customer storing the same free-text favourite five times. This does,
        # case-insensitively.
        Index(
            "uq_user_preference_answers_free_text",
            "user_id",
            "question_id",
            text("lower(free_text)"),
            unique=True,
            postgresql_where=text("option_id IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: RESTRICT on purpose - retiring a question must never take answers with it.
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("preference_questions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    option_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("preference_options.id", ondelete="RESTRICT"),
        nullable=True,
    )
    free_text: Mapped[str | None] = mapped_column(String(120), nullable=True)

    user: Mapped["User"] = relationship()
    question: Mapped[PreferenceQuestion] = relationship()
    option: Mapped[PreferenceOption | None] = relationship()

    @property
    def display_value(self) -> str:
        """What the customer actually chose, however it was stored."""

        if self.option is not None:
            return self.option.label
        return self.free_text or ""

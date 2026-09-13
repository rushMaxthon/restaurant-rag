"""Managing the questionnaire.

Two audiences with different powers, enforced in one place:

* A **platform admin** owns the global questions every restaurant inherits.
* An **owner** manages their own restaurant's questions, and may hide an
  inherited one for themselves. They can never edit or delete a global question,
  because it belongs to every other tenant too.

Deletes are always soft. The answer table's foreign key refuses a hard delete
anyway, but refusing it here produces a sentence an owner can act on rather than
a constraint violation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config.database import get_db
from app.models.enums import UserRole
from app.models.preference import (
    PreferenceOption,
    PreferenceQuestion,
    PreferenceQuestionOverride,
    UserPreferenceAnswer,
)
from app.models.user import User
from app.schemas.preference_admin import (
    AdminPreferenceOptionResponse,
    AdminPreferenceQuestionResponse,
    PreferenceOptionCreate,
    PreferenceOptionUpdate,
    PreferenceQuestionCreate,
    PreferenceQuestionUpdate,
    PreferenceReorderRequest,
    PreferenceVisibilityRequest,
)
from app.services.auth import get_current_user, resolve_owner_restaurant_id

router = APIRouter(prefix="/admin/preferences", tags=["Preference Admin"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def _scope(db: Session, user: User) -> uuid.UUID | None:
    """The restaurant this caller manages, or None for the platform admin."""

    if user.role == UserRole.ADMIN:
        return None
    if user.role == UserRole.OWNER:
        return resolve_owner_restaurant_id(db, user)
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to manage preferences",
    )


def _load_question(db: Session, question_id: uuid.UUID) -> PreferenceQuestion:
    question = db.scalar(
        select(PreferenceQuestion)
        .options(selectinload(PreferenceQuestion.options))
        .where(PreferenceQuestion.id == question_id, PreferenceQuestion.deleted_at.is_(None))
    )
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
    return question


def _assert_writable(question: PreferenceQuestion, scope: uuid.UUID | None) -> None:
    """Refuse an edit the caller does not own.

    An owner reaching a global question is the case worth a clear message: it is
    not theirs to change, but hiding it is available and does not affect anyone
    else.
    """

    if scope is None:
        if question.restaurant_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This question belongs to a restaurant. Manage it from that restaurant.",
            )
        return

    if question.restaurant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "This is a platform question shared with every restaurant and cannot be edited "
                "here. You can hide it for your restaurant instead."
            ),
        )
    if question.restaurant_id != scope:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")


def _answer_counts(db: Session, question_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not question_ids:
        return {}
    rows = db.execute(
        select(UserPreferenceAnswer.question_id, func.count())
        .where(UserPreferenceAnswer.question_id.in_(question_ids))
        .group_by(UserPreferenceAnswer.question_id)
    ).all()
    return {question_id: count for question_id, count in rows}


def _serialize(
    question: PreferenceQuestion,
    *,
    scope: uuid.UUID | None,
    hidden: bool,
    answer_count: int,
) -> AdminPreferenceQuestionResponse:
    return AdminPreferenceQuestionResponse(
        id=question.id,
        restaurant_id=question.restaurant_id,
        key=question.key,
        prompt=question.prompt,
        help_text=question.help_text,
        input_type=question.input_type,
        is_required=question.is_required,
        min_selections=question.min_selections,
        max_selections=question.max_selections,
        allows_free_text=question.allows_free_text,
        signal_role=question.signal_role,
        display_order=question.display_order,
        is_active=question.is_active,
        is_inherited=question.restaurant_id is None and scope is not None,
        is_hidden_here=hidden,
        answer_count=answer_count,
        options=[
            AdminPreferenceOptionResponse.model_validate(option)
            for option in sorted(
                (option for option in question.options if option.deleted_at is None),
                key=lambda option: option.display_order,
            )
        ],
    )


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------


@router.get("/questions", response_model=list[AdminPreferenceQuestionResponse])
def list_questions(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    include_inactive: bool = Query(default=True),
) -> list[AdminPreferenceQuestionResponse]:
    """Everything this caller can see: their own questions, plus inherited ones."""

    scope = _scope(db, current_user)

    query = (
        select(PreferenceQuestion)
        .options(selectinload(PreferenceQuestion.options))
        .where(PreferenceQuestion.deleted_at.is_(None))
    )
    if scope is None:
        query = query.where(PreferenceQuestion.restaurant_id.is_(None))
    else:
        query = query.where(
            (PreferenceQuestion.restaurant_id.is_(None))
            | (PreferenceQuestion.restaurant_id == scope)
        )
    if not include_inactive:
        query = query.where(PreferenceQuestion.is_active.is_(True))

    questions = list(db.scalars(query).unique())

    hidden: set[uuid.UUID] = set()
    if scope is not None:
        hidden = {
            override.question_id
            for override in db.scalars(
                select(PreferenceQuestionOverride).where(
                    PreferenceQuestionOverride.restaurant_id == scope,
                    PreferenceQuestionOverride.is_hidden.is_(True),
                )
            )
        }

    counts = _answer_counts(db, [question.id for question in questions])
    serialized = [
        _serialize(
            question,
            scope=scope,
            hidden=question.id in hidden,
            answer_count=counts.get(question.id, 0),
        )
        for question in questions
    ]
    serialized.sort(key=lambda entry: (entry.display_order, entry.key))
    return serialized


@router.post("/questions", response_model=AdminPreferenceQuestionResponse, status_code=status.HTTP_201_CREATED)
def create_question(
    payload: PreferenceQuestionCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AdminPreferenceQuestionResponse:
    scope = _scope(db, current_user)

    clash = db.scalar(
        select(PreferenceQuestion.id).where(
            PreferenceQuestion.key == payload.key,
            PreferenceQuestion.deleted_at.is_(None),
            PreferenceQuestion.restaurant_id.is_(None) if scope is None else PreferenceQuestion.restaurant_id == scope,
        )
    )
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A question with the key '{payload.key}' already exists here.",
        )

    # Ordered after everything the caller can see, not just after their own
    # questions. An owner has no questions of their own to begin with, so taking
    # the max over those alone gave every new question `display_order = 1` and
    # dropped it above the five inherited ones.
    visible_scope = (
        PreferenceQuestion.restaurant_id.is_(None)
        if scope is None
        else (PreferenceQuestion.restaurant_id.is_(None))
        | (PreferenceQuestion.restaurant_id == scope)
    )
    next_order = (
        db.scalar(
            select(func.coalesce(func.max(PreferenceQuestion.display_order), 0)).where(
                PreferenceQuestion.deleted_at.is_(None),
                visible_scope,
            )
        )
        or 0
    )

    question = PreferenceQuestion(
        restaurant_id=scope,
        key=payload.key,
        prompt=payload.prompt,
        help_text=payload.help_text,
        input_type=payload.input_type,
        is_required=payload.is_required,
        min_selections=payload.min_selections,
        max_selections=payload.max_selections,
        allows_free_text=payload.allows_free_text,
        signal_role=payload.signal_role,
        display_order=next_order + 1,
        is_active=payload.is_active,
    )
    db.add(question)
    db.flush()

    for index, option in enumerate(payload.options, start=1):
        db.add(
            PreferenceOption(
                question_id=question.id,
                value=option.value,
                label=option.label,
                help_text=option.help_text,
                option_metadata=option.metadata,
                display_order=option.display_order or index,
                is_active=option.is_active,
            )
        )

    db.commit()
    db.refresh(question)
    return _serialize(question, scope=scope, hidden=False, answer_count=0)


@router.patch("/questions/{question_id}", response_model=AdminPreferenceQuestionResponse)
def update_question(
    question_id: uuid.UUID,
    payload: PreferenceQuestionUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AdminPreferenceQuestionResponse:
    scope = _scope(db, current_user)
    question = _load_question(db, question_id)
    _assert_writable(question, scope)

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(question, field, value)

    db.commit()
    db.refresh(question)
    counts = _answer_counts(db, [question.id])
    return _serialize(question, scope=scope, hidden=False, answer_count=counts.get(question.id, 0))


@router.delete(
    "/questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_question(
    question_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Retire a question. Always a soft delete - answers are never destroyed."""

    scope = _scope(db, current_user)
    question = _load_question(db, question_id)
    _assert_writable(question, scope)

    question.deleted_at = datetime.now(UTC)
    question.is_active = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/questions/{question_id}/visibility", response_model=AdminPreferenceQuestionResponse)
def set_question_visibility(
    question_id: uuid.UUID,
    payload: PreferenceVisibilityRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AdminPreferenceQuestionResponse:
    """Hide or restore an inherited question, for this restaurant only.

    This is the owner's alternative to editing a platform question: the global
    row is untouched and every other restaurant keeps asking it.
    """

    scope = _scope(db, current_user)
    if scope is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Platform questions are hidden per restaurant. Deactivate it instead.",
        )

    question = _load_question(db, question_id)
    if question.restaurant_id not in (None, scope):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")

    if question.restaurant_id == scope:
        # Their own question: activation is the natural control, no override row.
        question.is_active = not payload.is_hidden
    else:
        override = db.scalar(
            select(PreferenceQuestionOverride).where(
                PreferenceQuestionOverride.restaurant_id == scope,
                PreferenceQuestionOverride.question_id == question.id,
            )
        )
        if override is None:
            override = PreferenceQuestionOverride(restaurant_id=scope, question_id=question.id)
            db.add(override)
        override.is_hidden = payload.is_hidden

    db.commit()
    db.refresh(question)
    counts = _answer_counts(db, [question.id])
    return _serialize(
        question,
        scope=scope,
        hidden=payload.is_hidden and question.restaurant_id != scope,
        answer_count=counts.get(question.id, 0),
    )


@router.post("/questions/reorder", response_model=list[AdminPreferenceQuestionResponse])
def reorder_questions(
    payload: PreferenceReorderRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[AdminPreferenceQuestionResponse]:
    """Set the order of the whole list in one call.

    An owner reordering an inherited question records the position on their
    override row rather than on the shared question, so the platform ordering is
    unaffected for everyone else.
    """

    scope = _scope(db, current_user)

    for position, question_id in enumerate(payload.ids, start=1):
        question = _load_question(db, question_id)
        if scope is not None and question.restaurant_id is None:
            override = db.scalar(
                select(PreferenceQuestionOverride).where(
                    PreferenceQuestionOverride.restaurant_id == scope,
                    PreferenceQuestionOverride.question_id == question.id,
                )
            )
            if override is None:
                override = PreferenceQuestionOverride(
                    restaurant_id=scope, question_id=question.id, is_hidden=False
                )
                db.add(override)
            override.display_order = position
        else:
            _assert_writable(question, scope)
            question.display_order = position

    db.commit()
    return list_questions(db, current_user)


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------


@router.post("/questions/{question_id}/options", response_model=AdminPreferenceOptionResponse, status_code=status.HTTP_201_CREATED)
def create_option(
    question_id: uuid.UUID,
    payload: PreferenceOptionCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AdminPreferenceOptionResponse:
    scope = _scope(db, current_user)
    question = _load_question(db, question_id)
    _assert_writable(question, scope)

    clash = db.scalar(
        select(PreferenceOption.id).where(
            PreferenceOption.question_id == question.id,
            PreferenceOption.value == payload.value,
            PreferenceOption.deleted_at.is_(None),
        )
    )
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"'{payload.value}' is already an option on this question.",
        )

    next_order = (
        db.scalar(
            select(func.coalesce(func.max(PreferenceOption.display_order), 0)).where(
                PreferenceOption.question_id == question.id
            )
        )
        or 0
    )

    option = PreferenceOption(
        question_id=question.id,
        value=payload.value,
        label=payload.label,
        help_text=payload.help_text,
        option_metadata=payload.metadata,
        display_order=payload.display_order or next_order + 1,
        is_active=payload.is_active,
    )
    db.add(option)
    db.commit()
    db.refresh(option)
    return AdminPreferenceOptionResponse.model_validate(option)


@router.patch("/options/{option_id}", response_model=AdminPreferenceOptionResponse)
def update_option(
    option_id: uuid.UUID,
    payload: PreferenceOptionUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> AdminPreferenceOptionResponse:
    scope = _scope(db, current_user)
    option = db.scalar(
        select(PreferenceOption).where(
            PreferenceOption.id == option_id, PreferenceOption.deleted_at.is_(None)
        )
    )
    if option is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Option not found")
    _assert_writable(_load_question(db, option.question_id), scope)

    data = payload.model_dump(exclude_unset=True)
    if "metadata" in data:
        option.option_metadata = data.pop("metadata")
    for field, value in data.items():
        setattr(option, field, value)

    db.commit()
    db.refresh(option)
    return AdminPreferenceOptionResponse.model_validate(option)


@router.delete(
    "/options/{option_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_option(
    option_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    """Withdraw an option. Soft, so customers who chose it keep their answer."""

    scope = _scope(db, current_user)
    option = db.scalar(
        select(PreferenceOption).where(
            PreferenceOption.id == option_id, PreferenceOption.deleted_at.is_(None)
        )
    )
    if option is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Option not found")
    _assert_writable(_load_question(db, option.question_id), scope)

    option.deleted_at = datetime.now(UTC)
    option.is_active = False
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/questions/{question_id}/options/reorder", response_model=list[AdminPreferenceOptionResponse])
def reorder_options(
    question_id: uuid.UUID,
    payload: PreferenceReorderRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[AdminPreferenceOptionResponse]:
    scope = _scope(db, current_user)
    question = _load_question(db, question_id)
    _assert_writable(question, scope)

    by_id = {option.id: option for option in question.options if option.deleted_at is None}
    for position, option_id in enumerate(payload.ids, start=1):
        option = by_id.get(option_id)
        if option is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reorder list contains an option that is not on this question.",
            )
        option.display_order = position

    db.commit()
    db.refresh(question)
    return [
        AdminPreferenceOptionResponse.model_validate(option)
        for option in sorted(
            (option for option in question.options if option.deleted_at is None),
            key=lambda option: option.display_order,
        )
    ]

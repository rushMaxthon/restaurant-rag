"""Resolving the questionnaire, and projecting answers back onto the legacy row.

Two responsibilities that belong together because they are two halves of the
same contract:

* **Resolution** decides which questions a given app should ask. Platform
  questions are inherited by every restaurant; a restaurant may add its own, and
  may hide an inherited one for itself without affecting anyone else.

* **Projection** rebuilds `user_preferences` from the answers. That table is no
  longer written directly by the API, but it is still what
  `services/recommendations.py` reads on every request. Keeping it as a derived
  copy is what lets the questionnaire become dynamic without touching a single
  line of the scoring engine - and what makes this change safe to ship.

The projection reads `signal_role` to know what an answer means, and reads an
option's `metadata` to know how to value it. Nothing here hardcodes a cuisine, a
diet or a budget tier, so an owner adding a diet option gets working scoring
without a deploy.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models.enums import PreferenceInputType, PreferenceSignalRole
from app.models.preference import (
    PreferenceOption,
    PreferenceQuestion,
    PreferenceQuestionOverride,
    UserPreferenceAnswer,
)
from app.models.user_preferences import UserPreferences

logger = logging.getLogger(__name__)

#: Mirrors `_budget_to_amount` / `_budget_to_sensitivity` in the recommender, and
#: is only a fallback: an option that carries its own `amount` and `sensitivity`
#: in metadata always wins. Kept so a budget option added without metadata still
#: produces sane numbers rather than zeroes.
BUDGET_FALLBACK: dict[str, tuple[float, float]] = {
    "LOW": (220.0, 0.7),
    "MID": (420.0, 1.0),
    "HIGH": (760.0, 1.35),
}


@dataclass(frozen=True)
class ResolvedQuestion:
    """A question as one app should render it."""

    question: PreferenceQuestion
    options: list[PreferenceOption]
    display_order: int
    #: True when this came from the platform rather than the restaurant. The
    #: admin UI uses it to show an owner what they may hide but not edit.
    is_inherited: bool


def _live_options(question: PreferenceQuestion) -> list[PreferenceOption]:
    return sorted(
        (option for option in question.options if option.is_live),
        key=lambda option: (option.display_order, option.label),
    )


def resolve_questionnaire(
    db: Session,
    *,
    restaurant_id: uuid.UUID | None,
) -> list[ResolvedQuestion]:
    """The active questions for one restaurant, in the order to ask them.

    Platform questions come first unless a restaurant has repositioned them.
    A restaurant question whose `key` matches a platform question replaces it,
    which is how an owner rewords an inherited question rather than hiding it
    and starting over.
    """

    query = (
        select(PreferenceQuestion)
        .options(selectinload(PreferenceQuestion.options))
        .where(
            PreferenceQuestion.deleted_at.is_(None),
            PreferenceQuestion.is_active.is_(True),
        )
    )
    if restaurant_id is None:
        query = query.where(PreferenceQuestion.restaurant_id.is_(None))
    else:
        query = query.where(
            (PreferenceQuestion.restaurant_id.is_(None))
            | (PreferenceQuestion.restaurant_id == restaurant_id)
        )

    questions = list(db.scalars(query).unique())

    hidden_ids: set[uuid.UUID] = set()
    order_overrides: dict[uuid.UUID, int] = {}
    if restaurant_id is not None:
        for override in db.scalars(
            select(PreferenceQuestionOverride).where(
                PreferenceQuestionOverride.restaurant_id == restaurant_id
            )
        ):
            if override.is_hidden:
                hidden_ids.add(override.question_id)
            if override.display_order is not None:
                order_overrides[override.question_id] = override.display_order

    # A restaurant's own question shadows the platform question of the same key.
    own_keys = {
        question.key for question in questions if question.restaurant_id == restaurant_id and restaurant_id is not None
    }

    resolved: list[ResolvedQuestion] = []
    for question in questions:
        is_inherited = question.restaurant_id is None and restaurant_id is not None
        if question.id in hidden_ids:
            continue
        if is_inherited and question.key in own_keys:
            continue
        options = _live_options(question)
        # A select question with nothing to select is a dead end on screen.
        if not options and not question.allows_free_text:
            continue
        resolved.append(
            ResolvedQuestion(
                question=question,
                options=options,
                display_order=order_overrides.get(question.id, question.display_order),
                is_inherited=is_inherited,
            )
        )

    resolved.sort(key=lambda entry: (entry.display_order, entry.question.key))
    return resolved


def get_user_answers(db: Session, user_id: uuid.UUID) -> list[UserPreferenceAnswer]:
    return list(
        db.scalars(
            select(UserPreferenceAnswer)
            .options(
                selectinload(UserPreferenceAnswer.option),
                selectinload(UserPreferenceAnswer.question),
            )
            .where(UserPreferenceAnswer.user_id == user_id)
        ).unique()
    )


# --------------------------------------------------------------------------
# Projection
# --------------------------------------------------------------------------


def _option_value(option: PreferenceOption, *keys: str) -> Any:
    metadata = option.option_metadata or {}
    for key in keys:
        if key in metadata and metadata[key] is not None:
            return metadata[key]
    return None


def project_answers_to_user_preferences(db: Session, user_id: uuid.UUID) -> UserPreferences:
    """Rebuild the legacy preference row from the normalised answers.

    Called inside the same transaction as every answer write, so the two can
    never disagree. Questions carrying `signal_role = NONE` are deliberately
    skipped: they are collected for later use and must not perturb scoring.
    """

    answers = get_user_answers(db, user_id)

    model = db.scalar(select(UserPreferences).where(UserPreferences.user_id == user_id))
    if model is None:
        model = UserPreferences(user_id=user_id)
        db.add(model)

    cuisines: list[str] = []
    disliked: list[str] = []
    favorites: list[str] = []
    diet_values: list[str] = []
    spice_level: str | None = None
    budget_tier: str | None = None
    budget_amount: float | None = None
    budget_sensitivity: float | None = None

    for answer in answers:
        question = answer.question
        # An answer pointing at a retired question or a withdrawn option stays in
        # the table - it is the customer's data - but it must not reach scoring.
        if question is None or not question.is_live:
            continue
        option = answer.option
        if option is not None and not option.is_live:
            continue

        role = question.signal_role
        label = option.label if option is not None else (answer.free_text or "")
        if not label:
            continue

        if role == PreferenceSignalRole.CUISINE:
            cuisines.append(label)
        elif role == PreferenceSignalRole.DISLIKED_CUISINE:
            disliked.append(label)
        elif role == PreferenceSignalRole.FAVORITE_ITEM:
            favorites.append(label)
        elif role == PreferenceSignalRole.DIET and option is not None:
            # `is_veg` in metadata is authoritative; the option's own value is the
            # fallback so a seeded VEG/NON_VEG option works without metadata.
            is_veg = _option_value(option, "is_veg")
            if is_veg is True:
                diet_values.append("VEG")
            elif is_veg is False:
                diet_values.append("NON_VEG")
            else:
                diet_values.append(option.value.upper())
        elif role == PreferenceSignalRole.SPICE and option is not None:
            spice_level = str(_option_value(option, "level") or option.value).upper()
        elif role == PreferenceSignalRole.BUDGET and option is not None:
            budget_tier = str(_option_value(option, "tier") or option.value).upper()
            amount = _option_value(option, "amount")
            sensitivity = _option_value(option, "sensitivity")
            fallback_amount, fallback_sensitivity = BUDGET_FALLBACK.get(budget_tier, (0.0, 1.0))
            budget_amount = float(amount) if amount is not None else fallback_amount
            budget_sensitivity = float(sensitivity) if sensitivity is not None else fallback_sensitivity

    model.favorite_cuisines = _dedupe(cuisines)
    model.disliked_cuisines = _dedupe(disliked)
    model.favorite_items = _dedupe(favorites)
    # The legacy column is a list but the recommender reads a single diet, so
    # only the first survives - which matches the single-select question.
    # `VEGETARIAN` becoming `VEG` here is a normalisation, not a change: the
    # recommender already maps both to `VEG` through its own alias table.
    model.dietary_preferences = diet_values[:1]
    model.spice_level = spice_level
    model.budget_tier = budget_tier

    # Budget is the one projection that must not run unconditionally.
    #
    # `average_budget` is not merely a restatement of the tier. Where a tier is
    # absent the recommender infers one from this number
    # (`_model_to_profile`: `if not budget_tier and average_budget > 0`), and
    # several live rows carry a real spend figure with no tier at all. Writing a
    # zero here because the customer skipped the budget question would delete
    # that signal and quietly change their ranking.
    #
    # So these two are touched only when a budget answer actually exists, and
    # then with exactly the values the previous save path produced.
    if budget_tier is not None:
        model.average_budget = Decimal(str(budget_amount if budget_amount is not None else 0.0))
        model.price_sensitivity = Decimal(
            str(budget_sensitivity if budget_sensitivity is not None else 1.0)
        )
    # Preserved rather than recomputed: nothing writes it today, and clearing it
    # would silently change scoring for the seeded accounts that do have values.
    if not isinstance(model.cuisine_affinity_scores, dict):
        model.cuisine_affinity_scores = {}

    db.flush()
    return model


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = " ".join(str(value or "").strip().split())
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result





# --------------------------------------------------------------------------
# Saving
# --------------------------------------------------------------------------


class PreferenceValidationError(ValueError):
    """A submission the questionnaire does not allow."""


def save_user_answers(
    db: Session,
    *,
    user_id: uuid.UUID,
    restaurant_id: uuid.UUID | None,
    submissions: list[tuple[uuid.UUID, list[uuid.UUID], list[str]]],
) -> UserPreferences:
    """Replace a customer's answers, then reproject the legacy row.

    A submission is authoritative for the questions it names: omitting a
    question leaves its previous answer alone, while naming it with an empty
    selection clears it. That distinction is what lets the profile screen save
    one question at a time without wiping the rest.

    Answers to questions outside the current questionnaire are never touched
    here. A customer who answered something that has since been retired keeps
    that answer; it simply stops reaching the projection.
    """

    resolved = {entry.question.id: entry for entry in resolve_questionnaire(db, restaurant_id=restaurant_id)}

    for question_id, option_ids, free_text in submissions:
        entry = resolved.get(question_id)
        if entry is None:
            raise PreferenceValidationError(f"Question {question_id} is not part of this questionnaire.")

        question = entry.question
        allowed_option_ids = {option.id for option in entry.options}

        unknown = [str(option_id) for option_id in option_ids if option_id not in allowed_option_ids]
        if unknown:
            raise PreferenceValidationError(
                f"'{question.key}' does not offer option(s) {', '.join(unknown)}."
            )

        if free_text and not question.allows_free_text:
            raise PreferenceValidationError(f"'{question.key}' does not accept free text.")

        deduped_options = list(dict.fromkeys(option_ids))
        deduped_text = _dedupe(free_text)
        total = len(deduped_options) + len(deduped_text)

        if question.input_type == PreferenceInputType.SINGLE_SELECT and total > 1:
            raise PreferenceValidationError(f"'{question.key}' accepts a single answer.")
        if question.is_required and total < max(question.min_selections, 1):
            raise PreferenceValidationError(f"'{question.key}' is required.")
        if total and total < question.min_selections:
            raise PreferenceValidationError(
                f"'{question.key}' needs at least {question.min_selections} selections."
            )
        if question.max_selections is not None and total > question.max_selections:
            raise PreferenceValidationError(
                f"'{question.key}' allows at most {question.max_selections} selections."
            )

        # Replace rather than merge: the client always sends a question's full
        # answer, so a removed choice has to disappear.
        db.query(UserPreferenceAnswer).filter(
            UserPreferenceAnswer.user_id == user_id,
            UserPreferenceAnswer.question_id == question_id,
        ).delete(synchronize_session=False)

        for option_id in deduped_options:
            db.add(
                UserPreferenceAnswer(
                    user_id=user_id,
                    question_id=question_id,
                    option_id=option_id,
                )
            )
        for text_value in deduped_text:
            db.add(
                UserPreferenceAnswer(
                    user_id=user_id,
                    question_id=question_id,
                    free_text=text_value[:120],
                )
            )

    db.flush()
    return project_answers_to_user_preferences(db, user_id)


def build_answer_view(
    db: Session,
    *,
    user_id: uuid.UUID,
    restaurant_id: uuid.UUID | None,
) -> list[dict[str, Any]]:
    """A customer's answers, grouped per question and flagged when stale."""

    live_question_ids = {entry.question.id for entry in resolve_questionnaire(db, restaurant_id=restaurant_id)}

    grouped: dict[uuid.UUID, dict[str, Any]] = {}
    for answer in get_user_answers(db, user_id):
        question = answer.question
        if question is None:
            continue
        bucket = grouped.setdefault(
            question.id,
            {
                "question_id": question.id,
                "question_key": question.key,
                "option_ids": [],
                "free_text": [],
                "labels": [],
                "has_stale_selection": question.id not in live_question_ids,
            },
        )
        if answer.option is not None:
            bucket["option_ids"].append(answer.option.id)
            bucket["labels"].append(answer.option.label)
            if not answer.option.is_live:
                bucket["has_stale_selection"] = True
        elif answer.free_text:
            bucket["free_text"].append(answer.free_text)
            bucket["labels"].append(answer.free_text)

    return list(grouped.values())


__all__ = [
    "PreferenceValidationError",
    "ResolvedQuestion",
    "build_answer_view",
    "get_user_answers",
    "project_answers_to_user_preferences",
    "resolve_questionnaire",
    "save_user_answers",
]

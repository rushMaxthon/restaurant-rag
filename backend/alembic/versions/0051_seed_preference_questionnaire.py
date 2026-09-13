"""Seed the current questionnaire, and backfill every existing answer.

Reproduces the five hardcoded onboarding steps as global questions, with the
same prompts, the same options and the same values the clients ship today, so
the dynamic questionnaire opens identical to the static one.

Then it migrates the eight populated `user_preferences` rows into
`user_preference_answers`. Two details that matter:

* Customers chose values the hardcoded lists never offered - `Indian` and
  `Thai` as cuisines, `Pad Thai Veg` as a favourite. Nothing is dropped. A
  cuisine that is missing becomes a new option on the cuisine question, because
  a real customer picking it is exactly what makes it a legitimate option; a
  missing favourite becomes free text, because that question accepts free text
  and a one-off dish is not worth promoting.
* Diet is stored inconsistently today - five rows say `Vegetarian`, one says
  `VEG`. Both map through the same alias table the recommender already uses.

`user_preferences` is left untouched and keeps serving the recommendation
engine. This migration only adds the normalised copy alongside it.
"""

from __future__ import annotations

import json
import uuid

import sqlalchemy as sa
from alembic import op

revision = "0051_seed_preference_questionnaire"
down_revision = "0050_dynamic_preferences"
branch_labels = None
depends_on = None


# Stable ids, so a later migration or a fixture can reference a seeded question
# without looking it up by name.
NAMESPACE = uuid.UUID("6f2b6f1e-6a1e-4e3a-9f1a-5d9c2b7a0e11")


def _qid(key: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"question:{key}")


def _oid(key: str, value: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"option:{key}:{value}")


# Inlined rather than imported from `app.services.recommendations`. A migration
# has to keep producing the same result years from now; importing application
# code couples it to whatever that module becomes.
DIET_ALIASES = {
    "veg": "VEG",
    "vegetarian": "VEG",
    "non veg": "NON_VEG",
    "non vegetarian": "NON_VEG",
}
SPICE_ALIASES = {"low": "LOW", "medium": "MEDIUM", "high": "HIGH"}
BUDGET_ALIASES = {"low": "LOW", "mid": "MID", "medium": "MID", "high": "HIGH"}


def _norm(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _json(value: dict) -> str:
    return json.dumps(value or {})


# (key, prompt, help_text, input_type, signal_role, allows_free_text, options)
# `is_required` is false throughout because no step in the current wizard
# enforces a choice. Making one required here would change behaviour, which this
# migration must not do; an owner can turn it on afterwards.
QUESTIONS: list[dict] = [
    {
        "key": "cuisines",
        "prompt": "Pick your favorite cuisines",
        "help_text": "Choose a few tastes you want us to prioritize from the start.",
        "input_type": "MULTI_SELECT",
        "signal_role": "CUISINE",
        "allows_free_text": False,
        "options": [
            ("pizza", "Pizza", {}),
            ("burgers", "Burgers", {}),
            ("chinese", "Chinese", {}),
            ("healthy", "Healthy", {}),
            ("desserts", "Desserts", {}),
            ("biryani", "Biryani", {}),
            ("south_indian", "South Indian", {}),
            ("north_indian", "North Indian", {}),
            ("italian", "Italian", {}),
        ],
    },
    {
        "key": "diet",
        "prompt": "What diet should we prefer?",
        "help_text": "We will use this to avoid irrelevant recommendations.",
        "input_type": "SINGLE_SELECT",
        "signal_role": "DIET",
        "allows_free_text": False,
        # `is_veg` is what the scoring engine reads. Putting it here rather than
        # in a Python constant is what lets an owner add a diet option later
        # that actually affects ranking.
        "options": [
            ("VEG", "Veg", {"is_veg": True}),
            ("NON_VEG", "Non-Veg", {"is_veg": False}),
        ],
    },
    {
        "key": "spice",
        "prompt": "How spicy do you like it?",
        "help_text": "We will bias recommendations toward your comfort zone.",
        "input_type": "SINGLE_SELECT",
        "signal_role": "SPICE",
        "allows_free_text": False,
        "options": [
            ("LOW", "Low", {"level": "LOW"}),
            ("MEDIUM", "Medium", {"level": "MEDIUM"}),
            ("HIGH", "High", {"level": "HIGH"}),
        ],
    },
    {
        "key": "budget",
        "prompt": "Set your typical budget",
        "help_text": "This helps us keep early suggestions realistic and useful.",
        "input_type": "SINGLE_SELECT",
        "signal_role": "BUDGET",
        "allows_free_text": False,
        # `amount` and `sensitivity` mirror `_budget_to_amount` and
        # `_budget_to_sensitivity` exactly, so the projection reproduces the
        # values already stored on `user_preferences`.
        "options": [
            ("LOW", "Low", {"tier": "LOW", "amount": 220.0, "sensitivity": 0.7}),
            ("MID", "Mid", {"tier": "MID", "amount": 420.0, "sensitivity": 1.0}),
            ("HIGH", "High", {"tier": "HIGH", "amount": 760.0, "sensitivity": 1.35}),
        ],
    },
    {
        "key": "favorite_items",
        "prompt": "Any favorite items?",
        "help_text": "Optional, but helpful for faster personalization.",
        "input_type": "MULTI_SELECT",
        "signal_role": "FAVORITE_ITEM",
        "allows_free_text": True,
        "options": [
            ("margherita_pizza", "Margherita Pizza", {}),
            ("paneer_tikka", "Paneer Tikka", {}),
            ("chicken_biryani", "Chicken Biryani", {}),
            ("veg_burger", "Veg Burger", {}),
            ("pasta", "Pasta", {}),
            ("momos", "Momos", {}),
            ("salad_bowl", "Salad Bowl", {}),
            ("ice_cream", "Ice Cream", {}),
        ],
    },
]


def upgrade() -> None:
    bind = op.get_bind()

    # --- seed the questionnaire ------------------------------------------
    for order, question in enumerate(QUESTIONS, start=1):
        bind.execute(
            sa.text(
                """
                INSERT INTO preference_questions
                    (id, restaurant_id, key, prompt, help_text, input_type,
                     is_required, min_selections, max_selections, allows_free_text,
                     signal_role, display_order, is_active, created_at, updated_at)
                VALUES
                    (:id, NULL, :key, :prompt, :help_text, CAST(:input_type AS preference_input_type),
                     false, 0, NULL, :allows_free_text,
                     CAST(:signal_role AS preference_signal_role), :display_order, true, now(), now())
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "id": _qid(question["key"]),
                "key": question["key"],
                "prompt": question["prompt"],
                "help_text": question["help_text"],
                "input_type": question["input_type"],
                "allows_free_text": question["allows_free_text"],
                "signal_role": question["signal_role"],
                "display_order": order,
            },
        )

        for option_order, (value, label, metadata) in enumerate(question["options"], start=1):
            bind.execute(
                sa.text(
                    """
                    INSERT INTO preference_options
                        (id, question_id, value, label, metadata, display_order,
                         is_active, created_at, updated_at)
                    VALUES
                        (:id, :question_id, :value, :label, CAST(:metadata AS jsonb),
                         :display_order, true, now(), now())
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "id": _oid(question["key"], value),
                    "question_id": _qid(question["key"]),
                    "value": value,
                    "label": label,
                    "metadata": _json(metadata),
                    "display_order": option_order,
                },
            )

    # --- backfill existing answers ---------------------------------------
    _backfill(bind)


def _option_lookup(bind, key: str) -> dict[str, uuid.UUID]:
    """Normalised label and value, both pointing at the option id."""

    rows = bind.execute(
        sa.text(
            """
            SELECT o.id, o.value, o.label
            FROM preference_options o
            JOIN preference_questions q ON q.id = o.question_id
            WHERE q.id = :question_id
            """
        ),
        {"question_id": _qid(key)},
    ).all()

    lookup: dict[str, uuid.UUID] = {}
    for option_id, value, label in rows:
        lookup[_norm(value)] = option_id
        lookup[_norm(label)] = option_id
    return lookup


def _insert_answer(bind, *, user_id, question_key: str, option_id=None, free_text=None) -> None:
    bind.execute(
        sa.text(
            """
            INSERT INTO user_preference_answers
                (id, user_id, question_id, option_id, free_text, created_at, updated_at)
            VALUES (:id, :user_id, :question_id, :option_id, :free_text, now(), now())
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "id": uuid.uuid4(),
            "user_id": user_id,
            "question_id": _qid(question_key),
            "option_id": option_id,
            "free_text": free_text,
        },
    )


def _backfill(bind) -> None:
    rows = bind.execute(
        sa.text(
            """
            SELECT user_id, favorite_cuisines, dietary_preferences, spice_level,
                   budget_tier, favorite_items
            FROM user_preferences
            """
        )
    ).all()

    lookups = {key: _option_lookup(bind, key) for key in ("cuisines", "diet", "spice", "budget", "favorite_items")}
    next_cuisine_order = bind.execute(
        sa.text(
            "SELECT COALESCE(MAX(display_order), 0) FROM preference_options WHERE question_id = :qid"
        ),
        {"qid": _qid("cuisines")},
    ).scalar() or 0

    for user_id, cuisines, diets, spice, budget, favorites in rows:
        # Cuisines: promote anything unrecognised to a real option. A customer
        # having chosen it is what makes it legitimate, and this question does
        # not accept free text.
        for raw in cuisines or []:
            normalized = _norm(raw)
            if not normalized:
                continue
            option_id = lookups["cuisines"].get(normalized)
            if option_id is None:
                next_cuisine_order += 1
                option_id = _oid("cuisines", normalized.replace(" ", "_"))
                bind.execute(
                    sa.text(
                        """
                        INSERT INTO preference_options
                            (id, question_id, value, label, metadata, display_order,
                             is_active, created_at, updated_at)
                        VALUES (:id, :qid, :value, :label, '{}'::jsonb, :display_order, true, now(), now())
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {
                        "id": option_id,
                        "qid": _qid("cuisines"),
                        "value": normalized.replace(" ", "_")[:64],
                        "label": str(raw).strip()[:120],
                        "display_order": next_cuisine_order,
                    },
                )
                lookups["cuisines"][normalized] = option_id
            _insert_answer(bind, user_id=user_id, question_key="cuisines", option_id=option_id)

        # Diet, through the same aliases the recommender uses, so `Vegetarian`
        # and `VEG` land on the same option.
        for raw in diets or []:
            resolved = DIET_ALIASES.get(_norm(raw), _norm(raw).upper())
            option_id = lookups["diet"].get(_norm(resolved))
            if option_id is not None:
                _insert_answer(bind, user_id=user_id, question_key="diet", option_id=option_id)
                break

        if spice:
            resolved = SPICE_ALIASES.get(_norm(spice), _norm(spice).upper())
            option_id = lookups["spice"].get(_norm(resolved))
            if option_id is not None:
                _insert_answer(bind, user_id=user_id, question_key="spice", option_id=option_id)

        if budget:
            resolved = BUDGET_ALIASES.get(_norm(budget), _norm(budget).upper())
            option_id = lookups["budget"].get(_norm(resolved))
            if option_id is not None:
                _insert_answer(bind, user_id=user_id, question_key="budget", option_id=option_id)

        # Favourites: this question accepts free text, so an unlisted dish is
        # kept as typed rather than promoted to an option nobody else picked.
        seen_free_text: set[str] = set()
        for raw in favorites or []:
            normalized = _norm(raw)
            if not normalized:
                continue
            option_id = lookups["favorite_items"].get(normalized)
            if option_id is not None:
                _insert_answer(bind, user_id=user_id, question_key="favorite_items", option_id=option_id)
            elif normalized not in seen_free_text:
                seen_free_text.add(normalized)
                _insert_answer(
                    bind,
                    user_id=user_id,
                    question_key="favorite_items",
                    free_text=str(raw).strip()[:120],
                )


def downgrade() -> None:
    bind = op.get_bind()
    question_ids = [_qid(question["key"]) for question in QUESTIONS]
    # Answers first: the FK from answers to questions is RESTRICT.
    bind.execute(
        sa.text("DELETE FROM user_preference_answers WHERE question_id = ANY(:ids)"),
        {"ids": question_ids},
    )
    bind.execute(
        sa.text("DELETE FROM preference_options WHERE question_id = ANY(:ids)"),
        {"ids": question_ids},
    )
    bind.execute(
        sa.text("DELETE FROM preference_questions WHERE id = ANY(:ids)"),
        {"ids": question_ids},
    )

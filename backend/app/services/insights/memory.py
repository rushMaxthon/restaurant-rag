"""Resolving follow-up questions against the previous turn.

"And last month?" is only answerable if something remembers what was being
asked about. This inherits the previous turn's analysis and overrides only what
the new question actually changes.

**Memory carries the analysis and the window. It never carries scope.** The
restaurant is re-resolved from the authenticated user on every turn, so a
follow-up cannot inherit, widen, or be talked into a different restaurant — no
matter what the text says. That is enforced structurally rather than by
instruction, and there is a test for it.

Inheritance is rules-based and explicit. A wrongly inherited period would
silently answer a different question than the one asked, which is worse than
failing to resolve the follow-up at all — so anything ambiguous falls through to
normal routing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import Any

from app.models.enums import ChatMessageRole
from app.models.owner_chat import OwnerChatMessage
from app.services.insights.router import RoutedQuestion, parse_period, route_question
from app.services.insights.skills import SKILL_NAMES, SkillParams

logger = logging.getLogger(__name__)

# Turns that resolved no analysis, so there is nothing for a follow-up to
# inherit. A conversational reply is not a question about data.
NON_INHERITABLE_SKILLS = frozenset({"small_talk"})

# Short questions that only make sense against something already discussed.
FOLLOW_UP_PATTERNS: tuple[str, ...] = (
    r"^\s*(and|what about|how about|ok|okay|and what about)\b",
    r"^\s*(why|why\?|why is that|how come)\s*\??\s*$",
    r"^\s*(same|same for|and for)\b",
    r"^\s*(what|how) about\b",
)

# A follow-up asking for the cause escalates to a diagnosis rather than
# repeating the previous analysis over a new window.
WHY_PATTERNS: tuple[str, ...] = (
    r"^\s*why\b",
    r"\bhow come\b",
    r"\bwhat caused\b",
    r"\bwhat's behind\b",
)

# Phrases that would widen scope. Matching one changes nothing about the scope —
# it only stops the turn being treated as an inheritable follow-up, so the
# question is routed from scratch and answered for this restaurant alone.
SCOPE_PROBE_PATTERNS: tuple[str, ...] = (
    r"\ball restaurants?\b",
    r"\bevery restaurant\b",
    r"\bother restaurants?\b",
    r"\bacross (the )?(platform|business|company)\b",
    r"\bignore (previous|prior|above|earlier)\b",
    r"\brestaurant [0-9a-f]{8}-",
)


@dataclass(slots=True)
class ConversationMemory:
    """What the previous assistant turn resolved."""

    skill: str
    params: SkillParams

    @classmethod
    def from_message(cls, message: OwnerChatMessage) -> "ConversationMemory | None":
        if not message.skill or message.skill not in SKILL_NAMES:
            return None
        if message.skill in NON_INHERITABLE_SKILLS:
            # A greeting resolved no analysis, so there is nothing to follow up
            # on. Inheriting it made "and last month?" after "hello" greet the
            # owner a second time, with a window attached.
            return None
        return cls(skill=message.skill, params=params_from_payload(message.skill_params))


def params_from_payload(payload: dict[str, Any] | None) -> SkillParams:
    """Rebuild params from a stored turn, ignoring anything unrecognised."""

    from datetime import date

    data = payload or {}

    def as_date(value: Any) -> date | None:
        if not value:
            return None
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            return None

    def as_int(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def as_text(value: Any) -> str | None:
        return str(value)[:120] if isinstance(value, str) and value.strip() else None

    return SkillParams(
        date_from=as_date(data.get("date_from")),
        date_to=as_date(data.get("date_to")),
        window_days=as_int(data.get("window_days")),
        metric=as_text(data.get("metric")),
        subject=as_text(data.get("subject")),
        topic=as_text(data.get("topic")),
    )


def latest_memory(history: list[OwnerChatMessage]) -> ConversationMemory | None:
    """The most recent assistant turn that resolved a real analysis."""

    for message in reversed(history):
        if message.role != ChatMessageRole.ASSISTANT:
            continue
        memory = ConversationMemory.from_message(message)
        if memory is not None:
            return memory
    return None


def _matches(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def looks_like_follow_up(question: str) -> bool:
    return _matches(question.strip().lower(), FOLLOW_UP_PATTERNS)


def mentions_other_restaurants(question: str) -> bool:
    """Whether the text is reaching for data outside this restaurant.

    Scope is resolved from the authenticated user regardless, so this cannot
    grant access. It exists so such a turn is not treated as an inheritable
    follow-up, which keeps a stale window from being silently reused.
    """

    return _matches(question.strip().lower(), SCOPE_PROBE_PATTERNS)


def resolve_with_memory(
    question: str,
    *,
    memory: ConversationMemory | None,
    allow_model: bool | None = None,
) -> RoutedQuestion:
    """Route a question, inheriting from the previous turn when it is a follow-up."""

    text = question.strip().lower()

    if memory is None or not looks_like_follow_up(question) or mentions_other_restaurants(question):
        return route_question(question, allow_model=allow_model)

    # "Why?" asks for a cause, so it escalates rather than repeating the
    # previous analysis over a new window.
    if _matches(text, WHY_PATTERNS):
        inherited = replace(memory.params, metric=None)
        return RoutedQuestion(
            skill="revenue_diagnosis", params=inherited, source="memory"
        )

    # Anything the follow-up states itself wins; everything else is inherited.
    # Only what the owner actually said. With the default applied every
    # follow-up looked like it had named a new window, so "what about my best
    # selling dish" inherited the previous analysis instead of routing itself.
    stated_period = parse_period(question, apply_default=False)
    has_new_period = (
        stated_period.window_days is not None
        or stated_period.date_from is not None
        or stated_period.date_to is not None
    )

    routed_fresh = None
    if not has_new_period:
        # No new window and no new analysis means nothing to resolve, so fall
        # through rather than answering the previous question again.
        routed_fresh = route_question(question, allow_model=False)
        if routed_fresh.confidence != "low":
            return routed_fresh
        return route_question(question, allow_model=allow_model)

    inherited = SkillParams(
        date_from=stated_period.date_from,
        date_to=stated_period.date_to,
        window_days=stated_period.window_days,
        metric=memory.params.metric,
        subject=memory.params.subject,
        topic=memory.params.topic,
        # Carried, or a follow-up quietly answers less than the question it is
        # following up on: "and last month?" after a four-part question lost its
        # parts and came back with revenue alone.
        parts=memory.params.parts,
        direction=memory.params.direction,
        rank_by=memory.params.rank_by,
        limit=memory.params.limit,
    )
    return RoutedQuestion(skill=memory.skill, params=inherited, source="memory")


__all__ = [
    "ConversationMemory",
    "latest_memory",
    "looks_like_follow_up",
    "mentions_other_restaurants",
    "params_from_payload",
    "resolve_with_memory",
]

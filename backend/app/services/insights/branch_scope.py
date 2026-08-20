"""Recognising a branch an owner named in a question, and narrowing to it.

Matching runs against the restaurant's *actual* branch names rather than
against grammar. Parsing "at X" out of the sentence looks tempting and fails
immediately: "how were sales at lunch", "at the weekend", and "at 7pm" all
produce a branch name that does not exist. Starting from the real branch list
means only a real branch can ever match, and a question with no branch in it is
left exactly as it was.

Nothing here widens scope. A mention resolves to a branch of the restaurant the
caller was already authorised for, or it resolves to nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.services.insights.scope import InsightsScope

# Words too generic to identify a branch on their own. A restaurant called
# "Bowl House" whose branches are "Bowl House Main" and "Bowl House Riverside"
# must not match on "bowl", or every question about bowls picks a branch.
GENERIC_BRANCH_WORDS = frozenset(
    {
        "branch",
        "location",
        "outlet",
        "store",
        "shop",
        "kitchen",
        "restaurant",
        "cafe",
        "the",
        "and",
        "at",
        "in",
        "of",
    }
)

MIN_TOKEN_LENGTH = 4


@dataclass(frozen=True, slots=True)
class BranchMatch:
    restaurant_location_id: object
    branch_name: str
    is_open: bool


@dataclass(frozen=True, slots=True)
class BranchMention:
    """Which branches, if any, a question named.

    `conflict` is set when the question named a branch the current scope is not
    allowed to answer for — an owner already pinned to one branch asking about
    another. That is refused rather than silently answered at a different scope.
    """

    matches: tuple[BranchMatch, ...] = ()
    conflict: str | None = None
    known_branches: tuple[str, ...] = field(default=())

    @property
    def is_comparison(self) -> bool:
        return len(self.matches) > 1


def _distinctive_tokens(branch_name: str, shared: set[str]) -> set[str]:
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", branch_name.casefold())
        if len(token) >= MIN_TOKEN_LENGTH and token not in GENERIC_BRANCH_WORDS
    }
    return tokens - shared


def resolve_branch_mentions(
    db: Session, scope: InsightsScope, question: str
) -> BranchMention:
    """Find the branches a question names, within the caller's scope.

    A branch matches on its full name or on a token unique to it among this
    restaurant's branches — so "Ellisbridge" finds "Bangkok Bowl Ellisbridge",
    while "Bangkok" matches nothing because every branch shares it.
    """

    branches = list(
        db.scalars(
            select(RestaurantLocation).where(
                RestaurantLocation.restaurant_id == scope.restaurant_id
            )
        )
    )
    if not branches:
        return BranchMention()

    known = tuple(sorted(branch.branch_name for branch in branches))
    text = question.casefold()

    restaurant_name = db.scalar(
        select(Restaurant.name).where(Restaurant.id == scope.restaurant_id)
    )
    shared = {
        token
        for token in re.findall(r"[a-z0-9]+", (restaurant_name or "").casefold())
        if len(token) >= MIN_TOKEN_LENGTH
    }
    # A token carried by more than one branch cannot identify either of them.
    seen: dict[str, int] = {}
    for branch in branches:
        for token in _distinctive_tokens(branch.branch_name, set()):
            seen[token] = seen.get(token, 0) + 1
    shared |= {token for token, count in seen.items() if count > 1}

    matched: list[BranchMatch] = []
    for branch in branches:
        name = branch.branch_name.casefold().strip()
        tokens = _distinctive_tokens(branch.branch_name, shared)
        hit = name in text or any(
            re.search(rf"\b{re.escape(token)}\b", text) for token in tokens
        )
        if hit:
            matched.append(
                BranchMatch(
                    restaurant_location_id=branch.id,
                    branch_name=branch.branch_name,
                    is_open=branch.is_open,
                )
            )

    if not matched:
        return BranchMention(known_branches=known)

    if scope.restaurant_location_id is not None:
        outside = [
            match
            for match in matched
            if match.restaurant_location_id != scope.restaurant_location_id
        ]
        if outside:
            return BranchMention(
                conflict=", ".join(sorted(match.branch_name for match in outside)),
                known_branches=known,
            )

    return BranchMention(matches=tuple(matched), known_branches=known)


def narrow_scope(scope: InsightsScope, match: BranchMatch) -> InsightsScope:
    """A scope pinned to one branch of the same, already-verified restaurant."""

    return InsightsScope(
        restaurant_id=scope.restaurant_id,
        restaurant_location_id=match.restaurant_location_id,
    )


__all__ = [
    "BranchMatch",
    "BranchMention",
    "GENERIC_BRANCH_WORDS",
    "narrow_scope",
    "resolve_branch_mentions",
]

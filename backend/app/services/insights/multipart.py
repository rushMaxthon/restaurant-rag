"""Breaking a multi-part owner question into the parts it actually asks for.

An owner rarely asks for one number. "Give me last month — revenue, orders,
best seller, and new customers" is four questions in one sentence, and a router
that returns a single skill answers a quarter of it. Worse, it answers that
quarter in the confident voice of a complete reply, so there is nothing to tell
the owner that three of their four questions were dropped.

This module finds the parts. It does not run anything: it maps question text
onto a list of `Part`s, each naming an existing skill and the parameters that
skill needs. Composition happens in `skills.multi_part`, which runs each part
under the caller's own scope and merges the validated results.

Two design choices worth stating, because both are about not over-reaching:

* Detection is conservative. Two parts are not enough on their own — the
  question also has to read like a list ("and", a comma, a second question
  mark). Without that guard, "why are orders being cancelled" decomposes into
  cancellations *and* an order count, and a perfectly good single answer turns
  into a worse compound one.
* Nothing here is specific to any one question. Parts are patterns over the
  metrics the system already has, so any combination of them composes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Part:
    """One thing a question asks for, and the skill that answers it."""

    key: str
    # What to call this part when it cannot be answered. Written for an owner.
    label: str
    skill: str
    metric: str | None = None
    rank_by: str | None = None
    direction: str | None = None


# Order matters only for readability of the merged answer: parts are reported in
# the order listed here, which runs headline figures first and detail after.
PART_PATTERNS: tuple[tuple[Part, tuple[str, ...]], ...] = (
    (
        Part(key="revenue", label="Revenue", skill="metric_lookup", metric="gross_revenue"),
        (
            r"\bhow much (revenue|money|sales|turnover)\b",
            r"\brevenue\b",
            r"\bturnover\b",
            r"\btotal sales\b",
            r"\bsales figures?\b",
        ),
    ),
    (
        Part(key="orders", label="Order count", skill="metric_lookup", metric="orders"),
        (
            # "orders" only — never "ordered", so "which dish was ordered the
            # most" does not also register as a request for an order count.
            r"\bhow many orders\b",
            r"\bnumber of orders\b",
            r"\border count\b",
            r"\borders\b",
        ),
    ),
    (
        Part(
            key="top_item",
            label="Best-selling item",
            skill="item_performance",
            direction="top",
            rank_by="quantity",
        ),
        (
            r"\b(which|what)\b[^?]*\b(items?|dish(es)?|products?)\b[^?]*\b(most|best|top)\b",
            r"\bbest[- ]?(selling|seller)\b",
            r"\bmost (ordered|popular|sold)\b",
            r"\btop (item|dish|seller|product)\b",
        ),
    ),
    (
        Part(key="new_customers", label="New customers", skill="customer_retention"),
        (
            r"\bnew customers?\b",
            r"\bhow many customers?\b",
            r"\bcustomer count\b",
            r"\breturning customers?\b",
        ),
    ),
    (
        Part(key="average_order_value", label="Average order value", skill="metric_lookup",
             metric="average_order_value"),
        (r"\baverage order value\b", r"\baov\b"),
    ),
    (
        Part(key="cancellations", label="Cancellations", skill="cancellation_reasons"),
        (r"\bcancell?(ed|ations?)\b",),
    ),
    (
        Part(key="busiest_time", label="Busiest times", skill="time_patterns"),
        (
            r"\bbusiest\b",
            r"\bpeak (time|hour|day)s?\b",
            r"\bwhat times?\b.*\bbusy\b",
        ),
    ),
)

PARTS_BY_KEY: dict[str, Part] = {part.key: part for part, _ in PART_PATTERNS}

# The question has to read like a list before two matches become two questions.
# One sentence mentioning two things in passing is still one question.
ENUMERATION = re.compile(r",|\band\b|\balso\b|;|\?.*\?", re.IGNORECASE)

# Two is the floor by definition; above this the question is almost certainly
# broader than the parts we recognise, and answering the recognised ones would
# still be a partial reply presented as a whole one.
MAX_PARTS = 5


def _normalize(question: str) -> str:
    return re.sub(r"\s+", " ", question.strip().lower())


def decompose(question: str) -> tuple[Part, ...]:
    """The parts this question asks for, or empty if it is not multi-part.

    Empty means "route this the ordinary way". A single match is deliberately
    not a decomposition: the existing single-skill routing already handles it,
    and handles it better.
    """

    text = _normalize(question)
    if not ENUMERATION.search(text):
        return ()

    found: list[Part] = []
    for part, patterns in PART_PATTERNS:
        if any(re.search(pattern, text) for pattern in patterns):
            found.append(part)

    if len(found) < 2:
        return ()
    return tuple(found[:MAX_PARTS])


__all__ = ["ENUMERATION", "MAX_PARTS", "PARTS_BY_KEY", "PART_PATTERNS", "Part", "decompose"]

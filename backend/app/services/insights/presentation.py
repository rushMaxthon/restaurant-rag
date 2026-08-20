"""How an answer is shaped on the page, separate from what it says.

Every figure in this system is already correct by the time it reaches here — the
skills compute it and the guardrail checks it. What was missing was readability:
each skill joined its sentences with a space, so a five-part answer arrived as
one dense paragraph regardless of whether it held one fact or a ranked list of
six.

The shape follows the content rather than a house style:

* a single fact stays a single sentence, with no decoration at all
* several parallel facts become a list, because a list is what they are
* an answer with genuinely distinct parts gets headings; one with two parts
  does not
* the figure a sentence exists to deliver is emphasised, and nothing else is —
  bolding every number makes a page of noise and tells a reader nothing

The output is a small, deliberate subset of Markdown: `###` headings, `-` and
`1.` lists, `**bold**`, and blank-line-separated paragraphs. Nothing else, so
the renderer stays a few lines and cannot be surprised.

Emphasis is applied to whole rendered figures (`**₹1,578.92**`) and never inside
one, so the digits a number check extracts are unchanged by formatting.
"""

from __future__ import annotations

from typing import Iterable

# Kept small on purpose. Every construct here has to be rendered by the client,
# and each one added is a way for an answer to look broken.
HEADING_PREFIX = "### "


def bold(text: str | float | int) -> str:
    """Emphasise a whole value.

    Always wraps the complete rendered figure. Splitting emphasis inside a
    number — `**₹1,5**78.92` — would leave the digits intact for the guardrail
    but unreadable for a person.
    """

    return f"**{text}**"


def heading(text: str) -> str:
    return f"{HEADING_PREFIX}{text}"


def bullets(items: Iterable[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item)


def numbered(items: Iterable[str]) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(_clean(items), 1))


def paragraph(*parts: str) -> str:
    """One paragraph from several sentences."""

    return " ".join(_clean(parts))


def blocks(*chunks: str | None) -> str:
    """Join blocks with a blank line between them, dropping the empty ones.

    A blank line is what separates a paragraph from a list in Markdown, and
    dropping empties means a caller can pass an optional section without
    guarding it and without leaving a gap where it would have been.
    """

    return "\n\n".join(_clean(chunks))


def labelled(label: str, value: str) -> str:
    """A list row that leads with what it is, then what it was."""

    return f"{bold(label)} — {value}"


def action(what: str, why: str) -> str:
    """A recommendation, with the doing and the reasoning kept apart.

    An owner deciding whether to act needs the action first and the evidence
    second; running them together as one sentence is what made the old
    recommendations read as a paragraph of justification with an instruction
    buried in it.
    """

    return f"{bold(what)}\n   {why}"


def _clean(values: Iterable[str | None]) -> list[str]:
    return [value.strip() for value in values if value and value.strip()]


__all__ = [
    "HEADING_PREFIX",
    "action",
    "blocks",
    "bold",
    "bullets",
    "heading",
    "labelled",
    "numbered",
    "paragraph",
]

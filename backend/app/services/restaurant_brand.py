"""What a restaurant says about itself, at more than a sentence.

`restaurant_storefront.py` holds the short copy — a page title, a hero line, a
meta description. This holds the long form: headed sections about the kitchen,
and the questions a customer asks before a first order.

Three decisions shape it, and all three are the opposite of what
`restaurant_storefront.py` does.

**Nothing is derived.** That module fills every missing key from the
restaurant's name, cuisine and city, because a tenant onboarded five minutes
ago still needs a page title and a generic one is better than a blank browser
tab. Here, a generated "Commitment to Quality" paragraph would be a claim about
a real business's standards that nobody at that business made — and it would be
the same paragraph under six different restaurants' names, which is the exact
bug `restaurant_storefront.py` exists to have fixed. Empty is a correct and
common answer, and the storefront renders nothing for it.

**It lives in its own column.** `resolve_storefront` rebuilds its map from an
allowlist, so a key it does not know is dropped on the next save. Brand content
stored in that JSONB would survive until the first time an owner edited their
page title somewhere else and then disappear with no error.

**Invalid input is refused, not silently dropped.** An owner pasting eleven
sections should be told the limit, not have the last three quietly discarded —
the operator's screen is the only place this is ever edited, and a save that
reports success while losing content is how people stop trusting a form.
"""

from __future__ import annotations

from typing import Any

# Sizes are picked from where the text lands, not rounded for neatness.
# A heading sits on one line of a card; a body is two or three short
# paragraphs at most before a reader stops; a bullet is a phrase.
HEADING_LIMIT = 80
BODY_LIMIT = 1200
BULLET_LIMIT = 180
QUESTION_LIMIT = 180
ANSWER_LIMIT = 1200

# Enough for the shape of page this is for — overview, what they are known
# for, how ordering works, a note on quality — and few enough that the page
# stays a page rather than becoming a document.
MAX_SECTIONS = 8
MAX_BULLETS = 10
MAX_FAQS = 12

ABOUT_SECTIONS_KEY = "about_sections"
FAQS_KEY = "faqs"

BRAND_KEYS = (ABOUT_SECTIONS_KEY, FAQS_KEY)


class BrandValidationError(ValueError):
    """The submitted brand content is not something this platform will store."""


def _text(value: Any, *, limit: int, what: str, required: bool) -> str:
    """One field, trimmed and length-checked.

    Whitespace inside is preserved rather than collapsed, unlike the short copy
    — a body is prose and may legitimately carry paragraph breaks, and
    flattening them would turn an owner's three paragraphs into one wall.
    Carriage returns are normalised so a value pasted from Windows does not
    render with blank lines doubled.
    """

    if value is None:
        value = ""
    if not isinstance(value, str):
        raise BrandValidationError(f"{what} must be text.")
    cleaned = value.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not cleaned:
        if required:
            raise BrandValidationError(f"{what} cannot be empty.")
        return ""
    if len(cleaned) > limit:
        raise BrandValidationError(f"Keep {what.lower()} to {limit} characters or fewer.")
    return cleaned


def _section(raw: Any, *, index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        raise BrandValidationError(f"Section {index} is not filled in correctly.")

    heading = _text(raw.get("heading"), limit=HEADING_LIMIT, what="A section heading", required=False)
    body = _text(raw.get("body"), limit=BODY_LIMIT, what="A section body", required=False)

    bullets_raw = raw.get("bullets") or []
    if not isinstance(bullets_raw, list):
        raise BrandValidationError("Section bullets must be a list.")
    if len(bullets_raw) > MAX_BULLETS:
        raise BrandValidationError(f"A section can have at most {MAX_BULLETS} bullet points.")
    bullets = [
        text
        for text in (
            _text(bullet, limit=BULLET_LIMIT, what="A bullet point", required=False)
            for bullet in bullets_raw
        )
        if text
    ]

    # A section with a heading and nothing under it is an empty box on the
    # page; one with a body and no heading has nowhere to sit. Both are
    # dropped rather than refused, because an editor with a spare blank row at
    # the bottom is normal and should not block a save.
    if not heading or not (body or bullets):
        return None

    section: dict[str, Any] = {"heading": heading, "body": body}
    if bullets:
        section["bullets"] = bullets
    return section


def _faq(raw: Any, *, index: int) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        raise BrandValidationError(f"Question {index} is not filled in correctly.")

    question = _text(raw.get("question"), limit=QUESTION_LIMIT, what="A question", required=False)
    answer = _text(raw.get("answer"), limit=ANSWER_LIMIT, what="An answer", required=False)

    # Half a pair is worse than none: a question with no answer published on a
    # website reads as an oversight, and an answer with no question is
    # meaningless. A blank row is simply dropped.
    if not question or not answer:
        return None
    return {"question": question, "answer": answer}


def resolve_brand(
    payload: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Turn a submitted edit into what is actually stored.

    Only the keys present in `payload` change, so a form that edits the FAQ
    does not blank the about sections. Sending a key as an empty list clears
    that half deliberately, which is a different act from not mentioning it.
    """

    stored: dict[str, Any] = {}
    source = existing or {}
    for key in BRAND_KEYS:
        value = source.get(key)
        if isinstance(value, list) and value:
            stored[key] = value

    if ABOUT_SECTIONS_KEY in payload:
        raw = payload[ABOUT_SECTIONS_KEY]
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            raise BrandValidationError("Sections must be a list.")
        if len(raw) > MAX_SECTIONS:
            raise BrandValidationError(f"You can have at most {MAX_SECTIONS} sections.")
        sections = [
            section
            for section in (_section(item, index=at + 1) for at, item in enumerate(raw))
            if section is not None
        ]
        if sections:
            stored[ABOUT_SECTIONS_KEY] = sections
        else:
            stored.pop(ABOUT_SECTIONS_KEY, None)

    if FAQS_KEY in payload:
        raw = payload[FAQS_KEY]
        if raw is None:
            raw = []
        if not isinstance(raw, list):
            raise BrandValidationError("Questions must be a list.")
        if len(raw) > MAX_FAQS:
            raise BrandValidationError(f"You can have at most {MAX_FAQS} questions.")
        faqs = [
            faq for faq in (_faq(item, index=at + 1) for at, item in enumerate(raw)) if faq is not None
        ]
        if faqs:
            stored[FAQS_KEY] = faqs
        else:
            stored.pop(FAQS_KEY, None)

    return stored


def read_brand(restaurant: Any) -> dict[str, list[Any]]:
    """This restaurant's brand content, with both keys always present.

    Both come back as lists, empty when nothing is written, so no client has to
    distinguish "absent" from "none" — there is no difference here, and giving
    clients one to handle would invite two of them handling it differently.

    Re-validated on the way out rather than trusted: this column is JSONB and
    the rules have changed before. A row written under an older, looser rule
    should not be able to put a 4,000-character "paragraph" on a page because
    it got in before the cap existed.
    """

    raw = getattr(restaurant, "brand", None) or {}
    sections_raw = raw.get(ABOUT_SECTIONS_KEY)
    faqs_raw = raw.get(FAQS_KEY)

    sections: list[dict[str, Any]] = []
    if isinstance(sections_raw, list):
        for at, item in enumerate(sections_raw[:MAX_SECTIONS]):
            try:
                section = _section(item, index=at + 1)
            except BrandValidationError:
                continue
            if section is not None:
                sections.append(section)

    faqs: list[dict[str, str]] = []
    if isinstance(faqs_raw, list):
        for at, item in enumerate(faqs_raw[:MAX_FAQS]):
            try:
                faq = _faq(item, index=at + 1)
            except BrandValidationError:
                continue
            if faq is not None:
                faqs.append(faq)

    return {ABOUT_SECTIONS_KEY: sections, FAQS_KEY: faqs}


BRAND_LIMITS: dict[str, int] = {
    "heading": HEADING_LIMIT,
    "body": BODY_LIMIT,
    "bullet": BULLET_LIMIT,
    "question": QUESTION_LIMIT,
    "answer": ANSWER_LIMIT,
    "max_sections": MAX_SECTIONS,
    "max_bullets": MAX_BULLETS,
    "max_faqs": MAX_FAQS,
}


__all__ = [
    "ABOUT_SECTIONS_KEY",
    "BRAND_KEYS",
    "BRAND_LIMITS",
    "FAQS_KEY",
    "BrandValidationError",
    "read_brand",
    "resolve_brand",
]

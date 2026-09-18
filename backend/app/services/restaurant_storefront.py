"""The words on a restaurant's own website.

Every tenant onboarded so far inherited Bangkok Bowl's page title, meta
description and hero copy, because they were string literals in
`frontend-customer/src/routes/index.tsx`. Six restaurants, six domains, one
restaurant's marketing — including in their search-engine listings, which is
the part that does lasting damage: a crawler that indexed
`dragon-wok.example.com` under "Bangkok Bowl — Thai Food Delivery" is
describing the wrong business to the world.

This is the same shape as `restaurant_theme.py` and for the same reason: a
restaurant's copy is its own, so it lives on the restaurant and the owner
writes it — not on the app client, which is the build configuration an
administrator set up.

**Every key always comes back.** `read_storefront` derives what is missing
from the restaurant's own name, cuisine and city, so a tenant onboarded five
minutes ago reads sensibly rather than blank, and no client ever has to decide
what to do about an empty field. That derivation is the whole reason this is a
service rather than a dict: the defaults are a product decision, not a
frontend one, and they must be identical wherever they are rendered.
"""

from __future__ import annotations

from typing import Any

from app.models.restaurant import Restaurant

META_TITLE_KEY = "meta_title"
META_DESCRIPTION_KEY = "meta_description"
OG_TITLE_KEY = "og_title"
OG_DESCRIPTION_KEY = "og_description"
HERO_HEADLINE_KEY = "hero_headline"
HERO_SUBCOPY_KEY = "hero_subcopy"
CONCIERGE_INTRO_KEY = "concierge_intro"
LOGIN_BLURB_KEY = "login_blurb"

# Length caps sized to where each string actually lands, not picked round.
# A title past ~60 characters is truncated in a search result and a
# description past ~160 likewise, so storing more is storing something nobody
# will read. The on-page strings are capped generously; they wrap.
STOREFRONT_LIMITS: dict[str, int] = {
    META_TITLE_KEY: 70,
    META_DESCRIPTION_KEY: 180,
    OG_TITLE_KEY: 70,
    OG_DESCRIPTION_KEY: 180,
    HERO_HEADLINE_KEY: 80,
    HERO_SUBCOPY_KEY: 240,
    CONCIERGE_INTRO_KEY: 240,
    LOGIN_BLURB_KEY: 180,
}

STOREFRONT_KEYS = tuple(STOREFRONT_LIMITS)


class StorefrontValidationError(ValueError):
    """The submitted copy is not something this platform will store."""


def _clean(value: Any, *, key: str) -> str:
    """One field, trimmed and length-checked, or "" for anything unusable.

    Whitespace collapses because these strings are pasted from documents and
    a title carrying a newline breaks the `<title>` it ends up in.
    """

    if not isinstance(value, str):
        return ""
    collapsed = " ".join(value.split())
    if not collapsed:
        return ""
    limit = STOREFRONT_LIMITS[key]
    if len(collapsed) > limit:
        raise StorefrontValidationError(
            f"Keep {key.replace('_', ' ')} to {limit} characters or fewer."
        )
    return collapsed


def resolve_storefront(
    payload: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Turn a submitted edit into what is actually stored.

    Only the keys present in `payload` change, so a form that edits one field
    does not blank the rest — the failure mode of a whole-object write, and the
    reason the plan rejected `AppClient.config` for anything that matters.

    An empty string is stored as an absent key rather than as "", because
    clearing a field means "go back to the derived default", not "this
    restaurant's hero has no words".
    """

    stored = {
        key: value
        for key, value in (existing or {}).items()
        if key in STOREFRONT_LIMITS and isinstance(value, str) and value
    }

    for key in STOREFRONT_KEYS:
        if key not in payload:
            continue
        cleaned = _clean(payload[key], key=key)
        if cleaned:
            stored[key] = cleaned
        else:
            stored.pop(key, None)

    return stored


def default_storefront(restaurant: Restaurant) -> dict[str, str]:
    """What a restaurant says about itself before anybody writes anything.

    Built from the three things onboarding always collects — name, cuisine,
    city — so the result is specific to this restaurant on day one. Generic
    filler would be worse than the bug being fixed: at least Bangkok Bowl's
    copy described a real restaurant.
    """

    name = (restaurant.name or "").strip() or "Our kitchen"
    cuisine = (restaurant.cuisine_type or "").strip()
    city = (restaurant.city or "").strip()

    # "Thai food delivery in Ahmedabad" reads as a sentence; each half is
    # dropped rather than left as a dangling preposition when it is missing.
    what = f"{cuisine} food" if cuisine else "Food"
    where = f" in {city}" if city else ""

    description = (restaurant.description or "").strip()
    subcopy = description or f"{what} from {name}, cooked to order and delivered{where}."

    return {
        META_TITLE_KEY: f"{name} — {what} delivery{where}".strip(),
        META_DESCRIPTION_KEY: subcopy,
        OG_TITLE_KEY: f"{name} — {what} delivery{where}".strip(),
        OG_DESCRIPTION_KEY: subcopy,
        HERO_HEADLINE_KEY: name,
        HERO_SUBCOPY_KEY: subcopy,
        CONCIERGE_INTRO_KEY: (
            f"Ask me anything about the menu at {name} — what is spicy, what is "
            "popular, what suits a group."
        ),
        LOGIN_BLURB_KEY: f"Sign in to order from {name}{where}.",
    }


def read_storefront(restaurant: Restaurant) -> dict[str, str]:
    """The restaurant's copy, with every key filled in.

    A stored value wins; anything absent or unusable falls back to the derived
    default. Per key, not all-or-nothing: an owner who has written only a hero
    headline keeps the derived meta description rather than losing it.
    """

    stored = restaurant.storefront or {}
    resolved = default_storefront(restaurant)

    for key in STOREFRONT_KEYS:
        value = stored.get(key)
        if isinstance(value, str) and value.strip():
            resolved[key] = " ".join(value.split())

    return resolved


__all__ = [
    "STOREFRONT_KEYS",
    "STOREFRONT_LIMITS",
    "StorefrontValidationError",
    "default_storefront",
    "read_storefront",
    "resolve_storefront",
]

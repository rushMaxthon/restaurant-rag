"""Everything a storefront needs to look like the restaurant, not like us.

`restaurant_theme` handles the one thing an owner picks in their own
dashboard: an accent colour. That is the right scope for an owner, and this
does not widen it — an owner owns their accent, not the meaning of
"delivered".

This is the other half: the things an operator sets up once while onboarding
a tenant and nobody touches again. A logo. A name to put in the browser tab.
A typeface. They live on the app client because they describe the *build*,
which is the distinction `build_app_config_response` already draws and
documents — the restaurant's theme wins over this record on the one key they
share, because the restaurant is what the owner controls.

Two rules run through it. Anything unreadable is refused on the way in
rather than rendered: a free hex field is a contrast trap, and the person
filling this form is onboarding somebody else's business and will not see
the result. And anything missing falls back to a platform default, because a
half-onboarded tenant must still serve a working storefront rather than a
page with no colour and no name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from app.models.app_client import AppClient
from app.services.restaurant_theme import (
    DEFAULT_PRIMARY_COLOR,
    HEX_PATTERN,
    ThemeValidationError,
    normalize_color,
)

PRIMARY_COLOR_KEY = "primary_color"
ACCENT_COLOR_KEY = "accent_color"
LOGO_URL_KEY = "logo_url"
LOGO_DARK_URL_KEY = "logo_dark_url"
FAVICON_URL_KEY = "favicon_url"
COVER_IMAGE_URL_KEY = "cover_image_url"
FONT_FAMILY_KEY = "font_family"
APP_NAME_KEY = "app_name"
TAGLINE_KEY = "tagline"


@dataclass(frozen=True)
class FontChoice:
    id: str
    label: str
    stack: str
    description: str


# An allowlist, not a free text field, for two reasons. A storefront that
# names a family nobody is serving renders in whatever the device happens to
# have, which differs per platform and is nobody's brand. And a font name
# arriving from a form and going straight into a CSS declaration is an
# injection waiting to happen.
FONT_CHOICES: tuple[FontChoice, ...] = (
    FontChoice(
        "manrope",
        "Manrope",
        '"Manrope", system-ui, sans-serif',
        "The platform default. Friendly and even.",
    ),
    FontChoice(
        "inter",
        "Inter",
        '"Inter", system-ui, sans-serif',
        "Neutral and highly legible at small sizes.",
    ),
    FontChoice(
        "plus-jakarta",
        "Plus Jakarta Sans",
        '"Plus Jakarta Sans", system-ui, sans-serif',
        "Rounder and warmer. Suits casual dining.",
    ),
    FontChoice(
        "dm-serif",
        "DM Serif Display",
        '"DM Serif Display", Georgia, serif',
        "A serif for headings. Reads as established.",
    ),
    FontChoice(
        "space-grotesk",
        "Space Grotesk",
        '"Space Grotesk", system-ui, sans-serif',
        "Squared and modern. Stands out in a list.",
    ),
)

FONTS_BY_ID = {font.id: font for font in FONT_CHOICES}
DEFAULT_FONT_ID = FONT_CHOICES[0].id

# Long enough for a real name, short enough that it cannot be used to smuggle
# a paragraph into a browser tab.
_MAX_NAME = 60
_MAX_TAGLINE = 120
_MAX_URL = 500


class BrandingValidationError(ValueError):
    """The requested branding is not something this platform will store."""


def _clean_text(value: Any, *, limit: int, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise BrandingValidationError(f"{label} must be text.")
    # Control characters would survive into a page title and a manifest.
    text = "".join(character for character in value.strip() if character.isprintable())
    if len(text) > limit:
        raise BrandingValidationError(f"{label} must be {limit} characters or fewer.")
    return text


def _clean_url(value: Any, *, label: str) -> str:
    """An https URL, or nothing.

    `javascript:` and `data:` are the reason this is a check and not a trim:
    these values end up in `src` and `href` attributes on a page served under
    the tenant's own domain, and one of them is a script the operator did not
    write.
    """

    if value is None:
        return ""
    if not isinstance(value, str):
        raise BrandingValidationError(f"{label} must be a URL.")
    url = value.strip()
    if not url:
        return ""
    if len(url) > _MAX_URL:
        raise BrandingValidationError(f"{label} must be {_MAX_URL} characters or fewer.")
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise BrandingValidationError(
            f"{label} must be a full https:// address."
        )
    return url


def normalize_font(value: Any) -> str:
    if value is None or value == "":
        return DEFAULT_FONT_ID
    if not isinstance(value, str) or value.strip().lower() not in FONTS_BY_ID:
        raise BrandingValidationError(
            f"Unknown font. Choose one of: {', '.join(sorted(FONTS_BY_ID))}."
        )
    return value.strip().lower()


def font_stack(font_id: str) -> str:
    """The CSS family list for a stored font id, always a known-safe string."""

    return FONTS_BY_ID.get(font_id, FONTS_BY_ID[DEFAULT_FONT_ID]).stack


def resolve_branding(payload: dict[str, Any], *, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Turn a form submission into the record actually stored.

    Only keys present in the payload are changed, so a form that edits the
    logo does not silently clear the tagline it never showed.
    """

    stored = dict(existing or {})

    if PRIMARY_COLOR_KEY in payload:
        try:
            stored[PRIMARY_COLOR_KEY] = normalize_color(payload[PRIMARY_COLOR_KEY] or "")
        except ThemeValidationError as error:
            raise BrandingValidationError(str(error)) from error
    if ACCENT_COLOR_KEY in payload:
        value = payload[ACCENT_COLOR_KEY]
        if not value:
            stored.pop(ACCENT_COLOR_KEY, None)
        else:
            try:
                stored[ACCENT_COLOR_KEY] = normalize_color(value)
            except ThemeValidationError as error:
                raise BrandingValidationError(str(error)) from error

    for key, label in (
        (LOGO_URL_KEY, "Logo"),
        (LOGO_DARK_URL_KEY, "Dark logo"),
        (FAVICON_URL_KEY, "Favicon"),
        (COVER_IMAGE_URL_KEY, "Cover image"),
    ):
        if key in payload:
            cleaned = _clean_url(payload[key], label=label)
            if cleaned:
                stored[key] = cleaned
            else:
                stored.pop(key, None)

    if FONT_FAMILY_KEY in payload:
        stored[FONT_FAMILY_KEY] = normalize_font(payload[FONT_FAMILY_KEY])

    if APP_NAME_KEY in payload:
        name = _clean_text(payload[APP_NAME_KEY], limit=_MAX_NAME, label="App name")
        if name:
            stored[APP_NAME_KEY] = name
        else:
            stored.pop(APP_NAME_KEY, None)

    if TAGLINE_KEY in payload:
        tagline = _clean_text(payload[TAGLINE_KEY], limit=_MAX_TAGLINE, label="Tagline")
        if tagline:
            stored[TAGLINE_KEY] = tagline
        else:
            stored.pop(TAGLINE_KEY, None)

    return stored


def read_branding(app_client: AppClient) -> dict[str, Any]:
    """The stored branding, completed with platform defaults.

    Every key a storefront reads is present in the result, so the client
    never has to decide what to do about a missing one. A tenant halfway
    through onboarding still gets a working page.
    """

    stored = dict(app_client.branding or {})

    color = stored.get(PRIMARY_COLOR_KEY)
    if not isinstance(color, str) or not HEX_PATTERN.match(color.upper()):
        color = DEFAULT_PRIMARY_COLOR
    else:
        color = color.upper()

    accent = stored.get(ACCENT_COLOR_KEY)
    if not isinstance(accent, str) or not HEX_PATTERN.match(accent.upper()):
        accent = ""
    else:
        accent = accent.upper()

    font_id = stored.get(FONT_FAMILY_KEY)
    if not isinstance(font_id, str) or font_id not in FONTS_BY_ID:
        font_id = DEFAULT_FONT_ID

    def url(key: str) -> str:
        value = stored.get(key)
        return value if isinstance(value, str) else ""

    def text(key: str) -> str:
        value = stored.get(key)
        return value if isinstance(value, str) else ""

    return {
        PRIMARY_COLOR_KEY: color,
        ACCENT_COLOR_KEY: accent,
        LOGO_URL_KEY: url(LOGO_URL_KEY),
        LOGO_DARK_URL_KEY: url(LOGO_DARK_URL_KEY),
        FAVICON_URL_KEY: url(FAVICON_URL_KEY),
        COVER_IMAGE_URL_KEY: url(COVER_IMAGE_URL_KEY),
        FONT_FAMILY_KEY: font_id,
        # Sent resolved as well as named: the storefront writes this straight
        # into a CSS custom property, and it should not have to carry its own
        # copy of the allowlist to do it.
        "font_stack": font_stack(font_id),
        APP_NAME_KEY: text(APP_NAME_KEY) or app_client.display_name,
        TAGLINE_KEY: text(TAGLINE_KEY),
    }


__all__ = [
    "ACCENT_COLOR_KEY",
    "APP_NAME_KEY",
    "BrandingValidationError",
    "COVER_IMAGE_URL_KEY",
    "DEFAULT_FONT_ID",
    "FAVICON_URL_KEY",
    "FONT_CHOICES",
    "FONT_FAMILY_KEY",
    "LOGO_DARK_URL_KEY",
    "LOGO_URL_KEY",
    "PRIMARY_COLOR_KEY",
    "TAGLINE_KEY",
    "font_stack",
    "normalize_font",
    "read_branding",
    "resolve_branding",
]

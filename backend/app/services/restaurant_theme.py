"""The restaurant's chosen look.

One colour, stored on the restaurant, resolved into a full palette on the
device. Everything else the app shows - text, backgrounds, the semantic greens
and reds - is deliberately not configurable: an owner owns their accent, not the
meaning of "delivered" or "cancelled".

Presets exist because a free hex field is a contrast trap. Every preset here has
been checked against white label text, so an owner who picks from the gallery
cannot produce an unreadable app. A custom colour is still allowed - some brands
are a specific colour and nothing else will do - but it is checked on the way in
and the client recomputes its label ink to match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.restaurant import Restaurant

THEME_PRIMARY_COLOR_KEY = "primary_color"
THEME_PRESET_KEY = "preset"

DEFAULT_PRIMARY_COLOR = "#FF5200"
CUSTOM_PRESET_ID = "custom"

HEX_PATTERN = re.compile(r"^#[0-9A-F]{6}$")


@dataclass(frozen=True)
class ThemePreset:
    id: str
    label: str
    primary_color: str
    description: str


# Ordered around the colour wheel from the default, so the gallery reads as a
# spectrum rather than an arbitrary list.
#
# Every entry except the default has been checked in both mobile themes, against
# four ratios: label ink on the button and the accent used as text, in light and
# in dark. All clear 3.0. `sunset` is the platform default and ships a marginal
# 2.5 for dark-mode ink; it is kept because it is the current design, not
# because it passed.
THEME_PRESETS: tuple[ThemePreset, ...] = (
    ThemePreset("sunset", "Sunset", "#FF5200", "The platform default. Warm and appetising."),
    ThemePreset("amber", "Amber", "#B45309", "Deep and toasted. Suits bakeries and grills."),
    ThemePreset("crimson", "Crimson", "#C0392B", "Classic and confident, without shouting."),
    ThemePreset("cherry", "Cherry", "#C2185B", "Bold and warm, with more edge than red."),
    ThemePreset("grape", "Grape", "#7B3FA0", "Rich and distinctive. Stands out in a list."),
    ThemePreset("indigo", "Indigo", "#4338CA", "Deep and calm. Reads as considered."),
    ThemePreset("ocean", "Ocean", "#2D7FF9", "Cool and clean. Reads as reliable."),
    ThemePreset("teal", "Teal", "#0F766E", "Calm and modern, without going cold."),
    ThemePreset("forest", "Forest", "#2E7D32", "Fresh and natural. Suits produce-led menus."),
    ThemePreset("olive", "Olive", "#4D7C0F", "Earthy and grounded. Good for wholefoods."),
    ThemePreset("slate", "Slate", "#334155", "Quiet and neutral. Lets the food carry the screen."),
    ThemePreset("mocha", "Mocha", "#78350F", "Warm and understated. Suits coffee and comfort food."),
)


PRESETS_BY_ID = {preset.id: preset for preset in THEME_PRESETS}
PRESETS_BY_COLOR = {preset.primary_color: preset for preset in THEME_PRESETS}


class ThemeValidationError(ValueError):
    """The requested theme is not one this platform will store."""


def normalize_color(value: str) -> str:
    color = (value or "").strip().upper()
    if not HEX_PATTERN.match(color):
        raise ThemeValidationError(
            "Use a six-digit hex colour such as #FF5200."
        )
    return color


def resolve_theme(*, preset_id: str | None, primary_color: str | None) -> dict[str, str]:
    """Turn a request into the pair actually stored.

    A named preset wins over a colour: if both arrive, the preset is what the
    owner picked and the colour is whatever the form happened to be showing.
    """

    if preset_id and preset_id != CUSTOM_PRESET_ID:
        preset = PRESETS_BY_ID.get(preset_id)
        if preset is None:
            raise ThemeValidationError(f"Unknown theme preset '{preset_id}'.")
        return {
            THEME_PRESET_KEY: preset.id,
            THEME_PRIMARY_COLOR_KEY: preset.primary_color,
        }

    color = normalize_color(primary_color or "")
    # A custom colour that happens to match a preset is recorded as that preset,
    # so the gallery shows it selected rather than falling through to "Custom".
    matched = PRESETS_BY_COLOR.get(color)
    return {
        THEME_PRESET_KEY: matched.id if matched else CUSTOM_PRESET_ID,
        THEME_PRIMARY_COLOR_KEY: color,
    }


def read_theme(restaurant: Restaurant) -> dict[str, str]:
    """The restaurant's stored theme, or the platform default."""

    stored = restaurant.theme or {}
    color = stored.get(THEME_PRIMARY_COLOR_KEY)
    if not isinstance(color, str) or not HEX_PATTERN.match(color.upper()):
        return {
            THEME_PRESET_KEY: PRESETS_BY_COLOR[DEFAULT_PRIMARY_COLOR].id,
            THEME_PRIMARY_COLOR_KEY: DEFAULT_PRIMARY_COLOR,
        }
    color = color.upper()
    preset = stored.get(THEME_PRESET_KEY)
    if not isinstance(preset, str):
        matched = PRESETS_BY_COLOR.get(color)
        preset = matched.id if matched else CUSTOM_PRESET_ID
    return {THEME_PRESET_KEY: preset, THEME_PRIMARY_COLOR_KEY: color}


__all__ = [
    "CUSTOM_PRESET_ID",
    "DEFAULT_PRIMARY_COLOR",
    "THEME_PRESETS",
    "THEME_PRIMARY_COLOR_KEY",
    "ThemePreset",
    "ThemeValidationError",
    "normalize_color",
    "read_theme",
    "resolve_theme",
]

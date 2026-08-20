from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Iterable

from app.config import get_settings
from app.models.menu_item import MenuItem
from app.services.bestsellers import is_menu_item_bestseller

NORMALIZED_SPICY_KEYWORDS = {
    "spicy",
    "hot",
    "fiery",
    "schezwan",
    "szechuan",
    "chilli",
    "chili",
    "kolhapuri",
    "chettinad",
    "peri peri",
    "peri-peri",
    "pepper",
    "tandoori",
}

SIGNAL_KEYWORD_MAP: dict[str, set[str]] = {
    "spicy": NORMALIZED_SPICY_KEYWORDS,
    "cheesy": {
        "cheese",
        "cheesy",
        "mozzarella",
        "parmesan",
        "cheddar",
        "gouda",
        "cream cheese",
    },
    "chicken": {
        "chicken",
        "peri peri chicken",
        "peri-peri chicken",
        "chicken tikka",
        "fried chicken",
    },
    "paneer": {
        "paneer",
        "cottage cheese",
    },
    "cold_drink": {
        "cold drink",
        "soft drink",
        "cola",
        "coke",
        "pepsi",
        "soda",
        "iced tea",
        "lemonade",
        "juice",
        "mocktail",
        "shake",
    },
    "dessert": {
        "dessert",
        "sweet",
        "cake",
        "pastry",
        "brownie",
        "ice cream",
        "kulfi",
        "tiramisu",
        "gulab jamun",
        "cheesecake",
        "cookie",
        "mousse",
    },
    "pizza": {
        "pizza",
        "margherita",
        "pepperoni",
        "farmhouse",
        "deep dish",
    },
    "burger": {
        "burger",
        "cheeseburger",
        "slider",
        "hamburger",
        "patty",
    },
    "indian": {
        "indian",
        "biryani",
        "curry",
        "masala",
        "naan",
        "tandoori",
        "dal",
        "kebab",
        "thali",
        "chaat",
    },
    "italian": {
        "italian",
        "pasta",
        "alfredo",
        "arrabbiata",
        "risotto",
        "lasagna",
        "pizza",
        "bruschetta",
        "gnocchi",
    },
    "chinese": {
        "chinese",
        "noodle",
        "noodles",
        "fried rice",
        "manchurian",
        "dimsum",
        "dumpling",
        "dumplings",
        "schezwan",
        "szechuan",
    },
    "thai": {
        "thai",
        "pad thai",
        "green curry",
        "red curry",
        "tom yum",
        "basil rice",
        "satay",
    },
}

CUISINE_SIGNAL_KEYS = {"indian", "italian", "chinese", "thai"}
DIET_SIGNAL_KEYS = {"veg", "non_veg"}
TRENDING_POPULARITY_THRESHOLD = 75.0


@dataclass(frozen=True)
class MenuItemSignals:
    direct_signals: set[str]
    cuisine_signals: set[str]
    diet_signals: set[str]
    all_signals: set[str]


def _normalize_signal_text(value: str | None) -> str:
    return " ".join((value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def _collect_signal_haystacks(
    menu_item: MenuItem,
    *,
    restaurant_cuisine_type: str | None = None,
    ingredients: Iterable[str] | None = None,
) -> list[str]:
    values = [
        menu_item.name,
        menu_item.description,
        menu_item.category,
        menu_item.cuisine_type,
        restaurant_cuisine_type,
    ]
    if ingredients is not None:
        values.extend(str(value) for value in ingredients)
    return [_normalize_signal_text(value) for value in values if _normalize_signal_text(value)]


def extract_menu_item_signals(
    menu_item: MenuItem,
    *,
    restaurant_cuisine_type: str | None = None,
    ingredients: Iterable[str] | None = None,
) -> MenuItemSignals:
    haystacks = _collect_signal_haystacks(
        menu_item,
        restaurant_cuisine_type=restaurant_cuisine_type,
        ingredients=ingredients,
    )
    direct_signals: set[str] = set()

    for signal, keywords in SIGNAL_KEYWORD_MAP.items():
        if any(keyword in haystack for haystack in haystacks for keyword in keywords):
            direct_signals.add(signal)

    if menu_item.is_veg:
        direct_signals.add("veg")
    else:
        direct_signals.add("non_veg")

    cuisine_signals = {signal for signal in direct_signals if signal in CUISINE_SIGNAL_KEYS}
    diet_signals = {signal for signal in direct_signals if signal in DIET_SIGNAL_KEYS}
    return MenuItemSignals(
        direct_signals=direct_signals,
        cuisine_signals=cuisine_signals,
        diet_signals=diet_signals,
        all_signals=direct_signals | cuisine_signals | diet_signals,
    )


def resolve_menu_item_launch_timestamp(menu_item: MenuItem) -> datetime:
    launched_at = menu_item.launched_at or menu_item.created_at
    if launched_at.tzinfo is None:
        return launched_at.replace(tzinfo=UTC)
    return launched_at


def is_manual_new_launch(menu_item: MenuItem) -> bool:
    return bool(getattr(menu_item, "is_new_launch", False))


def is_menu_item_new(menu_item: MenuItem, *, now: datetime | None = None) -> bool:
    if not is_manual_new_launch(menu_item):
        return False

    settings = get_settings()
    window_days = max(settings.new_item_window_days, 0)
    if window_days <= 0:
        return False

    current_time = now or datetime.now(UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)

    launched_at = resolve_menu_item_launch_timestamp(menu_item)
    return launched_at >= current_time - timedelta(days=window_days)


def get_new_item_reason(menu_item: MenuItem) -> str | None:
    if not is_menu_item_new(menu_item):
        return None

    settings = get_settings()
    return (
        f"Marked as a just-launched item within the last "
        f"{max(settings.new_item_window_days, 0)} days."
    )


def resolve_menu_item_popularity_score(menu_item: MenuItem) -> float:
    popularity_score = menu_item.popularity_score
    if popularity_score is None:
        return 0.0
    if isinstance(popularity_score, Decimal):
        return float(popularity_score)
    return float(popularity_score)


def is_high_popularity_value(value: float | int | Decimal | None) -> bool:
    if value is None:
        return False
    numeric = float(value)
    if numeric <= 1.0:
        return numeric >= 0.75
    return numeric >= TRENDING_POPULARITY_THRESHOLD


def is_menu_item_trending(
    menu_item: MenuItem,
    *,
    popularity_score: float | int | Decimal | None = None,
) -> bool:
    numeric_popularity = (
        resolve_menu_item_popularity_score(menu_item)
        if popularity_score is None
        else float(popularity_score)
    )
    return is_menu_item_new(menu_item) and is_high_popularity_value(numeric_popularity)


def build_generic_menu_item_badge_metadata(
    menu_item: MenuItem,
) -> tuple[str | None, str | None]:
    if is_menu_item_trending(menu_item):
        return "Trending Now", "A just-launched item gaining strong customer demand."
    if is_menu_item_bestseller(menu_item):
        return "Best Seller", "One of the most-ordered items at this branch recently."
    if is_menu_item_new(menu_item):
        return "Just Launched", "Manually marked as a recent launch."
    return None, None

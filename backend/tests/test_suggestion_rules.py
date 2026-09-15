"""The rules that decide what a waiter offers next.

Pure over their inputs on purpose. The selling rules are the part most likely
to be argued about later, and a rule that needs a database and a session to
exercise is a rule nobody re-checks after changing it.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.suggestions import (
    AddOnOption,
    CandidateItem,
    CartLineFacts,
    CategoryFallbackItem,
    ComboUpgrade,
    PairingPattern,
    SizeOption,
    choose_category_default,
    choose_pairing,
    choose_upsell,
    order_category_fallback,
)

CURRY = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
TEA = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
RICE = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
PIZZA = uuid.UUID("00000000-0000-0000-0000-0000000000ef")


def _candidate(item_id: uuid.UUID, *, is_veg: bool = True, available: bool = True) -> CandidateItem:
    return CandidateItem(
        menu_item_id=item_id,
        category="Beverages",
        is_veg=is_veg,
        is_available=available,
    )


class PairingRuleTests(unittest.TestCase):
    def test_a_pattern_missing_exactly_one_item_yields_that_item(self) -> None:
        pattern = PairingPattern(item_ids=(CURRY, TEA), confidence_score=Decimal("9"))

        result = choose_pairing(
            [pattern],
            {CURRY},
            candidates={TEA: _candidate(TEA)},
            diet=None,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.menu_item_id, TEA)
        self.assertEqual(result.basis, "co_occurrence")
        self.assertEqual(result.kind, "cross_sell")

    def test_a_pattern_missing_two_items_is_not_a_pairing(self) -> None:
        """Suggesting two things at once is a menu, not a waiter's nudge."""

        pattern = PairingPattern(item_ids=(CURRY, TEA, RICE), confidence_score=Decimal("9"))

        self.assertIsNone(
            choose_pairing(
                [pattern],
                {CURRY},
                candidates={TEA: _candidate(TEA), RICE: _candidate(RICE)},
                diet=None,
            )
        )

    def test_a_pattern_that_does_not_touch_the_cart_is_ignored(self) -> None:
        pattern = PairingPattern(item_ids=(TEA, RICE), confidence_score=Decimal("9"))

        self.assertIsNone(
            choose_pairing([pattern], {CURRY}, candidates={TEA: _candidate(TEA)}, diet=None)
        )

    def test_the_highest_confidence_pattern_wins(self) -> None:
        weak = PairingPattern(item_ids=(CURRY, TEA), confidence_score=Decimal("3"))
        strong = PairingPattern(item_ids=(CURRY, RICE), confidence_score=Decimal("11"))

        result = choose_pairing(
            [weak, strong],
            {CURRY},
            candidates={TEA: _candidate(TEA), RICE: _candidate(RICE)},
            diet=None,
        )

        self.assertEqual(result.menu_item_id, RICE)

    def test_a_veg_customer_is_never_offered_a_non_veg_pairing(self) -> None:
        """The business-rule filter runs BEFORE ranking, everywhere in this repo."""

        pattern = PairingPattern(item_ids=(CURRY, TEA), confidence_score=Decimal("99"))

        self.assertIsNone(
            choose_pairing(
                [pattern],
                {CURRY},
                candidates={TEA: _candidate(TEA, is_veg=False)},
                diet="VEG",
            )
        )

    def test_an_unavailable_item_is_never_offered(self) -> None:
        pattern = PairingPattern(item_ids=(CURRY, TEA), confidence_score=Decimal("99"))

        self.assertIsNone(
            choose_pairing(
                [pattern],
                {CURRY},
                candidates={TEA: _candidate(TEA, available=False)},
                diet=None,
            )
        )

    def test_an_empty_cart_yields_nothing(self) -> None:
        pattern = PairingPattern(item_ids=(CURRY, TEA), confidence_score=Decimal("9"))

        self.assertIsNone(
            choose_pairing([pattern], set(), candidates={TEA: _candidate(TEA)}, diet=None)
        )


class CategoryFallbackTests(unittest.TestCase):
    """The honest gap-filler.

    Measured on 2026-09-14: 7 visible combos mined from 17 multi-item delivered
    orders. Six pairs cannot cover a 117-item menu, so without this the
    evidence-backed rule is silent nearly always. It earns its place ONLY
    because `basis` forces the copy to admit which one fired.
    """

    def test_a_cart_with_no_drink_is_offered_the_bestselling_drink(self) -> None:
        result = choose_category_default(
            {"Main Course"},
            bestsellers={"Beverages": [TEA]},
            candidates={TEA: _candidate(TEA)},
            diet=None,
        )

        self.assertIsNotNone(result)
        self.assertEqual(result.menu_item_id, TEA)
        self.assertEqual(result.basis, "category_default")
        self.assertEqual(result.kind, "cross_sell")

    def test_a_category_the_cart_already_has_is_not_offered(self) -> None:
        self.assertIsNone(
            choose_category_default(
                {"Main Course", "Beverages"},
                bestsellers={"Beverages": [TEA]},
                candidates={TEA: _candidate(TEA)},
                diet=None,
            )
        )

    def test_the_diet_filter_applies_to_the_fallback_too(self) -> None:
        self.assertIsNone(
            choose_category_default(
                {"Main Course"},
                bestsellers={"Beverages": [TEA]},
                candidates={TEA: _candidate(TEA, is_veg=False)},
                diet="VEG",
            )
        )

    def test_no_bestseller_for_the_missing_category_yields_silence(self) -> None:
        self.assertIsNone(
            choose_category_default(
                {"Main Course"},
                bestsellers={},
                candidates={},
                diet=None,
            )
        )

    def test_an_empty_cart_yields_nothing(self) -> None:
        """Empty category set (no resolvable items) yields no suggestion."""

        self.assertIsNone(
            choose_category_default(
                set(),
                bestsellers={"Beverages": [TEA]},
                candidates={TEA: _candidate(TEA)},
                diet=None,
            )
        )


class CategoryFallbackOrderingTests(unittest.TestCase):
    """The order `_bestsellers_by_category` falls back to when a category has
    no real bestseller yet.

    Suppression memory keys on whichever id this order puts first, so the
    same set of candidates must sort the same way on every call — that is
    what each test below is actually checking, not just "is it cheapest".
    """

    def test_the_cheapest_item_sorts_first(self) -> None:
        cheap = CategoryFallbackItem(menu_item_id=TEA, price=Decimal("30"), name="Tea")
        pricey = CategoryFallbackItem(menu_item_id=RICE, price=Decimal("90"), name="Mango Lassi")

        self.assertEqual(order_category_fallback([pricey, cheap]), [TEA, RICE])

    def test_equal_price_breaks_the_tie_on_name(self) -> None:
        later_name = CategoryFallbackItem(menu_item_id=RICE, price=Decimal("50"), name="Soda")
        earlier_name = CategoryFallbackItem(menu_item_id=TEA, price=Decimal("50"), name="Lemonade")

        self.assertEqual(order_category_fallback([later_name, earlier_name]), [TEA, RICE])

    def test_equal_price_and_name_breaks_the_tie_on_id(self) -> None:
        lower_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        higher_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
        first = CategoryFallbackItem(menu_item_id=higher_id, price=Decimal("50"), name="Soda")
        second = CategoryFallbackItem(menu_item_id=lower_id, price=Decimal("50"), name="Soda")

        self.assertEqual(order_category_fallback([first, second]), [lower_id, higher_id])

    def test_the_order_is_stable_across_repeated_calls(self) -> None:
        """Guards the actual defect: a non-deterministic order would let the
        same cart offer a different item on retry and defeat DECLINE_LIMIT."""

        items = [
            CategoryFallbackItem(menu_item_id=TEA, price=Decimal("30"), name="Tea"),
            CategoryFallbackItem(menu_item_id=RICE, price=Decimal("30"), name="Cola"),
            CategoryFallbackItem(menu_item_id=CURRY, price=Decimal("90"), name="Cake"),
        ]

        first_call = order_category_fallback(list(items))
        second_call = order_category_fallback(list(reversed(items)))

        self.assertEqual(first_call, second_call)
        self.assertEqual(first_call, [RICE, TEA, CURRY])

    def test_an_empty_category_yields_an_empty_order(self) -> None:
        self.assertEqual(order_category_fallback([]), [])


class UpsellLadderTests(unittest.TestCase):
    """Ordered by value to the CUSTOMER, not margin to the restaurant.

    A combo saves money, a size gives more food, an add-on only costs more. A
    waiter who opens with the most profitable add-on gets tuned out, and then
    none of the three rungs work.
    """

    def _line(self, item_id=PIZZA, *, size_id=None, option_ids=()):
        return CartLineFacts(
            menu_item_id=item_id,
            size_id=size_id,
            customization_option_ids=frozenset(option_ids),
        )

    def test_a_combo_upgrade_beats_a_size_upgrade(self) -> None:
        combo_id = uuid.uuid4()
        larger = uuid.uuid4()

        result = choose_upsell(
            [self._line(size_id=uuid.uuid4())],
            combos=[ComboUpgrade(combo_id=combo_id, item_ids=(PIZZA,), saving=Decimal("4.00"))],
            sizes=[SizeOption(menu_item_id=PIZZA, size_id=larger, extra_cost=Decimal("3.00"))],
            add_ons=[],
        )

        self.assertEqual(result.basis, "combo_upgrade")
        self.assertEqual(result.combo_id, combo_id)
        self.assertEqual(result.saving, Decimal("4.00"))
        self.assertEqual(result.kind, "up_sell")

    def test_a_size_upgrade_beats_an_add_on(self) -> None:
        larger = uuid.uuid4()
        option = uuid.uuid4()

        result = choose_upsell(
            [self._line(size_id=uuid.uuid4())],
            combos=[],
            sizes=[SizeOption(menu_item_id=PIZZA, size_id=larger, extra_cost=Decimal("3.00"))],
            add_ons=[AddOnOption(menu_item_id=PIZZA, option_id=option, extra_cost=Decimal("1.00"))],
        )

        self.assertEqual(result.basis, "size_upgrade")
        self.assertEqual(result.size_id, larger)
        self.assertEqual(result.extra_cost, Decimal("3.00"))

    def test_an_add_on_is_the_last_resort(self) -> None:
        option = uuid.uuid4()

        result = choose_upsell(
            [self._line()],
            combos=[],
            sizes=[],
            add_ons=[AddOnOption(menu_item_id=PIZZA, option_id=option, extra_cost=Decimal("1.00"))],
        )

        self.assertEqual(result.basis, "add_on")
        self.assertEqual(result.customization_option_id, option)

    def test_a_combo_the_cart_does_not_fully_contain_is_not_offered(self) -> None:
        """A combo upgrade is only an upgrade if the cart already holds it."""

        other = uuid.uuid4()

        self.assertIsNone(
            choose_upsell(
                [self._line()],
                combos=[ComboUpgrade(combo_id=uuid.uuid4(), item_ids=(PIZZA, other), saving=Decimal("4.00"))],
                sizes=[],
                add_ons=[],
            )
        )

    def test_an_add_on_already_chosen_is_not_offered_again(self) -> None:
        option = uuid.uuid4()

        self.assertIsNone(
            choose_upsell(
                [self._line(option_ids=(option,))],
                combos=[],
                sizes=[],
                add_ons=[AddOnOption(menu_item_id=PIZZA, option_id=option, extra_cost=Decimal("1.00"))],
            )
        )

    def test_an_empty_cart_yields_nothing(self) -> None:
        self.assertIsNone(choose_upsell([], combos=[], sizes=[], add_ons=[]))


if __name__ == "__main__":
    unittest.main()

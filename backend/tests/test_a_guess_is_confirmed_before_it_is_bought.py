"""A dish nobody named exactly is a question, never a purchase.

Live, mid-order, building a pizza:

    > Green curry
      Added 1 x Build Your Own Pizza to your order. Anything else?
    > Mozzarella and mushroom
      Added 1 x Farmhouse Pizza to your order. Anything else?

The customer was naming toppings. A $329 pizza went into the cart, and
nothing asked them anything.

`_add_named_dish` already refuses to choose between dishes with somebody's
money — "a name that fits several dishes is a question, not a choice this
agent gets to make" — but it only refuses when SEVERAL dish names matched the
words. "Mozzarella and mushroom" matches no dish name at all, so that guard
never fired, and the semantic cascade below it resolved a dish anyway and
added it.

It is the same judgement in both cases: nobody said that dish's name. The
count of near misses does not change whether the customer asked for it.

The near-miss path still has to work, so the rule is confirm-then-add rather
than refuse. "khaman dhokla" matches no dish name either — Radhe Dhokla sells
Vagharela Khaman — and that is an order somebody really places. It is now
answered "Did you mean Vagharela Khaman?" and a yes adds it, which is what a
waiter does with a name they did not quite catch.

An exact name is untouched: "Chiang Mai Noodle Box" adds without an extra
question, because there is nothing to confirm.

And the confirmation is only asked when the add would otherwise go straight
through. A dish that still needs a size answers with "Which size for Vagharela
Khaman?", which names the dish as plainly as any confirmation would and lets
the customer correct it before a penny is committed — so "khaman dhokla" and
every typo like it keeps its one-step path. The extra question is spent only
where it buys something: a dish with nothing left to ask, which would land in
the cart unannounced.
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent import loop as loop_module

SOURCE = inspect.getsource(loop_module.run_turn)


def add_named_dish() -> str:
    start = SOURCE.index("def _add_named_dish")
    return SOURCE[start : SOURCE.index("def _run_add", start)]


class NothingIsBoughtOnAGuessTests(unittest.TestCase):
    """The $329 pizza."""

    def test_an_inexact_name_is_confirmed_rather_than_added(self) -> None:
        # The only guard used to be `len(candidates) > 1`, so a name matching
        # NO dish fell straight through to the semantic cascade and was added.
        # That branch stays — it lists the near misses, which is a better
        # question when there are several — and this is the case it never
        # covered.
        self.assertIn(
            "would_be_added_without_asking(lookup)",
            add_named_dish(),
            "a name matching no dish at all still skips the confirmation",
        )

    def test_the_confirmation_is_asked_before_any_add(self) -> None:
        body = add_named_dish()
        confirm = body.index("Did you mean")
        add = body.index("_run_add(")
        self.assertLess(confirm, add, "it adds first and asks afterwards")

    def test_an_exact_name_still_adds_without_an_extra_question(self) -> None:
        # Otherwise every order grows a confirmation step nobody needs.
        self.assertIn("if exact", add_named_dish())


class WhenTheConfirmationIsWorthAskingTests(unittest.TestCase):
    """Only when the add would otherwise go straight through."""

    def rule(self, lookup):
        from app.services.ordering_agent.loop import would_be_added_without_asking

        return would_be_added_without_asking(lookup)

    def test_a_dish_with_nothing_left_to_ask_would_land_unannounced(self) -> None:
        # Farmhouse Pizza: no sizes, no required group. This is the one that
        # put $329 in a cart.
        self.assertTrue(self.rule({"name": "Farmhouse Pizza"}))
        self.assertTrue(self.rule({"name": "X", "available_sizes": [], "customization_groups": []}))

    def test_a_dish_that_still_needs_a_size_asks_anyway(self) -> None:
        # "Which size for Vagharela Khaman?" names the dish itself, so a
        # second question would only slow a real order down.
        self.assertFalse(
            self.rule({"name": "Vagharela Khaman", "available_sizes": [{"size_id": "s1"}]})
        )

    def test_a_dish_with_a_required_group_asks_anyway(self) -> None:
        self.assertFalse(
            self.rule({
                "name": "Pizza",
                "customization_groups": [{"title": "Crust", "needs_selection": True}],
            })
        )

    def test_an_optional_group_is_not_a_question(self) -> None:
        # Optional groups do not block an add, so nothing would be asked.
        self.assertTrue(
            self.rule({
                "name": "Pizza",
                "customization_groups": [{"title": "Toppings", "needs_selection": False}],
            })
        )

    def test_the_catalog_shape_is_read_too(self) -> None:
        # Two shapes reach this rule. `add_to_cart`'s needs_choice result says
        # `available_sizes` and `needs_selection`; `get_dish`'s catalog result
        # — which is the one `_add_named_dish` actually holds — says `sizes` /
        # `has_sizes` and `is_required`. Reading only the first made every
        # sized dish look like it would land silently, and "khaman dhokla"
        # asked "Did you mean Vagharela Khaman?" instead of its size.
        self.assertFalse(self.rule({"name": "Vagharela Khaman", "has_sizes": True, "sizes": []}))
        self.assertFalse(
            self.rule({"name": "Vagharela Khaman", "sizes": [{"name": "Per Plate"}]})
        )
        self.assertFalse(
            self.rule({
                "name": "Build Your Own Pizza",
                "customization_groups": [{"title": "Sauce", "is_required": True}],
            })
        )

    def test_an_optional_catalog_group_is_still_not_a_question(self) -> None:
        # Farmhouse Pizza's shape: nothing required, nothing sized.
        self.assertTrue(
            self.rule({
                "name": "Farmhouse Pizza",
                "has_sizes": False,
                "sizes": [],
                "customization_groups": [{"title": "Toppings", "is_required": False}],
            })
        )

    def test_nothing_to_read_is_treated_as_going_straight_through(self) -> None:
        # The cautious way round: confirm rather than spend.
        self.assertTrue(self.rule(None))
        self.assertTrue(self.rule({}))


class TheSentenceItselfTests(unittest.TestCase):
    """What the customer reads."""

    def test_it_names_the_dish_it_found(self) -> None:
        # "Did you mean something else?" is not a question anybody can answer.
        body = add_named_dish()
        self.assertIn("Did you mean", body)

    def test_it_asks_one_thing(self) -> None:
        # The house rule: "the answer to both of them is yes".
        for line in add_named_dish().splitlines():
            if "Did you mean" in line and '"' in line:
                self.assertNotIn(", or ", line, line)


if __name__ == "__main__":
    unittest.main()

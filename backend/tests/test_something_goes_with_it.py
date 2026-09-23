"""Adding a dish is the moment a waiter offers something with it.

    Added 1 x Build Your Own Pizza to your order. Anything else?

True, and the least a restaurant could say. Somebody who has just chosen a
pizza is the easiest person in the world to sell a drink to, and this asked an
open question instead — "anything else?" puts the work of remembering the menu
back on the customer, at the one moment they were ready to be led.

The suggestions are rows, not taste. `dishes_to_suggest` already orders by the
branch's own bestseller and popularity columns, takes at most one per section
so three suggestions are three ideas rather than three main courses, and skips
whatever is already in the cart. Nothing here is a guess about what goes with
what; it is what people at this branch actually order.

It stays ONE question. The suggestions are laid out to be read and "Anything
else?" is still the only thing asked, because "Added it. Would you like a
drink, or anything else?" is two questions and the answer to both is yes —
which is the fault this codebase has already fixed twice.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent.loop import ToolCallRecord, bind_chat_currency, describe_applied


def added(name="Build Your Own Pizza", quantity=1) -> list[ToolCallRecord]:
    return [
        ToolCallRecord(
            tool="add_to_cart",
            args={},
            result={
                "outcome": "action",
                "name": name,
                "quantity": quantity,
                "action": {"kind": "add", "status": "applied", "quantity": quantity},
            },
        )
    ]


GOES_WITH = [
    {"name": "Thai Iced Tea", "price": "4.49"},
    {"name": "Mango Sticky Rice", "price": "8.99"},
]


class NothingToSuggestTests(unittest.TestCase):
    """Unchanged, and still the common case."""

    def setUp(self) -> None:
        bind_chat_currency("USD")

    def test_the_sentence_is_exactly_what_it_was(self) -> None:
        self.assertEqual(
            describe_applied(added("Corn Fritters", 2)),
            "Added 2 x Corn Fritters to your order. Anything else?",
        )

    def test_an_empty_list_changes_nothing(self) -> None:
        self.assertEqual(describe_applied(added(), goes_with=[]), describe_applied(added()))

    def test_nothing_applied_still_says_nothing(self) -> None:
        self.assertIsNone(describe_applied([], goes_with=GOES_WITH))


class SomethingToSuggestTests(unittest.TestCase):
    """The offer a waiter makes."""

    def setUp(self) -> None:
        bind_chat_currency("USD")

    def said(self) -> str:
        return describe_applied(added(), goes_with=GOES_WITH)

    def test_what_was_added_is_still_said_first(self) -> None:
        self.assertTrue(
            self.said().startswith("Added 1 x Build Your Own Pizza to your order."),
            self.said(),
        )

    def test_each_suggestion_is_named_and_priced(self) -> None:
        said = self.said()
        self.assertIn("- Thai Iced Tea - $4.49", said)
        self.assertIn("- Mango Sticky Rice - $8.99", said)

    def test_it_is_offered_rather_than_asserted(self) -> None:
        # "Goes well with" is a claim about the kitchen; these rows are only
        # what people order. The wording has to stay on the right side of that.
        said = self.said().lower()
        self.assertTrue(
            "often" in said or "popular" in said or "people" in said,
            self.said(),
        )

    def test_it_still_asks_exactly_one_thing(self) -> None:
        self.assertEqual(self.said().count("?"), 1)
        self.assertIn("Anything else?", self.said())

    def test_the_question_is_last(self) -> None:
        # Buried above a price list it reads as part of the list.
        self.assertTrue(self.said().rstrip().endswith("Anything else?"), self.said())


class RemovingIsNotAnOpeningTests(unittest.TestCase):
    """Taking something out is not the moment to sell."""

    def setUp(self) -> None:
        bind_chat_currency("USD")

    def test_a_removal_is_not_followed_by_suggestions(self) -> None:
        removed = [
            ToolCallRecord(
                tool="remove_from_cart",
                args={},
                result={
                    "outcome": "action",
                    "name": "Corn Fritters",
                    "action": {"kind": "remove", "status": "applied"},
                },
            )
        ]
        said = describe_applied(removed, goes_with=GOES_WITH)
        self.assertIn("Removed Corn Fritters", said)
        self.assertNotIn("Thai Iced Tea", said)


if __name__ == "__main__":
    unittest.main()

"""A price a customer names is a filter, not a phrase to search for.

"A light lunch under $20" used to be handed to the menu reader whole. It
matched no dish called that, so the reply listed the branch's entire menu
under a sentence saying there was nothing — eight dishes, every one of them
under twenty dollars. The wording was fixed first; this is the half that
makes the reply actually answer the question.

Two decisions are worth stating, because both were available and only one is
consistent with this codebase.

**The number comes from the reading, not from the words.** `read_order_intent`
extracts `max_price`, the same way it already extracts `category` and the
dish. Nothing here scans for "under" or "cheap": a list of words deciding what
a message meant is exactly what this agent does not do, and the model is
already reading every message anyway.

**The ceiling narrows the base query, not a branch of it.** A customer who
says "paneer under 200" means both halves at once, so the filter sits on the
statement every strategy builds from — by name, by section, by a shortened
phrase, or the whole menu. Bolting it onto one branch would have answered
"paneer under 200" with paneer at any price.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.ordering_agent import tools as tools_module
from app.services.ordering_agent.planner import read_order_intent


class TheReadingCarriesTheCeilingTests(unittest.TestCase):
    """`max_price` off the model's answer, coerced before anything uses it."""

    def reading(self, answer: str) -> dict:
        return read_order_intent("anything under 200", generate=lambda *a, **k: answer)

    def test_a_number_is_kept_as_a_number(self) -> None:
        got = self.reading('{"browse": "anything", "max_price": 200}')
        self.assertEqual(got["max_price"], Decimal("200"))

    def test_a_string_the_model_wrote_is_coerced(self) -> None:
        # Asked for a bare number, the model still answers "200" about as
        # often as 200, and a string would reach a numeric column.
        self.assertEqual(self.reading('{"max_price": "200"}')["max_price"], Decimal("200"))

    def test_a_currency_symbol_does_not_defeat_it(self) -> None:
        self.assertEqual(self.reading('{"max_price": "\\u20b9200"}')["max_price"], Decimal("200"))
        self.assertEqual(self.reading('{"max_price": "$20.50"}')["max_price"], Decimal("20.50"))

    def test_no_ceiling_is_none_rather_than_zero(self) -> None:
        # Zero would filter the whole menu away.
        for answer in ('{"max_price": null}', '{"max_price": "cheap"}',
                       '{"max_price": 0}', '{"max_price": -5}', '{"max_price": true}', "{}"):
            with self.subTest(answer=answer):
                self.assertIsNone(self.reading(answer)["max_price"])

    def test_a_model_that_answers_nothing_still_reads(self) -> None:
        self.assertIsNone(read_order_intent("hi", generate=lambda *a, **k: "not json")["max_price"])


class TheCeilingNarrowsTheQueryTests(unittest.TestCase):
    """`dishes_to_show`, with the database stubbed to record what it was asked.

    The rows do not matter here; which WHERE clauses were built does, because
    that is the whole behaviour: a ceiling that reaches only one search
    strategy is a ceiling a customer can walk around by naming a dish.
    """

    def setUp(self) -> None:
        self.statements: list[str] = []

        class FakeSession:
            def scalars(_self, statement):
                self.statements.append(
                    str(statement.compile(compile_kwargs={"literal_binds": True}))
                )
                return iter([])

        self.db = FakeSession()
        self.scope = SimpleNamespace(
            restaurant_location_id=uuid.uuid4(), restaurant_id=uuid.uuid4(), diet=None,
        )

    def show(self, phrase: str, **kwargs):
        return tools_module.dishes_to_show(self.db, self.scope, phrase, **kwargs)

    def test_every_search_carries_the_ceiling(self) -> None:
        # Every strategy: by name, by section, by a shortened phrase, and the
        # whole menu. The one exception is deliberate and is the subject of
        # the next test.
        self.show("paneer", max_price=Decimal("200"), report={})
        self.assertTrue(self.statements, "it asked the database something")
        searches = [s for s in self.statements if "ORDER BY menu_items.price" not in s]
        self.assertTrue(searches)
        for sql in searches:
            with self.subTest(sql=sql[-90:]):
                self.assertIn("price <= 200", sql.replace("menu_items.", ""))

    def test_the_cheapest_query_deliberately_drops_it(self) -> None:
        # The "nothing came in under your figure, here is the cheapest we do
        # have" answer cannot itself be filtered by that figure, or it would
        # have nothing to return either.
        self.show("paneer", max_price=Decimal("200"), report={})
        cheapest = [s for s in self.statements if "ORDER BY menu_items.price" in s]
        self.assertEqual(len(cheapest), 1)
        self.assertNotIn("price <=", cheapest[0].replace("menu_items.", ""))

    def test_without_one_nothing_is_filtered_by_price(self) -> None:
        self.show("paneer", report={})
        for sql in self.statements:
            self.assertNotIn("price <=", sql.replace("menu_items.", ""))

    def test_the_name_search_still_happens_underneath_it(self) -> None:
        # Both halves of "paneer under 200", not one.
        self.show("paneer", max_price=Decimal("200"), report={})
        self.assertTrue(
            any("name" in sql.lower() and "price <= 200" in sql.replace("menu_items.", "")
                for sql in self.statements),
            "the words are still searched for, under the ceiling",
        )


class WhatItFoundIsReportedHonestlyTests(unittest.TestCase):
    """`found_by`, which decides the sentence written above the list."""

    def rows_for(self, under_ceiling: list, whole_menu: list, max_price):
        """A session answering the ceilinged queries and the unceilinged one
        differently, which is the only thing that separates the two cases."""

        class FakeSession:
            def scalars(_self, statement):
                sql = str(statement.compile(compile_kwargs={"literal_binds": True}))
                bare = sql.replace("menu_items.", "")
                # A search for the words, or for a section, finds nothing —
                # which is the case that reaches the ceiling at all. The plain
                # ceilinged query is the budget answer; the one ordered by
                # price is the over-budget fallback, which drops the ceiling.
                # Rendered as lower(name) LIKE lower(...) by the default compiler,
                # so the word to look for is LIKE rather than ILIKE.
                if "LIKE" in bare.upper() or "category =" in bare:
                    return iter([])
                if "ORDER BY price" in bare:
                    return iter(whole_menu)
                return iter(under_ceiling)

        scope = SimpleNamespace(
            restaurant_location_id=uuid.uuid4(), restaurant_id=uuid.uuid4(), diet=None,
        )
        report: dict = {}
        rows = tools_module.dishes_to_show(
            FakeSession(), scope, "anything", max_price=max_price, report=report,
        )
        return rows, report

    def a_dish(self, name: str, price: str):
        # `has_sizes` is a real column; `dishes_to_show` carries it so a
        # single-dish read-back knows not to quote one price for a dish
        # sold in three.
        return SimpleNamespace(name=name, price=Decimal(price), is_veg=True, has_sizes=False)

    def test_rows_under_the_ceiling_are_not_called_a_fallback(self) -> None:
        # They are an answer to what was asked, not the shrug that "fallback"
        # describes — and the caller writes a different sentence for each.
        _, report = self.rows_for(
            under_ceiling=[self.a_dish("Corn Fritters", "8.49")],
            whole_menu=[self.a_dish("Corn Fritters", "8.49")],
            max_price=Decimal("20"),
        )
        self.assertEqual(report["found_by"], "budget")

    def test_nothing_under_the_ceiling_says_so_rather_than_answering_empty(self) -> None:
        # An empty list reads as "no menu" by the time it reaches a customer.
        # The cheapest dishes plus an honest sentence is the useful reply.
        rows, report = self.rows_for(
            under_ceiling=[],
            whole_menu=[self.a_dish("Appetizer Sampler", "18.99")],
            max_price=Decimal("2"),
        )
        self.assertEqual(report["found_by"], "over_budget")
        self.assertEqual([r["name"] for r in rows], ["Appetizer Sampler"])

    def test_no_ceiling_leaves_the_old_words_alone(self) -> None:
        _, report = self.rows_for(under_ceiling=[], whole_menu=[], max_price=None)
        self.assertNotIn(report.get("found_by"), {"budget", "over_budget"})


if __name__ == "__main__":
    unittest.main()

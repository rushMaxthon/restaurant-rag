"""The words on a restaurant's own website.

Page title, meta description and hero copy were string literals in the
customer web app, so all six tenants shared one restaurant's marketing —
including in their search-engine listings, which is the part that does lasting
damage: a crawler that indexed `dragon-wok.example.com` under "Bangkok Bowl —
Thai Food Delivery" is describing the wrong business to the world.

Three properties carry the weight here, and each has a way of going wrong that
would not be obvious from reading the code:

- **Every key always comes back.** Whatever is unwritten is derived from the
  restaurant's own name, cuisine and city, so a tenant onboarded five minutes
  ago reads correctly and no client has to decide what to do about a blank.
- **An edit changes only what it sent.** The whole-object write is how a form
  that edits a hero silently blanks a meta description somebody wrote last
  month.
- **Clearing means "go back to the default"**, not "this restaurant's hero has
  no words".
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.restaurant_storefront import (
    STOREFRONT_KEYS,
    STOREFRONT_LIMITS,
    StorefrontValidationError,
    default_storefront,
    read_storefront,
    resolve_storefront,
)


def a_restaurant(**overrides):
    base = {
        "name": "Dragon Wok",
        "cuisine_type": "Chinese",
        "city": "Ahmedabad",
        "description": "Delicious dim sum and stir-fried noodles.",
        "storefront": {},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class WhatARestaurantSaysByItselfTests(unittest.TestCase):
    def test_every_key_is_present_for_a_restaurant_that_has_written_nothing(self) -> None:
        copy = read_storefront(a_restaurant())
        for key in STOREFRONT_KEYS:
            self.assertIn(key, copy, key)
            self.assertTrue(copy[key].strip(), key)

    def test_the_defaults_are_about_this_restaurant(self) -> None:
        copy = read_storefront(a_restaurant())
        self.assertEqual(copy["meta_title"], "Dragon Wok — Chinese food delivery in Ahmedabad")
        self.assertEqual(copy["hero_headline"], "Dragon Wok")
        self.assertIn("Dragon Wok", copy["login_blurb"])
        # The bug being fixed, stated as an assertion.
        for key in STOREFRONT_KEYS:
            self.assertNotIn("Bangkok", copy[key], key)

    def test_a_half_onboarded_restaurant_still_reads_as_a_sentence(self) -> None:
        """No cuisine, no city, no description — onboarding collects them late."""

        copy = read_storefront(
            a_restaurant(cuisine_type="", city="", description=None)
        )
        self.assertEqual(copy["meta_title"], "Dragon Wok — Food delivery")
        # No dangling "in " where the city would have been.
        self.assertFalse(copy["login_blurb"].endswith("in ."))
        self.assertEqual(copy["login_blurb"], "Sign in to order from Dragon Wok.")

    def test_a_nameless_restaurant_does_not_produce_a_nameless_title(self) -> None:
        copy = read_storefront(a_restaurant(name="  ", cuisine_type="", city=""))
        self.assertTrue(copy["meta_title"].strip())
        self.assertFalse(copy["meta_title"].startswith("—"))

    def test_the_description_is_used_where_there_is_one(self) -> None:
        copy = read_storefront(a_restaurant())
        self.assertEqual(copy["meta_description"], "Delicious dim sum and stir-fried noodles.")

    def test_without_a_description_one_is_built(self) -> None:
        copy = read_storefront(a_restaurant(description=""))
        self.assertIn("Dragon Wok", copy["meta_description"])
        self.assertIn("Ahmedabad", copy["meta_description"])


class WhatAnOwnerWritesTests(unittest.TestCase):
    def test_a_written_value_wins_over_the_derived_one(self) -> None:
        copy = read_storefront(
            a_restaurant(storefront={"hero_headline": "Wok this way"})
        )
        self.assertEqual(copy["hero_headline"], "Wok this way")

    def test_writing_one_field_leaves_the_others_derived(self) -> None:
        """Per key, not all-or-nothing.

        An owner who writes a hero headline must not lose the derived meta
        description — the derivation is not a placeholder they opted out of by
        touching one field.
        """

        copy = read_storefront(
            a_restaurant(storefront={"hero_headline": "Wok this way"})
        )
        self.assertEqual(copy["meta_title"], "Dragon Wok — Chinese food delivery in Ahmedabad")

    def test_an_edit_does_not_blank_what_it_did_not_send(self) -> None:
        stored = resolve_storefront(
            {"meta_title": "Dragon Wok, Ahmedabad"},
            existing={"hero_headline": "Wok this way"},
        )
        self.assertEqual(stored["hero_headline"], "Wok this way")
        self.assertEqual(stored["meta_title"], "Dragon Wok, Ahmedabad")

    def test_clearing_a_field_restores_the_derived_default(self) -> None:
        stored = resolve_storefront(
            {"hero_headline": ""}, existing={"hero_headline": "Wok this way"}
        )
        self.assertNotIn("hero_headline", stored)
        self.assertEqual(read_storefront(a_restaurant(storefront=stored))["hero_headline"], "Dragon Wok")

    def test_whitespace_is_clearing(self) -> None:
        stored = resolve_storefront(
            {"hero_headline": "   "}, existing={"hero_headline": "Wok this way"}
        )
        self.assertNotIn("hero_headline", stored)

    def test_a_pasted_newline_does_not_reach_the_title_tag(self) -> None:
        stored = resolve_storefront({"meta_title": "Dragon Wok\n  Ahmedabad"})
        self.assertEqual(stored["meta_title"], "Dragon Wok Ahmedabad")

    def test_too_long_is_refused_rather_than_truncated(self) -> None:
        with self.assertRaises(StorefrontValidationError):
            resolve_storefront({"meta_title": "x" * (STOREFRONT_LIMITS["meta_title"] + 1)})

    def test_exactly_at_the_limit_is_allowed(self) -> None:
        value = "x" * STOREFRONT_LIMITS["meta_title"]
        self.assertEqual(resolve_storefront({"meta_title": value})["meta_title"], value)

    def test_a_key_this_platform_does_not_store_is_ignored(self) -> None:
        stored = resolve_storefront({"hero_headline": "Wok this way", "script": "<script>"})
        self.assertEqual(stored, {"hero_headline": "Wok this way"})

    def test_junk_already_in_the_column_does_not_reach_a_page(self) -> None:
        """Rows can predate validation, or be written by other tooling."""

        copy = read_storefront(
            a_restaurant(storefront={"hero_headline": 42, "meta_title": None})
        )
        self.assertEqual(copy["hero_headline"], "Dragon Wok")
        self.assertEqual(copy["meta_title"], "Dragon Wok — Chinese food delivery in Ahmedabad")

    def test_the_defaults_are_the_same_whoever_asks(self) -> None:
        """`default_storefront` is what the edit screen shows beside each input.

        It has to agree exactly with what `read_storefront` falls back to, or
        an owner is told they are replacing one thing and replaces another.
        """

        restaurant = a_restaurant()
        self.assertEqual(default_storefront(restaurant), read_storefront(restaurant))


if __name__ == "__main__":
    unittest.main()

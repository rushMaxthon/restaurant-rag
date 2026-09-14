"""Preferences for someone who has no row in `users`.

Spec: docs/superpowers/specs/2026-09-14-guest-preferences-design.md

The concierge is usable before login by design, so a visitor can say they are
vegetarian twice and be recommended meat on their next visit. Nothing about them
survives the session, because a guest has no row to attach preferences to.

Three decisions from the spec are encoded here, and each has a test whose
failure would mean the feature is doing something nobody agreed to:

* only DURABLE traits are stored — diet and spice level. Cuisine and budget
  describe the meal, not the person; "something cheap tonight" must not become a
  permanent budget tier.
* the ACCOUNT wins on login. A browser's inference never overwrites what a
  person deliberately set.
* client-supplied preferences are honoured for a GUEST and ignored entirely for
  an authenticated user. This is the trust boundary — "backend enforces, UI only
  hides" — and `test_client_preferences_are_ignored_for_a_real_account` is the
  most important assertion in this file.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.chat_principal import GuestPrincipal
from app.services.rag import (
    SessionConversationState,
    _fallback_extract_intent,
    ExtractedIntent,
    durable_traits_from_intent,
    durable_traits_from_message,
    guest_preference_profile,
    resolve_chat_preferences,
    seed_intent_from_preferences,
)


def intent(**kwargs: object) -> ExtractedIntent:
    return ExtractedIntent(intent="dish_recommendation", **kwargs)  # type: ignore[arg-type]


class DurableTraitTests(unittest.TestCase):
    def test_diet_and_spice_are_durable(self) -> None:
        traits = durable_traits_from_intent(intent(diet="veg", spicy=True))
        self.assertEqual(traits, {"diet": "VEG", "spice_level": "HIGH"})

    def test_not_spicy_is_a_trait_too(self) -> None:
        """`spicy=False` is a statement, not an absence.

        "nothing too spicy" tells us as much as "extra spicy" does, and storing
        only the positive case would remember the customers who like heat and
        forget the ones who cannot take it.
        """

        self.assertEqual(durable_traits_from_intent(intent(spicy=False)), {"spice_level": "LOW"})

    def test_cuisine_and_budget_are_not_stored(self) -> None:
        """Decision 3, and the whole reason this function exists.

        These describe one meal. Persisting them would make a single cheap lunch
        into a permanent budget tier.
        """

        traits = durable_traits_from_intent(intent(cuisine="thai", budget=15))
        self.assertEqual(traits, {})

    def test_an_intent_that_says_nothing_stores_nothing(self) -> None:
        self.assertEqual(durable_traits_from_intent(intent()), {})

    def test_an_unrecognised_diet_is_dropped_not_guessed(self) -> None:
        self.assertEqual(durable_traits_from_intent(intent(diet="pescatarian")), {})


class GuestProfileTests(unittest.TestCase):
    def test_a_profile_duck_types_as_user_preferences(self) -> None:
        """Retrieval reads preferences with getattr, so this needs no adapter.

        `_normalized_preference_diet` and `_preference_spice_hint` both look up
        `dietary_preferences` and `spice_level`. Matching those names is what
        lets a guest's traits travel the same path as a stored row.
        """

        profile = guest_preference_profile({"diet": "VEG", "spice_level": "LOW"})
        assert profile is not None
        self.assertEqual(list(profile.dietary_preferences), ["VEG"])
        self.assertEqual(profile.spice_level, "LOW")

    def test_junk_becomes_nothing_rather_than_reaching_a_query(self) -> None:
        self.assertIsNone(guest_preference_profile({"diet": "'; drop table users;--"}))

    def test_an_empty_payload_is_no_profile(self) -> None:
        self.assertIsNone(guest_preference_profile({}))
        self.assertIsNone(guest_preference_profile(None))


class TrustBoundaryTests(unittest.TestCase):
    """Who is allowed to assert a preference.

    CLAUDE.md: backend enforces, UI only hides. A guest has no server-side
    identity, so their browser is the only place their traits can live — but an
    authenticated user has a row, and a client must never be able to speak over
    it.
    """

    def test_a_guest_is_served_from_the_request(self) -> None:
        principal = GuestPrincipal(id=uuid.uuid4())
        profile = resolve_chat_preferences(
            db=None,
            principal=principal,
            guest_preferences={"diet": "VEG"},
        )
        assert profile is not None
        self.assertEqual(list(profile.dietary_preferences), ["VEG"])

    def test_client_preferences_are_ignored_for_a_real_account(self) -> None:
        """The assertion this whole file exists for.

        A signed-in customer's preferences come from the database. A forged
        `guest_preferences` must not be merged, must not act as a fallback, and
        must not win — it must be as though it were never sent. `db=None` here
        stands in for "no stored preferences": the correct answer is None, NOT
        the client's claim.
        """

        class FakeUser:
            id = uuid.uuid4()

        profile = resolve_chat_preferences(
            db=None,
            principal=FakeUser(),  # type: ignore[arg-type]
            guest_preferences={"diet": "VEG", "spice_level": "HIGH"},
        )
        self.assertIsNone(profile)


class IntentSeedingTests(unittest.TestCase):
    """How a stored trait actually reaches the results.

    Discovered while implementing, and it changed the design. The spec said diet
    and spice would be "always applied" by loading the preference object on
    every turn — but `_normalized_preference_diet` and `_preference_spice_hint`
    are read in exactly one place, `_new_item_sort_key`, as ranking bonuses.
    Loading them more often would not have filtered anything.

    What actually shapes retrieval is `intent.diet`: it goes into the effective
    query and the candidate filters. So a stored trait is applied by seeding the
    intent when the message itself did not state one — which reuses the whole
    existing filter path instead of running a second one beside it.
    """

    def test_a_stored_diet_fills_an_intent_that_did_not_state_one(self) -> None:
        i = intent()
        seed_intent_from_preferences(i, guest_preference_profile({"diet": "VEG"}))
        self.assertEqual(i.diet, "veg")

    def test_the_message_always_wins(self) -> None:
        """What someone asks for now beats what they said before.

        A vegetarian ordering for someone else must be able to say so. Letting a
        stored trait override an explicit request would make the preference
        impossible to escape without editing an account setting mid-conversation.
        """

        i = intent(diet="non_veg")
        seed_intent_from_preferences(i, guest_preference_profile({"diet": "VEG"}))
        self.assertEqual(i.diet, "non_veg")

    def test_spice_seeds_the_same_way(self) -> None:
        i = intent()
        seed_intent_from_preferences(i, guest_preference_profile({"spice_level": "HIGH"}))
        self.assertIs(i.spicy, True)

    def test_an_explicit_not_spicy_survives_a_stored_preference_for_heat(self) -> None:
        i = intent(spicy=False)
        seed_intent_from_preferences(i, guest_preference_profile({"spice_level": "HIGH"}))
        self.assertIs(i.spicy, False)

    def test_no_preferences_changes_nothing(self) -> None:
        i = intent()
        seed_intent_from_preferences(i, None)
        self.assertIsNone(i.diet)
        self.assertIsNone(i.spicy)


class InferenceFromMessageTests(unittest.TestCase):
    """What the fast path can actually learn.

    `_fallback_extract_intent` sets neither diet nor spicy for ANY phrasing, and
    it is the path most messages take — so inference built on the intent alone
    learned nothing in practice. The cache descriptor does detect diet, so that
    is where diet comes from.
    """

    def test_a_stated_diet_is_learned(self) -> None:
        for phrase in ("I am vegetarian, what do you have", "veg food please"):
            with self.subTest(phrase=phrase):
                i = _fallback_extract_intent(phrase, SessionConversationState())
                self.assertEqual(durable_traits_from_message(phrase, i), {"diet": "VEG"})

    def test_non_veg_is_not_read_as_veg(self) -> None:
        """The descriptor tested \\bveg\\b before "non veg", and "non veg"
        contains "veg" — so the non-veg branch was unreachable and the request
        was classified as its own opposite."""

        phrase = "non veg please"
        i = _fallback_extract_intent(phrase, SessionConversationState())
        self.assertEqual(durable_traits_from_message(phrase, i), {"diet": "NON_VEG"})

    def test_negated_spice_is_never_stored_from_the_descriptor(self) -> None:
        """"nothing too spicy" reports spicy=True there — a substring test with
        no negation handling. Storing HIGH for someone who said the opposite is
        the silent wrong inference this feature must not make."""

        phrase = "nothing too spicy"
        i = _fallback_extract_intent(phrase, SessionConversationState())
        self.assertNotIn("spice_level", durable_traits_from_message(phrase, i))

    def test_a_neutral_message_learns_nothing(self) -> None:
        phrase = "show me momos"
        i = _fallback_extract_intent(phrase, SessionConversationState())
        self.assertEqual(durable_traits_from_message(phrase, i), {})


if __name__ == "__main__":
    unittest.main()

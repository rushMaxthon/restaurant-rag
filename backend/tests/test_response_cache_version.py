"""The cache version is load-bearing, and it was silently not bumped.

Commit 5212542 taught the concierge to stop offering food the kitchen cannot
serve. The trim works — verified directly against the exact failing reply, it
detects "chutney" and removes the sentence. The app went on offering chutney
anyway.

The replies were never reaching it. `_response_cache_key` carries a version
literal, and the whole point of that literal is that changing reply behaviour
invalidates every reply cached under the old behaviour. The fix changed
behaviour and left the version alone, so pre-fix fabrications kept being served
from Redis under:

    rag:response:global:v10:dish_search:spicy-vegetarian:veg:spicy

Note `global`. The key is not per-session and not per-user, which is why
reproducing with a fresh session id proved nothing and made the bug look like
the fix had failed.

Two things conspired to hide it. The cache write happens AFTER the trim, so
every new reply is stored correctly and the code reads as if it works. And
Redis only started running locally in 6d8ecac — before that every cache
operation degraded to a miss, so the version had never actually had to matter
on this machine.

These tests pin the mechanism rather than the number: the version must appear
in the key, and two different versions must not collide. A future bump is then
a one-line change that cannot silently do nothing.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services import rag


class ResponseCacheVersionTests(unittest.TestCase):
    def test_the_version_appears_in_the_key(self) -> None:
        """Otherwise bumping it invalidates nothing."""

        key = rag._response_cache_key("something spicy and vegetarian", None)
        self.assertIn(rag.RESPONSE_CACHE_VERSION, key)

    def test_two_versions_cannot_collide(self) -> None:
        """A bump must actually move every reply to a new key.

        The bug was a version that never changed. The failure this guards is
        subtler: a version that changes but does not separate the namespaces,
        which would look like a bump and behave like none.
        """

        message = "something spicy and vegetarian"
        with patch.object(rag, "RESPONSE_CACHE_VERSION", "v10"):
            old = rag._response_cache_key(message, None)
        with patch.object(rag, "RESPONSE_CACHE_VERSION", "v11"):
            new = rag._response_cache_key(message, None)
        self.assertNotEqual(old, new)

    def test_the_version_is_not_the_one_that_served_ungrounded_replies(self) -> None:
        """v10 is burned.

        Entries written under it predate the grounding trim and may offer food
        that does not exist. Returning to it would resurrect them for whatever
        remains of their TTL.
        """

        self.assertNotEqual(rag.RESPONSE_CACHE_VERSION, "v10")



class PreferenceInTheKeyTests(unittest.TestCase):
    """A cached reply must belong to the preferences that shaped it.

    Reported from the app: a guest says "I am vegetarian", then asks "I need
    spicy menu" and gets meat back. The preference was applied correctly — with
    a phrasing nothing had cached, that request returns only veg — and then
    thrown away, because the answer came from Redis.

    `_infer_cache_query_descriptor` reads diet out of the MESSAGE, and "I need
    spicy menu" names none. So the key carried no diet and every guest asking
    that question shared one entry regardless of what they eat. Whoever asked
    first populated it.

    Same shape as the version bug above: the key did not capture everything that
    changes the reply. There it was a behaviour change, here it is the reader.

    Not affected, checked: session-carried context. `_resolve_global_cacheability`
    already refuses the global cache for `uses_personal_context` and
    `is_follow_up`, so a follow-up like "something cheaper" was never sharing an
    entry.
    """

    MESSAGE = "i need spicy menu"

    def test_opposite_diets_do_not_share_an_entry(self) -> None:
        veg = rag._response_cache_key(self.MESSAGE, None, preference_diet="veg")
        non_veg = rag._response_cache_key(self.MESSAGE, None, preference_diet="non_veg")
        self.assertNotEqual(veg, non_veg)

    def test_a_preference_separates_from_having_none(self) -> None:
        """The reported case exactly: a veg guest must not read the entry a
        guest with no stated diet wrote."""

        none_stated = rag._response_cache_key(self.MESSAGE, None)
        veg = rag._response_cache_key(self.MESSAGE, None, preference_diet="veg")
        self.assertNotEqual(none_stated, veg)

    def test_a_diet_named_in_the_message_still_works(self) -> None:
        """The existing path must not regress: when the message says it, the
        descriptor already put it in the key and the result is the same."""

        spoken = rag._response_cache_key("veg food please", None)
        seeded = rag._response_cache_key("veg food please", None, preference_diet="veg")
        self.assertEqual(spoken, seeded)

    def test_the_same_preference_still_shares_an_entry(self) -> None:
        """The cache must keep earning its keep — two vegetarians asking the
        same question should hit, not miss."""

        first = rag._response_cache_key(self.MESSAGE, None, preference_diet="veg")
        second = rag._response_cache_key(self.MESSAGE, None, preference_diet="veg")
        self.assertEqual(first, second)


class SessionHistoryIsNotGloballyCacheableTests(unittest.TestCase):
    """One conversation's context must not become everyone's answer.

    Reported: "Which item are trending?" replied "We don't have a 'special' item
    on the menu today — but the Penne Arrabbiata...". The customer had never
    mentioned "special". It was sitting in Redis under

        rag:response:global:v11:recommendation:are-trending:veg

    so it was a cache hit, and the key was correct for the question. The stored
    CONTENT was shaped by somebody else's conversation: RECENT HISTORY and
    SESSION SUMMARY go into every prompt, a previous turn in that session had
    been about "special", and the model opened by denying it.

    `_resolve_global_cacheability` refuses `personal_context`, `follow_up`,
    `contextual_menu_question`, greetings and restaurant scope. Having
    conversation history is none of those — so every turn after the first in a
    session was eligible to be written to a cache shared with strangers.

    This cannot be fixed by putting history in the key: the missing input is
    another user's conversation, which is not a property of this request. The
    only correct answer is not to share the reply at all.

    Reading stays allowed. A cached generic answer served mid-conversation
    merely loses a little context for that one person; writing is what harms
    everybody else.
    """

    def test_a_turn_with_history_is_not_written_to_the_global_cache(self) -> None:
        self.assertFalse(rag.may_cache_globally(cacheable=True, history_messages=[object()]))

    def test_a_first_turn_still_caches(self) -> None:
        """The cache must keep earning its keep. First-turn questions — "what is
        popular", "show me pizza" — are the bulk of repeat traffic and have no
        history to contaminate them."""

        self.assertTrue(rag.may_cache_globally(cacheable=True, history_messages=[]))

    def test_an_already_uncacheable_turn_stays_uncacheable(self) -> None:
        self.assertFalse(rag.may_cache_globally(cacheable=False, history_messages=[]))

    def test_a_guest_is_protected_by_session_state_not_history(self) -> None:
        """The vector that actually caused the reported bug.

        A guest gets NO chat_history rows — that table's user_id is NOT NULL
        with an FK to `users` — so `history_messages` is always empty for them
        and RECENT HISTORY is always blank. Their whole conversation lives in
        the Redis session state behind SESSION SUMMARY.

        Guarding on history alone passed its tests, looked right, and protected
        nobody who was not signed in. Found by running the flow: the trending
        key was still written.
        """

        self.assertFalse(
            rag.may_cache_globally(
                cacheable=True,
                history_messages=[],
                session_summary="topic=special; intent=dish_search",
            )
        )

    def test_the_literal_none_summary_is_not_treated_as_context(self) -> None:
        """`_session_state_prompt_summary` returns the STRING "none" for a fresh
        session, so a naive truthiness check would refuse to cache anything."""

        self.assertTrue(
            rag.may_cache_globally(cacheable=True, history_messages=[], session_summary="none")
        )


if __name__ == "__main__":
    unittest.main()

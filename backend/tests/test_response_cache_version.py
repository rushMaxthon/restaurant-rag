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


if __name__ == "__main__":
    unittest.main()

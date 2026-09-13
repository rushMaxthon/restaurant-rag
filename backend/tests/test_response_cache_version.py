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


if __name__ == "__main__":
    unittest.main()

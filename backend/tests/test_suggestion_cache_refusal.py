"""A reply carrying a suggestion may never be cached globally.

This is the same class of bug `may_cache_globally` already exists to catch, and
it has slipped through twice: once because the guard checked history but not
the session summary, and once because guests have no history rows at all.

A suggestion is a function of THIS customer's cart. Cached under a key that
does not include the cart, it would be replayed to the next person asking the
same question — telling them a drink goes with a curry they never ordered.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.rag import may_cache_globally


class CacheRefusalTests(unittest.TestCase):
    def test_a_reply_with_a_suggestion_is_never_globally_cached(self) -> None:
        self.assertFalse(
            may_cache_globally(
                cacheable=True,
                history_messages=[],
                session_summary="none",
                has_suggestion=True,
            )
        )

    def test_a_plain_reply_is_still_cacheable(self) -> None:
        """The guard must not become "never cache anything"."""

        self.assertTrue(
            may_cache_globally(
                cacheable=True,
                history_messages=[],
                session_summary="none",
                has_suggestion=False,
            )
        )

    def test_the_existing_session_guards_still_apply(self) -> None:
        self.assertFalse(
            may_cache_globally(
                cacheable=True,
                history_messages=[],
                session_summary="diet=VEG",
                has_suggestion=False,
            )
        )


if __name__ == "__main__":
    unittest.main()

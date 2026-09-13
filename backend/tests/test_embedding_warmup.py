"""The cold-start cost of the embedding model, and who pays it.

The bug these lock down was invisible in production and nearly invisible here.
Retrieval kept answering; it just answered from the keyword tier, because
`_embed_query` swallows a failure by design so a dead Ollama cannot take the
chat down with it. The customer saw one literal name match where they should
have seen six semantic ones, and nothing in the response said why.

Measured on a CPU-only host with qwen3:8b already resident:

    cold  /api/embed  nomic-embed-text   23.0s
    warm  /api/embed  nomic-embed-text    0.05s

against `ollama_embedding_timeout_seconds = 20.0`. Every first query after the
embedding model was evicted lost vector retrieval entirely, and every query
after that was fine — which is why it read as flaky rather than broken.

Two things follow, and both are asserted here: the timeout has to clear a cold
load, and a real customer must not be the request that pays for one.
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
from app.services import embeddings as emb


# The slowest cold load observed on the reference CPU-only host. The timeout is
# asserted against this rather than against a bare number so that a future
# change to either one has to confront the measurement.
MEASURED_COLD_LOAD_SECONDS = 23.0


class EmbeddingTimeoutTests(unittest.TestCase):
    def test_timeout_clears_a_cold_model_load(self) -> None:
        """20s did not, and that is the whole defect.

        A local Ollama evicts a model after `keep_alive` and reloads it on the
        next request. That reload is part of the response time, so the ceiling
        has to cover it, not just the warm path.
        """

        self.assertGreater(
            emb.settings.ollama_embedding_timeout_seconds,
            MEASURED_COLD_LOAD_SECONDS,
            "Embedding timeout must exceed a cold model load or the first query "
            "after an idle period silently loses vector retrieval",
        )


class WarmupTests(unittest.TestCase):
    def test_warmup_asks_the_provider_for_one_vector(self) -> None:
        with patch.object(emb.settings, "embedding_provider", "ollama"):
            with patch.object(emb, "get_embedding", return_value=[0.0] * 768) as embed:
                self.assertTrue(emb.warm_embedding_provider())
        embed.assert_called_once()
        # The query side, because that is the side a customer's message uses and
        # therefore the one whose weights need to be resident.
        self.assertEqual(embed.call_args.kwargs.get("task"), "query")

    def test_warmup_failure_never_reaches_the_caller(self) -> None:
        """Startup must survive an Ollama that is not running.

        Every AI path already degrades to a deterministic fallback. Refusing to
        boot because the optional half of retrieval is unavailable would turn a
        quality problem into an outage.
        """

        with patch.object(emb.settings, "embedding_provider", "ollama"):
            with patch.object(emb, "get_embedding", side_effect=emb.EmbeddingError("boom")):
                self.assertFalse(emb.warm_embedding_provider())

    def test_warmup_is_skipped_for_a_managed_provider(self) -> None:
        """Gemini holds no weights for us, so there is nothing to warm."""

        with patch.object(emb.settings, "embedding_provider", "gemini"):
            with patch.object(emb, "get_embedding") as embed:
                self.assertFalse(emb.warm_embedding_provider())
        embed.assert_not_called()


if __name__ == "__main__":
    unittest.main()

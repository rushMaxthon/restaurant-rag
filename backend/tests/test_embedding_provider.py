"""Provider selection, dimension safety, and the recoverable failure contract.

The behaviour these lock down is not "an embedding is returned" — it is that a
FAILED embedding never costs the customer their suggestions. That regression is
invisible in production: retrieval still answers, just with nothing in it.
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

import httpx

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services import embeddings as emb


class ProviderSelectionTests(unittest.TestCase):
    def test_ollama_is_the_default_provider(self) -> None:
        with patch.object(emb.settings, "embedding_provider", "ollama"):
            self.assertEqual(emb.active_provider(), "ollama")
            self.assertTrue(emb.requires_ollama())

    def test_gemini_removes_the_ollama_dependency(self) -> None:
        with patch.object(emb.settings, "embedding_provider", "gemini"):
            self.assertEqual(emb.active_provider(), "gemini")
            self.assertFalse(emb.requires_ollama())

    def test_provider_selection_is_case_and_space_insensitive(self) -> None:
        with patch.object(emb.settings, "embedding_provider", "  GEMINI "):
            self.assertEqual(emb.active_provider(), "gemini")

    def test_unknown_provider_is_a_recoverable_error(self) -> None:
        with patch.object(emb.settings, "embedding_provider", "pinecone"):
            with self.assertRaises(emb.EmbeddingError):
                emb.get_embedding("paneer tikka")

    def test_signature_distinguishes_the_two_vector_spaces(self) -> None:
        with patch.object(emb.settings, "embedding_provider", "ollama"):
            local = emb.embedding_signature()
        with patch.object(emb.settings, "embedding_provider", "gemini"):
            cloud = emb.embedding_signature()
        # Vectors from different models are not comparable, so the backfill
        # relies on these never colliding.
        self.assertNotEqual(local, cloud)
        self.assertIn("nomic-embed-text", local)
        self.assertIn("gemini", cloud)


class DimensionSafetyTests(unittest.TestCase):
    """A wrong-width vector must never reach the Vector(768) column."""

    def test_wrong_dimension_is_rejected(self) -> None:
        with self.assertRaises(emb.EmbeddingError) as caught:
            emb._validate([0.0] * 3072, "Gemini")
        self.assertIn("3072", str(caught.exception))
        self.assertIn("768", str(caught.exception))

    def test_correct_dimension_passes_and_is_floats(self) -> None:
        vector = emb._validate([1] * 768, "Ollama")
        self.assertEqual(len(vector), 768)
        self.assertIsInstance(vector[0], float)

    def test_non_numeric_vector_is_rejected(self) -> None:
        with self.assertRaises(emb.EmbeddingError):
            emb._validate(["not-a-number"] * 768, "Gemini")

    def test_missing_vector_is_rejected(self) -> None:
        with self.assertRaises(emb.EmbeddingError):
            emb._validate(None, "Gemini")


class GeminiContractTests(unittest.TestCase):
    def test_missing_api_key_is_a_recoverable_error(self) -> None:
        with patch.object(emb.settings, "embedding_provider", "gemini"), patch.object(
            emb.settings, "gemini_api_key", ""
        ):
            with self.assertRaises(emb.EmbeddingError) as caught:
                emb.get_embedding("paneer tikka")
        self.assertIn("GEMINI_API_KEY", str(caught.exception))

    def test_request_shape_and_key_placement(self) -> None:
        """768 must be requested explicitly, and the key must be a header.

        A key in the query string lands in access logs and proxy logs; and if
        outputDimensionality were omitted Gemini would return its native 3072,
        which the column cannot store.
        """

        seen: dict = {}

        class FakeResponse:
            status_code = 200

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"embedding": {"values": [0.1] * 768}}

        class FakeClient:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args) -> None:
                return None

            def post(self, url, json=None, headers=None):
                seen["url"] = url
                seen["json"] = json
                seen["headers"] = headers
                return FakeResponse()

        with patch.object(emb.settings, "embedding_provider", "gemini"), patch.object(
            emb.settings, "gemini_api_key", "test-key"
        ), patch.object(emb.httpx, "Client", FakeClient):
            vector = emb.get_embedding("paneer tikka", task="query")

        self.assertEqual(len(vector), 768)
        self.assertEqual(seen["json"]["outputDimensionality"], 768)
        self.assertEqual(seen["json"]["taskType"], "RETRIEVAL_QUERY")
        self.assertEqual(seen["headers"]["x-goog-api-key"], "test-key")
        self.assertNotIn("test-key", seen["url"])
        self.assertIn(":embedContent", seen["url"])

    def test_document_and_query_use_different_task_types(self) -> None:
        self.assertNotEqual(
            emb._GEMINI_TASK_TYPES["document"], emb._GEMINI_TASK_TYPES["query"]
        )

    def test_rate_limit_is_reported_as_a_recoverable_error(self) -> None:
        class FakeResponse:
            status_code = 429
            text = "quota exceeded"

            def raise_for_status(self) -> None:
                raise AssertionError("should not be reached for 429")

            def json(self) -> dict:
                return {}

        class FakeClient:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args) -> None:
                return None

            def post(self, *args, **kwargs):
                return FakeResponse()

        with patch.object(emb.settings, "embedding_provider", "gemini"), patch.object(
            emb.settings, "gemini_api_key", "test-key"
        ), patch.object(emb.httpx, "Client", FakeClient):
            with self.assertRaises(emb.EmbeddingError) as caught:
                emb.get_embedding("paneer tikka")
        self.assertIn("429", str(caught.exception))


class QueryFallbackTests(unittest.TestCase):
    """The regression that matters: an embedding outage must not empty the answer."""

    def test_embedding_failure_returns_none_rather_than_raising(self) -> None:
        from app.services import rag

        rag._embed_query_cached.cache_clear()
        with patch.object(
            rag, "get_embedding", side_effect=emb.EmbeddingError("provider down")
        ), patch.object(rag, "cache_get_json", return_value=None):
            result = rag._embed_query("something spicy")

        # None, not an exception: raising here unwound past the keyword, popular
        # and emergency tiers and left the customer with zero suggestions.
        self.assertIsNone(result)

    def test_every_transport_failure_becomes_a_recoverable_error(self) -> None:
        for error in (
            httpx.ConnectError("refused"),
            httpx.ReadTimeout("timed out"),
            httpx.HTTPError("boom"),
        ):
            with self.subTest(error=type(error).__name__):
                with patch.object(emb.settings, "embedding_provider", "ollama"), patch(
                    "app.services.ollama_client.build_client", side_effect=error
                ):
                    with self.assertRaises(emb.EmbeddingError):
                        emb.get_embedding("paneer tikka")

    def test_empty_text_is_refused_before_any_network_call(self) -> None:
        with self.assertRaises(emb.EmbeddingError):
            emb.get_embedding("   ")


if __name__ == "__main__":
    unittest.main()

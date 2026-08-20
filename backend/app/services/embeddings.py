"""Text -> vector, without the caller knowing who did it.

One function matters here: `get_embedding(text, task=...)`. Everything upstream —
the menu embedding task, the customer query path — calls that and never learns
whether the vector came from a local Ollama or from Gemini.

Three decisions shape the module:

* **Failure is recoverable, and says so in the type system.** Every provider
  error becomes `EmbeddingError`. It is deliberately NOT an `HTTPException`: the
  previous code raised one from deep inside retrieval, which unwound past the
  keyword and popular fallbacks and left the customer with an empty answer. A
  plain exception lets the caller decide, and the caller's decision is to carry
  on without a vector.

* **The dimension is checked on every response.** Both providers must return
  exactly `embedding_dimensions` floats, because that is the width of the
  `Vector(768)` column. If a request shape is wrong — say Gemini ignores
  `outputDimensionality` and returns its native 3072 — this fails loudly on the
  first call instead of writing unusable rows.

* **Query and document embeddings are asked for differently.** Retrieval quality
  improves when the model knows which side it is embedding. Gemini exposes this
  as `taskType`; Ollama has no equivalent and ignores it. Callers say what they
  mean and the provider does what it can with it.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import httpx

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# What the text is FOR. Gemini embeds a search query and a stored document
# differently, and using the wrong one measurably degrades retrieval.
EmbeddingTask = Literal["document", "query"]

_GEMINI_TASK_TYPES: dict[str, str] = {
    "document": "RETRIEVAL_DOCUMENT",
    "query": "RETRIEVAL_QUERY",
}

PROVIDER_OLLAMA = "ollama"
PROVIDER_GEMINI = "gemini"


class EmbeddingError(RuntimeError):
    """Any failure to produce a vector: transport, auth, quota, or bad payload.

    One type for all of them on purpose. Callers do not act differently on a
    timeout than on a 429 — both mean "no vector this time" — and collapsing
    them keeps the recovery path at each call site to a single `except`.
    """


def active_provider() -> str:
    return (settings.embedding_provider or PROVIDER_OLLAMA).strip().lower()


def embedding_signature() -> str:
    """Identifies the vector space the current configuration produces.

    Vectors from different models are not comparable even at identical
    dimensions, so this is what the backfill compares to decide whether stored
    vectors still mean anything.
    """

    provider = active_provider()
    model = (
        settings.gemini_embedding_model
        if provider == PROVIDER_GEMINI
        else settings.ollama_embedding_model
    )
    return f"{provider}:{model}:{settings.embedding_dimensions}"


def requires_ollama() -> bool:
    """Whether this configuration needs an Ollama host for embeddings at all."""

    return active_provider() == PROVIDER_OLLAMA


def _validate(vector: Any, provider: str) -> list[float]:
    expected = settings.embedding_dimensions
    if not isinstance(vector, list) or len(vector) != expected:
        got = len(vector) if isinstance(vector, list) else type(vector).__name__
        raise EmbeddingError(
            f"{provider} returned {got} dimensions, expected {expected}. "
            "The pgvector column cannot store this; check the model and the "
            "requested output dimensionality."
        )
    try:
        return [float(value) for value in vector]
    except (TypeError, ValueError) as error:
        raise EmbeddingError(f"{provider} returned a non-numeric vector") from error


# --- Ollama (local development) ---------------------------------------------


def _embed_ollama(text: str) -> list[float]:
    # Imported here rather than at module scope so that a Gemini-only
    # deployment never touches the Ollama client module. Production with
    # EMBEDDING_PROVIDER=gemini has no Ollama dependency, at import or runtime.
    from app.services.ollama_client import (
        EMBED_ENDPOINT,
        build_client,
        embedding_local_only_options,
    )

    payload = {
        "model": settings.ollama_embedding_model,
        "input": text,
        **embedding_local_only_options(),
    }
    timeout = httpx.Timeout(
        connect=5.0,
        read=settings.ollama_embedding_timeout_seconds,
        write=10.0,
        pool=5.0,
    )
    try:
        with build_client(timeout, embedding=True) as client:
            response = client.post(EMBED_ENDPOINT, json=payload)
            response.raise_for_status()
        body: dict[str, Any] = response.json()
    except httpx.HTTPError as error:
        raise EmbeddingError(f"Ollama embedding request failed: {error}") from error
    except ValueError as error:  # malformed JSON
        raise EmbeddingError("Ollama returned a non-JSON embedding response") from error

    # /api/embed returns {"embeddings": [[...]]}; older builds return
    # {"embedding": [...]}. Both are accepted.
    embeddings = body.get("embeddings")
    if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
        vector = embeddings[0]
    else:
        vector = body.get("embedding")
    return _validate(vector, "Ollama")


# --- Gemini (production) ----------------------------------------------------


def _embed_gemini(text: str, task: EmbeddingTask) -> list[float]:
    if not settings.gemini_api_key:
        raise EmbeddingError(
            "EMBEDDING_PROVIDER=gemini but GEMINI_API_KEY is not set"
        )

    model = settings.gemini_embedding_model
    url = f"{settings.gemini_embedding_base_url}/models/{model}:embedContent"
    payload = {
        "model": f"models/{model}",
        "content": {"parts": [{"text": text}]},
        "taskType": _GEMINI_TASK_TYPES[task],
        # Matryoshka truncation to the width of the pgvector column. Gemini
        # Embedding 2 normalizes truncated vectors itself; gemini-embedding-001
        # does NOT, which is why 2 is the configured default.
        "outputDimensionality": settings.embedding_dimensions,
    }
    timeout = httpx.Timeout(
        connect=5.0,
        read=settings.gemini_embedding_timeout_seconds,
        write=10.0,
        pool=5.0,
    )
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(
                url,
                json=payload,
                # Header, not a query parameter: a key in a URL lands in access
                # logs and proxy logs.
                headers={"x-goog-api-key": settings.gemini_api_key},
            )
            if response.status_code == 429:
                raise EmbeddingError("Gemini rate limit or quota exceeded (429)")
            response.raise_for_status()
        body = response.json()
    except EmbeddingError:
        raise
    except httpx.HTTPStatusError as error:
        detail = error.response.text[:200]
        raise EmbeddingError(
            f"Gemini embedding failed ({error.response.status_code}): {detail}"
        ) from error
    except httpx.HTTPError as error:
        raise EmbeddingError(f"Gemini embedding request failed: {error}") from error
    except ValueError as error:
        raise EmbeddingError("Gemini returned a non-JSON embedding response") from error

    vector = ((body or {}).get("embedding") or {}).get("values")
    return _validate(vector, "Gemini")


# --- the only function callers need ------------------------------------------


def get_embedding(text: str, *, task: EmbeddingTask = "document") -> list[float]:
    """Embed `text` with the configured provider.

    Raises `EmbeddingError` on any failure. Callers on a user-facing path should
    catch it and continue without a vector rather than surfacing an error —
    retrieval has keyword and popularity tiers that work without one.
    """

    cleaned = (text or "").strip()
    if not cleaned:
        raise EmbeddingError("Cannot embed empty text")

    provider = active_provider()
    if provider == PROVIDER_GEMINI:
        return _embed_gemini(cleaned, task)
    if provider == PROVIDER_OLLAMA:
        return _embed_ollama(cleaned)
    raise EmbeddingError(
        f"Unknown EMBEDDING_PROVIDER {provider!r}; expected 'ollama' or 'gemini'"
    )


__all__ = [
    "PROVIDER_GEMINI",
    "PROVIDER_OLLAMA",
    "EmbeddingError",
    "EmbeddingTask",
    "active_provider",
    "embedding_signature",
    "get_embedding",
    "requires_ollama",
]

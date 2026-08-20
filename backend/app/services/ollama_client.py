"""One place that knows how to talk to Ollama.

Before this module every call site built its own endpoint string and its own
httpx client, which was fine while there was exactly one unauthenticated local
server. Ollama Cloud changes that in three ways at once, and none of them should
be re-implemented nine times:

* **Requests need a bearer token.** Nine modules make generation calls. A header
  duplicated nine times is a header that will be forgotten in the tenth.
* **Generation and embeddings can live on different hosts.** Ollama Cloud serves
  no embedding route — `/api/embed` answers 401 for every model with or without
  a key, while `/api/embeddings` and `/v1/embeddings` answer 404 outright, and
  `/api/generate` with the same key answers 200. So embeddings stay on a local
  Ollama even when generation is in the cloud.
* **Some request options are local-only.** `keep_alive` asks a server to hold
  model weights in memory. Against a managed endpoint it describes nothing, and
  sending it is at best noise.

The key is sent to the generation host and nowhere else. `embedding_headers()`
returns the token only when embeddings resolve to that same host, because a
credential issued for one service must not be handed to another simply because
both happen to speak the Ollama protocol.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings

settings = get_settings()

# --- endpoints --------------------------------------------------------------
#
# Module-level, matching what every call site did before, so importing this
# changes no behaviour beyond where the strings are built.

GENERATE_ENDPOINT = f"{settings.ollama_base_url}/api/generate"
EMBED_ENDPOINT = f"{settings.ollama_embedding_url}/api/embed"
TAGS_ENDPOINT = f"{settings.ollama_base_url}/api/tags"

# Shared connection limits. Ollama serves one generation at a time per model, so
# a large pool buys nothing; this is sized to avoid holding sockets open.
HTTP_LIMITS = httpx.Limits(max_keepalive_connections=10, max_connections=20)


def generation_headers() -> dict[str, str]:
    """Auth for the generation host. Empty for a local Ollama, which needs none."""

    if not settings.ollama_api_key:
        return {}
    return {"Authorization": f"Bearer {settings.ollama_api_key}"}


def embedding_headers() -> dict[str, str]:
    """Auth for the embedding host — only when it IS the generation host.

    A split deployment points embeddings at a local Ollama that neither needs nor
    should receive a cloud credential. Sending it anyway would leak the key to
    whatever host the embedding URL happens to name.
    """

    if settings.ollama_embedding_url != settings.ollama_base_url:
        return {}
    return generation_headers()


def think_option() -> dict[str, Any]:
    """The `think` field, as this deployment's model needs it.

    Returned as a dict so a call site splats it in and never has to know whether
    the value is a boolean or a string — the API accepts `false` to disable
    reasoning and `"low"`/`"medium"`/`"high"` to scale it, and which one is
    correct is a property of the configured model, not of the call site.

    Unrecognised values fall back to `False`, which is the conservative choice:
    a typo disables reasoning rather than silently enabling an expensive amount
    of it.
    """

    mode = (settings.ollama_think_mode or "false").strip().lower()
    if mode in {"low", "medium", "high"}:
        return {"think": mode}
    return {"think": False}


def local_only_options() -> dict[str, Any]:
    """Request fields that mean something to a local server and nothing to Cloud.

    `keep_alive` controls how long a server keeps model weights resident. A
    managed endpoint decides that itself, so the field is omitted there. Returned
    as a dict to be splatted into a payload, so a call site adds or drops the
    whole group without an `if`.
    """

    if settings.ollama_is_cloud:
        return {}
    return {"keep_alive": settings.ollama_keep_alive}


def embedding_local_only_options() -> dict[str, Any]:
    """As above, judged against the host embeddings actually go to."""

    if settings.ollama_embedding_url != settings.ollama_base_url:
        # A separate embedding host is by definition the local one in this
        # deployment shape, so keep_alive applies and is worth sending.
        return {"keep_alive": settings.ollama_keep_alive}
    return local_only_options()


def build_client(
    timeout: httpx.Timeout,
    *,
    limits: httpx.Limits | None = None,
    embedding: bool = False,
) -> httpx.Client:
    """An httpx client carrying the right auth for its target host.

    Callers keep their own timeouts: a two-sentence briefing and a full owner
    answer need very different read budgets, and collapsing them into one shared
    client would make the briefing wait as long as the answer before giving up.
    """

    return httpx.Client(
        timeout=timeout,
        limits=limits or HTTP_LIMITS,
        headers=embedding_headers() if embedding else generation_headers(),
    )


__all__ = [
    "EMBED_ENDPOINT",
    "GENERATE_ENDPOINT",
    "HTTP_LIMITS",
    "TAGS_ENDPOINT",
    "build_client",
    "embedding_headers",
    "embedding_local_only_options",
    "generation_headers",
    "local_only_options",
]

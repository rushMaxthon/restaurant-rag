"""Keep the models resident, so no customer pays to load them.

A local Ollama holds model weights in memory for `keep_alive` and then evicts
them. The next request reloads them — inside that request's own timeout, on
somebody's turn. Nothing about that is visible as an error: the answer is
simply slow, and if it is slow enough the caller gives up and falls back.

That is not a theory. Measured on a live WhatsApp thread on 2026-09-21:

    Ordering agent turn fallback_reason=None records=1 actions=1 elapsed=54.14s

54 seconds against a 30-second budget, effectively all of it one intent read
waiting on a cold qwen3:8b. The same read takes 4.4s warm. The customer got a
worse answer as well as a slower one, because the turn had to finish from its
budget-exceeded path.

The API already warmed the embedding model at startup, for exactly this reason,
and that is where this module comes from. Two things were missing:

* **The generation model was never warmed at all** — and it is the expensive
  one: 5.6GB against nomic-embed-text's 274MB.
* **Warming once only covers the first hour.** `keep_alive` is a window that
  restarts on each request, so a quiet morning evicts the weights just as
  surely as a restart does, and the first customer after the quiet pays. A
  restaurant with no orders since nine is the normal case, not the edge one.

So this warms both models, and keeps warming them on an interval derived from
`keep_alive` itself, in every long-lived process that uses them: the API and
the Celery worker that answers WhatsApp.

It costs a permanently resident model, which is the point — that is what
`keep_alive` was already asking for. It costs no tokens: `warm_generation_model`
uses Ollama's empty-prompt load, which generates nothing.
"""

from __future__ import annotations

import logging
import threading

from app.config import get_settings
from app.services.embeddings import warm_embedding_provider
from app.services.ollama_client import keep_alive_seconds, warm_generation_model

logger = logging.getLogger(__name__)

settings = get_settings()

# Half the residency window. Generous on purpose: a re-warm that lands late is
# worth nothing, and the cost of landing early is one cheap no-op request.
_INTERVAL_FRACTION = 0.5

# Below this the loop would be re-warming more or less continuously, which says
# the deployment wants eviction rather than residency. Honour that instead of
# fighting it.
_MIN_INTERVAL_SECONDS = 60.0

_stop = threading.Event()


def warm_up_interval_seconds() -> float | None:
    """How often to re-warm, or None to warm once and stop.

    Derived from `keep_alive` rather than configured separately, so the two
    cannot drift into the arrangement where the models are re-warmed just
    slightly too late and every quiet hour ends in one slow answer.
    """

    window = keep_alive_seconds()
    if window is None:
        # Either the weights never expire or a managed endpoint owns the
        # decision. One pass is still worth it against a local server that has
        # only just started; against Cloud, `warm_generation_model` is a wasted
        # request, so skip the pass entirely.
        return None

    interval = window * _INTERVAL_FRACTION
    return interval if interval >= _MIN_INTERVAL_SECONDS else None


def warm_once() -> None:
    """One pass over both models. Never raises — see each warmer for why."""

    warm_generation_model()
    warm_embedding_provider()


def _loop(interval: float | None) -> None:
    warm_once()
    if interval is None:
        return
    while not _stop.wait(interval):
        warm_once()


def start_model_warm_up(*, name: str) -> threading.Thread | None:
    """Warm the models in the background, for the life of this process.

    On a thread, never inline: a cold load measured 23s for the embedding model
    and 6.2s for the generation one here, and far more on a host reading the
    weights from disk for the first time. Blocking a worker's start or an API's
    startup for that would turn a quality improvement into an outage — the
    process would be refusing connections while looking like a hang.

    Daemon, so a slow or unreachable Ollama cannot hold up shutdown.

    Returns None when there is nothing to warm, so a caller can log the
    difference between "not warming" and "warming failed".
    """

    if settings.ollama_is_cloud:
        # A managed endpoint holds no weights on our behalf and charges per
        # call. There is nothing to keep resident and no reason to spend a
        # request finding that out on a timer.
        logger.info("Generation is remote; not warming models")
        return None

    interval = warm_up_interval_seconds()
    _stop.clear()
    thread = threading.Thread(target=_loop, args=(interval,), name=name, daemon=True)
    thread.start()
    if interval is None:
        logger.info("Warming models once (%s)", name)
    else:
        logger.info("Warming models every %.0fs (%s)", interval, name)
    return thread


def stop_model_warm_up() -> None:
    """Ask the loop to stop at its next tick. For tests and for symmetry."""

    _stop.set()


__all__ = [
    "start_model_warm_up",
    "stop_model_warm_up",
    "warm_once",
    "warm_up_interval_seconds",
]

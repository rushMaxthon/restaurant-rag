"""Short, expiring redirects for links a phone has to read.

A Stripe Checkout URL is ~230 characters and ends in an opaque fragment; in
a WhatsApp bubble it looks like the links people are told not to tap. The
customer needs one line. So the long URL is kept here under a random token
for as long as the session it points at can live, and `/api/p/<token>`
sends the phone on with a 302.

Never a third-party shortener: a checkout URL is a bearer capability to pay
for somebody's order, and it does not go into anyone else's database.

The token is `secrets.token_urlsafe(9)` — twelve characters, 72 bits, on a
link that expires in a day and cannot be enumerated. The long URL it hides
is itself the secret; this adds no weakness it did not already have.
"""

from __future__ import annotations

import logging
import secrets

from app.config import get_settings
from app.services.cache import cache_get_json, cache_set_json

logger = logging.getLogger(__name__)
settings = get_settings()

# A Checkout session lives 24 hours. The redirect lives exactly as long, so
# a link that still opens is a session that can still be paid.
LINK_TTL_SECONDS = 24 * 60 * 60


def _key(token: str) -> str:
    return f"shortlink:{token}"


def shorten(url: str) -> str:
    """The short form of `url`, or `url` itself when there is nowhere
    public to serve the short one from.

    `public_base_url` is where this API is reachable from a phone. Without
    it the long link is returned unchanged — worse to read, but it pays.
    """

    public = (settings.public_base_url or "").strip().rstrip("/")
    if not public or not url:
        return url
    token = secrets.token_urlsafe(9)
    try:
        cache_set_json(_key(token), {"url": url}, ttl_seconds=LINK_TTL_SECONDS)
    except Exception:  # noqa: BLE001 - a long link that pays beats no link
        logger.warning("Could not store a short link; sending the long one", exc_info=True)
        return url
    return f"{public}{settings.api_v1_prefix}/p/{token}"


def resolve(token: str) -> str | None:
    """Where a token points, or None once it has expired or never existed."""

    if not token or len(token) > 64:
        return None
    stored = cache_get_json(_key(token))
    if not isinstance(stored, dict):
        return None
    url = stored.get("url")
    return url if isinstance(url, str) and url.startswith("https://") else None


__all__ = ["LINK_TTL_SECONDS", "resolve", "shorten"]

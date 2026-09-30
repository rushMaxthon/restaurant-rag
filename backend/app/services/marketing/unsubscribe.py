"""The opt-out link a marketing message carries.

A customer reading a campaign on their lock screen must be able to stop
receiving them without finding the app, logging in and hunting through
settings. That means a link that identifies them on its own — so the link
itself is the credential, and the whole design is about keeping that narrow.

**Signed, not stored.** The token is the pair of ids plus an HMAC over them
under the app's signing key. No table, nothing to clean up, and nothing to look
up on a request that must work months after the message was sent. Forging one
requires the signing key, which is the same key that mints every session token.

**No expiry, on purpose.** Someone acting on a message from six weeks ago is
exactly who this is for, and a link that answers "this link has expired" to a
person trying to opt out is worse than no link. The capability it grants is
one-directional: the worst a leaked token does is opt its owner out of
marketing, which they can undo in the app, and which never touches order
updates.

**GET never mutates.** Mail clients, link scanners and chat previews fetch URLs
without a human involved; a GET that opted people out would unsubscribe them
silently. GET renders a confirmation page, POST performs it. That costs one tap
and is the reason this is safe to reuse for email in Phase 2.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import uuid

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

#: Truncated to 16 bytes. The full digest doubles the token length for no gain
#: against an attacker who has to forge it online, one request at a time.
_DIGEST_BYTES = 16


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(body: str) -> str:
    digest = hmac.new(
        settings.jwt_secret_key.encode(), body.encode(), hashlib.sha256
    ).digest()[:_DIGEST_BYTES]
    return _b64encode(digest)


def make_token(user_id: uuid.UUID, campaign_id: uuid.UUID) -> str:
    """A token naming who is opting out, and which message prompted it."""

    body = f"{_b64encode(user_id.bytes)}.{_b64encode(campaign_id.bytes)}"
    return f"{body}.{_sign(body)}"


def read_token(token: str) -> tuple[uuid.UUID, uuid.UUID] | None:
    """The ids inside a token, or None if it is not one we issued."""

    # A token is short; anything long is someone probing, and decoding it is
    # work we should not do.
    if not token or len(token) > 200:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None

    body = f"{parts[0]}.{parts[1]}"
    # Constant-time: a timing-variable comparison here leaks the signature one
    # byte at a time to anyone willing to make enough requests.
    if not hmac.compare_digest(_sign(body), parts[2]):
        return None

    try:
        return uuid.UUID(bytes=_b64decode(parts[0])), uuid.UUID(
            bytes=_b64decode(parts[1])
        )
    except (ValueError, TypeError):
        return None


def unsubscribe_url(user_id: uuid.UUID, campaign_id: uuid.UUID) -> str | None:
    """Where that customer taps to stop receiving campaigns.

    None when `public_base_url` is unset, because a link to a host nobody can
    reach is worse than no link: it looks like an opt-out that failed. Callers
    omit the field rather than sending a broken one.
    """

    public = (settings.public_base_url or "").strip().rstrip("/")
    if not public:
        return None
    token = make_token(user_id, campaign_id)
    return f"{public}{settings.api_v1_prefix}/marketing/unsubscribe/{token}"

"""Refuse to run a real deployment that is configured unsafely.

Found in the 2026-10-07 security review: every dangerous switch in this
backend was guarded by `environment`, and `environment` defaulted to
"development". A deployment that simply forgot to set it accepted the fixed
phone code for any customer, returned tracebacks, and published /docs; one
that forgot `JWT_SECRET_KEY` signed tokens with a string that is in this
repository, so anyone could mint an admin login.

The defaults are now the safe ones (`settings.py`). This is the second half,
called from `app/main.py` and the Celery app:

- The repository's own JWT secret outside local development **stops the
  process**: that is an open door, not a weakness.
- A JWT secret shorter than 32 characters, and DEBUG left on, are logged as
  errors but do not stop it. This check ships to a live Render service whose
  settings could not be inspected first, and taking the API down on deploy
  would be worse than either. DEBUG is switched off regardless
  (`effective_debug`), so no traceback reaches a client.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: The environments where development conveniences are allowed. The same
#: names `services/otp.py` and the rehearsal courier accept.
LOCAL_ENVIRONMENTS = frozenset({"development", "dev", "local", "test", "testing"})

#: The value `settings.py` ships with. Never valid outside development.
_REPOSITORY_JWT_SECRET = "change-this-in-production"
_MIN_SECRET_LENGTH = 32


class UnsafeConfiguration(RuntimeError):
    """Raised at startup; the message says which setting to fix."""


def is_local(settings) -> bool:
    return (settings.environment or "").strip().lower() in LOCAL_ENVIRONMENTS


def effective_debug(settings) -> bool:
    """DEBUG as the app should use it: never on outside local development."""

    return bool(settings.debug) and is_local(settings)


def check(settings) -> None:
    if is_local(settings):
        return
    secret = settings.jwt_secret_key or ""
    if secret == _REPOSITORY_JWT_SECRET:
        raise UnsafeConfiguration(
            f"Refusing to start in environment {settings.environment!r}: JWT_SECRET_KEY is the "
            "repository default, so anyone could sign a login token. Set a long random value."
        )
    if len(secret) < _MIN_SECRET_LENGTH:
        logger.error(
            "JWT_SECRET_KEY is shorter than %s characters; set a longer random value.",
            _MIN_SECRET_LENGTH,
        )
    if settings.debug:
        logger.error("DEBUG is on in environment %r; it has been switched off. Set DEBUG=false.", settings.environment)


def docs_urls(settings) -> tuple[str | None, str | None, str | None]:
    """(docs, redoc, openapi) - served locally, hidden everywhere else.

    The OpenAPI document is a complete map of every admin, payout, kitchen
    and webhook route with its schema; there is no reason to publish it.
    """

    if is_local(settings):
        return "/docs", "/redoc", "/openapi.json"
    return None, None, None

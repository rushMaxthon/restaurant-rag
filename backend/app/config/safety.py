"""Refuse to run a real deployment that is configured unsafely.

Found in the 2026-10-07 security review: every dangerous switch in this
backend was guarded by `environment`, and `environment` defaulted to
"development". A deployment that simply forgot to set it accepted the fixed
phone code for any customer, returned tracebacks, and published /docs; one
that forgot `JWT_SECRET_KEY` signed tokens with a string that is in this
repository, so anyone could mint an admin login.

The defaults are now the safe ones (`settings.py`). This is the second half:
anything that is not local development and is still unsafe stops at startup
with a sentence naming what to set, rather than running quietly open. Called
from `app/main.py` and the Celery app, so neither process can start that way.
"""

from __future__ import annotations

#: The environments where development conveniences are allowed. The same
#: names `services/otp.py` and the rehearsal courier accept.
LOCAL_ENVIRONMENTS = frozenset({"development", "dev", "local", "test", "testing"})

#: The value `settings.py` ships with. Never valid outside development.
_REPOSITORY_JWT_SECRET = "change-this-in-production"
_MIN_SECRET_LENGTH = 32


class UnsafeConfiguration(RuntimeError):
    """Raised at startup; the message lists every setting to fix."""


def is_local(settings) -> bool:
    return (settings.environment or "").strip().lower() in LOCAL_ENVIRONMENTS


def problems(settings) -> list[str]:
    if is_local(settings):
        return []
    found = []
    secret = settings.jwt_secret_key or ""
    if secret == _REPOSITORY_JWT_SECRET or len(secret) < _MIN_SECRET_LENGTH:
        found.append(
            f"JWT_SECRET_KEY is the repository default or shorter than {_MIN_SECRET_LENGTH} "
            "characters; anyone could sign a login token. Set a long random value."
        )
    if settings.debug:
        found.append("DEBUG is on; errors would show internal tracebacks to clients. Set DEBUG=false.")
    return found


def check(settings) -> None:
    found = problems(settings)
    if found:
        raise UnsafeConfiguration(
            f"Refusing to start in environment {settings.environment!r}:\n- " + "\n- ".join(found)
        )


def docs_urls(settings) -> tuple[str | None, str | None, str | None]:
    """(docs, redoc, openapi) - served locally, hidden everywhere else.

    The OpenAPI document is a complete map of every admin, payout, kitchen
    and webhook route with its schema; there is no reason to publish it.
    """

    if is_local(settings):
        return "/docs", "/redoc", "/openapi.json"
    return None, None, None

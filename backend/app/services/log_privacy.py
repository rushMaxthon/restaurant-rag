"""Values that identify a customer, made safe to log.

Found in the 2026-10-07 security review: chat logged every message in full -
customers type addresses and phone numbers into chat - WhatsApp replies
logged the customer's whole number, and a failed push logged the whole device
token. Logs outlive the database rows and are read by more people; none of
these lines needed the value itself.

`said()` returns an object, not a string, so it costs nothing on a log line
that is filtered out: the text is only worked out when the line is written.
"""

from __future__ import annotations

import hashlib
import logging
import re

from app.config import get_settings


def _local() -> bool:
    from app.config.safety import is_local

    return is_local(get_settings())


def phone(number: str | None) -> str:
    """The last four digits: enough to tell two customers apart in a log."""

    if not number:
        return "-"
    digits = "".join(ch for ch in str(number) if ch.isdigit())
    return f"…{digits[-4:]}" if len(digits) >= 4 else "…"


def token(value: str | None) -> str:
    """The last eight characters of a device or session token."""

    if not value:
        return "-"
    return f"…{str(value)[-8:]}"


class said:  # noqa: N801 - reads as a word in a log call: said(message)
    """What a customer typed: itself on a developer's machine, otherwise its
    length and a short fingerprint (the same text, the same fingerprint)."""

    __slots__ = ("_text",)

    def __init__(self, text: str | None) -> None:
        self._text = text

    def __str__(self) -> str:
        if self._text is None or self._text == "":
            return "-"
        text = str(self._text)
        if _local():
            return text
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
        return f"<{len(text)} chars #{digest}>"

    __repr__ = __str__


#: Query parameters and headers whose value is a credential.
_SECRET_PARAM = re.compile(
    r"(?i)\b(key|api_key|apikey|access_token|token|client_secret|secret|password|signature)=([^&\s\"']+)"
)
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]+")


def redact(text: str) -> str:
    """`text` with credential values blanked: `key=...`, `api_key=...`, bearer tokens."""

    text = _SECRET_PARAM.sub(lambda m: f"{m.group(1)}=[redacted]", text)
    return _BEARER.sub(lambda m: f"{m.group(1)} [redacted]", text)


class RedactSecrets(logging.Filter):
    """Blanks credentials in every record before a handler writes it.

    The HTTP client logs each request URL at INFO, and Google's geocoding key
    and Ola Maps' key both travel in the query string - a day of local logs
    held Google's key 24 times (2026-10-07). Installed on every root handler
    by `install()`, in the API and the worker.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never lose a log line over this
            return True
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        return True


def install() -> None:
    """Put `RedactSecrets` on every handler the root logger has."""

    for handler in logging.getLogger().handlers:
        if not any(isinstance(existing, RedactSecrets) for existing in handler.filters):
            handler.addFilter(RedactSecrets())


__all__ = ["RedactSecrets", "install", "phone", "redact", "said", "token"]

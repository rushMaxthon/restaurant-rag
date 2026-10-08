"""The 4-digit code a customer reads to the rider at the door.

Derived, not stored: an HMAC of the order id under a server secret. The
customer's order page can show it without any column holding it in clear,
and a database read alone does not let anybody complete a delivery. Four
digits is guessable in 10,000 tries, which is why the rider gets five.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid

from app.config import get_settings

MAX_ATTEMPTS = 5


def _secret() -> bytes:
    settings = get_settings()
    return (settings.rider_otp_secret or settings.jwt_secret_key).encode("utf-8")


def code_for(order_id: uuid.UUID) -> str:
    digest = hmac.new(_secret(), f"delivery-otp:{order_id}".encode(), hashlib.sha256).hexdigest()
    return f"{int(digest[:8], 16) % 10000:04d}"


def hash_code(code: str) -> str:
    """Kept on the delivery row only to show an admin that a code was issued."""

    return hashlib.sha256(f"delivery-otp:{code}".encode()).hexdigest()


def matches(order_id: uuid.UUID, code: str | None) -> bool:
    return hmac.compare_digest(code_for(order_id), (code or "").strip())


__all__ = ["MAX_ATTEMPTS", "code_for", "hash_code", "matches"]

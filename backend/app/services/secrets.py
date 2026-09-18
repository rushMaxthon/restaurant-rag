"""Credentials this platform holds on behalf of somebody else.

A single-tenant deployment keeps its own secrets in environment variables,
where the operator put them and where nothing but the process can read them.
A platform that onboards restaurants holds *their* secrets — a WhatsApp
access token that can send messages as their business, a webhook verify
token — and those arrive at runtime, through a form, and have to live in the
database until the tenant is offboarded.

So they are encrypted at rest with a key that is not in the database. A
dump of `restaurant_whatsapp_channels` on its own is then useless: the
ciphertext needs `SECRETS_ENCRYPTION_KEY`, which lives with the process, the
way the database password does.

Fernet, from `cryptography`, which is already installed — `python-jose`
pulls it in for JWT signing. It is authenticated encryption, so a tampered
value fails loudly rather than decrypting to nonsense.

Nothing here ever logs a plaintext value, and nothing returns one by
accident: `decrypt_secret` raises on a value it cannot authenticate rather
than falling back to the input, because a token that silently stays
ciphertext would be sent to Meta as a bearer token.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

logger = logging.getLogger(__name__)


class SecretsUnavailable(RuntimeError):
    """No usable encryption key, so a tenant's credential cannot be handled.

    Raised rather than falling back to storing plaintext. A deployment that
    has not been given a key is one that should refuse to accept somebody
    else's access token, not one that should keep it in the clear.
    """


@lru_cache(maxsize=1)
def _cipher() -> Fernet:
    key = (get_settings().secrets_encryption_key or "").strip()
    if not key:
        raise SecretsUnavailable(
            "SECRETS_ENCRYPTION_KEY is not set, so tenant credentials cannot be "
            "stored. Generate one with: python -c "
            "\"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as error:
        raise SecretsUnavailable(
            "SECRETS_ENCRYPTION_KEY is not a valid Fernet key (32 url-safe "
            "base64-encoded bytes)"
        ) from error


def secrets_available() -> bool:
    """Whether this deployment can hold a tenant's credentials at all.

    For the onboarding UI, which should say so before a form is filled in
    rather than after it is submitted.
    """

    try:
        _cipher()
    except SecretsUnavailable:
        return False
    return True


def encrypt_secret(plaintext: str) -> str:
    """One credential, ready to be written to a column.

    An empty value stays empty: a channel with no app secret of its own is a
    normal thing, and encrypting "" to hide the fact that there is nothing
    there helps nobody.
    """

    if not plaintext:
        return ""
    return _cipher().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """The credential back, or a raised error — never the ciphertext.

    A value that will not authenticate means the key has changed or the row
    has been tampered with. Both are worth stopping for: the alternative is
    sending Meta a bearer token that is really a base64 blob and reading the
    401 as the tenant's number being wrong.
    """

    if not ciphertext:
        return ""
    try:
        return _cipher().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as error:
        # Deliberately says nothing about the value itself.
        logger.error("A stored credential could not be decrypted")
        raise SecretsUnavailable(
            "A stored credential could not be decrypted. The encryption key may "
            "have changed since it was written."
        ) from error

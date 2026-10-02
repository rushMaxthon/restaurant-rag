"""Signing in with a phone number and a one-time code.

The flow every Indian food app uses, and the one this storefront's customers
expect: type a number, type the code, you are in — no password to invent and
none to forget.

**There is no SMS sender yet, and this module is honest about that.** The only
code it can check is a fixed one from settings, which is a demo device and
nothing else: a fixed code is a password that every account on the platform
shares and that is printed in a config file. So it is guarded twice, in the
same shape as `enable_delivery_rehearsal`:

* `enable_phone_otp_login` is off by default, and
* the fixed code is only ever accepted when `environment` is unmistakably
  local.

With the flag on in production and no sender wired, `delivery_for` reports
that there is no way to send a code and the route refuses. It never falls
through to accepting the fixed one, because the failure mode of that mistake
is "anybody can sign in as anybody" — which is not a degraded service, it is
the absence of authentication.

Replacing the fixed code with a real sender means: store a per-phone challenge
with an expiry and an attempt count, rate-limit both requesting and verifying,
and compare in constant time. None of that exists here, deliberately — a store
that is never read by a real code path is a store nobody has tested.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import ColumnElement, func

from app.config import get_settings

#: Environments where a fixed code may be accepted. The same list the
#: rehearsal courier uses, for the same reason: a flag is one `.env` line away
#: from being wrong, so the environment has to agree.
LOCAL_ENVIRONMENTS = {"development", "dev", "local", "test", "testing"}

#: How many trailing digits identify a subscriber.
#:
#: Phone numbers in this database were written by several paths over time and
#: are not in one shape: `(982) 000-0011`, `+19059039992` and `9192127000` are
#: all really there. A sign-in that compared them literally would hand an
#: existing customer a brand new account and an empty order history, which is
#: the worst outcome this flow has.
#:
#: Ten is the national subscriber number in India, where this is deployed. It
#: is a real limitation and not a general rule: a country with shorter numbers
#: would match too loosely. The fix when that day comes is to store a
#: normalised E.164 column and compare it, not to widen this.
SUBSCRIBER_DIGITS = 10

_NOT_DIGITS = re.compile(r"\D")


@dataclass(frozen=True, slots=True)
class OtpAvailability:
    """Whether a code can be sent at all, and why not when it cannot."""

    available: bool
    #: `""` when available. Otherwise `disabled` or `no_sender`.
    reason: str = ""
    #: True when the fixed code from settings is the one that will work. The
    #: route echoes the code back in this case so a demo does not need an SMS
    #: at all — and it is only ever true on a local environment.
    debug: bool = False


def otp_availability() -> OtpAvailability:
    """Whether this deployment can sign anybody in by phone right now."""

    settings = get_settings()
    if not settings.enable_phone_otp_login:
        return OtpAvailability(False, "disabled")
    if settings.environment.strip().lower() in LOCAL_ENVIRONMENTS:
        return OtpAvailability(True, debug=True)
    # The flag is on somewhere real and there is nothing to send with. Said
    # out loud rather than quietly accepting the fixed code.
    return OtpAvailability(False, "no_sender")


def subscriber_key(phone_number: str | None) -> str:
    """The trailing digits that identify a subscriber, or `""`.

    Everything that is not a digit goes, including the `+` and the country
    code, because the stored values disagree about both.
    """

    digits = _NOT_DIGITS.sub("", phone_number or "")
    return digits[-SUBSCRIBER_DIGITS:] if digits else ""


def matches_subscriber(column: ColumnElement[str | None], key: str) -> ColumnElement[bool]:
    """A WHERE clause matching a stored phone number against `subscriber_key`.

    The stripping has to happen in SQL as well as in Python, because the stored
    side is what is inconsistent. Postgres only — which this app already is,
    for pgvector.
    """

    return func.right(func.regexp_replace(column, r"\D", "", "g"), SUBSCRIBER_DIGITS) == key


def code_is_valid(code: str) -> bool:
    """Whether this is the code we are currently willing to accept.

    Only ever the fixed one, and only where `otp_availability` says so. A
    caller that skips that check gets False here too, so the guard cannot be
    forgotten at one call site.
    """

    availability = otp_availability()
    if not availability.available or not availability.debug:
        return False
    expected = get_settings().otp_debug_code.strip()
    # An empty configured code would otherwise accept an empty submission.
    return bool(expected) and code.strip() == expected


__all__ = [
    "LOCAL_ENVIRONMENTS",
    "SUBSCRIBER_DIGITS",
    "OtpAvailability",
    "code_is_valid",
    "matches_subscriber",
    "otp_availability",
    "subscriber_key",
]

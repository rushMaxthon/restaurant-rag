"""SMS, through whichever gateway the restaurant already pays.

Deliberately provider-agnostic. Indian restaurants reach their customers
through a dozen different aggregators and none of them is the obvious default,
so this posts a small JSON body to a URL the owner supplies and accepts any 2xx
as delivered. That is a weaker integration than a first-party SDK and it is
the honest one: hardcoding Twilio would mean every restaurant not on Twilio
cannot use the channel at all.

Two rules the owner's money depends on:

**The opt-out footer is appended here, not by the editor.** It is a legal
requirement, it is not the owner's to remove, and the editor already showed it
greyed out and counted it toward the bill. Appending it at the last moment is
what guarantees the message that goes out matches the one that was costed.

**Length is billed in 160-character parts.** `messageParts` in the admin and
`_parts` here have to agree, because the first is what the owner was quoted
and the second is what they are charged.
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.models.enums import MarketingChannel
from app.services.marketing.providers.base import (
    BatchMember,
    BatchResult,
    MemberOutcome,
    ProviderError,
    RenderedMessage,
)

logger = logging.getLogger(__name__)
settings = get_settings()

SEGMENT_LENGTH = 160
OPT_OUT_FOOTER = "Reply STOP to opt out"


def compose(body: str) -> str:
    """The text as the customer receives it, footer included.

    Idempotent: a body that already ends with the footer is not given a
    second one. An owner who types the line themselves should not be charged
    for it twice.
    """

    text = body.strip()
    if text.upper().endswith(OPT_OUT_FOOTER.upper()):
        return text
    return f"{text} {OPT_OUT_FOOTER}"


def parts(body: str) -> int:
    """How many billable messages this is. Never zero — see the admin's copy."""

    return max(1, -(-len(compose(body)) // SEGMENT_LENGTH))


class SmsProvider:
    channel = MarketingChannel.SMS

    def __init__(self, *, config: dict, credentials: dict) -> None:
        self._url = str(config.get("api_url") or "").strip()
        self._sender = str(config.get("sender_id") or "").strip()
        self._key = str(credentials.get("api_key") or "").strip()
        if not self._url or not self._key:
            raise ProviderError(
                "SMS is not finished connecting — it still needs your provider's send "
                "URL and an API key."
            )

    def addresses_for(self, user) -> list[str]:
        raw = (getattr(user, "phone_number", None) or "").strip()
        return [raw] if len(raw) >= 8 else []

    def max_batch(self) -> int:
        return 100

    def send(self, members: list[BatchMember], *, message: RenderedMessage) -> BatchResult:
        text = compose(message.body)
        headers = {"Authorization": f"Bearer {self._key}"}
        outcomes: list[MemberOutcome] = []

        with httpx.Client(timeout=settings.marketing_provider_timeout_seconds) as client:
            for member in members:
                address = member.addresses[0] if member.addresses else None
                if not address:
                    outcomes.append(
                        MemberOutcome(
                            user_id=member.user_id,
                            delivered=False,
                            reason="No mobile number on file",
                        )
                    )
                    continue

                payload = {
                    "to": address,
                    "sender": self._sender,
                    "message": text,
                    # Sent so a gateway that supports it can bill and report
                    # per part rather than guessing at the encoding.
                    "parts": parts(message.body),
                }
                try:
                    response = client.post(self._url, headers=headers, json=payload)
                except httpx.HTTPError as exc:
                    outcomes.append(
                        MemberOutcome(
                            user_id=member.user_id,
                            delivered=False,
                            reason=f"Your SMS provider was unreachable: {exc}"[:255],
                        )
                    )
                    continue

                if response.status_code < 300:
                    outcomes.append(MemberOutcome(user_id=member.user_id, delivered=True))
                    continue

                outcomes.append(
                    MemberOutcome(
                        user_id=member.user_id,
                        delivered=False,
                        reason=_describe(response)[:255],
                    )
                )

        return BatchResult(outcomes=outcomes)


def _describe(response: httpx.Response) -> str:
    if response.status_code in (401, 403):
        return "Your SMS provider rejected the API key. Reconnect SMS with a new one."
    detail = (response.text or "").strip()
    if detail:
        return f"Your SMS provider refused it ({response.status_code}): {detail[:180]}"
    return f"Your SMS provider refused it ({response.status_code})"

"""WhatsApp, through Meta's Cloud API.

The one channel whose content rules are set by someone else. WhatsApp only
delivers a business-initiated message that matches a **template Meta approved
in advance**, so the campaign editor offers a layout picker instead of a text
box, and this provider sends `type: template` rather than `type: text`. A
provider that posted free text here would be building a feature WhatsApp
refuses at the far end, and the owner would find out from a failed send.

The template's variable slots are filled from the rendered copy. Meta numbers
them from 1, positionally, which is why the body text is passed as a single
`{{1}}` rather than as named fields: a named-parameter template has to be
registered as such, and the Hub cannot know how the owner registered theirs.

One message per customer. There is no multicast on this API — each recipient
is its own request — so `max_batch` is the number of requests dispatch will
make before committing progress, not a bulk endpoint.
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

GRAPH_VERSION = "v21.0"

#: Meta error codes that mean "this address will never work", as opposed to
#: "this attempt did not". Only the first kind should retire a phone number.
#: 131026 is "message undeliverable" — the number is not on WhatsApp at all.
PERMANENT_ERROR_CODES = {131026, 131047, 131052}


class WhatsAppProvider:
    channel = MarketingChannel.WHATSAPP

    def __init__(self, *, config: dict, credentials: dict) -> None:
        self._phone_number_id = str(config.get("phone_number_id") or "").strip()
        self._token = str(credentials.get("access_token") or "").strip()
        if not self._phone_number_id or not self._token:
            raise ProviderError(
                "WhatsApp is not finished connecting — it still needs a phone number ID "
                "and an access token."
            )

    def addresses_for(self, user) -> list[str]:
        """The customer's phone, digits only, as Meta wants it.

        No plus, no spaces, no dashes: the Cloud API takes an E.164 number
        without the leading `+`, and a number that reaches the kitchen fine as
        "+91 80 4718 2203" is silently undeliverable in that form.
        """

        raw = (getattr(user, "phone_number", None) or "").strip()
        digits = "".join(character for character in raw if character.isdigit())
        return [digits] if len(digits) >= 8 else []

    def max_batch(self) -> int:
        # No bulk endpoint exists. This is how often progress is committed,
        # and it is small so a large send's bar actually moves.
        return 50

    def send(self, members: list[BatchMember], *, message: RenderedMessage) -> BatchResult:
        template_name = str(message.extra.get("whatsapp_template") or message.extra.get("template_id") or "").strip()
        if not template_name:
            raise ProviderError(
                "Pick one of your approved WhatsApp layouts — Meta will not deliver "
                "anything else."
            )
        language = str(message.extra.get("whatsapp_language") or "en").strip() or "en"

        url = f"https://graph.facebook.com/{GRAPH_VERSION}/{self._phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self._token}"}
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
                    "messaging_product": "whatsapp",
                    "to": address,
                    "type": "template",
                    "template": {
                        "name": template_name,
                        "language": {"code": language},
                        "components": [
                            {
                                "type": "body",
                                "parameters": [{"type": "text", "text": message.body}],
                            }
                        ],
                    },
                }
                outcomes.append(self._send_one(client, url, headers, payload, member))

        return BatchResult(outcomes=outcomes)

    def _send_one(self, client, url, headers, payload, member: BatchMember) -> MemberOutcome:
        """One request, with every failure turned into a sentence.

        A transport error is reported per recipient rather than raised,
        because a single unreachable number must not abandon the rest of the
        send — the campaign is already SENDING and the other nine hundred
        people are still owed their message.
        """

        try:
            response = client.post(url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            return MemberOutcome(
                user_id=member.user_id, delivered=False, reason=f"WhatsApp unreachable: {exc}"[:255]
            )

        if response.status_code < 300:
            return MemberOutcome(user_id=member.user_id, delivered=True)

        reason, permanent = _describe(response)
        return MemberOutcome(
            user_id=member.user_id,
            delivered=False,
            reason=reason[:255],
            dead_addresses=list(member.addresses) if permanent else [],
        )


def _describe(response: httpx.Response) -> tuple[str, bool]:
    """Meta's error, as something an owner can act on.

    The raw shape is `{"error": {"message": ..., "code": ...}}`. The code is
    what decides whether the number is retired; the message is what the owner
    reads, so the two are kept apart rather than concatenated into one string
    nobody can parse later.
    """

    try:
        body = response.json().get("error", {})
    except ValueError:
        return f"WhatsApp refused the message ({response.status_code})", False

    code = body.get("code")
    message = body.get("message") or f"WhatsApp refused the message ({response.status_code})"

    if response.status_code in (401, 403):
        return (
            "WhatsApp rejected your access token. Reconnect WhatsApp to generate a new one.",
            False,
        )
    if code == 132001:
        return (
            "That message layout is not approved by Meta yet. Approval usually takes a day.",
            False,
        )
    if code in PERMANENT_ERROR_CODES:
        return ("This number is not on WhatsApp.", True)
    return (str(message), False)

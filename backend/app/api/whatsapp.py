"""Meta's webhook for the WhatsApp concierge.

Two endpoints, both unauthenticated in the usual sense: Meta has no bearer
token to give us. The GET is the one-time subscription handshake; the POST is
every inbound message, authenticated by its signature the same way the Stripe
webhook is.

The POST answers 200 to almost everything on purpose. Meta retries what it
reads as a failure, so a message we cannot or should not answer is accepted and
dropped rather than rejected — the alternative is the same message arriving
again every few minutes. The only refusal is a bad signature, which is a
request that did not come from Meta at all.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, Query, Request, Response, status

from app.config import get_settings
from app.services.cache import cache_get_json, cache_set_json
from app.services.marketing.inbound import handle_marketing_reply
from app.services.whatsapp import (
    inbound_messages,
    is_our_number,
    may_answer,
    verify_signature,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/whatsapp", tags=["WhatsApp"])
settings = get_settings()

ACCEPTED = {"status": "ok"}


@router.get("/webhook", include_in_schema=False)
def verify_subscription(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    """Meta's subscription check: echo the challenge if the token matches.

    Plain text, not JSON — Meta compares the body byte for byte and a quoted
    JSON string does not match.
    """

    expected = settings.whatsapp_verify_token
    if not expected or hub_mode != "subscribe" or hub_verify_token != expected:
        logger.warning("WhatsApp subscription check refused (mode=%s)", hub_mode)
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    return Response(content=hub_challenge or "", media_type="text/plain")


def _already_answered(message_id: str) -> bool:
    """Has this exact message been taken already?

    Meta redelivers anything it believes failed, including deliveries we
    answered slowly. Without this the customer gets the same answer twice.
    Redis degrades to a miss when it is down, so the worst case is the old
    behaviour rather than a dropped message.
    """

    if not message_id:
        return False
    key = f"whatsapp:seen:{message_id}"
    if cache_get_json(key) is not None:
        return True
    cache_set_json(key, True, ttl_seconds=settings.whatsapp_seen_message_ttl_seconds)
    return False


@router.post("/webhook", include_in_schema=False)
async def receive(
    request: Request,
    signature: str | None = Header(default=None, alias="X-Hub-Signature-256"),
) -> dict[str, str]:
    """Take a delivery, hand the questions to a worker, and answer immediately.

    The reply is not generated here. The assistant runs on Ollama and routinely
    takes 15-25 seconds, far past the few seconds Meta waits before calling the
    delivery failed and sending it again.
    """

    payload = await request.body()
    if not verify_signature(payload, signature):
        # The only refusal. Everything else is accepted and quietly ignored.
        logger.warning("WhatsApp delivery refused: bad signature")
        return Response(status_code=status.HTTP_403_FORBIDDEN)  # type: ignore[return-value]

    if not settings.whatsapp_enabled:
        # 503, not 200. A 200 tells Meta the message was handled and it is
        # never sent again - so a switched-off channel on a webhook that still
        # points here would swallow the messages of whoever the number really
        # belongs to. An error makes Meta retry, and they arrive once the
        # webhook is pointed back where it should be.
        logger.warning("WhatsApp delivery refused: channel disabled")
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)  # type: ignore[return-value]

    try:
        body = await request.json()
    except ValueError:
        logger.warning("WhatsApp delivery was not JSON")
        return ACCEPTED

    # Imported here so the module graph does not pull Celery into the API on
    # import, which is how a broken broker becomes a failed startup.
    from app.tasks.whatsapp import answer_whatsapp_message

    for message in inbound_messages(body):
        # "STOP" is honoured before anything else looks at the message, and
        # deliberately before the allowlist and the our-number checks below.
        #
        # Every marketing WhatsApp template carries "Reply STOP to stop
        # receiving these". A customer who does exactly that must not have
        # their reply dropped because they are not on a testing allowlist, or
        # because the number they replied to is a second number on the same
        # Meta account. Both of those are our configuration problems and none
        # of them is a reason to keep messaging someone who said no.
        #
        # It also returns before the assistant is given the text: answering
        # "Sorry, I didn't understand — would you like to see the menu?" to
        # somebody opting out is the worst possible reply.
        if handle_marketing_reply(message.from_number, message.text, source="whatsapp"):
            continue

        if not is_our_number(message.phone_number_id):
            # Someone else's number on a shared account. Not ours to answer.
            logger.info(
                "WhatsApp message ignored: arrived at %s, we answer for %s",
                message.phone_number_id or "(none)",
                settings.whatsapp_phone_number_id or "(none)",
            )
            continue
        if not may_answer(message.from_number):
            # Not on the testing allowlist. Silence, not a reply: this number
            # may belong to a live business whose customers are not ours.
            logger.info("WhatsApp message ignored: sender not on the allowlist")
            continue
        if _already_answered(message.message_id):
            logger.info("WhatsApp message %s already answered", message.message_id)
            continue

        answer_whatsapp_message.delay(
            from_number=message.from_number,
            text=message.text,
            message_id=message.message_id,
        )

    return ACCEPTED

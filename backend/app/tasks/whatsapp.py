"""Answering a WhatsApp message, off the request that delivered it.

Meta waits a few seconds for the webhook and retries what it reads as a
failure. The assistant runs on Ollama and routinely takes 15-25 seconds, so the
answer cannot be produced while Meta is holding the line. The webhook takes the
message and this does the work.

Nothing here decides what to say. `handle_chat_message` is the same function
the web concierge calls, so the two channels answer from one set of rules about
one menu, and cannot drift into disagreeing about it.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.config import get_settings
from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.services.chat_principal import guest_principal_for_session
from app.services.rag import handle_chat_message
from app.services.whatsapp import render_reply, send_text

logger = logging.getLogger(__name__)
settings = get_settings()

# One conversation per phone number, stable across restarts. A session id minted
# per message would give every turn its own memory, and the assistant would
# meet the same person as a stranger every time they typed.
WHATSAPP_SESSION_NAMESPACE = uuid.UUID("6f1b4a02-9d5e-4a1c-9a2f-2b7c3e5d8a41")


def session_for(from_number: str) -> uuid.UUID:
    return uuid.uuid5(WHATSAPP_SESSION_NAMESPACE, f"whatsapp:{from_number}")


def _configured_restaurant_id() -> uuid.UUID | None:
    """Which menu this number answers from, or None for all of them.

    A malformed id is treated as unset rather than raising: the wrong scope is
    a worse outcome than the broad one, but neither is worth refusing to answer
    a customer over.
    """

    raw = (settings.whatsapp_restaurant_id or "").strip()
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        logger.error("whatsapp_restaurant_id is not a uuid: %r", raw)
        return None


@celery_app.task(
    name="app.tasks.whatsapp.answer_whatsapp_message",
    bind=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 2},
)
def answer_whatsapp_message(
    self: Any,
    *,
    from_number: str,
    text: str,
    message_id: str = "",
) -> dict[str, str]:
    if not settings.whatsapp_enabled:
        return {"status": "disabled"}

    session_id = session_for(from_number)
    principal = guest_principal_for_session(session_id)

    with SessionLocal() as db:
        answer = handle_chat_message(
            db,
            user=principal,
            message=text,
            session_id=session_id,
            restaurant_id=_configured_restaurant_id(),
        )

    body = render_reply(answer.reply, list(answer.suggestions or []))
    if not body:
        # The assistant had nothing to say. Silence reads as a broken bot, so
        # say the honest thing instead.
        body = "Sorry — I could not find anything for that. Try naming a dish or a craving?"

    sent = send_text(from_number, body)
    logger.info(
        "WhatsApp answered message_id=%s to=%s chars=%s sent=%s",
        message_id,
        from_number,
        len(body),
        sent,
    )
    return {"status": "sent" if sent else "failed", "message_id": message_id}

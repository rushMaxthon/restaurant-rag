"""Answering a WhatsApp message, off the request that delivered it.

Meta waits a few seconds for the webhook and retries what it reads as a
failure. The assistant runs on Ollama and routinely takes 15-25 seconds, so the
answer cannot be produced while Meta is holding the line. The webhook takes the
message and this does the work.

Nothing here decides what to say. `handle_chat_message` is the same function
the web concierge calls, so the two channels answer from one set of rules about
one menu, and cannot drift into disagreeing about it.

Two things this channel has to supply that a browser supplies on the web. The
cart, because there is no localStorage here — it is kept against the
conversation and the actions the agent returns are applied to it on this side
instead of by a client. And the customer's identity: Meta has verified that
this number belongs to the person typing, which is what lets an order be
placed without a sign-in nobody can perform in a chat thread.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.config import get_settings
from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.services.chat_principal import guest_principal_for_session
from app.services.ordering_agent import session_cart
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


def _compose_reply(answer: Any, proposed: list[dict[str, Any]]) -> str:
    """What to send back, and in what order.

    The agent's line wins when the agent owns the turn: it is the half that
    knows about the cart, the order and the payment, and the reply pipeline
    answers a question about a cart by searching the menu for a dish called
    "cart". The payment link goes on its own line, unshortened and
    unsurrounded, because a link a customer cannot tap is an order they
    cannot pay for.
    """

    spoken = (
        answer.agent_reply
        if getattr(answer, "agent_asks", False) and answer.agent_reply
        else answer.reply
    )
    parts = [render_reply(spoken, list(answer.suggestions or []))]

    placed = getattr(answer, "placed_order", None) or {}
    if placed.get("payment_url"):
        parts.append(f"Pay here:\n{placed['payment_url']}")
    elif getattr(answer, "order_ready", False):
        # No buttons in a chat thread, so the confirmation is a word.
        parts.append("Reply YES and I will place it and send you a payment link.")

    if proposed:
        parts.append("Just say the word and I will do that.")
    return "\n\n".join(part for part in parts if part)


def _configured_location_id() -> uuid.UUID | None:
    """Which branch this number orders from.

    An order needs one, and a chat thread has no branch picker. Unset means
    the agent answers about the menu but cannot place anything — which is
    the honest failure, rather than guessing a branch on a customer's behalf.
    """

    raw = (getattr(settings, "whatsapp_restaurant_location_id", "") or "").strip()
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        logger.error("whatsapp_restaurant_location_id is not a uuid: %r", raw)
        return None


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
    cart = session_cart.load(session_id)

    with SessionLocal() as db:
        answer = handle_chat_message(
            db,
            user=principal,
            message=text,
            session_id=session_id,
            restaurant_id=_configured_restaurant_id(),
            restaurant_location_id=_configured_location_id(),
            cart=cart,
            # Meta verified this number before delivering the message. It is
            # the whole basis on which an order can be placed here.
            verified_phone=from_number,
        )

    # No client to apply them, so this side does — the same actions, the same
    # rules about which of them may be applied at all.
    updated, proposed = session_cart.apply_actions(cart, [
        action.model_dump(mode="json") if hasattr(action, "model_dump") else dict(action)
        for action in (answer.cart_actions or [])
    ])
    if updated != cart:
        session_cart.save(session_id, updated)
    if answer.placed_order:
        # The items are on the order now. A cart that outlives it is how
        # somebody orders the same thing twice.
        session_cart.clear(session_id)

    body = _compose_reply(answer, proposed)
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

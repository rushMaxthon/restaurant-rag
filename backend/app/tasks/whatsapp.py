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

import json
import logging
import uuid
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.config.celery import celery_app
from app.config.database import SessionLocal
from app.services.chat_principal import guest_principal_for_session
from app.services.ordering_agent import order_draft, session_cart
from app.services.rag import handle_chat_message
from app.services.whatsapp import (
    MOST_ROWS,
    render_reply,
    send_buttons,
    send_list,
    send_text,
    show_typing,
    split_printed_list,
)

logger = logging.getLogger(__name__)
settings = get_settings()

# One conversation per phone number, stable across restarts. A session id minted
# per message would give every turn its own memory, and the assistant would
# meet the same person as a stranger every time they typed.
WHATSAPP_SESSION_NAMESPACE = uuid.UUID("6f1b4a02-9d5e-4a1c-9a2f-2b7c3e5d8a41")


def session_for(from_number: str) -> uuid.UUID:
    return uuid.uuid5(WHATSAPP_SESSION_NAMESPACE, f"whatsapp:{from_number}")


def _agent_owns(answer: Any) -> bool:
    """Whether the agent's own sentence is the answer this turn.

    Named because two things depend on it and must not disagree: what gets
    said, and which dishes — if any — end up listed under it.
    """

    return bool(getattr(answer, "agent_asks", False) and getattr(answer, "agent_reply", None))


def dishes_listed_under(answer: Any) -> list[str]:
    """The dish names this reply will list under it, in the order shown.

    Recorded by the caller so a number answers them. The condition is the
    agent's: when it owns the turn its suggestions are dropped, because
    "you have 3 x Corn Fritters, subtotal $25.47" followed by two dishes to
    consider is a second conversation nobody started — and a list that was
    never printed must never be what a number counts along.
    """

    if _agent_owns(answer):
        return []
    names: list[str] = []
    for item in getattr(answer, "suggestions", None) or []:
        name = getattr(item, "name", None) or (
            item.get("name") if isinstance(item, dict) else None
        )
        if name:
            names.append(str(name))
    return names


#: The questions a tap can answer with yes or no, and what the two taps say.
#:
#: The LABELS are cosmetic; the ids carry "yes" and "no", which is what the
#: turn already reads against the question it wrote down (`_answer_standing`).
#: So a tap takes the path a typed "yes" takes, and nothing new can go wrong
#: on it — which matters most here, because these are the turns where reading
#: the answer goes wrong today: "2", in reply to "Take all 2 items off your
#: order?", was read as a yes.
_YES_NO_BUTTONS = {
    "more": ("Yes, add more", "No, that's all"),
    "checkout": ("Check out", "Not yet"),
    "add": ("Yes, add it", "No thanks"),
    "clear_cart": ("Yes, clear it", "Keep it"),
    "place": ("Place the order", "Not yet"),
    "keep_order": ("Yes, keep it", "No, cancel it"),
    "drop_order": ("Yes, cancel it", "No, keep it"),
    "restore_cart": ("Yes please", "No thanks"),
}


def buttons_for(awaiting: dict[str, Any] | None) -> list[tuple[str, str]]:
    """The tappable answers to the question this turn ended on, if it has two.

    `name_one` and `time_on_day` are deliberately absent: they want a dish or
    a time, and two buttons cannot offer either.
    """

    if not isinstance(awaiting, dict):
        return []
    labels = _YES_NO_BUTTONS.get(str(awaiting.get("yes") or ""))
    if labels is None:
        return []
    return [("say:yes", labels[0]), ("say:no", labels[1])]


def rows_that_fit(rows: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """The rows, or none at all when there are more than a list can hold.

    Ten is Meta's cap and several of this menu's lists are longer — Bodakdev
    has eleven sections and eleven pizzas. Those stay as numbered text, which
    is why the numbered text has to keep working: a tappable list improves a
    message that already worked, it is never the only way to answer.

    None rather than the first ten, because a list that silently stops at ten
    of eleven is a claim that the menu ends there — the same reason the
    sections offer says how many more it has.
    """

    return rows if 2 <= len(rows) <= MOST_ROWS else []


def _compose_reply(
    answer: Any, proposed: list[dict[str, Any]], currency: str | None = None
) -> str:
    """What to send back, and in what order.

    The agent's line wins when the agent owns the turn: it is the half that
    knows about the cart, the order and the payment, and the reply pipeline
    answers a question about a cart by searching the menu for a dish called
    "cart". The payment link goes on its own line, unshortened and
    unsurrounded, because a link a customer cannot tap is an order they
    cannot pay for.
    """

    owns = _agent_owns(answer)
    spoken = answer.agent_reply if owns else answer.reply
    # Dishes to consider go under an answer about the menu. Under "you have
    # 3 x Corn Fritters, subtotal $25.47" they are a second conversation
    # nobody started — the web dropped the same list for the same reason.
    parts = [
        render_reply(spoken, [] if owns else list(answer.suggestions or []), currency)
    ]

    placed = getattr(answer, "placed_order", None) or {}
    if placed.get("payment_url"):
        parts.append(f"Pay here:\n{placed['payment_url']}")
    # No "reply YES" line: on this channel a ready order is placed on the turn
    # the details land (`auto_place`), so being ready and not placed means it
    # was tried and could not be — and the agent's line above says why. The
    # promise was measured live: YES, Yes, yes, the same sentence back each time.

    if proposed:
        parts.append("Just say the word and I will do that.")
    return "\n\n".join(part for part in parts if part)


def e164(wa_id: str) -> str:
    """Meta's number for this person, as the rest of the app writes numbers.

    A wa_id is E.164 with the "+" stripped: "916353100362". Everywhere else
    a number with no plus is one a customer typed, measured against the
    deployment's own national length — so this one was read as a malformed
    Canadian number and every order for it was refused at the schema.

    The country code is always present in a wa_id, so restoring the plus is
    the whole conversion, and it is done here, once, where the number
    arrives — not at each of the places that later treat it as a phone.
    """

    digits = "".join(character for character in wa_id if character.isdigit())
    return f"+{digits}" if digits else ""


def _app_client_id_for(db: Any, restaurant_id: uuid.UUID | None) -> uuid.UUID | None:
    """Which app this number's customer belongs to.

    Identity is scoped by app client — the same phone in the marketplace app
    and in a single-restaurant app are two different accounts, on purpose —
    and a CUSTOMER row without one is refused by the database. A chat thread
    carries no bundle id, so the app is the one that owns the restaurant this
    number answers for.
    """

    if restaurant_id is None:
        return None
    from app.models.app_client import AppClient

    return db.scalar(
        select(AppClient.id).where(AppClient.restaurant_id == restaurant_id).limit(1)
    )


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


def _configured_currency(db: Any) -> str | None:
    """What the restaurant this number answers for charges in.

    Read per message off the session the turn already holds: one lookup by
    primary key, and a currency changed in the admin reaches the next message
    rather than the next deploy.
    """

    restaurant_id = _configured_restaurant_id()
    if restaurant_id is None:
        return None
    from app.models.restaurant import Restaurant

    return db.scalar(select(Restaurant.currency).where(Restaurant.id == restaurant_id))


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

    # Read receipt and typing bubble first, before the seconds of work: a
    # customer watching an empty screen sends the message again, and a
    # second turn starts on a conversation that has not finished its first.
    show_typing(message_id)

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
            # The number Meta verified, in the shape an order is written in.
            verified_phone=e164(from_number),
            app_client_id=_app_client_id_for(db, _configured_restaurant_id()),
            # No buttons in a chat thread: see `run_turn`'s `auto_place`.
            auto_place=True,
        )
        # Read inside the session that answered, so the dishes listed under
        # the reply carry the symbol the menu is priced in.
        currency = _configured_currency(db)

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

    body = _compose_reply(answer, proposed, currency)
    # The dishes this reply lists are now the list in front of the customer,
    # so a number answers them. Only the pipeline's own suggestions reach
    # here: when the agent owns the turn it has already recorded whatever it
    # showed, and `dishes_listed_under` returns nothing rather than
    # overwriting it with a list that was never printed.
    listed = dishes_listed_under(answer)
    if listed:
        order_draft.remember_offered(session_id, listed)
    if not body:
        # The assistant had nothing to say. Silence reads as a broken bot, so
        # say the honest thing instead.
        body = "Sorry — I could not find anything for that. Try naming a dish or a craving?"

    # Offer the answer as taps where the question has a small, fixed set of
    # them. Read from the draft the turn just wrote rather than from its prose:
    # the turn already recorded what it asked and what answers it will accept,
    # and re-deriving that by reading our own sentence back is how the two
    # would come to disagree.
    #
    # Every one of these degrades to the text that was going to be sent
    # anyway, so a question that does not fit a button or a list is not a
    # question that fails.
    sent, how = _answer_by_tap(session_id, from_number, body)
    if not sent and how == "text":
        sent = send_text(from_number, body)
    logger.info(
        "WhatsApp answered message_id=%s to=%s chars=%s as=%s sent=%s",
        message_id,
        from_number,
        len(body),
        how,
        sent,
    )
    return {"status": "sent" if sent else "failed", "message_id": message_id}


def _answer_by_tap(session_id: uuid.UUID, to: str, body: str) -> tuple[bool, str]:
    """Send the reply as buttons or a list where the question allows it.

    Returns whether it was sent and which shape was used; `("...", "text")`
    means nothing tappable applied and the caller should send the words.

    The QUESTION decides, not the longest thing on screen. `awaiting.yes` is
    the turn's own record of what it asked, so a message that ends on yes or
    no gets buttons even when it also printed a list — live, "Added 1 x Build
    Your Own Pizza. People often add: ... Anything else?" was going out as a
    tappable list of the two suggestions, hiding the actual question behind a
    Choose button. The suggestions stay in the text, where they can be read
    and typed.

    A list only when the question IS the list: those end on `name_one`, or on
    no held question at all, and then the rows are the answers.

    Never both. Two questions in one message is what the agent spent a week
    removing. `awaiting` is cleared at the top of every turn and rewritten
    only by a turn that ends on a question, so what is in it now is what this
    message just asked — not something left over from two turns ago.
    """

    buttons = buttons_for(_stored(order_draft.load(session_id).awaiting))
    if buttons:
        return send_buttons(to, body, buttons), "buttons"

    asked, rows = split_printed_list(body)
    rows = rows_that_fit(rows)
    if rows:
        return send_list(to, asked, rows), "list"
    return False, "text"


def _stored(raw: str | None) -> dict[str, Any] | None:
    """One of the draft's JSON stores, or None if it will not read."""

    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None

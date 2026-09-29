"""The WhatsApp side of the concierge: reading Meta's deliveries, and replying.

This module is deliberately thin. It does not answer anything — the answering
is `rag.handle_chat_message`, the same function the web concierge calls, so the
two channels cannot drift into giving different advice about the same menu.
What lives here is the part that is specific to WhatsApp:

* authenticating a delivery by its signature, since there is no other
  credential on the request (the Stripe webhook is authenticated the same way);
* deciding whether a message was even meant for us;
* turning Meta's envelope into something the assistant can read, and the
  assistant's answer back into something WhatsApp will send.

**The number may not be ours alone.** A WhatsApp number can be shared with
another integration, and Meta delivers each inbound message to every subscribed
app. If both answer, the customer gets two replies to one question. Every
delivery names the number it arrived at, so `is_our_number` is the guard, and it
fails closed: an unconfigured deployment answers nobody.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any

import httpx

from app.config import get_settings
from app.services.currency import format_amount

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass(frozen=True)
class InboundMessage:
    """One question from one person, lifted out of Meta's envelope."""

    message_id: str
    from_number: str
    phone_number_id: str
    text: str


def verify_signature(payload: bytes, header: str | None, *, app_secret: str | None = None) -> bool:
    """Is this delivery really from Meta?

    HMAC-SHA256 of the RAW body under the app secret, as `sha256=<hex>`. The
    raw bytes matter: re-serialised JSON reorders keys and changes whitespace,
    and the digest no longer matches.

    Returns False when there is no configured secret. A deployment that has not
    been given one must refuse everything rather than accept anything, which is
    the failure that would otherwise let a stranger drive the assistant.
    """

    secret = app_secret if app_secret is not None else settings.whatsapp_app_secret
    if not secret or not header:
        return False

    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    provided = header[len("sha256=") :] if header.startswith("sha256=") else header
    return hmac.compare_digest(expected, provided)


def is_our_number(phone_number_id: str, *, configured: str | None = None) -> bool:
    """Did this arrive at the number this bot speaks for?

    The whole point of the WhatsApp channel not stepping on another
    integration. Both sides must be non-empty: an event with no number, or a
    deployment with no number configured, is not a match.
    """

    ours = configured if configured is not None else settings.whatsapp_phone_number_id
    return bool(ours) and bool(phone_number_id) and phone_number_id == ours


def may_answer(from_number: str, *, allowed: str | None = None) -> bool:
    """May this particular person be answered?

    Empty list means everyone, which is the production answer. During testing
    on a number that belongs to someone else's live business it is set to the
    testers, because the alternative is what happened the first time this ran:
    a real customer of that business asked their question and got three
    restaurant recommendations back.

    Compared on digits alone, so +91 63531 00362 and 916353100362 are the same
    person however they were written down.
    """

    raw = allowed if allowed is not None else settings.whatsapp_allowed_senders
    entries = [
        "".join(ch for ch in entry if ch.isdigit())
        for entry in (raw or "").split(",")
        if entry.strip()
    ]
    if not entries:
        return True
    digits = "".join(ch for ch in (from_number or "") if ch.isdigit())
    return bool(digits) and digits in entries


#: What a tapped button or list row carries back, so the tap can be read as
#: the words the customer would otherwise have typed.
#:
#: The ID is what we act on, never the title. Meta caps a row title at 24
#: characters and a button title at 20, so "Iced Matcha Coconut Latte" comes
#: back truncated — and a truncated dish name matches nothing. A position does
#: not truncate, and the list it counts along is already written down.
_TAPPED = re.compile(r"^(pick|say):(.+)$", re.S)


def tapped_answer(interactive: Any) -> str:
    """A tapped button or list row, as the message it stands for.

    Everything downstream — the ordinal reader, the plain-phrase table, the
    model — sees exactly what a customer typing the same answer would have
    sent. That is the whole design: tapping adds no new path through the turn,
    so nothing that works by typing can break by tapping.

    A reply whose id is not ours falls back to its title, because a message
    built by something else (a template, a flow added later) is still an
    answer and is better read than dropped.
    """

    if not isinstance(interactive, dict):
        return ""
    reply = interactive.get(str(interactive.get("type") or ""))
    if not isinstance(reply, dict):
        # Meta has used both `button_reply` and `list_reply` under a `type`
        # naming them; a shape that does not self-describe is searched for the
        # one key that could be a reply rather than guessed at.
        reply = next(
            (v for k, v in interactive.items() if k.endswith("_reply") and isinstance(v, dict)),
            None,
        )
    if not isinstance(reply, dict):
        return ""
    ours = _TAPPED.match(str(reply.get("id") or "").strip())
    if ours is not None:
        return ours.group(2).strip()
    return str(reply.get("title") or "").strip()


def inbound_messages(payload: Any) -> list[InboundMessage]:
    """Every answerable message in one delivery.

    Tolerant on purpose. Meta posts delivery receipts, reactions, media and
    shapes that did not exist when this was written, through the same webhook;
    anything unreadable is simply not a question. Raising here would return a
    500, and Meta retries a 500 until it gives up.
    """

    found: list[InboundMessage] = []
    if not isinstance(payload, dict):
        return found

    for entry in payload.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata")
            phone_number_id = ""
            if isinstance(metadata, dict):
                phone_number_id = str(metadata.get("phone_number_id") or "")

            for message in value.get("messages") or []:
                if not isinstance(message, dict):
                    continue
                if message.get("type") == "text":
                    text_block = message.get("text")
                    body = ""
                    if isinstance(text_block, dict):
                        body = str(text_block.get("body") or "").strip()
                elif message.get("type") == "interactive":
                    body = tapped_answer(message.get("interactive"))
                else:
                    continue
                if not body:
                    continue
                found.append(
                    InboundMessage(
                        message_id=str(message.get("id") or ""),
                        from_number=str(message.get("from") or ""),
                        phone_number_id=phone_number_id,
                        text=body,
                    )
                )
    return found


def _priced(value: Any, currency: str | None) -> str:
    """One suggestion's price, in the money this restaurant charges.

    `currency` is the CHANNEL's, not the item's: this number answers for one
    restaurant at a time (`whatsapp_restaurant_id`), so every dish it can
    suggest is priced in the same money. When a number can serve several
    restaurants — the per-tenant channels in section 3 of the plan — this has
    to become the item's own currency, and the item already carries a
    `restaurant_id` to find it with.
    """

    try:
        return format_amount(float(value), currency)
    except (TypeError, ValueError):
        return str(value)


def render_reply(
    reply: str,
    suggestions: list[Any] | None = None,
    currency: str | None = None,
) -> str:
    """The assistant's answer as one WhatsApp message.

    The web concierge returns dish cards — an image, a name, a price, a button.
    WhatsApp has no such thing in a plain text reply, so the dishes are listed
    under the answer with their prices. Losing the pictures is a real loss and
    the honest first version; interactive lists are the next step, and they
    bring limits of their own (ten rows, twenty-four character titles).

    Trimmed to the configured length because WhatsApp rejects an over-long body
    outright: a trimmed answer reaches the customer, a rejected one does not.
    """

    parts = [reply.strip()]
    listed = 0
    for item in suggestions or []:
        name = getattr(item, "name", None) or (item.get("name") if isinstance(item, dict) else None)
        if not name:
            continue
        price = getattr(item, "price", None) or (
            item.get("price") if isinstance(item, dict) else None
        )
        listed += 1
        # Numbered, not bulleted, and recorded by the caller through
        # `dishes_listed_under` — every other list this app prints is
        # answerable by position, and these were the exception. The greeting
        # is the first message a customer ever sees and its four dishes were
        # the one list "1" did not answer.
        #
        # With a symbol, or not at all. This was `f" — {price}"`, which put a
        # bare "185.00" under a dish on a rupee menu — a number with no unit,
        # which every reader silently supplies from their own expectations.
        parts.append(
            f"{listed}. {name}" + (f" — {_priced(price, currency)}" if price else "")
        )
    if listed:
        # Its own paragraph. Run straight onto the last dish it reads as a
        # fifth item in the list. The empty strings the join drops are why
        # the newline is inside the string rather than a part of its own.
        parts.append("\nReply with the number or the name.")

    body = "\n".join(part for part in parts if part).strip()
    limit = int(settings.whatsapp_max_body_chars)
    if len(body) > limit:
        body = body[: limit - 1].rstrip() + "…"
    return body


# Any currency's symbol, not only the dollar this started with, and the
# fractional part optional: a rupee amount — and a whole-rupee one especially,
# since INR is written without paise — was the one figure in a message that
# never got bolded.
_MONEY_RE = re.compile(r"(?<![*\w])([$₹£€]|د\.إ)(\d[\d,]*(?:\.\d{2})?)(?![*\w])")
_ADDED_RE = re.compile(r"^(Added \d+ x )(?!\*)(.+?)( to your order\.)", re.M)
_PLACED_FOR_RE = re.compile(r"(placed for )([A-Z][a-z]{2} \d\d:\d\d)")
_LABEL_RE = re.compile(
    r"^(Total paid|Order reference|Subtotal|Pay here|Try again here|Delivery today|Pickup today):",
    re.M,
)


#: A line of a list we printed: "1. Margherita Pizza - $11.99".
_NUMBERED_LINE = re.compile(r"^\d{1,2}\. ")

#: The invitation that goes under a printed list. Dropped when the list is
#: tappable instead, because "reply with the number" under a row somebody taps
#: is an instruction for a message they are not sending.
_NUMBER_OR_NAME = "Reply with the number or the name."


#: What separates a listed thing from its price: "Margherita Pizza - $11.99",
#: 'Small (8") — $14.99', "Green curry (+$1.00)". All three are written by this
#: app, which is why they can be taken apart again.
_LISTED_PRICE = re.compile(r"\s+—\s+|\s+-\s+|\s+\(\+")


def split_printed_list(body: str) -> tuple[str, list[tuple[str, str, str]]]:
    """The message without the list it printed, and that list as tappable rows.

    Built from the PRINTED lines rather than from what the turn recorded, and
    that is the whole point. Two things go wrong when rows come from the draft
    instead, and both were measured:

    * A stale choice attaches rows to a message that printed no list. Live,
      "There is nothing in your order yet." went out carrying seven topping
      rows from a question two turns earlier — a list the customer could tap
      that had nothing to do with what they had just been told.
    * The price disappears. The draft stores names and ids; the printed line
      is where 'Small (8") — $14.99' exists. Offering a size with no price is
      the money bug this app already fixed once, in the other direction.

    So the rows say exactly what the text said, or there are no rows. Returns
    an empty list whenever it would have to guess, and the caller then sends
    the words it was going to send anyway.
    """

    lines = str(body or "").split("\n")
    rows: list[tuple[str, str, str]] = []
    kept: list[str] = []
    for line in lines:
        numbered = _NUMBERED_LINE.match(line)
        if numbered is None:
            kept.append(line)
            continue
        rest = line[numbered.end() :].strip()
        parts = _LISTED_PRICE.split(rest, maxsplit=1)
        title = parts[0].strip()
        priced = parts[1].strip().rstrip(")") if len(parts) > 1 else ""
        if priced and " (+" in rest:
            # The separator ate the plus, and "$1.00" beside a topping reads
            # as its price rather than as what it adds.
            priced = f"+{priced}"
        if not title:
            # A line we cannot take apart means the rows and the text would
            # disagree, and a row that says the wrong thing is worse than no
            # rows at all.
            return body, []
        rows.append((f"pick:{len(rows) + 1}", title, priced))
    # One line is not a list, and a list of one is not worth a tap.
    if len(rows) < 2:
        return body, []
    kept = [line for line in kept if line.strip() != _NUMBER_OR_NAME]
    # On the sections offer the invitation is the tail of a sentence rather
    # than a line of its own.
    kept = [line.replace(f" {_NUMBER_OR_NAME}", "").rstrip() for line in kept]
    said = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    if not said:
        # Nothing left to say above the rows. Meta requires a body, and a list
        # with no question over it is not one either.
        return body, []
    return said, rows


def format_for_whatsapp(text: str) -> str:
    """Dress a plain message for the phone. Presentation, never meaning.

    Bold on the figures a customer acts on — amounts, the dish just added,
    the time an order is for, the labels on a receipt. Bullets where a list
    was written with dashes. A tick on a payment that landed, a cross on one
    that did not. Markdown bold from the reply pipeline, which had been
    arriving as literal asterisks, becomes WhatsApp bold.

    Idempotent, so a message that has already been dressed is left alone:
    an amount already inside a bold span is not bolded again.
    """

    if not text:
        return text
    out = text.replace("\r\n", "\n")
    # The pipeline writes markdown; the phone reads single asterisks.
    out = re.sub(r"\*\*(.+?)\*\*", r"*\1*", out)
    out = re.sub(r"^- ", "• ", out, flags=re.M)
    out = _ADDED_RE.sub(r"\1*\2*\3", out)
    out = _PLACED_FOR_RE.sub(r"\1*\2*", out)
    out = _LABEL_RE.sub(r"*\1:*", out)
    out = _MONEY_RE.sub(r"*\1\2*", out)
    # "*Total paid:* *$12.00*" reads as one bold run on the phone anyway;
    # one span is the cleaner markup and survives a second pass unchanged.
    out = out.replace("* *", " ")
    if out.startswith("Payment received"):
        out = "✅ " + out
    elif out.startswith("Your payment did not go through"):
        out = "❌ " + out
    elif out.startswith("Your cart:"):
        out = "🛒 " + out
    # Never more than one blank line in a row.
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def show_typing(message_id: str) -> bool:
    """Mark their message read and show the typing bubble. True if Meta took it.

    One call does both — `status: read` with a `typing_indicator` — and the
    bubble clears itself when the reply is sent, or after 25 seconds, which
    is longer than any turn measured here.

    Why it is worth a call at all: a turn takes four to eight seconds, and
    for those seconds the customer sees nothing, not even a read receipt.
    There is no way to tell a bot that is thinking from one that is broken,
    so they send the message again and a second turn starts on a
    conversation that has not finished its first.

    Never raises and never blocks the answer. A customer who does not see a
    bubble still gets their food; one whose answer failed because we were
    drawing a bubble would not.
    """

    if not message_id or not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        return False

    url = f"{settings.whatsapp_api_base_url}/{settings.whatsapp_phone_number_id}/messages"
    try:
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
            json={
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id,
                "typing_indicator": {"type": "text"},
            },
            # Short on purpose: this is a courtesy, and the customer is
            # waiting for the answer behind it.
            timeout=5.0,
        )
    except httpx.HTTPError:
        logger.warning("WhatsApp typing indicator failed", exc_info=True)
        return False

    if response.status_code >= 400:
        logger.warning(
            "WhatsApp typing indicator refused status=%s body=%s",
            response.status_code,
            response.text[:200],
        )
        return False
    return True


def _send(to: str, message: dict[str, Any]) -> bool:
    """Post one composed message to Meta. True if it was accepted.

    Failures are logged and swallowed: this runs on a worker, and the only
    thing a raise would achieve is a retry that sends the customer the same
    answer twice.
    """

    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        logger.warning("WhatsApp send skipped: channel is not configured")
        return False

    url = f"{settings.whatsapp_api_base_url}/{settings.whatsapp_phone_number_id}/messages"
    try:
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
            json={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                **message,
            },
            timeout=20.0,
        )
    except httpx.HTTPError:
        logger.exception("WhatsApp send failed for %s", to)
        return False

    if response.status_code >= 400:
        # Body, not just status: Meta explains refusals (expired token, outside
        # the 24-hour window, unregistered recipient) only in the body.
        logger.error(
            "WhatsApp send rejected for %s: %s %s", to, response.status_code, response.text[:400]
        )
        return False
    return True


def send_text(to: str, body: str) -> bool:
    """Send one message back. True if Meta accepted it."""

    return _send(
        to,
        {"type": "text", "text": {"preview_url": False, "body": format_for_whatsapp(body)}},
    )


#: Meta's caps on what a tappable reply may say. Titles are truncated to fit
#: rather than refused: a row the customer can read and tap beats no row, and
#: nothing downstream reads the title anyway — the id carries the answer.
BUTTON_TITLE_CHARS = 20
ROW_TITLE_CHARS = 24
ROW_DESCRIPTION_CHARS = 72
MOST_BUTTONS = 3
MOST_ROWS = 10


def _fits(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def send_buttons(to: str, body: str, buttons: Sequence[tuple[str, str]]) -> bool:
    """A question with up to three tappable answers.

    For the yes/no turns — "Take all 2 items off your order?", "Ready to check
    out?" — which are exactly where reading the answer goes wrong: measured,
    "2" in reply to "Take all 2 items off?" was read as a yes. A tap carries
    an id we wrote, so on those turns the model is not asked to interpret
    anything at all.

    Falls back to plain text when there is nothing tappable to offer, so a
    caller never has to check first.
    """

    offered = [(i, t) for i, t in buttons if str(t).strip()][:MOST_BUTTONS]
    if not offered:
        return send_text(to, body)
    return _send(
        to,
        {
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": format_for_whatsapp(body)},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {"id": str(i), "title": _fits(t, BUTTON_TITLE_CHARS)},
                        }
                        for i, t in offered
                    ]
                },
            },
        },
    )


def send_list(
    to: str, body: str, rows: Sequence[tuple[str, str, str]], *, label: str = "Choose"
) -> bool:
    """A question with up to ten tappable rows behind one button.

    The customer taps rather than typing a name they have to copy or a number
    they have to count. Ten is Meta's cap on rows in one list, and it is why
    the numbered text version has to keep working: a branch with eleven
    sections cannot be a list message.
    """

    offered = [(i, t, d) for i, t, d in rows if str(t).strip()][:MOST_ROWS]
    if not offered:
        return send_text(to, body)
    return _send(
        to,
        {
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": format_for_whatsapp(body)},
                "action": {
                    "button": _fits(label, BUTTON_TITLE_CHARS),
                    "sections": [
                        {
                            "title": _fits(label, ROW_TITLE_CHARS),
                            "rows": [
                                {
                                    "id": str(i),
                                    "title": _fits(t, ROW_TITLE_CHARS),
                                    **(
                                        {"description": _fits(d, ROW_DESCRIPTION_CHARS)}
                                        if str(d or "").strip()
                                        else {}
                                    ),
                                }
                                for i, t, d in offered
                            ],
                        }
                    ],
                },
            },
        },
    )

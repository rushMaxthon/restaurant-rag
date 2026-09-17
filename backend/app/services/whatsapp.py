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
from typing import Any

import httpx

from app.config import get_settings

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
                if not isinstance(message, dict) or message.get("type") != "text":
                    continue
                text_block = message.get("text")
                body = ""
                if isinstance(text_block, dict):
                    body = str(text_block.get("body") or "").strip()
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


def render_reply(reply: str, suggestions: list[Any] | None = None) -> str:
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
    for item in suggestions or []:
        name = getattr(item, "name", None) or (item.get("name") if isinstance(item, dict) else None)
        if not name:
            continue
        price = getattr(item, "price", None) or (
            item.get("price") if isinstance(item, dict) else None
        )
        parts.append(f"• {name}" + (f" — {price}" if price else ""))

    body = "\n".join(part for part in parts if part).strip()
    limit = int(settings.whatsapp_max_body_chars)
    if len(body) > limit:
        body = body[: limit - 1].rstrip() + "…"
    return body


_MONEY_RE = re.compile(r"(?<![*\w])(\$\d[\d,]*\.\d{2})(?![*\w])")
_ADDED_RE = re.compile(r"^(Added \d+ x )(?!\*)(.+?)( to your order\.)", re.M)
_PLACED_FOR_RE = re.compile(r"(placed for )([A-Z][a-z]{2} \d\d:\d\d)")
_LABEL_RE = re.compile(
    r"^(Total paid|Order reference|Subtotal|Pay here|Try again here|Delivery today|Pickup today):",
    re.M,
)


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
    out = _MONEY_RE.sub(r"*\1*", out)
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


def send_text(to: str, body: str) -> bool:
    """Send one message back. True if Meta accepted it.

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
                "type": "text",
                "text": {"preview_url": False, "body": format_for_whatsapp(body)},
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

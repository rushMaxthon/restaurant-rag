"""Replies that are instructions to us rather than questions for the assistant.

A thin seam between the two inbound paths — Meta's WhatsApp webhook and the
SMS gateway callback — and `optout.py`, which does the work. It exists for two
reasons that are both about failure.

**It opens its own session.** The WhatsApp webhook is not a database route: it
takes no `Depends(get_db)` because almost everything it receives is a delivery
receipt it ignores. Threading a session through it for the rare STOP would
change a hot, mostly-idle path for a rare one.

**It never raises.** Meta retries anything that is not a 200, so an exception
escaping here turns one customer's STOP into the same STOP arriving every few
minutes forever. A failure to record the opt-out is logged and swallowed; the
alternative is a retry storm that still does not opt them out.
"""

from __future__ import annotations

import logging

from app.config.database import SessionLocal
from app.services.marketing.optout import apply_reply

logger = logging.getLogger(__name__)


def handle_marketing_reply(phone_number: str, text: str, *, source: str) -> bool:
    """True when the message was a STOP or START and has been dealt with.

    True means the caller must not process the message any further — the
    person asked to be left alone, and handing the text to an assistant that
    replies conversationally would be exactly the wrong answer.
    """

    try:
        with SessionLocal() as db:
            result = apply_reply(db, phone_number=phone_number, text=text, source=source)
    except Exception:  # noqa: BLE001 - see the module docstring
        logger.exception("Marketing opt-out reply failed source=%s", source)
        # Reported as handled anyway. If this was a STOP we could not record,
        # passing it to the ordering assistant to answer chattily is worse
        # than silence, and the retry would not fix the database either.
        from app.services.marketing.optout import is_start_word, is_stop_word

        return is_stop_word(text) or is_start_word(text)

    return result is not None

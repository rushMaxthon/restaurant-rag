"""Does the unpaid-order loop still trap a customer? Sends nothing.

Runs the real task against a session belonging to a customer who really does
have a pile of unpaid orders, with `send_text` stubbed, and prints what each
turn would have replied. The loop looked like this in a live thread:

    Hii          -> Your order for Thu 12:42 comes to $20.62 ... keep it?
    Cancel it    -> Your order for Thu 13:19 comes to $20.62 ... cancel it?
    Yes cancel   -> Cancelled. Shall I put those dishes back?
    Hii          -> Your order for Thu 12:42 comes to $20.62 ... keep it?

A greeting should be answered as a greeting, and the unpaid order should be
mentioned at most twice however many of them there are.
"""

from __future__ import annotations

import sys
import uuid
from unittest import mock

sys.path.insert(0, "F:/restaurant-rag/backend")

from app.services.ordering_agent import order_draft, session_cart
from app.tasks import whatsapp as wa

#: The number from the live thread. Its customer holds the unpaid orders; the
#: session below is a throwaway, so the real conversation is left untouched.
NUMBER = "916353100362"

SCRIPT = ["Hii", "hello", "menus", "Hii", "hey", "hii"]


def main() -> int:
    session = uuid.uuid4()
    replies: list[str] = []

    with (
        mock.patch.object(wa, "send_text", lambda to, body: replies.append(body) or True),
        mock.patch.object(wa, "show_typing", lambda *a, **k: None),
        mock.patch.object(wa, "session_for", lambda _n: session),
    ):
        for index, message in enumerate(SCRIPT, 1):
            wa.answer_whatsapp_message(
                from_number=NUMBER, text=message, message_id=f"verify-{index}"
            )
            first = replies[-1].splitlines()[0]
            print(f"  {message!r:<9} -> {first[:88]}")

    notices = order_draft.waiting_notices(session)
    print(f"\nunpaid-order notices used: {notices}")

    greetings = [r for m, r in zip(SCRIPT, replies) if m.lower().startswith(("hi", "he"))]
    billed = [r for r in greetings if "waiting to be paid" in r]

    session_cart.clear(session)
    order_draft.clear(session)
    order_draft.cache_delete(order_draft._waiting_key(session))

    if billed:
        print(f"\n!! {len(billed)} greeting(s) were answered with a bill")
        return 1
    if notices > 2:
        print(f"\n!! the notice fired {notices} times; the cap is 2")
        return 1
    print("\nevery greeting was answered as a greeting, and the cap held")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Every fault we fixed, replayed against the live WhatsApp configuration.

Runs real conversations through the real path — `handle_chat_message`, the
ordering agent, qwen3:8b, the live rows — for whichever restaurant
`whatsapp_restaurant_id` points at, and checks each reply against what that
turn is supposed to do. Only Meta's send is stubbed; no message leaves the
machine and no order is placed.

Each case names the fault it guards. A PASS means that fault is gone from
this build against this data; it is not a claim about every sentence the
model can produce.
"""

from __future__ import annotations

import re
import sys
import time
import uuid
from unittest import mock

sys.path.insert(0, "F:/restaurant-rag/backend")

from sqlalchemy import func, select

from app.config.database import SessionLocal
from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.services.chat_principal import guest_principal_for_session
from app.services.ordering_agent import order_draft, session_cart
from app.services.rag import handle_chat_message
from app.tasks import whatsapp as wa

GREEN, RED, DIM, OFF = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


class Conversation:
    """One customer, one thread, answered the way the Celery task answers."""

    def __init__(self, db, restaurant, location):
        self.db, self.restaurant, self.location = db, restaurant, location
        self.session = uuid.uuid4()
        self.principal = guest_principal_for_session(self.session)
        self.app_client_id = wa._app_client_id_for(db, restaurant.id)

    def say(self, message: str) -> str:
        cart = session_cart.load(self.session)
        answer = handle_chat_message(
            self.db,
            user=self.principal,
            message=message,
            session_id=self.session,
            restaurant_id=self.restaurant.id,
            restaurant_location_id=self.location.id,
            cart=cart,
            verified_phone=wa.e164("919999000077"),
            app_client_id=self.app_client_id,
            auto_place=True,
        )
        updated, proposed = session_cart.apply_actions(cart, [
            a.model_dump(mode="json") if hasattr(a, "model_dump") else dict(a)
            for a in (answer.cart_actions or [])
        ])
        if updated != cart:
            session_cart.save(self.session, updated)
        return wa._compose_reply(answer, proposed, self.restaurant.currency) or ""

    def basket(self) -> int:
        return len(session_cart.load(self.session))

    def close(self) -> None:
        session_cart.clear(self.session)
        order_draft.clear(self.session)
        order_draft.cache_delete(order_draft._waiting_key(self.session))


def run_case(db, restaurant, location, title, fault, steps):
    """`steps` is (message, check, what the check means)."""

    chat = Conversation(db, restaurant, location)
    print(f"\n{DIM}{fault}{OFF}\n{title}")
    ok = True
    try:
        for message, check, meaning in steps:
            began = time.monotonic()
            reply = chat.say(message)
            took = time.monotonic() - began
            passed = check(reply, chat)
            ok = ok and passed
            mark = f"{GREEN}PASS{OFF}" if passed else f"{RED}FAIL{OFF}"
            print(f"  {mark} {message!r:<16} {took:4.1f}s  {meaning}")
            if not passed:
                for line in reply.splitlines()[:4]:
                    print(f"        {RED}{line}{OFF}")
    finally:
        chat.close()
    return ok


def main() -> int:
    with SessionLocal() as db:
        restaurant = db.get(Restaurant, wa._configured_restaurant_id())
        location = db.get(RestaurantLocation, wa._configured_location_id())
        if restaurant is None or location is None:
            print("WhatsApp is not pointed at a restaurant and branch.")
            return 1
        items = db.scalar(select(func.count(MenuItem.id)).where(
            MenuItem.restaurant_location_id == location.id,
            MenuItem.is_available.is_(True),
        ))
        print("=" * 76)
        print(f"live WhatsApp config: {restaurant.name} · {location.branch_name} "
              f"· {restaurant.currency} · {items} items")
        print("=" * 76)

        has = lambda *w: (lambda r, c: all(x.lower() in r.lower() for x in w))  # noqa: E731
        lacks = lambda *w: (lambda r, c: not any(x.lower() in r.lower() for x in w))  # noqa: E731
        both = lambda f, g: (lambda r, c: f(r, c) and g(r, c))  # noqa: E731

        cases = [
            (
                "a greeting is answered as a restaurant",
                "was: a search-tool description that never said which business it was",
                [
                    ("Hi", has(restaurant.name, "mood"), "names the restaurant, asks the mood"),
                    ("Hii", has(restaurant.name), "the stretched spelling is a greeting too"),
                    ("heyy", has("mood"), "and so is this one"),
                ],
            ),
            (
                "a short reply is a reply",
                'was: "I didn\'t quite catch that" on the second message',
                [
                    ("Please", lacks("didn't quite catch"), "not called gibberish"),
                    ("go on", lacks("didn't quite catch"), "nor is this"),
                ],
            ),
            (
                "a dish named from a list we showed is added",
                'was: "Hello, Money Bags!" — the dish became the customer\'s name',
                [
                    ("menus", has("which one"), "reads the menu out and asks"),
                    ("Money Bags", both(has("added"), lambda r, c: c.basket() == 1),
                     "the dish reaches the cart, once"),
                ],
            ),
            (
                "a position picks from the list",
                'was: "Your cart is currently empty" after six suggestions',
                [
                    ("what appetizers do you have", has("which one"), "shows a list"),
                    ("the first one", lambda r, c: c.basket() >= 1 or "which size" in r.lower(),
                     "resolves to a real dish"),
                ],
            ),
            (
                "a pronoun is not a dish",
                'was: a dish called "one", 33 seconds, then "your cart is empty"',
                [
                    ("do you have soup", has("which one"), "shows the soups"),
                    ("add one", lacks("cart is empty"), "asks which, rather than failing"),
                ],
            ),
            (
                "an empty cart is never called an order",
                'was: "you\'re ready to proceed. Let me check the details" with nothing in it',
                [
                    ("yes", lacks("ready to proceed", "finalize your order"),
                     "no order is claimed"),
                ],
            ),
            (
                "the menu is never denied while being shown",
                'was: "We don\'t have anything on the menu" above six real dishes',
                [
                    ("no", lacks("anything on the menu", "nothing on the menu"),
                     "no self-contradiction"),
                ],
            ),
            (
                "prices carry the restaurant's own symbol",
                "was: a bare 185.00, and $ on a rupee menu",
                [
                    ("show me the menu",
                     lambda r, c: not re.search(r"(?<![$\u20b9\u00a3\u20ac\d.])\d+\.\d{2}\b", r),
                     "every figure has a symbol"),
                ],
            ),
        ]

        results = [run_case(db, restaurant, location, t, f, s) for t, f, s in cases]

    print("\n" + "=" * 76)
    passed = sum(1 for r in results if r)
    print(f"{passed}/{len(results)} cases pass")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

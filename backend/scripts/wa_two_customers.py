"""Two customers on the same number at the same time. Nothing of one reaches
the other.

Every fix this week added memory — what was shown, what was asked, the cart,
the details, the unpaid-order budget — and shared memory is how a chat system
serves one person's food to another. This interleaves two conversations turn
by turn, the way two customers actually message a restaurant, and checks that
each one's answers are their own.

Sends nothing. Places nothing. The two numbers are throwaways.
"""

from __future__ import annotations

import sys
import uuid

sys.path.insert(0, "F:/restaurant-rag/backend")

from sqlalchemy import select

from app.config.database import SessionLocal
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.services.chat_principal import guest_principal_for_session
from app.services.ordering_agent import order_draft, session_cart
from app.services.rag import handle_chat_message
from app.tasks import whatsapp as wa

GREEN, RED, OFF = "\033[32m", "\033[31m", "\033[0m"


class Customer:
    def __init__(self, db, restaurant, location, number: str, label: str):
        self.db, self.restaurant, self.location = db, restaurant, location
        self.number, self.label = number, label
        # Exactly how the task derives it: one conversation per phone number.
        self.session = wa.session_for(number)
        self.principal = guest_principal_for_session(self.session)
        self.app_client_id = wa._app_client_id_for(db, restaurant.id)
        self.replies: list[str] = []

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
            verified_phone=wa.e164(self.number),
            app_client_id=self.app_client_id,
            auto_place=True,
        )
        updated, proposed = session_cart.apply_actions(cart, [
            a.model_dump(mode="json") if hasattr(a, "model_dump") else dict(a)
            for a in (answer.cart_actions or [])
        ])
        if updated != cart:
            session_cart.save(self.session, updated)
        reply = wa._compose_reply(answer, proposed, self.restaurant.currency) or ""
        self.replies.append(reply)
        print(f"  {self.label} >>> {message!r:<26} {reply.splitlines()[0][:66]}")
        return reply

    def cart_names(self) -> list[str]:
        from app.models.menu_item import MenuItem

        out = []
        for line in session_cart.load(self.session):
            item = self.db.get(MenuItem, line.menu_item_id)
            out.append(item.name if item else "?")
        return out

    def close(self) -> None:
        session_cart.clear(self.session)
        order_draft.clear(self.session)
        order_draft.cache_delete(order_draft._waiting_key(self.session))


def main() -> int:
    problems: list[str] = []
    with SessionLocal() as db:
        restaurant = db.get(Restaurant, wa._configured_restaurant_id())
        location = db.get(RestaurantLocation, wa._configured_location_id())
        print(f"{restaurant.name} · {location.branch_name}\n")

        a = Customer(db, restaurant, location, "919900000001", "A")
        b = Customer(db, restaurant, location, "919900000002", "B")
        try:
            # Different sessions, from different numbers. Anything else and
            # the rest of this proves nothing.
            if a.session == b.session:
                problems.append("both numbers resolved to ONE conversation")

            print("interleaved, the way two customers really arrive:")
            a.say("Hi")
            b.say("Hi")
            a.say("do you have soup")
            b.say("what appetizers do you have")

            # The dangerous one: "the first one" means each customer's OWN
            # last list. A shared `last_shown` would put B's appetizer into
            # A's soup order.
            a.say("the first one")
            b.say("the first one")

            a_cart, b_cart = a.cart_names(), b.cart_names()
            print(f"\n  A's cart: {a_cart}")
            print(f"  B's cart: {b_cart}")

            if a_cart and b_cart and set(a_cart) == set(b_cart):
                problems.append("both customers ended up with the same dish")
            if not a_cart and not b_cart:
                print("  (neither added anything — the sizes were asked for instead)")

            # Details belong to one person.
            a.say("Aarti")
            held_a = order_draft.load(a.session).contact_name
            held_b = order_draft.load(b.session).contact_name
            print(f"\n  A's name on file: {held_a!r}")
            print(f"  B's name on file: {held_b!r}")
            if held_b and held_b == held_a:
                problems.append("A's name reached B's order")

            # And nothing of A's is quoted back to B.
            for dish in a_cart:
                if any(dish in reply for reply in b.replies):
                    problems.append(f"A's dish {dish!r} appeared in B's replies")
        finally:
            a.close()
            b.close()

    print()
    if problems:
        for problem in problems:
            print(f"{RED}LEAK{OFF} {problem}")
        return 1
    print(f"{GREEN}No leakage: separate conversations, carts and details.{OFF}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

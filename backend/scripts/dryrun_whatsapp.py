"""Talk to the assistant the way a customer does, and print what comes back.

This is not a test. It runs the REAL path a WhatsApp message takes —
`handle_chat_message`, the ordering agent, the live qwen3:8b, the live
Supabase rows — and composes the reply with the same `_compose_reply` the
Celery task uses. The only things stubbed are the two that would reach Meta:
`send_text` and `show_typing`.

Usage:
    python scripts/dryrun_whatsapp.py <script-name> [--restaurant "Radhe Dhokla"]

Each script is a list of messages a person would actually send, including
the lazy, rude and ambiguous ones. What matters is not that the assistant
answers cleverly; it is that it never says something untrue, never loses the
thread, and never asks the same question twice.
"""

from __future__ import annotations

import argparse
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

#: Conversations to run. Keys are script names.
SCRIPTS: dict[str, list[str]] = {
    # The thread from the screenshots, exactly as it was typed.
    "transcript": [
        "Hi",
        "Please",
        "menus",
        "Bombay Bhel",
        "500 gm",
        "That's all",
    ],
    # The screenshot verbatim, for the Bangkok Bowl number it was sent to.
    "transcript-verbatim": [
        "Hi",
        "Please",
        "menus",
        "Money Bags",
        "That's all",
        "Money Bags",
    ],
    # Somebody who knows what they want and says so plainly.
    "direct": [
        "hi",
        "do you have biryani",
        "add one",
        "500 gm",
        "that's all",
    ],
    # The lazy, one-word answers most people actually send.
    "terse": [
        "hey",
        "food",
        "ok",
        "yes",
        "the first one",
        "no",
    ],
    # Somebody changing their mind, which is the normal case.
    "wavering": [
        "hello",
        "show me something spicy",
        "actually no",
        "what about rice",
        "add one of those",
        "cancel that",
    ],
    # The whole thing: browse, pick, size, details, and a closed kitchen.
    "full-order": [
        "Hi",
        "do you have soup",
        "Clear Tofu Soup",
        "that's all",
        "delivery",
        "Vishal, vishal@example.com, 42 Example Road Ahmedabad",
    ],
    # Questions that are not orders at all.
    "questions": [
        "what time do you open",
        "how much is the biryani",
        "do you deliver to vesu",
        "is anything vegetarian",
    ],
}


def resolve(db, restaurant_name: str | None):
    """The branch to answer for: the configured one, or a named restaurant's
    branch that actually has a menu."""

    if restaurant_name is None:
        rid, lid = wa._configured_restaurant_id(), wa._configured_location_id()
        restaurant = db.get(Restaurant, rid) if rid else None
        location = db.get(RestaurantLocation, lid) if lid else None
        return restaurant, location

    restaurant = db.scalar(select(Restaurant).where(Restaurant.name == restaurant_name))
    if restaurant is None:
        raise SystemExit(f"no restaurant called {restaurant_name!r}")
    # The branch with the most items: a branch with none can only ever answer
    # "nothing on the menu", which tells us about the data, not the code.
    counts = (
        select(MenuItem.restaurant_location_id, func.count(MenuItem.id).label("n"))
        .where(MenuItem.is_available.is_(True))
        .group_by(MenuItem.restaurant_location_id)
        .subquery()
    )
    location = db.scalar(
        select(RestaurantLocation)
        .join(counts, counts.c.restaurant_location_id == RestaurantLocation.id)
        .where(RestaurantLocation.restaurant_id == restaurant.id)
        .order_by(counts.c.n.desc())
        .limit(1)
    )
    return restaurant, location


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("script", choices=sorted(SCRIPTS))
    parser.add_argument("--restaurant", default=None)
    args = parser.parse_args()

    # Nothing leaves this machine.
    with mock.patch.object(wa, "send_text", lambda *a, **k: True), \
         mock.patch.object(wa, "show_typing", lambda *a, **k: None):
        return run(args.script, args.restaurant)


def run(script: str, restaurant_name: str | None) -> int:
    session_id = uuid.uuid4()
    principal = guest_principal_for_session(session_id)
    from_number = "919876500000"

    with SessionLocal() as db:
        restaurant, location = resolve(db, restaurant_name)
        if restaurant is None or location is None:
            print("no restaurant/branch configured")
            return 1
        items = db.scalar(
            select(func.count(MenuItem.id)).where(
                MenuItem.restaurant_location_id == location.id,
                MenuItem.is_available.is_(True),
            )
        )
        print("=" * 72)
        print(f"{restaurant.name} · {location.branch_name} · {restaurant.currency} · {items} items")
        print(f"script: {script}")
        print("=" * 72)

        app_client_id = wa._app_client_id_for(db, restaurant.id)

        for message in SCRIPTS[script]:
            cart = session_cart.load(session_id)
            began = time.monotonic()
            answer = handle_chat_message(
                db,
                user=principal,
                message=message,
                session_id=session_id,
                restaurant_id=restaurant.id,
                restaurant_location_id=location.id,
                cart=cart,
                verified_phone=wa.e164(from_number),
                app_client_id=app_client_id,
                auto_place=True,
            )
            took = time.monotonic() - began

            updated, proposed = session_cart.apply_actions(cart, [
                a.model_dump(mode="json") if hasattr(a, "model_dump") else dict(a)
                for a in (answer.cart_actions or [])
            ])
            if updated != cart:
                session_cart.save(session_id, updated)
            if answer.placed_order:
                session_cart.clear(session_id)

            body = wa._compose_reply(answer, proposed, restaurant.currency) or (
                "Sorry — I could not find anything for that. Try naming a dish or a craving?"
            )

            print(f"\n\033[1m>>> {message}\033[0m   ({took:.1f}s)")
            for line in body.splitlines():
                print(f"    {line}")
            basket = session_cart.load(session_id)
            if basket:
                print(f"    [cart: {len(basket)} line(s)]")

        draft = order_draft.load(session_id)
        held = draft.known_fields()
        print("\n" + "-" * 72)
        print(f"cart at the end : {len(session_cart.load(session_id))} line(s)")
        print(f"details held    : {held or 'none'}")
        print(f"still asking    : {draft.missing_fields()}")
        session_cart.clear(session_id)
        order_draft.clear(session_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

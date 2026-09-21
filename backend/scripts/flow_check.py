"""Put many different customers through the real chat, and show what they get.

`dryrun_whatsapp.py` replays ONE conversation and prints the replies. This runs
a whole cast of them in a single process and, for each turn, also prints WHICH
LAYER answered — because the replies alone hide the thing that matters.

A worked example of why. Replaying the reported thread, "Red curry tofu" came
back as a warm paragraph about a house favourite. It reads perfectly. Radhe
Dhokla does not sell it: the ordering agent had answered nothing
(`records=0 actions=0`) and retrieval had fuzzy-matched the name, so the
sentence was written about a dish that does not exist. Nothing in the reply
says so. The provenance line does.

So each turn prints:

    >>> what the customer typed                             (seconds)
        the reply they see
        [agent: ... | rag: source=... llm=...ms | cart: ...]

The provenance is read off the loggers the services already write to, rather
than by threading a debug flag through `handle_chat_message` — the point is to
run the untouched path, and a parameter that only a harness passes is a
parameter that changes what is being tested.

Usage:
    python scripts/flow_check.py --restaurant "Radhe Dhokla"
    python scripts/flow_check.py --restaurant "Radhe Dhokla" --only terse,typos
    python scripts/flow_check.py --list

Set PYTHONIOENCODING=utf-8 on Windows, or the greeting's emoji kills the run.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
import uuid
from unittest import mock

sys.path.insert(0, "F:/restaurant-rag/backend")
sys.path.insert(0, "F:/restaurant-rag/backend/scripts")

from sqlalchemy import func, select

from app.config.database import SessionLocal
from app.models.menu_item import MenuItem
from app.models.restaurant_location import RestaurantLocation
from app.services.chat_principal import guest_principal_for_session
from app.services.ordering_agent import order_draft, session_cart
from app.services.rag import handle_chat_message
from app.tasks import whatsapp as wa

from dryrun_whatsapp import resolve

#: The cast. Each entry is (what kind of person this is, what they send).
#:
#: These are not happy paths with the corners filed off. Real customers are
#: terse, misspell things, ask for dishes a restaurant does not sell, change
#: their mind halfway, and type in two languages at once — and every one of
#: those has to end somewhere sensible, not in a paragraph about a dish that
#: does not exist.
PERSONAS: dict[str, tuple[str, list[str]]] = {
    "decisive": (
        "Knows exactly what they want and says so in one line.",
        [
            "Hi, 2 khaman dhokla for delivery please",
            "Rakesh, rakesh@example.com, 9876543210",
            "12 Athwa Gate, Surat",
        ],
    ),
    "browser": (
        "No idea what they want. Wants to be shown around.",
        [
            "hello",
            "what do you recommend",
            "what else do you have",
            "ok the first one",
        ],
    ),
    "terse": (
        "Two words at a time, never a full sentence.",
        ["hi", "dhokla", "yes", "1", "pickup"],
    ),
    "chatty": (
        "Writes a paragraph where a word would do.",
        [
            "hey there! my sister is visiting from Mumbai this weekend and she "
            "keeps going on about how Surat does dhokla better than anywhere "
            "else, so I thought I'd finally order some properly",
            "she doesn't eat anything too spicy though, is that going to be a problem?",
            "lovely, let's do two of those then",
        ],
    ),
    "typos": (
        "Phone keyboard, no punctuation, everything misspelled.",
        ["helo", "do u hv dhokhla", "khamn dhokla", "hw much", "ya add it"],
    ),
    "not-on-menu": (
        "Asks for things this restaurant does not sell. Must never be "
        "answered with an invented description.",
        ["hi", "do you have pizza", "red curry tofu", "chicken biryani"],
    ),
    "price-conscious": (
        "Shopping on price, not on craving.",
        ["hi", "what's your cheapest item", "anything under 100", "ok add that"],
    ),
    "dietary": (
        "Has a constraint and needs a straight answer about it.",
        ["hi", "is everything vegetarian", "anything jain", "nothing too spicy please"],
    ),
    "changes-mind": (
        "Adds, removes and re-counts. The cart has to keep up.",
        [
            "hi",
            "add 2 khaman dhokla",
            "actually make it 3",
            "no wait, remove them",
            "what's in my cart",
        ],
    ),
    "declines": (
        "Answers the assistant's own questions with 'no'. The reported "
        "thread: 'No' to 'Anything else?' was read as the name of a dish.",
        ["hi", "khaman dhokla", "yes", "No"],
    ),
    "questions-only": (
        "Never orders. Wants facts, and wrong facts here cost a customer.",
        [
            "what time do you close",
            "do you deliver to vesu",
            "do you take cash",
            "how long does delivery take",
        ],
    ),
    "impatient": (
        "Short-tempered. Being handled badly here is how a review gets written.",
        ["hello?", "is anyone there", "i just want to order dhokla", "how long"],
    ),
    "hinglish": (
        "Surat. Half the messages arrive like this.",
        ["bhai dhokla hai kya", "kitne ka hai", "haan ek pack bhej do", "ghar pe delivery"],
    ),
    "interrupts": (
        "Abandons a half-finished order to ask something unrelated, then "
        "comes back. The thread has to survive it.",
        [
            "hi",
            "add one khaman dhokla",
            "wait, what time do you close",
            "ok and do you deliver to adajan",
            "right, carry on with the order",
        ],
    ),
}

#: What the services log per turn, and what it tells us.
AGENT_LINE = re.compile(
    r"Ordering agent turn fallback_reason=(?P<reason>\S+) records=(?P<records>\d+) "
    r"actions=(?P<actions>\d+) elapsed=(?P<elapsed>\S+)"
)
TIMINGS_LINE = re.compile(r"RAG timings .*? total=(?P<total>\S+) ", re.S)
SOURCE_LINE = re.compile(r"source=(?P<source>\S+) intent=(?P<intent>\S+)")
LLM_LINE = re.compile(r" llm=(?P<llm>\S+?)ms")
RETRIEVAL_LINE = re.compile(r"retrieval_source.: .(?P<retrieval>[a-z_]+)")


class TurnLog(logging.Handler):
    """Collects this turn's service logs, so provenance is read not guessed."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(("app.services.rag", "app.services.ordering_agent")):
            try:
                self.lines.append(record.getMessage())
            except Exception:  # a broken log line must not break the harness
                pass

    def provenance(self) -> str:
        """One line saying who actually answered, and how hard it worked."""

        text = "\n".join(self.lines)
        parts: list[str] = []

        agent = AGENT_LINE.search(text)
        if agent is None:
            parts.append("agent: did not run")
        elif agent["records"] == "0" and agent["actions"] == "0":
            # The interesting case. The agent ran, decided nothing, and the
            # customer was answered by retrieval — which is where an invented
            # dish description comes from.
            parts.append(f"agent: nothing ({agent['elapsed']})")
        else:
            parts.append(
                f"agent: records={agent['records']} actions={agent['actions']} "
                f"({agent['elapsed']})"
            )
            if agent["reason"] != "None":
                parts[-1] += f" fallback={agent['reason']}"

        source = SOURCE_LINE.search(text)
        llm = LLM_LINE.search(text)
        if source is not None:
            rag = f"rag: {source['source']}/{source['intent']}"
            if llm is not None:
                # llm=0.00ms means the model was never asked, so whatever the
                # customer read was assembled deterministically.
                rag += f" llm={llm['llm']}ms"
            parts.append(rag)
        retrieval = RETRIEVAL_LINE.search(text)
        if retrieval is not None:
            parts.append(f"via={retrieval['retrieval']}")

        return " | ".join(parts)


def run_persona(db, restaurant, location, app_client_id, name: str, messages: list[str]) -> None:
    note, _ = PERSONAS[name][0], None
    session_id = uuid.uuid4()
    principal = guest_principal_for_session(session_id)
    from_number = "919876500000"

    print("\n" + "=" * 78)
    print(f"[{name}]  {PERSONAS[name][0]}")
    print("=" * 78)

    handler = TurnLog()
    root = logging.getLogger()
    root.addHandler(handler)
    previous_level = root.level
    root.setLevel(logging.INFO)
    try:
        for message in messages:
            handler.lines.clear()
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

            updated, proposed = session_cart.apply_actions(
                cart,
                [
                    a.model_dump(mode="json") if hasattr(a, "model_dump") else dict(a)
                    for a in (answer.cart_actions or [])
                ],
            )
            if updated != cart:
                session_cart.save(session_id, updated)
            if answer.placed_order:
                session_cart.clear(session_id)

            body = wa._compose_reply(answer, proposed, restaurant.currency) or (
                "(nothing — the customer would see the generic apology)"
            )

            print(f"\n>>> {message}   ({took:.1f}s)")
            for line in body.splitlines():
                print(f"    {line}")
            basket = session_cart.load(session_id)
            provenance = handler.provenance()
            if basket:
                provenance += f" | cart={len(basket)} line(s)"
            print(f"    \033[2m[{provenance}]\033[0m")
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)

    draft = order_draft.load(session_id)
    print(
        f"\n    ends with: cart={len(session_cart.load(session_id))} line(s), "
        f"held={draft.known_fields() or 'none'}, asking={draft.missing_fields()}"
    )
    session_cart.clear(session_id)
    order_draft.clear(session_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--restaurant", default="Radhe Dhokla")
    parser.add_argument("--only", default=None, help="comma-separated persona names")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list:
        for name, (note, messages) in PERSONAS.items():
            print(f"{name:16} {len(messages)} turns  — {note}")
        return 0

    wanted = [n.strip() for n in args.only.split(",")] if args.only else list(PERSONAS)
    unknown = [n for n in wanted if n not in PERSONAS]
    if unknown:
        raise SystemExit(f"no such persona: {', '.join(unknown)}")

    # Quiet everything that is not a service decision, or the provenance is
    # buried under Redis hits and httpx lines.
    logging.basicConfig(level=logging.WARNING, format="%(message)s", force=True)
    for noisy in ("httpx", "app.services.cache", "sqlalchemy"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # The console stays at WARNING while the ROOT logger drops to INFO for the
    # duration of a turn, so the service decisions reach `TurnLog` and nothing
    # else. Raising the root level alone prints every one of them twice over.
    for existing in logging.getLogger().handlers:
        existing.setLevel(logging.WARNING)

    with mock.patch.object(wa, "send_text", lambda *a, **k: True), mock.patch.object(
        wa, "show_typing", lambda *a, **k: None
    ):
        with SessionLocal() as db:
            restaurant, location = resolve(db, args.restaurant)
            if restaurant is None or location is None:
                print("no restaurant/branch configured")
                return 1
            items = db.scalar(
                select(func.count(MenuItem.id)).where(
                    MenuItem.restaurant_location_id == location.id,
                    MenuItem.is_available.is_(True),
                )
            )
            print("=" * 78)
            print(
                f"{restaurant.name} · {location.branch_name} · {restaurant.currency} "
                f"· {items} items · {len(wanted)} personas"
            )
            print("=" * 78)
            app_client_id = wa._app_client_id_for(db, restaurant.id)
            for name in wanted:
                run_persona(db, restaurant, location, app_client_id, name, PERSONAS[name][1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

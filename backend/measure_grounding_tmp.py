"""Measure how often the concierge names food that its own context never supplied.

The selling prompt tells the model to offer a pairing "when the context contains
something that naturally goes with the pick". It offers one either way, and
borrows the detail from another dish — "with the spicy chutney" on a dish that
has no chutney. Every word is a real menu word attached to the wrong dish, so
nothing reads as invented.

This scores replies with the detector already in the codebase: a term that
appears in the menu corpus but nowhere in THIS request's context was recalled,
not retrieved.
"""

import json
import urllib.request

from app.config.database import SessionLocal
from app.services.rag import _menu_vocabulary, ungrounded_menu_terms

QUESTIONS = [
    "something spicy and vegetarian",
    "i want momos",
    "what biryani do you have",
    "something light for lunch",
    "recommend a pizza",
    "i feel like noodles",
    "something sweet",
    "what's good for two people",
]


def ask(message: str) -> dict:
    request = urllib.request.Request(
        "http://127.0.0.1:8000/api/chat/message",
        data=json.dumps({"message": message}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=240) as response:
        return json.load(response)


db = SessionLocal()
vocabulary = _menu_vocabulary(db)

leaked = 0
for question in QUESTIONS:
    data = ask(question)
    reply = data["reply"]
    # The cards the customer can see ARE the context they were offered from.
    context = "\n".join(
        f"{s['name']} {s.get('description') or ''} {s.get('category') or ''}" for s in data["suggestions"]
    )
    ungrounded = ungrounded_menu_terms(reply, context, vocabulary)
    if ungrounded:
        leaked += 1
    print(f"\nQ: {question!r}")
    print(f"  reply: {reply[:150]}")
    print(f"  cards: {[s['name'] for s in data['suggestions']][:3]}")
    print(f"  UNGROUNDED: {sorted(ungrounded) if ungrounded else 'none'}")

print(f"\n{leaked}/{len(QUESTIONS)} replies named food their own context never supplied")

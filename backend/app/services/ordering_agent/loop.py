"""Task 5: the bounded loop that turns `planner.plan_step` into a turn.

`plan_step` only ever decides ONE next step (its own docstring says so);
this module is what calls it again and again, feeding each round's
`ToolCallRecord` back in as history, until it answers, refuses in a way that
cannot be recovered from this turn, or runs out of rounds or time. Sibling
of `insights/tool_chat.py`'s owner-facing loop in spirit, but genuinely
bounded on two axes at once (`ordering_agent_max_tool_rounds`,
`ordering_agent_budget_seconds`) rather than one, because a customer is
watching a chat window, not reading a nightly briefing — a turn that runs
long must fail predictably, not eventually.

Every id-bearing decision (which ids the model may use, whether the
browser's cart overrides what it wrote, whether a mutation's result is
allowed to claim it was applied) is `guards.py`'s job, not this module's —
this loop only sequences: plan, guard, run, record, repeat.

Task 6 (not this task) decides what "today's reply" is when
`TurnOutcome.fallback_reason` is set; this module never invents a customer-
facing sentence of its own to paper over one.
"""

from __future__ import annotations

from contextvars import ContextVar

import re
import json
import uuid
from datetime import datetime
from decimal import Decimal

import logging
import time
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.schemas.suggestions import CartLinePayload
from app.services import restaurant_locations as branch_hours
from app.services.currency import format_amount, format_rounded_amount
from app.models.order import Order
from app.services.ordering_agent import guards, open_orders, order_draft
from app.services.ordering_agent import tools as tools_module
from app.services.ordering_agent.planner import (
    default_generate,
    extract_cart_request,
    question_asked_in,
    quick_read,
    read_order_intent,
    Generate,
    PlanStep,
    ToolCallRecord,
    plan_step,
    validate_call,
)
from app.services.ordering_agent.tools import TOOLS, CartLineArgs, OrderingScope, ViewCartArgs

settings = get_settings()
logger = logging.getLogger(__name__)

Clock = Callable[[], float]


@dataclass(slots=True)
class TurnOutcome:
    """What one `run_turn` call produced, and how it ended.

    `answer`/`fallback_reason` are the two ways a turn can end, but not a
    strict either/or the way `PlanStep`'s fields are: a turn that hits
    `round_cap` or `budget_exceeded` still reports `fallback_reason` with
    `answer=None` — never a half-finished sentence, per the brief's "never a
    partial answer" rule. `actions`/`records` are populated regardless of
    how the turn ended, because a mutation already applied earlier in the
    same turn is real even if a later round timed out, and the caller logs
    every attempted call either way.
    """

    answer: str | None
    actions: list[dict[str, Any]]
    records: list[ToolCallRecord]
    fallback_reason: str | None
    elapsed_seconds: float
    # The order this turn created, if any: id, total and the link to pay it.
    # Carried rather than spoken — see `describe_placed_order`.
    placed_order: dict[str, Any] | None = None
    # True when everything needed is held and the customer has only to
    # say go. The client turns this into a button; see the module note
    # on why it is not left to the model.
    ready_to_place: bool = False
    # What the model said its answer was about ("cart", "menu", "other").
    # The caller routes on it: a reply pipeline with no cart must never be
    # the one answering a question about the cart.
    answer_about: str = "other"


# What the restaurant this conversation belongs to charges in.
#
# A ContextVar for the same reason the AI Manager's narration uses one:
# `_money` is called from a dozen sentence builders and from closures inside
# `run_turn`, none of which has a restaurant to hand, and the currency is a
# property of the conversation rather than of each figure in it.
#
# Until this existed every chat wrote "$". Live, on a +91 number: a menu was
# read out as "Money Bags - $9.49" for a kitchen that charges rupees — the
# right number under the wrong symbol, which reads as a real price a customer
# could agree to.
#
# Bound once at the top of `run_turn` and never reset: a request runs in its
# own context (a sync endpoint's threadpool call gets a copy) and so does a
# Celery task, so a binding cannot outlive the turn that made it or reach
# another restaurant's.
_chat_currency: ContextVar[str | None] = ContextVar("chat_currency", default=None)


def bind_chat_currency(code: str | None) -> None:
    """Write every price from here on in this currency."""

    _chat_currency.set(code)


#: How many dishes are read out at once. A chat message nobody scrolls is
#: worth less than a short list and an offer to narrow it down.
_DISHES_READ_OUT = 8


def _budget(value: Any) -> str:
    """A figure the customer named, written the way they said it.

    "under $20", not "under $20.00": they spoke a round number and hearing it
    read back with cents attached reads as a correction. `format_rounded_amount`
    exists for exactly this distinction — prose and ledgers have different
    readers — and prices elsewhere in the reply keep every cent.
    """

    try:
        return format_rounded_amount(float(value), _chat_currency.get())
    except (TypeError, ValueError):
        return str(value)


def _money(value: Any) -> str:
    try:
        return format_amount(float(value), _chat_currency.get())
    except (TypeError, ValueError):
        return str(value)


def _option_line(name: str, price: Any = None, extra: Any = None) -> str:
    """One option on its own line, with a figure only when there is one.

    A free option marked "(+$0.00)" reads as a charge, and eleven options run
    together in a paragraph read as none at all.
    """

    if price is not None:
        return f"- {name} \u2014 {_money(price)}"
    try:
        if extra is not None and float(extra) > 0:
            return f"- {name} (+{_money(extra)})"
    except (TypeError, ValueError):
        pass
    return f"- {name}"


def ask_for_choice(result: Any) -> str | None:
    """The next single question a `needs_choice` result asks, as prose.

    A dish that needs a size or a required group is the one case where the
    deterministic layer holds the complete answer — the dish, its sizes, its
    groups, their options and every price came from the tool's rows — and on
    the first live turn the model still spent four rounds on it and said
    nothing. So the loop asks the question itself, from those rows and nothing
    else: the house rule's template fallback, applied to the one outcome that
    has a fixed shape.

    **One thing at a time.** This used to compose a part for the size and a
    part for every outstanding group and join them, which produced, live:

        Crust for Build Your Own Pizza: Thin crust, Classic hand tossed,
        Cheese burst (+$4.00), Stuffed garlic crust (+$4.50). Sauce for Build
        Your Own Pizza: Tomato, Green curry (+$1.00), Tom yum cream (+$1.50),
        Garlic butter. Which would you like?

    Two questions, eleven options and four prices in one paragraph, closing on
    a "Which would you like?" that could mean either. Nobody orders like that,
    and nothing downstream could read the answer either.

    The size goes first, and not merely for tidiness: Crust is size-scoped on
    this menu — three separate groups, one per size, with different options at
    different prices — so a crust chosen before a size is an answer that
    cannot be used.

    Returns None for anything that is not a needs_choice, and None once
    nothing is outstanding.
    """

    if not isinstance(result, dict) or result.get("outcome") != "needs_choice":
        return None
    name = result.get("name") or "that dish"

    sizes = result.get("available_sizes") or []
    if result.get("needs_size") and sizes:
        listed = "\n".join(
            _option_line(str(size.get("name")), price=size.get("price")) for size in sizes
        )
        return f"Which size for {name}?\n{listed}"

    for group in result.get("customization_groups") or []:
        if not group.get("needs_selection"):
            continue
        # What they have already chosen is credited, and only what is left is
        # offered. Live: a group wanting three answered the first correct
        # pick with the identical question — the same list, the same count,
        # no sign anybody had heard.
        already = {str(o) for o in (group.get("selected_option_ids") or [])}
        chosen_names, lines = [], []
        for option in group.get("options") or []:
            if str(option.get("option_id")) in already:
                chosen_names.append(str(option.get("name")))
            else:
                lines.append(
                    _option_line(str(option.get("name")), extra=option.get("extra_price"))
                )
        if not lines:
            continue

        title = group.get("title") or "Choose"
        try:
            most = int(group.get("max_selection") or 1)
        except (TypeError, ValueError):
            most = 1
        try:
            still = max(1, int(group.get("min_selection") or 1) - len(already))
        except (TypeError, ValueError):
            still = 1

        # Always a question, and always the shape of the size question above
        # it. "Crust for Build Your Own Pizza:" is a heading; a customer
        # answers a question.
        head = f"Which {title.lower()} for {name}?"
        if chosen_names:
            head += f" You have {', '.join(chosen_names)} \u2014 pick {still} more."
        elif still > 1:
            head += f" Pick {still}."
        elif most > 1:
            # Nobody picks two of something they were not told they could have
            # two of. This menu's Toppings group takes seven, and was selling
            # them one at a time.
            head += " You can choose more than one."
        return head + "\n" + "\n".join(lines)

    return None


#: The question the menu offer ends on, as the MODEL should see it next turn.
#: The customer gets the whole list of sections; handing that list to the model
#: as "the question" is the shape `_hold` keeps a short question for.
_WHICH_SECTION = "Which of those would you like to see?"

#: The question a finished read-back ends on. Named because two places have to
#: agree on it exactly: `describe_cart` writes it, and the give-up path records
#: it as the question being waited on — and records it ONLY when the read-back
#: actually asked it, since a cart with an unchosen size ends on a different
#: sentence and must not be told it is ready.
_READY_TO_CHECK_OUT = "Ready to check out?"


def storable_group(group: Any) -> dict[str, Any]:
    """One customization group, in a form that survives `json.dumps`.

    The live rows carry UUIDs and Decimals and the pending choice is stored as
    JSON, so writing a group through unchanged raised

        TypeError: Object of type UUID is not JSON serializable

    on every turn that asked for a size. Caught by driving a real order, not by
    the suite, whose fixtures use strings for ids. Every field is named and
    coerced rather than leaning on a default encoder, so the stored shape is
    the one the readers below expect.
    """

    if not isinstance(group, dict):
        return {}
    return {
        "group_id": str(group.get("group_id") or ""),
        "title": str(group.get("title") or ""),
        "is_required": bool(group.get("is_required")),
        "min_selection": int(group.get("min_selection") or 0),
        "max_selection": int(group.get("max_selection") or 1),
        "options": [
            {
                "option_id": str(option.get("option_id")),
                "name": str(option.get("name")),
                "extra_price": str(option.get("extra_price") or "0"),
            }
            for option in (group.get("options") or [])
            if isinstance(option, dict) and option.get("option_id") and option.get("name")
        ],
    }


def _words_of(text: str) -> list[str]:
    """A message reduced to its words, for matching option names against."""

    lowered = (text or "").lower().replace("'", "").replace("\u2019", "")
    return [word for word in re.split(r"[^a-z0-9]+", lowered) if word]


def options_named_in(message: str, asked: Any) -> list[str]:
    """Which of the offered options this message names, in the order offered.

    Decided here rather than taken from the reading, because the reading is a
    model and does not agree with itself. Measured, with the toppings question
    standing: "Mozzarella" came back as `chose: ["Mozzarella"]` on one run and
    "Mozzarella and mushroom" as `add: [("Mozzarella and mushroom", 1)]` on the
    next — one dish, by that name, which does not exist. Meanwhile "no" read as
    `confirms: False`, and "none" and "skip" set nothing at all.

    Whole words only. A name found inside a longer word would let a refusal buy
    a topping — "tofurkey" is not an order of Tofu.

    Returning names rather than ids keeps this the same currency
    `_answer_choice` already matches in.
    """

    if not isinstance(asked, dict):
        return []
    words = _words_of(message)
    if not words:
        return []
    said = " ".join(words)
    named: list[str] = []
    for option in asked.get("options") or []:
        if not isinstance(option, dict) or not option.get("name"):
            continue
        name = str(option["name"])
        wanted = " ".join(_words_of(name))
        if not wanted or name in named:
            continue
        # Word-boundary containment: the option's words, in order, somewhere in
        # the message. " x " padding makes the boundaries explicit without a
        # regular expression per option.
        if f" {wanted} " in f" {said} ":
            named.append(name)
    return named


def cart_lines_named_in(message: str, lines: Any) -> list[dict[str, Any]]:
    """Which lines of this cart the message names, in the order they sit in it.

    Matched on the cart's OWN rows rather than on the reading, because the
    reading has no way to say "take one line out": "remove the khaman", "take
    it off" and "delete the dhokla" all come back as `cancel_order`, and
    nothing in that says which line.

    Whole words, for the same reason everywhere else does it — "remove the
    soupçon" must not take somebody's soup off the order.
    """

    if not lines:
        return []
    words = _words_of(message)
    if not words:
        return []
    said = f" {' '.join(words)} "
    named: list[dict[str, Any]] = []
    for line in lines:
        if not isinstance(line, dict) or not line.get("name"):
            continue
        for word in _words_of(str(line["name"])):
            if len(word) > 2 and f" {word} " in said:
                named.append(line)
                break
    return named


def line_to_remove(message: str, lines: Any) -> dict[str, Any] | None:
    """The one line to take off, or None when that is a question.

    Removing is destructive, so this follows the rule the rest of the cart
    tools follow: act where there is one obvious answer, ask where there is
    not. One line named is obvious. A cart holding one thing is obvious —
    "take it off" can only mean that. Anything else is a guess that throws
    away something somebody chose, so it returns None and the caller asks.
    """

    named = cart_lines_named_in(message, lines)
    if len(named) == 1:
        return named[0]
    if not named and lines and len(lines) == 1:
        only = lines[0]
        return only if isinstance(only, dict) else None
    return None


def next_optional_group(asked: Any, args: Any) -> dict[str, Any] | None:
    """The optional group worth offering before this dish lands, if any.

    Bangkok Bowl's Build Your Own Pizza has a Toppings group — MULTI, seven of
    them — that no customer has ever been shown. That is correct one layer
    down: an optional group is never "unmet", because its default IS the empty
    selection, so it does not block. The consequence is that `add_to_cart`
    applies the instant the required things are settled and the pizza is in the
    cart before anything could ask.

    So the last required answer checks here first. Nothing is offered until
    every required thing IS settled — asking about toppings before the sauce is
    a waiter interrupting himself — and a group carrying no options is not a
    question, so it is passed over rather than asked emptily.

    Answered from what `_remember_choice` wrote down, so it costs no query.
    """

    if not isinstance(asked, dict) or not isinstance(args, dict):
        return None
    later = [g for g in (asked.get("later") or []) if isinstance(g, dict)]
    if not later:
        return None

    if asked.get("needs_size") and not args.get("menu_item_size_id"):
        return None
    chosen = {
        str(option.get("option_id"))
        for option in (args.get("selected_options") or [])
        if isinstance(option, dict) and option.get("option_id")
    }
    for required in asked.get("required") or []:
        if not chosen.intersection(str(o) for o in (required or [])):
            return None

    for group in later:
        if group.get("options"):
            return group
    return None


def reask_standing_choice(standing: Any) -> str | None:
    """Put a standing question again, with its answers spelled out.

    Shared by the two places that need it. The re-ask path uses it when a
    message answered nothing; the dish lookup uses it when a message DID look
    like something — a dish to add — but only as a guess.

    That second case is why this is a function. Mid-build, with the crust
    question standing:

        > Mozzarella and mushroom
          Did you mean Farmhouse Pizza?

    Safe, and the wrong thing to say: the customer was naming toppings, and
    the reply abandoned the crust question to offer an unrelated pizza. A
    guess is not a reason to change the subject.

    None when there is nothing to put again — a question with no answers
    listed is not worth repeating, and repeating it is how a customer ends up
    reading the same sentence twice.
    """

    if not isinstance(standing, dict):
        return None
    options = ", ".join(
        str(option.get("name"))
        for option in (standing.get("options") or [])
        if isinstance(option, dict) and option.get("name")
    )
    if not options:
        return None
    question = str(standing.get("question") or "").rstrip()
    lead = f"Sorry, I did not catch that. {question}".rstrip()
    if "\n- " in question:
        # The question already lays its own options out, one per line, so
        # spelling them out again said everything twice and ran the tail onto
        # the last bullet: "- Thin crust Just reply with one of these: Classic
        # hand tossed, Cheese burst, ...".
        return lead
    return f"{lead} Just reply with one of these: {options}."


def chosen_options_in(line: Any) -> list[str]:
    """What the customer picked on this cart line, group by group.

    `view_cart` has carried this all along — every line holds its groups, each
    with `selected_option_ids` and the options' names — and the read-back used
    the size and dropped the rest, so a built pizza came back as

        - 1 x Build Your Own Pizza (Large (14")) - $25.49

    with the crust and the sauce nowhere in it, and the extra dollar in the
    price unexplained.

    Groups are named: "Green curry, Thin crust" is a list of words, and
    "Sauce: Green curry" is an order. An id matching no option is dropped
    rather than guessed at — this sentence is what somebody checks before
    paying, so a name it cannot prove has no business in it.
    """

    if not isinstance(line, dict):
        return []
    said: list[str] = []
    for group in line.get("customization_groups") or []:
        if not isinstance(group, dict):
            continue
        chosen = {str(o) for o in (group.get("selected_option_ids") or [])}
        if not chosen:
            continue
        names = [
            str(option.get("name"))
            for option in (group.get("options") or [])
            if isinstance(option, dict)
            and str(option.get("option_id")) in chosen
            and option.get("name")
        ]
        if not names:
            continue
        title = str(group.get("title") or "").strip()
        said.append(f"{title}: {', '.join(names)}" if title else ", ".join(names))
    return said


def describe_single_dish(dish: dict[str, Any]) -> str:
    """One dish read back, with an offer to add it.

    A dish sold in sizes has no single price to quote. This used to take
    `price` off the row and say it:

        > Build Your Own Pizza
          Build Your Own Pizza is $14.99. Shall I add one?

    $14.99 is the Small of three; the Large is $24.49. A quote the customer
    can say yes to and then be charged something else for is the same fault
    that put a Large in a cart at the base price.

    So a sized dish is named and offered without a figure, and the size
    question that follows carries every price. `has_sizes` is a column on
    `menu_items`, so the row being read out already knows.
    """

    name = dish.get("name") or "that dish"
    if dish.get("has_sizes"):
        return f"{name} comes in a few sizes. Shall I set one up?"
    return f"{name} is {_money(dish.get('price'))}. Shall I add one?"


def would_be_added_without_asking(lookup: Any) -> bool:
    """Whether adding this dish would put it in the cart with no further word.

    A dish that still needs a size or a required choice answers with "Which
    size for Vagharela Khaman?", which names the dish as plainly as any
    confirmation and lets the customer correct it before a penny is committed.
    A dish with nothing left to ask just lands.

    That is the difference between the two ways a name can be a guess. Live:

        > Mozzarella and mushroom
          Added 1 x Farmhouse Pizza to your order. Anything else?

    — a customer naming toppings, and a $329 pizza in the cart with nothing
    asked. Whereas "khaman dhokla" is also a guess (Radhe Dhokla sells
    Vagharela Khaman, and no dish name contains both words) and needs no
    second question, because the size question carries the dish's name.

    An optional group is not a question: it does not block an add, so it is
    not something the customer is about to be asked. Nothing readable counts
    as "would land", which is the cautious way round — confirm rather than
    spend.
    """

    if not isinstance(lookup, dict):
        return True
    # Two shapes reach this. `add_to_cart`'s needs_choice result says
    # `available_sizes` and marks a group `needs_selection`; `get_dish`'s
    # catalog result says `sizes`/`has_sizes` and describes a group by
    # `is_required`. Reading only the first was the bug in the first version
    # of this: `available_sizes` is absent from a `get_dish` result, so every
    # sized dish looked like one that would land silently, and "khaman dhokla"
    # started asking "Did you mean Vagharela Khaman?" instead of its size.
    if lookup.get("available_sizes") or lookup.get("sizes") or lookup.get("has_sizes"):
        return False
    for group in lookup.get("customization_groups") or []:
        if not isinstance(group, dict):
            continue
        if group.get("needs_selection") or group.get("is_required"):
            return False
    return True


def describe_cart(result: Any) -> str | None:
    """A `view_cart` result read back as a sentence, or None.

    Every figure comes from the tool's own rows: the client renders the cart
    itself, so this is only what the customer hears, and it must not disagree
    with the screen.
    """

    if not isinstance(result, dict) or "lines" not in result or "subtotal" not in result:
        return None
    lines = result.get("lines") or []
    if not lines:
        return "Your cart is empty at the moment."
    parts = []
    for line in lines:
        name = line.get("name") or "a dish"
        size = line.get("size_name")
        quantity = line.get("quantity") or 1
        total = line.get("total_price")
        label = f"{name} ({size})" if size else name
        said_line = f"- {quantity} x {label} - {_money(total)}"
        # What they picked, under the line it belongs to. A built pizza used
        # to read "(Large (14")) - $25.49" with the crust and the sauce
        # nowhere in it, and the extra dollar in the price unexplained.
        picked = chosen_options_in(line)
        if picked:
            said_line += "\n  " + "; ".join(picked)
        parts.append(said_line)
    # One line per dish. As a single sentence — "1 x Margherita Pizza -
    # $249.00; 2 x Corn Fritters - $16.98" — a cart was hard to read on a
    # phone and harder to trust with money. Plain dashes, so the web reads
    # it too; the phone turns them into bullets on the way out.
    said = "\n" + "\n".join(parts) + "\n"
    subtotal = _money(result.get("subtotal"))
    tail = f" {_READY_TO_CHECK_OUT}"
    if result.get("needs_choice"):
        # A line still missing a size or a required choice cannot be priced
        # honestly, so the subtotal is not the whole story and saying "ready
        # to check out" would be.
        tail = " One of those still needs a choice before it can be ordered."
    return f"Your cart:{said}Subtotal: {subtotal}.{tail}"


def describe_order_to_confirm(
    result: Any, draft: Any = None, quote: Any = None
) -> str | None:
    """The whole order read back, for a customer to stand behind before it goes.

    Every line, the total, where it is going and when — from the cart's own
    rows and the draft's own fields, so what they agree to is what will be
    charged. A real restaurant repeats the order back; this agent said "that
    is everything I need" and created it, and the first sight a customer got
    of what they had agreed to was Stripe's payment page.
    """

    if not isinstance(result, dict):
        return None
    lines = result.get("lines") or []
    if not lines or result.get("needs_choice"):
        # A line still missing a required choice cannot be priced honestly,
        # and an order nobody can total is not one to stand behind.
        return None
    said = []
    for line in lines:
        name = line.get("name") or "a dish"
        size = line.get("size_name")
        label = f"{name} ({size})" if size else name
        confirmed = f"- {line.get('quantity') or 1} x {label} - {_money(line.get('total_price'))}"
        # The same picks as the cart read-back, and for a stronger reason:
        # this is the last thing said before money is asked for, so it has to
        # be the whole of what they are agreeing to.
        picked = chosen_options_in(line)
        if picked:
            confirmed += "\n  " + "; ".join(picked)
        said.append(confirmed)
    # Their name at the moment it means most: the last thing said before
    # money is asked for.
    called = order_draft.first_name(getattr(draft, "contact_name", None)) if draft is not None else None
    parts = [f"Here is your order, {called}:" if called else "Here is your order:", "\n".join(said)]

    # The total is the one checkout will charge, from the same arithmetic —
    # never the cart's subtotal. Live: a customer agreed to $16.98 and the
    # order was placed for $20.62, the delivery fee and the tax having been
    # added where they could not see them.
    priced = quote if isinstance(quote, dict) and quote.get("priced") else None
    if priced:
        figures = [f"Subtotal: {_money(priced.get('subtotal'))}."]
        for label, key in (
            ("Delivery", "delivery_fee"),
            ("Tax", "tax_amount"),
        ):
            try:
                if float(priced.get(key) or 0) > 0:
                    figures.append(f"{label}: {_money(priced.get(key))}.")
            except (TypeError, ValueError):
                pass
        try:
            if float(priced.get("discount_amount") or 0) > 0:
                figures.append(f"Discount: -{_money(priced.get('discount_amount'))}.")
        except (TypeError, ValueError):
            pass
        figures.append(f"Total: {_money(priced.get('total_amount'))}.")
        parts.append("\n".join(figures))
    else:
        # No quote, so the only honest figure is the one the cart knows and
        # it is named for what it is.
        parts.append(f"Subtotal: {_money(result.get('subtotal'))}.")

    where = None
    if draft is not None:
        if (getattr(draft, "fulfillment_type", None) or "") == "DELIVERY":
            address = getattr(draft, "delivery_address", None)
            where = f"Delivery to {address}." if address else "For delivery."
        elif (getattr(draft, "fulfillment_type", None) or "") == "PICKUP":
            where = "For pickup."
        when = _clock(getattr(draft, "scheduled_at", None))
        if when:
            where = f"{where} For {when}." if where else f"For {when}."
    if where:
        parts.append(where)
    parts.append("Shall I place it?")
    return "\n".join(parts)


def placed_order_in(records: list[ToolCallRecord]) -> dict[str, Any] | None:
    """The order this turn placed, if it placed one."""

    for record in reversed(records):
        result = record.result
        if isinstance(result, dict) and result.get("outcome") == "placed":
            return result
    return None


def describe_placed_order(placed: dict[str, Any] | None) -> str | None:
    """What was placed, said from the order's own figures.

    The payment link is deliberately absent: a model repeating a long opaque
    URL is a customer who cannot pay. It reaches the browser as a field and
    is rendered there.
    """

    if not placed:
        return None
    total = _money(placed.get("total"))
    if placed.get("payment_problem"):
        return (
            f"Your order is placed and comes to {total}, but the payment link "
            "could not be created just now. It is saved and can be paid from "
            "your orders."
        )
    when = _clock(placed.get("scheduled_at"))
    if when:
        return f"Your order is placed for {when} and comes to {total}. The payment link is just below."
    return f"Your order is placed and comes to {total}. The payment link is just below."


def describe_collecting(missing: list[str] | None) -> str | None:
    """What is still needed, in words, from the field names.

    Used when a collecting turn runs out of rounds: the customer has just
    handed over their address and deserves better than the reply pipeline's
    "that one's outside my kitchen", which is what an intent extractor makes
    of a street name.
    """

    if not missing:
        return None
    said = {
        "fulfillment_type": "whether you want delivery or pickup",
        "contact_name": "your name",
        "contact_phone": "a phone number",
        "contact_email": "an email address",
        "delivery_address": "the delivery address",
    }
    wanted = [said.get(name, name) for name in missing]
    if len(wanted) == 1:
        return f"Thanks. I still need {wanted[0]}."
    return f"Thanks. I still need {', '.join(wanted[:-1])} and {wanted[-1]}."


def _identifiable(scope: OrderingScope) -> bool:
    """Whether an order could be placed for whoever this is.

    A signed-in customer has an account. A customer on WhatsApp does not yet
    — the account is made from their verified number at the moment of
    placing — and requiring one before that made every WhatsApp turn look
    unready forever, so nothing was ever placed.
    """

    return scope.customer is not None or bool(scope.verified_phone)


def describe_applied(
    records: list[ToolCallRecord], goes_with: list[dict[str, Any]] | None = None
) -> str | None:
    """What the turn actually did to the cart, said from the tool's own rows.

    A turn that added something and then had nothing to say let the reply
    pipeline fill the silence — and asked about an address or a dish it had
    just added, that pipeline says "that one's outside my kitchen". An action
    that happened should always be able to speak for itself.
    """

    said = []
    anything_added = False
    for record in records:
        result = record.result
        if not isinstance(result, dict) or result.get("outcome") != "action":
            continue
        action = result.get("action") or {}
        if action.get("status") != "applied":
            continue
        name = result.get("name") or "that dish"
        quantity = result.get("quantity") or action.get("quantity") or 1
        if action.get("kind") == "add":
            said.append(f"Added {quantity} x {name} to your order.")
            anything_added = True
        elif action.get("kind") == "set_quantity":
            said.append(f"{name} is now x{quantity}.")
        elif action.get("kind") == "remove":
            said.append(f"Removed {name} from your order.")
    if not said:
        return None
    head = " ".join(said)

    # Somebody who has just chosen a dish is the easiest person in the world
    # to offer a drink to, and "Anything else?" on its own hands the work of
    # remembering the menu back to them at exactly that moment. Only after an
    # ADD: taking something out is not an opening to sell.
    #
    # The rows are `dishes_to_suggest`'s — the branch's own bestseller and
    # popularity columns, one per section, minus what is already in the cart —
    # so nothing here is a guess about what goes with what.
    if anything_added and goes_with:
        listed = "\n".join(f"- {d.get('name')} - {_money(d.get('price'))}" for d in goes_with)
        head = f"{head}\n\nPeople often add:\n{listed}"

    # One question, so that "yes" to it has one meaning. "Anything else, or
    # shall we get it on its way?" put two to a customer at once, and the
    # answer to both of them is yes. It goes last, because buried above a
    # price list it reads as part of the list.
    return f"{head}\n\nAnything else?" if anything_added and goes_with else head + " Anything else?"


_PLACE_FAILURE_LINES = {
    "empty_cart": "There is nothing in your order yet. Tell me what you would like and I will add it.",
    "email_in_use": (
        "That email is already on another account here, so I cannot use it for this "
        "order. Give me a different email address, please."
    ),
    "not_identified": "I could not set up an account for this number, so I cannot place the order from here.",
    "no_session": "I lost track of this conversation. Tell me your order again and I will pick it up.",
}


_MONEY = re.compile(
    # A currency symbol and a number, or a bare number with exactly two
    # decimals — the two shapes a price is written in.
    r"(?:[$\u20b9\u00a3\u20ac]\s*\d[\d,]*(?:\.\d+)?)|(?:\b\d[\d,]*\.\d{2}\b)"
)


def _figures(text: str) -> set[str]:
    """Every money-shaped figure in a piece of text, currency dropped."""

    return {
        match.group(0).lstrip("$\u20b9\u00a3\u20ac").strip().replace(",", "")
        for match in _MONEY.finditer(text)
    }


def invented_figures(answer: str, facts: str) -> set[str]:
    """Money in the answer that the turn's own rows cannot account for.

    Live, to a real customer: "Your order is all set for pickup. The
    total amount is Rs 150." The cart was empty and this branch does not
    price in rupees — the model was not reading a row, there were no rows
    to read. The house rule is older than this agent (the narrator's
    numbers are checked back against the fact pack) and this is that
    check, on the one number a customer acts on.
    """

    return _figures(answer) - _figures(facts)


def names_a_tool(answer: str) -> str | None:
    """A tool this agent runs, named in prose meant for a customer.

    The model is given the tool registry so it can plan, and it sometimes
    writes its plan out instead of carrying it out. Live, to a real customer:

        Ready to check out? Your cart contains 1 x Money Bags - $9.49.
        Subtotal: $9.49. Call place_order now to proceed with payment.

    "Call place_order now" is an instruction the model wrote to itself. The
    customer cannot call anything, and being told to is worse than being told
    nothing — it reads as a broken machine.

    Sibling of `invented_figures`: both ask whether the sentence is fit to
    send, and both answer from the turn's own facts rather than from taste.
    A tool name cannot appear in natural prose by accident — every one of
    them carries an underscore — so a hit is certain rather than likely.
    """

    lowered = answer.lower()
    for tool in TOOLS:
        if "_" in tool and tool in lowered:
            return tool
    return None


def _short_of_minimum(result: dict[str, Any]) -> tuple[str, str, str] | None:
    """Subtotal, minimum and the gap, when that is why a placement was refused.

    Read off the two numbers the refusal carries rather than out of its
    sentence: the reason is written for a person, and matching words to
    decide what a refusal meant is the thing this agent does not do.
    """

    try:
        subtotal = Decimal(str(result.get("subtotal")))
        minimum = Decimal(str(result.get("minimum")))
    except (ArithmeticError, TypeError, ValueError):
        return None
    if subtotal >= minimum:
        return None
    return (_money(subtotal), _money(minimum), _money(minimum - subtotal))


def _clock(iso: str | None) -> str | None:
    """'Thu 10:30' from an ISO datetime, in the branch's own zone."""

    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).astimezone(branch_hours.BUSINESS_TIMEZONE).strftime("%a %H:%M")
    except ValueError:
        return None


def describe_time_settled(records: list[ToolCallRecord]) -> str | None:
    """A time this turn settled, said back — or the day it still needs.

    Live: "18th Sep, 3 PM" was accepted, kept, and answered with nothing at
    all. A turn that settles the time and falls silent hands the reply to a
    pipeline that knows nothing about it, and the two answers that came back
    contradicted each other — one saying 3 pm worked, the next saying it did
    not.
    """

    for record in reversed(records):
        if record.tool != "schedule_time" or not isinstance(record.result, dict):
            continue
        if record.result.get("outcome") == "needs_a_time":
            day = record.result.get("day") or "that day"
            hours = str(record.result.get("hours") or "").strip()
            return f"{day} it is. What time would you like it? {hours}".strip()
        if record.result.get("outcome") == "kept":
            when = _clock(record.result.get("scheduled_at"))
            return f"Right — I have that down for {when}." if when else None
        return None
    return None


def describe_time_problem(records: list[ToolCallRecord]) -> str | None:
    """A time that could not be kept, and the nearest one that could."""

    for record in reversed(records):
        if record.tool != "schedule_time":
            continue
        if isinstance(record.result, dict):
            if record.result.get("outcome") in {"kept", "needs_a_time"}:
                return None
            reason = str(record.result.get("reason") or "").rstrip(".")
            nearest = _clock(record.result.get("next_open"))
            offer = f" The earliest I can do is {nearest} — shall I make it that?" if nearest else ""
            return f"That time will not work: {reason}.{offer}"
        return "I could not read that time. Tell me it like 'at 11:30' or 'when you open'."
    return None


def describe_place_failure(records: list[ToolCallRecord]) -> str | None:
    """Why the order was not placed, from the tool's own result.

    Every outcome `place_order` can return short of "placed" is said here.
    Measured live on a real phone: it returned `empty_cart` and nothing
    spoke it, so the customer read "That is everything I need" after every
    message including YES, and the order never existed.
    """

    attempts = [record for record in records if record.tool == "place_order"]
    # The attempt that actually reached the handler, not a later one a guard
    # turned back. Live, `place_order` answered `email_in_use` and a retired
    # repeat with no result of its own was reported instead, so the customer
    # read "I could not place that order just now" and had no idea their
    # email was the problem.
    answered = [record for record in attempts if isinstance(record.result, dict)]
    for record in reversed(answered or attempts):
        if not isinstance(record.result, dict):
            # A handler that raised, or a call a guard refused. Live, this
            # was silent: the schema rejected the phone number on every
            # attempt and the customer read "That is everything I need to
            # place your order" six times, with no order behind it. A
            # placement that fails is never quiet again.
            logger.warning("Ordering agent could not place an order: %s", record.error)
            return "I could not place that order just now. Let me get someone to help."
        outcome = record.result.get("outcome")
        if outcome == "placed":
            return None
        if outcome == "needs_details":
            return describe_collecting(list(record.result.get("missing") or []))
        if outcome == "refused":
            nearest = _clock(record.result.get("next_open"))
            if nearest:
                # Closed now, open later: the one refusal that is really an
                # invitation. Everything the customer typed is kept; all
                # they have to say is when.
                label = str(record.result.get("fulfillment_label") or "your order")
                wanted = _clock(record.result.get("wanted_time"))
                if wanted:
                    # They named a time and the branch cannot keep it. Saying
                    # which time is the point: "that will not work" about an
                    # unnamed time reads as a refusal of the whole order.
                    return (
                        f"I cannot do {wanted} for {label}. The closest I can do is "
                        f"{nearest} — shall I make it that, or would you like another time?"
                    )
                return (
                    f"We are closed for {label} right now, but I can still take this "
                    f"for later. The next time I can do is {nearest} — shall I place it "
                    f"for then, or would you like another time?"
                )
            short = _short_of_minimum(record.result)
            if short is not None:
                subtotal, minimum, gap = short
                # The one refusal a customer can clear themselves, so it is
                # written as the next step rather than as a rejection.
                return (
                    f"Your order comes to {subtotal} and this branch takes orders from "
                    f"{minimum} — another {gap} and I can place it. What else can I add?"
                )
            # The backend's own words — a closed kitchen, an item that went
            # unavailable — are the reason, and the customer can act on them.
            reason = str(record.result.get("reason") or "").strip().rstrip(".")
            return f"I could not place that: {reason}." if reason else "I could not place that order."
        return _PLACE_FAILURE_LINES.get(str(outcome), "I could not place that order just now.")
    return None


def describe_ready(total: str | None = None) -> str:
    """Everything is gathered and only the confirmation is left.

    Said deterministically because the model would not: offered place_order
    as its only tool it still answered "proceed to checkout" and placed
    nothing. The customer gets a sentence and a button instead.
    """

    return "That is everything I need to place your order."


def describe_order_so_far(cart_result: Any) -> str | None:
    """The cart read back, or None when there is nothing in it.

    `describe_cart` answers an empty cart with a SENTENCE — "Your cart is empty
    at the moment." — which is right for a customer who asked what is in their
    cart and wrong for anything that tests it for truth. Dropped into "You have
    {...}" it produced:

        You have Your cart is empty at the moment.. Ready to check out?

    So the emptiness is decided by the rows, not by whether a string came back.
    """

    if not isinstance(cart_result, dict) or not (cart_result.get("lines") or []):
        return None
    return describe_cart(cart_result)


def _cart_summary_in(records: list[ToolCallRecord]) -> str | None:
    """The most recent cart this turn, read back — or None."""

    for record in reversed(records):
        said = describe_cart(record.result)
        if said is not None:
            return said
    return None


def _choice_question_in(records: list[ToolCallRecord]) -> str | None:
    """The most recent question this turn's rows raise — or None.

    A dish that needs a size, or a name that fits more than one dish: both
    are things only the customer can settle, and both are asked from the
    rows rather than guessed at.
    """

    for record in reversed(records):
        if isinstance(record.result, dict) and record.result.get("outcome") == "ambiguous":
            return str(record.result.get("question"))
        question = ask_for_choice(record.result)
        if question is not None:
            return question
    return None


def _repeated_call(records: list[ToolCallRecord], tool: str, args: dict[str, Any]) -> int | None:
    """The 1-based index of an earlier call this turn with the same tool and
    the same arguments, or None.

    Refused calls count too. They were exempt at first — "fair to retry once
    the model has fixed what it can" — but a model that resends the same
    arguments has fixed nothing, and measured live the exemption bought one
    `save_order_details` refused four times over, each a full model round:
    a 20-second turn for a customer who had just typed their address.
    """

    for index, record in enumerate(records, 1):
        if record.tool == tool and record.args == args:
            return index
    return None


# The tools that need an id the model did not invent, and therefore cannot
# be offered before it has one. `go_to_checkout` is not among them: its cart
# is injected, so it names nothing.
_ID_BEARING_TOOLS = frozenset({"add_to_cart", "remove_from_cart", "set_quantity"})


def _as_tool_lines(cart: list[CartLinePayload]) -> list[Any]:
    """The request's cart in the shape `view_cart` takes. `guards` owns the
    field-name translation; this is the one caller outside a planned call."""

    return [CartLineArgs.model_validate(line) for line in guards._request_cart_lines(cart)]


# While details are being collected, these are the only useful moves. Every
# other tool is a way to lose the thread of what the customer was in the
# middle of doing.
#: How a digit is spelled, so a phrase the customer wrote can be put back
#: together and checked against the menu. Orthography, not meaning: nothing
#: here decides what a message means, it only reconstructs "four cheese
#: pizza" from a reading that split it into 4 and "cheese pizza".
_NUMERALS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
    8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
}

_COLLECTING_TOOLS = ("order_requirements", "save_order_details", "place_order", "view_cart")
# The order can still change while its details are being gathered — "wait,
# add a coke too" is a normal thing to say after giving an address. Without
# these, a customer whose cart was empty when the details landed was stuck:
# every message answered "nothing in your order yet" and nothing could be
# added. Measured live on a real phone.
_CART_TOOLS = ("search_menu", "get_dish", "add_to_cart", "remove_from_cart", "set_quantity")


def _offered_tools(
    seen: set[uuid.UUID],
    ordering: bool = False,
    ready: bool = False,
    retired: set[str] | None = None,
) -> tuple[str, ...]:
    """Which tools this round may choose from.

    With nothing seen — an empty cart and no lookup yet — a cart tool has no
    id it could legitimately carry, and a model asked for one anyway will
    invent one; it invented "123" six rounds running on a live turn. So the
    rule is enforced by what is on offer rather than by refusing what comes
    back: look something up, and the cart tools appear.
    """

    offered = _tools_for(seen, ordering, ready)
    # A tool that already answered this turn is not offered again: its answer
    # is in the history to read, and asking twice is how a turn ended having
    # done nothing. Never narrowed to nothing — an empty offer would leave
    # the model no move at all.
    kept = tuple(name for name in offered if name not in (retired or ()))
    return kept or offered


def _tools_for(seen: set[uuid.UUID], ordering: bool, ready: bool) -> tuple[str, ...]:
    if ready:
        # place_order first, and the cart tools with it. This used to be the
        # one tool: offered four, the model answered "ready to be placed"
        # and placed nothing — twice. Placing is no longer the model's to
        # get wrong (the web has a button, a chat places deterministically
        # once the message has been read), so what matters now is that a
        # last-minute change can still be made.
        return tuple(name for name in ("place_order",) + _CART_TOOLS if name in TOOLS)
    if ordering:
        return tuple(name for name in _COLLECTING_TOOLS + _CART_TOOLS if name in TOOLS)
    if seen:
        return tuple(TOOLS)
    return tuple(name for name in TOOLS if name not in _ID_BEARING_TOOLS)


def _repair_named_dish(
    db: Session,
    scope: OrderingScope,
    step: PlanStep,
    seen: set[uuid.UUID],
    records: list[ToolCallRecord],
) -> PlanStep | None:
    """A refused call whose only fault was a dish name where an id belongs.

    Live failure: the model called `add_to_cart(menu_item_id="Veggie Garden
    Pizza")` and the planner refused it identically on all six rounds, so
    "just add it" did nothing at all. Naming a dish is the model's job and
    resolving the name is ours, so the lookup runs here, behind `get_dish`'s
    own confidence guardrail, and the repaired call is revalidated before it
    is allowed anywhere near a handler. Returns None when there is nothing
    to repair, which is every other refusal.
    """

    if step.error != "invalid_arguments" or not step.tool:
        return None
    planned_args, lookup = guards.resolve_dish_name(db, scope, step.tool, step.args)
    if lookup is None:
        return None
    guards.grow_seen_ids(seen, lookup)
    records.append(
        ToolCallRecord(tool="get_dish", args={"name": step.args.get("menu_item_id")}, result=lookup)
    )
    if planned_args is step.args or planned_args == step.args:
        # The name did not resolve confidently. The lookup is recorded above
        # either way, so the next round sees what was searched for.
        return None
    revalidated = validate_call(step.tool, planned_args)
    return revalidated if revalidated.ok else None


def _error_record(step: PlanStep) -> ToolCallRecord:
    """A planner refusal, reshaped into the same `ToolCallRecord` history
    entry a failed tool call gets — the model sees both the same way on the
    next round. `step.tool` is always `None` on every refusal path
    `planner.py`'s `_validate_call`/`plan_step` can take (a smuggled scope
    id or an unknown tool name never gets far enough to be recorded), so
    there is no real tool name to carry here; `""` is a placeholder, never
    read back out by anything that treats it as a real tool.
    """

    detail = f"{step.error}: {step.detail}" if step.detail else (step.error or "planner_error")
    return ToolCallRecord(tool=step.tool or "", args=step.args, error=detail)


def _currency_for(db: Any, scope: Any) -> str | None:
    """What this conversation's restaurant charges in, or None.

    None leaves the platform default, which is the honest answer when there
    is no database to ask — a test drives `run_turn` with `db=None` — and is
    never worth failing a turn over.
    """

    if db is None or getattr(scope, "restaurant_id", None) is None:
        return None
    try:
        from app.models.restaurant import Restaurant

        return db.scalar(
            select(Restaurant.currency).where(Restaurant.id == scope.restaurant_id)
        )
    except Exception:  # noqa: BLE001 - a symbol is not worth a failed turn
        logger.warning("Ordering agent could not read the restaurant's currency", exc_info=True)
        return None


def run_turn(
    db: Session,
    *,
    scope: OrderingScope,
    message: str,
    cart: list[CartLinePayload],
    generate: Generate | None = None,
    clock: Clock = time.monotonic,
    max_rounds: int | None = None,
    budget_seconds: float | None = None,
    # Whether this channel can offer a button. The web can: everything
    # gathered, the customer taps Place order, and nothing is ambiguous. A
    # chat thread cannot, and asking someone to "reply YES" when they have
    # just said yes is the loop this closes. Where there is no button, the
    # next message once everything is gathered places the order — unpaid,
    # so the customer's real confirmation is still the one that matters:
    # opening the payment link.
    auto_place: bool = False,
    previous_reply: str | None = None,
    recent_history: Sequence[dict[str, str]] | None = None,
) -> TurnOutcome:
    """Run one customer turn to completion, or to whichever bound stops it
    first. `clock`/`generate` are injected so a test drives every round
    deterministically — no sleeping for the budget, no Ollama for the plan —
    the same reason `plan_step` itself takes `generate` as an argument.

    Flag-gated per the house rule every AI feature follows: with
    `enable_ordering_agent` off, this returns immediately with
    `fallback_reason="flag_off"` and runs nothing else at all — no seeding,
    no clock reads beyond the one needed to report `elapsed_seconds`, no
    call to `plan_step`.
    """

    start = clock()
    # Before anything is said, so every figure in this turn is written in the
    # money this restaurant actually charges.
    bind_chat_currency(_currency_for(db, scope))
    if not settings.enable_ordering_agent:
        return TurnOutcome(
            answer=None,
            actions=[],
            records=[],
            fallback_reason="flag_off",
            elapsed_seconds=clock() - start,
        )

    rounds = max_rounds if max_rounds is not None else settings.ordering_agent_max_tool_rounds
    budget = budget_seconds if budget_seconds is not None else settings.ordering_agent_budget_seconds

    # Resolved HERE rather than left to the planner's own `generate or
    # default_generate`, because in production this argument is None — a test
    # injects a scripted model, a customer does not — and the wrapper below
    # needs something real to call. Getting this wrong raised on every live
    # turn while the whole suite stayed green.
    asked_for = generate if generate is not None else default_generate

    def generate(prompt: str, timeout_seconds: float, max_tokens: int) -> str:
        """The model, never given longer than the turn has left.

        The budget used to be read only between steps, so a call ran to its
        OWN timeout and the check noticed the overrun afterwards. Those
        timeouts are larger than the budget that contains them — 45s a call
        against 30s a turn — so one call could always outlive the whole turn,
        and one did: 54 seconds, live, of which a single cold model load was
        nearly all.

        Out of time returns nothing rather than raising. Every caller here
        already handles a model that answered nothing — it is the ordinary
        case when the model is unreachable — and that path is deliberate and
        tested, where an exception thrown from inside the reader would not be.
        """

        left = budget - (clock() - start)
        if left <= 0:
            return ""
        return asked_for(prompt, min(timeout_seconds, left), max_tokens)

    seen: set[uuid.UUID] = guards.seed_seen_ids(cart)
    # Dishes already put in the cart this turn by answering a question
    # with them. Live, on the real model: a pick came back as BOTH
    # `chose: ["Money Bags"]` and `add: [("Money Bags", 1)]`, and the
    # two paths each added it — one message, two of the dish, and the
    # sentence "Added 1 x Money Bags to your order." twice over.
    _picked_this_turn: set[str] = set()
    # Tools this turn has already answered with identical arguments.
    retired: set[str] = set()
    # The unpaid order this conversation left behind, looked up at most
    # once a turn and only when something asks about it.
    _waiting_for: list = []
    # The cart resolved once, up front, by the same code the tool uses. It
    # goes into every prompt as a fact and costs one query per turn; the
    # alternative is a model that has to remember to look before it speaks,
    # and on a live turn it did not.
    cart_summary: str | None = None
    # The same read-back without the prompt's framing, for the customer.
    cart_readback: str | None = None
    # The rows themselves, for the read-back that asks a customer to stand
    # behind the order. A sentence cannot be turned back into figures.
    cart_result: Any = None
    if cart:
        try:
            cart_result = TOOLS["view_cart"].handler(db, scope, ViewCartArgs(lines=_as_tool_lines(cart)))
            cart_summary = describe_cart(cart_result)
        except Exception:  # noqa: BLE001 - a prompt fact is never worth failing a turn for
            logger.warning("Ordering agent could not resolve the cart for the prompt", exc_info=True)
        if cart_summary:
            cart_readback = cart_summary
            cart_summary = "In the cart right now: " + cart_summary

    # What this conversation is in the middle of, if anything. Stated as a
    # fact for the same reason the cart is: a model that has to infer it
    # from the thread sometimes does not.
    # None while the customer is still browsing; a list of field names once
    # they have been asked for their details; empty once nothing is missing
    # and the order can be placed.
    collecting: list[str] | None = None
    # What an order would still need, stated whenever there is a cart to
    # order. Live: "let's go for checkout" read the cart back and stopped,
    # because nothing had told the model what placing it would require.
    pending: list[str] = []
    if scope.session_id is not None:
        draft = tools_module._draft_for(scope)
        if cart:
            pending = draft.missing_fields()
        # Collection is a property of an order, and an empty cart is not one.
        # Framed as "collecting" with nothing in the cart, the model wandered
        # (search, get_dish, get_dish again) and never added the dish the
        # customer had just named; as a plain cart turn the same message
        # adds it in two rounds. The draft keeps what it holds for when
        # there is something to order.
        if draft.collecting and cart:
            collecting = draft.missing_fields()

    def _still_missing() -> list[str] | None:
        """What the draft wants NOW, not when the turn began.

        The turn's own `save_order_details` calls have happened by the time
        anything is said, so the list computed up front is one step behind —
        it told a customer who had just given their address that it still
        needed their address.
        """

        if scope.session_id is None:
            return collecting
        fresh = tools_module._draft_for(scope)
        # The flag is read fresh too: a turn that STARTED the collection was
        # otherwise judged by its own beginning, and said nothing at the end
        # to a customer who had just handed over their address.
        if not fresh.collecting and collecting is None:
            return None
        return fresh.missing_fields()

    records: list[ToolCallRecord] = []
    actions: list[dict[str, Any]] = []

    def _take_time(when: str) -> None:
        """Keep the time the customer named, once the branch's own rules
        accept it — or record why they do not, so the turn can say so."""

        location = (
            db.get(branch_hours.RestaurantLocation, scope.restaurant_location_id)
            if db is not None and scope.restaurant_location_id
            else None
        )
        draft_now = order_draft.load(scope.session_id)
        fulfillment = branch_hours.OrderFulfillmentType(
            # Delivery when nobody has said, as everywhere else that has to
            # guess — the hours read back said "Pickup" to a customer who
            # went on to ask for delivery.
            draft_now.fulfillment_type or branch_hours.OrderFulfillmentType.DELIVERY.value
        )
        chosen: datetime | None
        if when == "opening":
            chosen = (
                branch_hours.next_available_slot_start(location, fulfillment_type=fulfillment)
                if location is not None
                else None
            )
            if chosen is None:
                records.append(ToolCallRecord(tool="schedule_time", args={"when": when},
                                              error="no_slot: nothing available to schedule"))
                return
        elif len(when.strip()) == 10:
            # A day and no clock time. Live: "18th Sep" became midnight on
            # the 18th, which no kitchen is open for, and the refusal then
            # offered a time earlier than the day they had asked about.
            # A day is an answerable question, not a refusal.
            try:
                that_day = datetime.strptime(when.strip(), "%Y-%m-%d").replace(
                    tzinfo=branch_hours.BUSINESS_TIMEZONE
                )
            except ValueError:
                records.append(ToolCallRecord(tool="schedule_time", args={"when": when},
                                              error="unreadable: that time could not be read"))
                return
            hours = (
                branch_hours.describe_hours(
                    location, fulfillment_type=fulfillment, reference_dt=that_day
                )
                if location is not None
                else None
            )
            records.append(ToolCallRecord(
                tool="schedule_time", args={"when": when},
                result={"outcome": "needs_a_time", "day": f"{that_day:%A %d %B}", "hours": hours},
            ))
            # The day is held with the question, so the time they answer with
            # lands on it. Without this, "3 PM" after "what time on Friday?"
            # was a time attached to nothing and read as today.
            _hold(
                f"What time on {that_day:%A %d %B}?",
                yes="time_on_day",
                subject=that_day.date().isoformat(),
            )
            return
        else:
            try:
                chosen = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(
                    tzinfo=branch_hours.BUSINESS_TIMEZONE
                )
            except ValueError:
                records.append(ToolCallRecord(tool="schedule_time", args={"when": when},
                                              error="unreadable: that time could not be read"))
                return
        if location is not None:
            ok, reason = branch_hours.schedule_slot_is_available(
                location, fulfillment_type=fulfillment, scheduled_at=chosen
            )
            if not ok:
                # Measured from the time they asked for, not from now: a
                # refusal for the 18th offered Thu 15:00, which is the day
                # before and no use to anybody.
                alternative = branch_hours.next_available_slot_start(
                    location,
                    fulfillment_type=fulfillment,
                    reference_dt=max(chosen, branch_hours._localize_reference_datetime(None)),
                )
                records.append(ToolCallRecord(
                    tool="schedule_time", args={"when": when},
                    result={"outcome": "unavailable", "reason": reason,
                            "next_open": alternative.isoformat() if alternative else None},
                ))
                if alternative is not None:
                    draft_now.offered_scheduled_at = alternative.isoformat()
                    order_draft.save(scope.session_id, draft_now)
                return
        kept, problems = order_draft.remember(draft_now, scheduled_at=chosen.isoformat())
        order_draft.save(scope.session_id, kept)
        records.append(ToolCallRecord(
            tool="schedule_time", args={"when": when},
            result={"outcome": "kept", "scheduled_at": kept.scheduled_at, "problems": problems},
        ))

    def _place_now() -> None:
        """Place the order, here, from rows that say it is ready."""

        prepared, guard_error = guards.prepare_tool_call(
            "place_order", {}, cart=cart, seen=seen, diet=scope.diet
        )
        if guard_error is not None:
            return
        try:
            if db is not None and getattr(db, "is_active", True) is False:
                db.rollback()
            result = TOOLS["place_order"].handler(db, scope, prepared)
            records.append(
                ToolCallRecord(tool="place_order", args=prepared.model_dump(), result=result)
            )
        except Exception as error:  # noqa: BLE001 - a failed placement is said, not raised
            logger.warning("Ordering agent could not place: %s", error, exc_info=True)
            records.append(
                ToolCallRecord(tool="place_order", args={}, error=f"tool_error: {error}")
            )

    def _describe_hours() -> str | None:
        """When this branch can do this kind of order, from its own schedule."""

        location = db.get(branch_hours.RestaurantLocation, scope.restaurant_location_id)
        if location is None:
            return None
        draft_now = order_draft.load(scope.session_id) if scope.session_id else None
        wanted_type = branch_hours.OrderFulfillmentType(
            (draft_now.fulfillment_type if draft_now else None)
            or branch_hours.OrderFulfillmentType.DELIVERY.value
        )
        return branch_hours.describe_hours(location, fulfillment_type=wanted_type)

    def _waiting_order():
        """The order they placed and have not paid for, looked up once."""

        if not _waiting_for:
            _waiting_for.append(open_orders.waiting_order(db, scope))
        return _waiting_for[0]

    def _order_line(order) -> str:
        """What that order is, in one sentence, from its own row."""

        when = _clock(order.scheduled_at.isoformat()) if order.scheduled_at else None
        for_when = f" for {when}" if when else ""
        return f"Your order{for_when} comes to {_money(order.total_amount)}"

    def _with_link(order, said: str) -> str:
        """A sentence about an order, with the way to pay it."""

        link = open_orders.payment_link_for(db, order) if db is not None else None
        return f"{said}\n\nPay here:\n{link}" if link else said

    def _ask_about_waiting(order, *, they_asked_to_cancel: bool = False) -> TurnOutcome:
        """Put the waiting order to them, with the link and one question.

        Asked the way round they raised it. A customer who said "cancel my
        order" and was asked "Shall I keep that order?" has to answer no to
        get what they asked for, and the yes they will reach for does the
        opposite of what they said.
        """

        if they_asked_to_cancel:
            question = "Shall I cancel it?"
            asked = _hold(question, yes="drop_order", asks=question)
        else:
            question = "Shall I keep that order?"
            asked = _hold(question, yes="keep_order", asks=question)
        said = f"{_order_line(order)} and is waiting to be paid."
        return _answering(f"{_with_link(order, said)}\n\n{asked}")

    def _drop_the_order(order) -> TurnOutcome:
        """Call it off, and offer back what it held."""

        if db is None:
            # Two different failures, and only one of them is about money.
            # Saying the payment went through when the real trouble is a
            # database we cannot reach would be a lie in the customer's
            # favour, which is still a lie.
            return _answering(
                "I could not reach your order just then. Say that again in a moment "
                "and I will sort it."
            )
        if not open_orders.abandon(db, order):
            # The reconciliation found the money had landed after all.
            # Telling somebody their order is gone while their card has been
            # charged is the one outcome worth a whole extra check.
            return _answering(
                "That payment has actually gone through, so the order is confirmed. "
                "Nothing has been cancelled."
            )
        _waiting_for[0] = None
        return _answering(
            "Cancelled, and nothing has been charged. "
            + _hold(
                "Shall I put those dishes back in your basket for another time?",
                yes="restore_cart",
                subject=str(order.id),
            )
        )

    def _put_back(order) -> None:
        """The order's dishes, back in the basket, through the same add path.

        Re-resolved against the live menu rather than restored from the
        order's snapshot: a dish that has since gone off the menu should be
        refused here exactly as it would be for anybody else.
        """

        for line in open_orders.lines_of(order):
            args: dict[str, Any] = {
                "menu_item_id": str(line.menu_item_id),
                "quantity": line.quantity,
            }
            if line.size_id:
                args["menu_item_size_id"] = str(line.size_id)
            if line.customization_option_ids:
                args["selected_options"] = [
                    {"option_id": str(option)} for option in line.customization_option_ids
                ]
            # The add guard refuses an id this turn has not looked up —
            # the rule that stops a model inventing a menu item and
            # putting it in somebody's cart. These ids are not an
            # invention: they were resolved and priced when the order was
            # written. Without this the basket came back empty.
            guards.grow_seen_ids(seen, args)
            actions.extend(_run_add(args))

    def _suggest_more() -> TurnOutcome | None:
        """A few things to offer somebody who wants more but has not said what.

        Wanting more without naming it is one of the commonest things a
        customer says, and a restaurant answers it by suggesting. Live, the
        turn found nothing in the sentence, had nothing to do, and read the
        cart back — the same cart, twice in a row.
        """

        # Nothing to suggest from. A turn driven with no database — every
        # scripted test, and any caller without a branch — asks this the
        # moment somebody says "yes" to "which one would you like", so it
        # has to answer "I have nothing" rather than raise.
        if db is None or not scope.restaurant_location_id:
            return None

        want_veg = True if (scope.diet or "").lower() == "veg" else None
        shown = tools_module.dishes_to_suggest(
            db,
            scope,
            in_cart=[line.menu_item_id for line in cart],
            is_veg=want_veg,
        )
        if not shown:
            return None
        listed = "\n".join(f"- {d['name']} - {_money(d['price'])}" for d in shown)
        opening = "Of course. People often add:" if cart else "Of course. These go quickly:"
        asked = _hold("Tell me the name and I will add it.", yes="name_one")
        _remember_dish_choice(asked, shown)
        return TurnOutcome(
            answer=f"{opening}\n{listed}\n\n{asked}",
            answer_about="menu",
            actions=actions,
            records=records,
            fallback_reason=None,
            elapsed_seconds=clock() - start,
        )

    def _show_dishes(
        phrase: str,
        category: str | None = None,
        max_price: Decimal | None = None,
    ) -> TurnOutcome | None:
        """Read the menu out: their words, our rows, their diet.

        The reply pipeline answers a menu question well when it is about
        flavour or a recommendation. It answers "do you have pizza" with
        Coconut Ice Cream, because semantic similarity matched dishes that
        take extras. When a customer names something the menu has, the menu
        is the answer.
        """

        want_veg = True if (scope.diet or "").lower() == "veg" else None
        # One more than we will read out, purely to learn whether there IS
        # one more. "Here is what we have" over eight rows of a 136-dish
        # menu is a claim about the menu, and it was false for every
        # restaurant big enough to matter.
        report: dict[str, Any] = {}
        found = tools_module.dishes_to_show(
            db, scope, phrase, is_veg=want_veg, category=category,
            max_price=max_price, limit=_DISHES_READ_OUT + 1, report=report,
        )
        if not found:
            return None
        found_by = str(report.get("found_by") or "named")
        # A section is read out whole. Eight of seventeen under "Here are a
        # few" is honest but useless to somebody who asked to see the Paneer
        # Taste section — they asked for the section, and the rest of it is
        # not a follow-up question they should have to think to ask.
        read_out = tools_module.WHOLE_SECTION_CAP if found_by == "section" else _DISHES_READ_OUT
        more = len(found) > read_out
        shown = found[:read_out]
        if len(shown) == 1:
            # They named the one thing they want. Reading it back as a list
            # of one and asking which they would like is not a conversation:
            # live, "I like Appetizer Sampler" got exactly that, and the
            # "Yes" that answered it reached nobody.
            only = shown[0]
            # One dish is now what is in front of them, so the last LIST is
            # not. Left standing, an ordinal reached back past this: measured
            # with two customers, "the first one" — right after being shown a
            # single Appetizer Sampler — added a dish from a list two turns
            # earlier, because nothing had superseded it.
            _forget_shown()
            return TurnOutcome(
                answer=_hold(
                    describe_single_dish(only),
                    yes="add",
                    subject=only["name"],
                ),
                answer_about="menu",
                actions=actions,
                records=records,
                fallback_reason=None,
                elapsed_seconds=clock() - start,
            )
        listed = "\n".join(f"- {d['name']} - {_money(d['price'])}" for d in shown)
        veg_note = "" if want_veg is None else ", all vegetarian"
        asked_for = phrase.strip()
        if found_by == "budget":
            # Their ceiling is what selected these rows, so it is what the
            # sentence is about. Saying the figure back is the confirmation
            # that it was heard — the whole failure this replaced was a reply
            # that gave no sign of having read the number at all.
            opening = f"Here is what we have under {_budget(max_price)}{veg_note}"
        elif found_by == "over_budget":
            # Nothing came in under it. The rows are the cheapest the branch
            # sells, which is the useful answer, and this is the honest
            # sentence over them.
            opening = (
                f"Nothing here comes in under {_budget(max_price)}. "
                f"These are the cheapest we have{veg_note}"
            )
        elif found_by == "fallback" and asked_for:
            # Acknowledging what they asked for is the house style — the
            # alternative is what shipped once: the branch's whole menu from
            # "Appetizer Sampler" down, under "Here is what we have", which
            # reads as having been ignored.
            #
            # But this used to say "We do not have {asked_for} here", and
            # that is a claim about the MENU when `fallback` is a fact about
            # the SEARCH: `dishes_to_show` reports it when nothing matched
            # the words, and the rows below are then simply the branch's
            # menu rather than anything selected to answer the question.
            #
            # The two come apart the moment somebody describes what they want
            # instead of naming it. "A light lunch under $20" matched no dish
            # name, so the reply opened "We do not have light lunch under $20
            # here" — and then listed eight dishes, every one of them under
            # twenty dollars. Reporting the failed match instead is true in
            # both cases and contradicts nothing: for "sushi" it reads almost
            # exactly as before.
            opening = f"I could not find {asked_for} on the menu. This is what we do have{veg_note}"
        elif found_by == "close" and asked_for:
            # Their words found something, just not the exact name they used.
            opening = f"I could not find {asked_for} exactly. The closest we have{veg_note}"
        elif found_by == "section":
            # Naming the section back is the confirmation it was understood,
            # and it is the difference between a list of dishes and an answer.
            section = str(report.get("section") or "").strip()
            opening = (
                f"Here is our {section}{veg_note}" if section
                else f"Here is what we have{veg_note}"
            )
            if more:
                opening = f"{opening} — the first {len(shown)} of {len(found) - 1}"
        elif more:
            # Only a complete list gets to say it is one.
            opening = f"Here are a few{veg_note}"
        else:
            opening = f"Here is what we have{veg_note}"
        asked = _hold("Which one would you like?", yes="name_one")
        _remember_dish_choice(asked, shown)
        return TurnOutcome(
            answer=f"{opening}:\n{listed}\n\n{asked}",
            answer_about="menu",
            actions=actions,
            records=records,
            fallback_reason=None,
            elapsed_seconds=clock() - start,
        )

    def _details_to_confirm() -> str | None:
        """Their details, if we are holding some nobody has stood behind.

        Only when there is nothing left to ask for: a half-filled draft is
        still being collected, and reading half of it back would be a
        stranger question than asking for the rest.
        """

        if scope.session_id is None or not cart:
            return None
        draft_now = tools_module._draft_for(scope)
        if draft_now.confirmed or draft_now.missing_fields():
            return None
        if int(draft_now.confirm_asks or 0) >= 2:
            # Asked twice already. Taken as read rather than asked a third
            # time, because the details came from their own account.
            return None
        parts = [draft_now.contact_name, draft_now.contact_email]
        if draft_now.fulfillment_type == "DELIVERY":
            parts.append(f"delivery to {draft_now.delivery_address}")
        else:
            parts.append("pickup")
        return ", ".join(p for p in parts if p)

    def _ask_to_confirm() -> TurnOutcome:
        """Read their details back, once, before spending their money."""

        held = _details_to_confirm() or ""
        draft_now = order_draft.load(scope.session_id)
        draft_now.confirm_asks = int(draft_now.confirm_asks or 0) + 1
        order_draft.save(scope.session_id, draft_now)
        return TurnOutcome(
            answer=(
                f"I have these from last time: {held}. Shall I use them? "
                "Say yes, or send me what to change."
            ),
            answer_about="order",
            actions=actions,
            records=records,
            fallback_reason=None,
            elapsed_seconds=clock() - start,
        )

    def _reask_or_give_up(asked: dict[str, Any]) -> TurnOutcome:
        """Put the question again, differently — or stop asking it.

        Live: an answer nobody could map dropped the question entirely and
        the reply pipeline filled three turns with the same closed-branch
        notice. A customer reading the same sentence twice has already
        stopped believing anybody is there, so the second asking spells the
        options out and there is no third.
        """

        options = ", ".join(o["name"] for o in asked["options"])
        if int(asked.get("asks", 1)) >= 2:
            _forget_choice()
            # The question is being dropped, so there is no thread left to
            # keep — and telling somebody whose last two messages we could not
            # read to "tell me the dish you would like" asks them to do the
            # thing that just failed, twice. The sections are what a restaurant
            # hands across the table, and naming one back shows it complete.
            order_so_far = describe_order_so_far(cart_result)
            if order_so_far:
                # There is an order in progress. Sending somebody back to the
                # menu here is how a half-finished order is lost: they picked
                # something, we could not read two messages, and the reply
                # changes the subject to browsing. Read the cart back instead,
                # which already ends on the question that finishes the order.
                answer = f"Sorry — I did not follow that. {order_so_far}"
                # That read-back writes its OWN closing question, and which one
                # depends on the rows: a line still missing a size cannot be
                # checked out, so `describe_cart` says so instead. Appending a
                # second question here printed "Ready to check out?" twice and
                # would have asked it even when it was not true. So the
                # question is only recorded when the read-back actually asked
                # it — recorded, because the next message is an answer to it
                # and needs something to be read against.
                if order_so_far.rstrip().endswith(_READY_TO_CHECK_OUT):
                    _hold(_READY_TO_CHECK_OUT, yes="checkout")
            else:
                offer = (
                    tools_module.offer_of_sections(tools_module.branch_sections(db, scope))
                    if db is not None and scope.restaurant_location_id
                    else None
                )
                answer = (
                    f"Sorry — I did not follow that. {offer}"
                    if offer
                    else (
                        "Sorry — I did not follow that. Let's start that one again: tell me "
                        "the dish you would like and I will set it up."
                    )
                )
        else:
            draft_now = order_draft.load(scope.session_id)
            asked["asks"] = int(asked.get("asks", 1)) + 1
            draft_now.pending_choice = json.dumps(asked)
            order_draft.save(scope.session_id, draft_now)
            answer = reask_standing_choice(asked) or ""
        return TurnOutcome(
            answer=answer,
            answer_about="cart",
            actions=actions,
            records=records,
            fallback_reason=None,
            elapsed_seconds=clock() - start,
        )

    def _awaiting() -> dict[str, Any] | None:
        """The question this conversation is waiting on an answer to."""

        if scope.session_id is None:
            return None
        raw = order_draft.load(scope.session_id).awaiting
        if not raw:
            return None
        try:
            held = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return held if isinstance(held, dict) and held.get("question") else None

    def _hold(
        question: str, *, yes: str, subject: str | None = None, asks: str | None = None
    ) -> str:
        """Write down the question we are ending on, and return it to be said.

        `yes` is what agreeing to it DOES — decided here, as we ask, not
        guessed later from the customer's words. Their words are read
        against `question` by the model on the next turn, so any way of
        agreeing works and no word in this file decides anything.
        """

        if scope.session_id is not None:
            draft_now = order_draft.load(scope.session_id)
            draft_now.awaiting = json.dumps(
                # `asks` is the question as the model should see it next
                # turn. A read-back is long and full of the customer's own
                # details, and given to the model as "the question" it mined
                # the address back out of it: "yes" arrived carrying a
                # delivery address, read as a new instruction, and the order
                # was read back a second time instead of being placed.
                {"question": question, "yes": yes, "subject": subject, "asks": asks or question}
            )
            order_draft.save(scope.session_id, draft_now)
        return question

    def _forget_awaiting() -> None:
        """Nobody is waiting on an answer any more."""

        if scope.session_id is None:
            return
        draft_now = order_draft.load(scope.session_id)
        if draft_now.awaiting:
            draft_now.awaiting = None
            order_draft.save(scope.session_id, draft_now)

    def _answering(said: str) -> TurnOutcome:
        """A turn that is only a sentence, said and over."""

        return TurnOutcome(
            answer=said,
            answer_about="order",
            actions=actions,
            records=records,
            fallback_reason=None,
            elapsed_seconds=clock() - start,
        )

    def _answer_standing(
        standing: dict[str, Any], wanted: dict[str, Any], *, agreed: bool
    ) -> TurnOutcome | None:
        """Act on the answer to the question we ended the last turn on.

        Returns the turn when the answer is the whole of it, or None having
        acted, so that what it did reads itself back. Live, before this: a
        customer shown one dish and asked "Which one would you like?" said
        "Yes", and the turn had nothing to read it against — the reply
        pipeline filled the silence with prose about fulfillment types, over
        a cart holding yesterday's dessert.
        """

        kind = standing.get("yes")
        subject = standing.get("subject")
        # Agreeing and saying what they want in the same breath is normal
        # speech. Live: "yes and add a thai iced tea too" was answered
        # "Of course. What else can I get you?" — they had just said.
        also_says = bool(
            wanted["add"]
            or wanted["details"]
            or wanted.get("when")
            or wanted.get("chose")
            or wanted.get("browse")
            or wanted.get("category")
        )
        if kind == "add" and subject:
            if not agreed:
                if also_says:
                    return None
                return _answering(
                    _hold("No problem. What else can I get you?", yes="name_one")
                )
            added = _add_named_dish(subject, 1)
            if added:
                actions.extend(added)
            # The reading names the dish too, having seen the question it
            # was answering: "haan bhai kar do" came back with both the
            # agreement and the drink, and the drink went in twice.
            wanted["add"] = None
            return None
        if kind in {"keep_order", "drop_order"}:
            order = _waiting_order()
            if order is None:
                return None
            # The two questions ask opposite things — one offers to keep it,
            # the other to cancel it — so the same yes means each.
            dropping = agreed if kind == "drop_order" else not agreed
            if not dropping:
                return _answering(
                    _with_link(order, "Kept. It will be ready once the payment lands.")
                )
            return _drop_the_order(order)
        if kind == "restore_cart":
            if not agreed:
                return _answering("No problem. Tell me whenever you would like to order.")
            order = None
            if db is not None and standing.get("subject"):
                try:
                    order = db.get(Order, uuid.UUID(str(standing["subject"])))
                except (TypeError, ValueError):
                    order = None
            if order is None:
                return _answering("Tell me what you would like and I will put it together.")
            _put_back(order)
            return None
        if kind == "place":
            if also_says:
                return None
            if not agreed:
                return _answering(
                    _hold(
                        "No problem, I will hold it. Tell me what to change, "
                        "or what else you would like.",
                        yes="name_one",
                    )
                )
            if scope.session_id is not None:
                kept = order_draft.load(scope.session_id)
                kept.order_confirmed = True
                order_draft.save(scope.session_id, kept)
            wanted["checkout"] = True
            return None
        if kind == "more":
            if agreed:
                if also_says:
                    return None
                return _answering(
                    _hold("Of course. What else can I get you?", yes="name_one")
                )
            # Done adding, so the next thing is the order itself.
            wanted["checkout"] = True
            return None
        if kind == "checkout":
            if agreed:
                wanted["checkout"] = True
                return None
            if also_says:
                return None
            return _answering(
                _hold("No rush. What else can I get you?", yes="name_one")
            )
        if kind == "name_one":
            # "Yes" to "which one would you like" answers nothing, and asking
            # it again in the same words is how a customer decides nobody is
            # there. The way out is to make it answerable.
            if also_says:
                return None
            if not agreed:
                # "No", "that's all", "nothing else": they do not want
                # another dish. Asking which one again is arguing with them,
                # and it is what shipped — the same sentence twice, once for
                # the yes and once for the no.
                #
                # BOTH questions go. A list is written down twice — `awaiting`
                # for what agreeing does, `pending_choice` for the dishes
                # offered — and letting go of only the first left the second
                # standing, so the re-ask guard fired on it anyway and the
                # customer was told off for declining.
                _forget_awaiting()
                _forget_choice()
                # Being done with the food is the start of checking out, and
                # the rest of the turn is where that is handled. On an empty
                # cart it says so plainly instead.
                wanted["checkout"] = True
                return None
            # They agreed and named nothing. If a list of ours is already in
            # front of them, that is what they agreed to — put it again
            # rather than replacing it with three different dishes. Live,
            # eight dhoklas were listed, "yes" arrived, and the reply was
            # "Of course. These go quickly:" over an unrelated three.
            standing_list = reask_standing_choice(_pending_choice() or _last_shown())
            if standing_list:
                return _answering(standing_list)
            # Nothing in front of them. A list is answerable in a way the
            # question is not, and it records what it offered, so the next
            # message can pick from it.
            offered = _suggest_more()
            if offered is not None:
                return offered
            return _answering(
                _hold(
                    "Happy to. Which one — just tell me the name and I will add it.",
                    yes="name_one",
                )
            )
        return None

    def _order_stood_behind() -> bool:
        """Whether this exact order has been read back and agreed to.

        True when there is no session to remember it in: a conversation with
        no memory must still be able to order.
        """

        if scope.session_id is None:
            return True
        kept = order_draft.load(scope.session_id)
        # Asked twice already. The order is created unpaid and the payment
        # link is what spends money, so a customer stuck behind a question
        # they have answered is the worse failure of the two.
        return bool(kept.order_confirmed) or int(kept.place_asks or 0) >= 2

    def _read_the_order_back() -> TurnOutcome | None:
        """Put the whole order to them, once, and hold the question."""

        held = tools_module._draft_for(scope) if scope.session_id is not None else None
        # The same arithmetic checkout runs, so the figure they agree to is
        # the figure they are charged.
        quote = None
        if db is not None and cart:
            try:
                wanted_type = tools_module.OrderFulfillmentType(
                    (held.fulfillment_type if held else None)
                    or tools_module.OrderFulfillmentType.DELIVERY.value
                )
                quote = TOOLS["price_quote"].handler(
                    db,
                    scope,
                    tools_module.PriceQuoteArgs(
                        lines=_as_tool_lines(cart), fulfillment_type=wanted_type
                    ),
                )
            except Exception:  # noqa: BLE001 - an unpriced read-back still reads back
                logger.warning("Ordering agent could not price the order to read back", exc_info=True)
        said = describe_order_to_confirm(cart_result, held, quote)
        if said is None:
            return None
        if scope.session_id is not None:
            kept = order_draft.load(scope.session_id)
            kept.place_asks = int(kept.place_asks or 0) + 1
            order_draft.save(scope.session_id, kept)
        return _answering(_hold(said, yes="place", asks="Shall I place your order?"))

    def _order_changed_under_them() -> None:
        """A cart that changed is not the order they agreed to."""

        if scope.session_id is None:
            return
        kept = order_draft.load(scope.session_id)
        if kept.order_confirmed or kept.place_asks:
            kept.order_confirmed = False
            kept.place_asks = 0
            order_draft.save(scope.session_id, kept)

    def _pending_choice() -> dict[str, Any] | None:
        """The question this conversation is waiting on an answer to."""

        if scope.session_id is None:
            return None
        raw = order_draft.load(scope.session_id).pending_choice
        if not raw:
            return None
        try:
            stored = json.loads(raw)
        except ValueError:
            return None
        return stored if isinstance(stored, dict) and stored.get("options") else None

    def _remember_choice(
        result: dict[str, Any],
        base: dict[str, Any] | None = None,
        later: list[dict[str, Any]] | None = None,
    ) -> None:
        """Write down the question just asked, with the ids behind it.

        A turn's records do not survive it. Without this the size question
        was asked correctly and the answer had nothing to land on.

        Three more things travel with it so the last required answer can decide
        whether anything optional is still worth offering, without going back
        to the database: each required group's option ids, whether a size is
        still wanted, and the optional groups nobody has been shown. `later` is
        passed explicitly once one of them has been offered, so the rest carry
        forward rather than being re-derived from a question that no longer
        mentions them.
        """

        if scope.session_id is None:
            return
        options = [
            {"name": str(size.get("name")), "size_id": str(size.get("size_id"))}
            for size in (result.get("available_sizes") or [])
            if size.get("size_id") and size.get("name")
        ]
        for group in result.get("customization_groups") or []:
            if not group.get("needs_selection"):
                continue
            for option in group.get("options") or []:
                if option.get("option_id") and option.get("name"):
                    options.append({"name": str(option["name"]), "option_id": str(option["option_id"])})
        if not options:
            return
        # What has already been settled travels with the question. Live:
        # "sweet chilli" was sent on its own, so the size chosen a message
        # earlier was gone and the dish asked for a size again — a customer
        # could answer correctly for ever and never finish.
        settled = dict(base or {})
        settled.setdefault("menu_item_id", str(result.get("menu_item_id")))
        settled.setdefault("quantity", int(result.get("quantity") or 1))
        groups = [g for g in (result.get("customization_groups") or []) if isinstance(g, dict)]
        draft_now = order_draft.load(scope.session_id)
        draft_now.pending_choice = json.dumps({
            "base": {k: v for k, v in settled.items() if v is not None},
            "question": ask_for_choice(result) or "",
            "options": options,
            # For `next_optional_group`, which runs when the last required
            # answer arrives and has no database to ask.
            "name": str(result.get("name") or ""),
            "needs_size": bool(result.get("needs_size")),
            "required": [
                [str(o.get("option_id")) for o in (g.get("options") or []) if o.get("option_id")]
                for g in groups
                if g.get("is_required")
            ],
            "later": [
                storable_group(g)
                for g in (
                    later
                    if later is not None
                    else [g for g in groups if not g.get("is_required") and g.get("options")]
                )
            ],
            # How many times this has been put to the customer.
            # Reset whenever something was actually settled. A customer
            # answering a three-part question correctly is not a customer
            # who cannot answer, and the do-not-repeat rule would have given
            # up on them two picks in.
            "asks": 1 if _made_progress(base) else int((_pending_choice() or {}).get("asks", 0)) + 1,
        })
        order_draft.save(scope.session_id, draft_now)

    def _last_shown() -> dict[str, Any] | None:
        """The dishes last put in front of this customer, if any."""

        if scope.session_id is None:
            return None
        raw = order_draft.load(scope.session_id).last_shown
        if not raw:
            return None
        try:
            stored = json.loads(raw)
        except ValueError:
            return None
        return stored if isinstance(stored, dict) and stored.get("options") else None

    def _last_question() -> str | None:
        """The question the last reply ended on, as recorded for this session.

        A browser sends the previous reply back with the next message
        (`previous_reply`); a chat thread has no client to carry it, so on
        WhatsApp this store is the only memory of what a bare "yes" is
        answering.
        """

        if scope.session_id is None:
            return None
        return order_draft.load(scope.session_id).last_question

    def _remember_shown(names: list[str]) -> None:
        """Write down what was just shown, replacing whatever was there.

        Only the last list. Two turns back is not what "the first one" means,
        and keeping a history would let a stale name win over a fresh one.
        """

        options = [{"name": str(name)} for name in names if str(name).strip()]
        if scope.session_id is None or not options:
            return
        draft_now = order_draft.load(scope.session_id)
        draft_now.last_shown = json.dumps({"options": options})
        order_draft.save(scope.session_id, draft_now)

    def _forget_shown() -> None:
        """Nothing is in front of them as a list any more.

        `last_shown` survives until another list replaces it, which is right
        while lists follow lists and wrong the moment something more specific
        does. A single dish, or a question about one, supersedes it.
        """

        if scope.session_id is None:
            return
        draft_now = order_draft.load(scope.session_id)
        if draft_now.last_shown:
            draft_now.last_shown = None
            order_draft.save(scope.session_id, draft_now)

    def _remember_dish_choice(question: str, shown: list[dict[str, Any]]) -> None:
        """Write down the dishes just read out, so the next message can pick one.

        `_hold` already records the QUESTION. It does not record the answers,
        and the answers are the half that matters: everything handling "they
        picked one of the things we offered" hangs off `pending_choice` — the
        reading is told the options through it, `_answer_dish_choice` maps a
        name onto it, and the never-ask-twice guard is keyed on it.

        Live, without this: eight appetizers were read out, "Which one would
        you like?" was asked, and "Money Bags" came back — the name of one of
        the eight. With nothing written down the reading had only its general
        schema to fall through to, which offers "the customer's name". The
        dish was filed as the customer's name, the cart stayed empty, and
        saying it again produced the same paragraph word for word.

        Names only. A dish is resolved against the branch's own menu when it
        is picked, through the same guarded lookup a typed name goes through,
        so an id recorded here would be a second source of truth for no gain.
        """

        options = [{"name": str(dish["name"])} for dish in shown if dish.get("name")]
        if scope.session_id is None or not options:
            return
        draft_now = order_draft.load(scope.session_id)
        draft_now.pending_choice = json.dumps(
            {"kind": "dish", "question": question, "options": options, "asks": 1}
        )
        # The same list, in the softer store too: if the question is later
        # given up on, the dishes are still the ones they were just shown.
        draft_now.last_shown = json.dumps({"options": options})
        order_draft.save(scope.session_id, draft_now)

    def _answer_dish_choice(asked: dict[str, Any], chose: list[str]) -> list[dict[str, Any]]:
        """Add the dishes they picked out of the list we read them.

        Matched against what was OFFERED and nothing else, exactly as
        `_answer_choice` matches a size: an answer to a question nobody asked
        must not put something in somebody's cart. The matched name then goes
        through `_add_named_dish`, so the add is resolved and guarded the way
        a dish typed from nowhere would be. This decides WHICH of our own
        words they meant, never what is on the menu.
        """

        added: list[dict[str, Any]] = []
        for one in chose:
            wanted_name = one.strip().casefold()
            # Naming the same dish twice in one message is naming it once.
            # The reading returns a list because a group orders for a group,
            # not because "Money Bags, Money Bags" means two.
            if not wanted_name or wanted_name in _picked_this_turn:
                continue
            _picked_this_turn.add(wanted_name)
            picked = next(
                (o for o in asked["options"] if o["name"].strip().casefold() == wanted_name),
                None,
            ) or next(
                (o for o in asked["options"]
                 if wanted_name in o["name"].strip().casefold()
                 or o["name"].strip().casefold().startswith(wanted_name)),
                None,
            )
            if picked is None:
                continue
            added.extend(_add_named_dish(picked["name"], 1))
        if added:
            _forget_choice()
        return added

    def _made_progress(base: dict[str, Any] | None) -> bool:
        """Whether this attempt settled something the last one had not."""

        before = (_pending_choice() or {}).get("base") or {}
        after = base or {}
        return (
            after.get("menu_item_size_id") != before.get("menu_item_size_id")
            or len(after.get("selected_options") or []) != len(before.get("selected_options") or [])
        )

    def _forget_choice() -> None:
        if scope.session_id is None:
            return
        draft_now = order_draft.load(scope.session_id)
        if draft_now.pending_choice:
            draft_now.pending_choice = None
            order_draft.save(scope.session_id, draft_now)

    def _answer_choice(asked: dict[str, Any], chose: list[str]) -> list[dict[str, Any]]:
        """Add the dish with the options the customer picked.

        Every name is matched against the options that were OFFERED, never
        against the menu at large: an answer to a question nobody asked must
        not put something in somebody's cart. Several at once, because a
        group can want three and a customer can name three.
        """

        args: dict[str, Any] = dict(asked.get("base") or {})
        args.setdefault("quantity", 1)
        chosen = list(args.get("selected_options") or [])
        taken = 0
        for one in chose:
            wanted_name = one.strip().casefold()
            picked = next(
                (o for o in asked["options"] if o["name"].strip().casefold() == wanted_name),
                None,
            )
            if picked is None:
                picked = next(
                    (o for o in asked["options"]
                     if wanted_name in o["name"].strip().casefold()
                     or o["name"].strip().casefold().startswith(wanted_name)),
                    None,
                )
            if picked is None:
                continue
            taken += 1
            if picked.get("size_id"):
                args["menu_item_size_id"] = picked["size_id"]
            else:
                chosen.append({"option_id": picked["option_id"]})
        if not taken:
            return []
        if chosen:
            args["selected_options"] = chosen
        guards.grow_seen_ids(seen, args)

        # Everything required is settled, so this add would land — which is the
        # only moment an optional group can still be offered. After it, the
        # dish is in the cart and nothing asks.
        offering = next_optional_group(asked, args)
        if offering is not None:
            _offer_optional(asked, args, offering)
            return []

        added = _run_add(args)
        if added:
            _forget_choice()
        return added

    def _offer_optional(
        asked: dict[str, Any], args: dict[str, Any], group: dict[str, Any]
    ) -> None:
        """Ask about one optional group, carrying everything settled with it.

        Built as a `needs_choice` so it goes through the same composer and the
        same memory as every other question: `ask_for_choice` already says "you
        can choose more than one" for a group that takes several, and
        `_remember_choice` already matches an answer against the ids offered.
        """

        rest = [
            other
            for other in (asked.get("later") or [])
            if isinstance(other, dict) and other.get("group_id") != group.get("group_id")
        ]
        offered = {
            "outcome": "needs_choice",
            "name": asked.get("name") or "",
            "menu_item_id": args.get("menu_item_id"),
            "quantity": args.get("quantity") or 1,
            "needs_size": False,
            "available_sizes": [],
            # Marked as wanted, because that is exactly what asking means.
            "customization_groups": [{**group, "needs_selection": True}],
        }
        records.append(ToolCallRecord(tool="add_to_cart", args=dict(args), result=offered))
        _remember_choice(offered, args, later=rest)
        # Marked optional so the turn knows this question may be walked past.
        if scope.session_id is not None:
            draft_now = order_draft.load(scope.session_id)
            stored = _pending_choice() or {}
            stored["optional"] = True
            draft_now.pending_choice = json.dumps(stored)
            order_draft.save(scope.session_id, draft_now)

    def _add_named_dish(name: str, quantity: int) -> list[dict[str, Any]]:
        """Put a dish the customer named into the cart.

        The name is resolved against this branch's own menu through the same
        lookup and confidence guardrail `get_dish` uses, so a dish that does
        not exist cannot be added by naming it convincingly, and the add goes
        through the same guard and handler a planned call would.
        """

        if db is None or not scope.restaurant_location_id:
            return []

        # A number can belong to the name. "four cheese pizza" read as four
        # of "cheese pizza" put four Cheese Burst Pizzas in a cart; the whole
        # phrase names a real dish, so it is tried first and wins when the
        # menu agrees. `_NUMERALS` is spelling, not meaning — it only lets
        # the phrase be reassembled the way the customer wrote it.
        if quantity > 1 and quantity in _NUMERALS:
            whole = f"{_NUMERALS[quantity]} {name}"
            if any(whole.casefold() == dish.casefold() for _, dish in
                   tools_module.dishes_matching_words(db, scope, whole)):
                name, quantity = whole, 1

        # Which dishes could they have meant, from the menu's own words. The
        # lookup below reports `confidence: "named"` for a near miss as
        # readily as for the real thing, so a name that fits several dishes
        # is a question, not a choice this agent gets to make with somebody's
        # money.
        want_veg = True if (scope.diet or "").lower() == "veg" else None
        candidates = tools_module.dishes_matching_words(db, scope, name, is_veg=want_veg)
        exact = [c for c in candidates if c[1].casefold() == name.casefold()]
        if not exact and len(candidates) > 1:
            listed = ", ".join(dish for _, dish in candidates[:-1]) + f" or {candidates[-1][1]}"
            records.append(ToolCallRecord(
                tool="get_dish", args={"name": name},
                result={"outcome": "ambiguous", "question": f"Did you mean {listed}?"},
            ))
            return []

        resolved_args, lookup = guards.resolve_dish_name(
            db, scope, "add_to_cart",
            {"menu_item_id": exact[0][0] if exact else name, "quantity": quantity},
        )
        if resolved_args.get("menu_item_id") == name:
            logger.info("Ordering agent could not resolve a dish the customer asked for: %r", name)
            return []
        if lookup:
            guards.grow_seen_ids(seen, lookup)
            records.append(ToolCallRecord(tool="get_dish", args={"name": name}, result=lookup))
        if exact:
            guards.grow_seen_ids(seen, {"menu_item_id": exact[0][0]})
            return _run_add(resolved_args)

        # Nobody said this dish's name. The guard above only refuses when
        # SEVERAL dish names matched the words; a phrase matching none of them
        # fell straight through to the semantic cascade, which resolved a dish
        # and bought it. Live, from a customer naming pizza toppings:
        #
        #     > Mozzarella and mushroom
        #       Added 1 x Farmhouse Pizza to your order. Anything else?
        #
        # The count of near misses never changed whether the customer asked
        # for it. Only whether anything else would be asked before it landed:
        # a dish still needing a size says its own name in the size question,
        # so "khaman dhokla" keeps its one-step path and only a dish that
        # would land silently costs a confirmation.
        if would_be_added_without_asking(lookup):
            # A question of ours is worth more than a guess of ours. Live,
            # mid-build with the crust question standing, "Mozzarella and
            # mushroom" — a customer naming toppings — was answered "Did you
            # mean Farmhouse Pizza?", which dropped the crust question and
            # offered an unrelated $329 pizza. Putting our own question again
            # keeps the half-built pizza alive.
            standing = reask_standing_choice(_pending_choice())
            found = str((lookup or {}).get("name") or "").strip()
            if standing or found:
                records.append(ToolCallRecord(
                    tool="get_dish", args={"name": name},
                    result={
                        "outcome": "ambiguous",
                        "question": standing or f"Did you mean {found}?",
                    },
                ))
            return []
        return _run_add(resolved_args)

    def _run_add(args: dict[str, Any]) -> list[dict[str, Any]]:
        """Run add_to_cart and keep what it says. A dish that needs a size
        answers `needs_choice`; the question is written down so the next
        message can answer it."""

        prepared, guard_error = guards.prepare_tool_call(
            "add_to_cart", args, cart=cart, seen=seen, diet=scope.diet
        )
        if guard_error is not None:
            logger.info("Ordering agent could not add what was asked for: %s", guard_error)
            return []
        try:
            result = TOOLS["add_to_cart"].handler(db, scope, prepared)
        except Exception as error:  # noqa: BLE001 - never lose the turn over it
            logger.warning("Ordering agent add raised: %s", error, exc_info=True)
            return []
        result = guards.enforce_destructive_policy(result)
        guards.grow_seen_ids(seen, result)
        records.append(ToolCallRecord(tool="add_to_cart", args=prepared.model_dump(), result=result))
        if isinstance(result, dict) and result.get("outcome") == "needs_choice":
            _remember_choice(result, args)
        action = result.get("action") if isinstance(result, dict) else None
        return [action] if action else []

    def _run_remove(line: dict[str, Any]) -> list[dict[str, Any]]:
        """Take one line off, through the same guard a planned call goes
        through.

        The line comes from `view_cart`, so its id is one the customer's own
        cart is holding rather than a name the model hopes exists — which is
        exactly what `RemoveFromCartArgs` asks for. It is grown into `seen`
        for the same reason: the guard refuses a dish nothing showed this
        turn, and our own cart read-back is what showed it.
        """

        args = {
            "menu_item_id": line.get("menu_item_id"),
            "existing_lines": _as_tool_lines(cart),
        }
        guards.grow_seen_ids(seen, {"menu_item_id": line.get("menu_item_id")})
        prepared, guard_error = guards.prepare_tool_call(
            "remove_from_cart", args, cart=cart, seen=seen, diet=scope.diet
        )
        if guard_error is not None:
            logger.info("Ordering agent could not take that off: %s", guard_error)
            return []
        try:
            result = TOOLS["remove_from_cart"].handler(db, scope, prepared)
        except Exception as error:  # noqa: BLE001 - never lose the turn over it
            logger.warning("Ordering agent remove raised: %s", error, exc_info=True)
            return []
        result = guards.enforce_destructive_policy(result)
        records.append(
            ToolCallRecord(tool="remove_from_cart", args=prepared.model_dump(), result=result)
        )
        action = result.get("action") if isinstance(result, dict) else None
        return [action] if action else []

    def _add_what_was_asked_for() -> list[dict[str, Any]]:
        """Carry out the add the planner would not.

        Only from a turn that achieved nothing, so the happy path pays for
        no extra round. The message is read narrowly for a dish, the name is
        resolved against this branch's menu (never the model's word for what
        exists), and the add goes through the same guard and handler any
        planned call would.
        """

        if db is None or actions or not scope.restaurant_location_id:
            return []
        asked = extract_cart_request(message, generate=generate)
        if asked is None:
            return []
        return _add_named_dish(*asked)

    def _capped(reason: str) -> TurnOutcome:
        # A cap with a needs_choice result in hand is not a failed turn: the
        # question is asked from the tool's rows (see `ask_for_choice`), and
        # the turn ends as a success. Any other cap keeps the brief's rule —
        # no partial answer, the caller falls back to today's reply.
        # Nothing done and nothing said: the likeliest reason is that the
        # customer asked for a dish and the planner went in circles.
        actions.extend(_add_what_was_asked_for())

        ready_now = _still_missing() == [] and (_identifiable(scope) and bool(cart))
        # A channel with no button, everything gathered, and rounds spent
        # arguing with itself: place it. The model would not, measured over
        # five different ways of asking, and the customer has already given
        # everything an order needs. It is created unpaid, so the
        # confirmation that matters is still theirs — opening the link.
        already_tried = any(r.tool == "place_order" for r in records)
        if (
            auto_place
            and placing_wanted
            and ready_now
            and not placed_order_in(records)
            and not already_tried
            # Not at the cap either. An order nobody has agreed to is not
            # improved by the turn having run out of rounds.
            and _order_stood_behind()
        ):
            prepared, guard_error = guards.prepare_tool_call(
                "place_order", {}, cart=cart, seen=seen, diet=scope.diet
            )
            if guard_error is None:
                try:
                    # A read that failed earlier in the turn leaves the
                    # session needing one before anything can be written.
                    # Nothing the agent wants is pending — its tools commit
                    # their own work — so this only clears the wreckage.
                    if db is not None and getattr(db, "is_active", True) is False:
                        db.rollback()
                    result = TOOLS["place_order"].handler(db, scope, prepared)
                    records.append(
                        ToolCallRecord(tool="place_order", args=prepared.model_dump(), result=result)
                    )
                except Exception as error:  # noqa: BLE001 - never lose the turn over it
                    logger.warning("Ordering agent could not place at the cap: %s", error, exc_info=True)

        # Computed once and reused below, because `_hold_the_question` tells
        # which sentence this is by identity: calling `describe_applied` twice
        # returns two equal strings that are not the same object.
        applied = describe_applied(records, goes_with=_goes_with(records))
        summary = _cart_summary_in(records) or cart_readback
        question = (
            describe_placed_order(placed_order_in(records))
            or applied
            or _choice_question_in(records)
            or describe_time_problem(records)
            or describe_time_settled(records)
            or describe_place_failure(records)
            or describe_collecting(_still_missing())
            or (describe_ready() if ready_now else None)
            or summary
        )
        if question is not None:
            logger.info("Ordering agent asked the needs_choice question itself after %s", reason)
            # The same rule `_settled` uses. It was missing here, and a slow
            # turn is exactly when it matters: this path asked "Anything
            # else?" without recording it, so the customer's "No" answered
            # nothing and was searched for on the menu instead.
            _hold_the_question(question, applied=applied, summary=summary)
            # A read-back the loop composed from cart or choice rows is about
            # those rows, whatever the model would have called it.
            return TurnOutcome(
                answer=question, actions=actions, records=records,
                fallback_reason=None, elapsed_seconds=clock() - start,
                answer_about="order" if collecting is not None else "cart",
                placed_order=placed_order_in(records),
                ready_to_place=ready_now and placed_order_in(records) is None,
            )
        return TurnOutcome(
            answer=None, actions=actions, records=records,
            fallback_reason=reason, elapsed_seconds=clock() - start,
            ready_to_place=ready_now and placed_order_in(records) is None,
        )

    def _hold_the_question(
        answer: str | None, *, applied: str | None, summary: str | None
    ) -> None:
        """Record the question a read-back ends on, so the answer to it lands.

        Every sentence this agent ends on is a question, and the next message
        is usually its answer — "No" to "Anything else?" means stop adding,
        not "find me a dish called No". `_hold` is what makes that possible,
        and for a while only ONE of the two paths that compose these sentences
        called it.

        Which sentence it is, is decided by identity rather than by matching
        the words: the composers build these strings from live rows, and a
        comparison against a literal here would go quietly wrong the first
        time one of them was reworded.
        """

        if not answer:
            return
        if applied is not None and answer is applied:
            _hold("Anything else?", yes="more")
        elif summary is not None and answer is summary:
            _hold("Ready to check out?", yes="checkout")

    def _goes_with(records: list[ToolCallRecord]) -> list[dict[str, Any]]:
        """A couple of things to offer alongside what was just added.

        Rows, never taste: `dishes_to_suggest` orders by this branch's own
        bestseller and popularity columns and takes at most one per section,
        so three suggestions are three ideas rather than three main courses.

        The dish just added is excluded explicitly. The cart this turn was
        handed predates it — the caller applies the actions afterwards — so
        without this the first thing offered alongside a pizza was that pizza.
        """

        if db is None or not scope.restaurant_location_id:
            return []
        just_added = [
            (r.result or {}).get("action", {}).get("menu_item_id")
            for r in records
            if isinstance(r.result, dict)
            and (r.result.get("action") or {}).get("kind") == "add"
        ]
        want_veg = True if (scope.diet or "").lower() == "veg" else None
        try:
            return tools_module.dishes_to_suggest(
                db,
                scope,
                in_cart=[line.menu_item_id for line in cart] + [i for i in just_added if i],
                is_veg=want_veg,
                limit=2,
            )
        except Exception:  # noqa: BLE001 - a suggestion is never worth the turn
            logger.warning("Ordering agent could not read suggestions", exc_info=True)
            return []

    def _settled(asked_to_see_cart: bool = False) -> TurnOutcome:
        """The turn as the rows alone can end it — no words from the model.

        The order below is what to say when a turn ENDED somewhere: an order
        placed outranks a dish added, which outranks a question about a size.

        `asked_to_see_cart` turns that off for the one case where the customer
        asked a direct question. Live: "Show my cart", on a complete order,
        was answered "That is everything I need to place your order." — true,
        and not what they asked. Then "I want to see my cart" got the same
        sentence again.
        """

        placed = placed_order_in(records)
        applied = describe_applied(records, goes_with=_goes_with(records))
        summary = _cart_summary_in(records) or cart_readback
        if asked_to_see_cart and summary:
            answer = summary
        else:
            answer = (
                describe_placed_order(placed)
                or applied
                or _choice_question_in(records)
                or describe_time_problem(records)
                or describe_time_settled(records)
                or describe_place_failure(records)
                or describe_collecting(_still_missing())
                or (describe_ready() if _still_missing() == [] and collecting is not None and cart else None)
                or summary
            )
        # Whatever question this read-back ends on is held, so that the next
        # message can be read against it rather than against nothing.
        _hold_the_question(answer, applied=applied, summary=summary)
        return TurnOutcome(
            answer=answer,
            placed_order=placed,
            ready_to_place=_still_missing() == [] and (_identifiable(scope) and bool(cart)) and placed is None,
            answer_about="order",
            actions=actions,
            records=records,
            fallback_reason=None,
            elapsed_seconds=clock() - start,
        )

    # What this message wants, read once before any planning. Everything the
    # agent guarantees hangs off a tool having run, and the planner answers
    # in prose instead often enough that three conversations in a row died
    # here — asking to check out and giving a name, an email and an address,
    # each answered pleasantly with nothing done. See `read_order_intent`.
    # A sentence that plainly says one thing is read off the sentence. Only
    # ever a read, and only when it says nothing else — see `quick_read`.
    held_question = _awaiting()
    if held_question is not None:
        _forget_awaiting()
    plain = quick_read(message)
    # Kept, so a reading that makes nothing of the message can fall back to
    # it rather than lose it. See where it is restored, below.
    plain_before_holding = plain
    if held_question is not None and plain == "checkout":
        # "Go ahead", "done", "kar do" are how people agree, and a question
        # of ours is standing — so this message is read as its answer rather
        # than shortcut into an instruction. Live: "haan bhai kar do", a yes
        # to "Shall I add one?", was answered "there is nothing in your order
        # yet". Asking to SEE something is never an answer to yes or no, so
        # "cart" and "menu" keep the fast path.
        plain = None
    if plain in {"cart", "checkout"} and not cart:
        # Asking about an order that has nothing in it. Measured: "checkout"
        # on an empty cart spent 17.9 seconds arriving at a menu suggestion,
        # and "cart" spent 6.5 — for a fact known before either started.
        return TurnOutcome(
            answer=_PLACE_FAILURE_LINES["empty_cart"],
            answer_about="cart",
            actions=actions,
            records=records,
            fallback_reason=None,
            elapsed_seconds=clock() - start,
        )
    if plain == "cart" and cart_readback:
        return _settled(asked_to_see_cart=True)
    if plain == "menu":
        # This used to stand aside — "the reply pipeline answers about the
        # menu, and better" — and live, it does not. There is no handler for
        # it there at all: "Menu" reaches retrieval as a search query, matches
        # no keyword, vector-matches eight arbitrary dishes, and the model
        # writes prose over them. On a real thread that produced a pitch for
        # the Tom Yum Prawn Pizza to somebody who had asked to see the menu.
        #
        # The sections are the answer, for the reason a restaurant hands over
        # a menu with sections instead of reciting 136 dishes — and naming one
        # back now reads out that whole section, so it leads somewhere.
        sections = (
            tools_module.branch_sections(db, scope)
            if db is not None and scope.restaurant_location_id
            else []
        )
        offer = tools_module.offer_of_sections(sections)
        if offer:
            return TurnOutcome(
                # `asks` is the short question; the customer gets the list.
                # `_hold` records a short one on purpose — a long read-back
                # given to the model AS the question gets mined for its
                # contents, and a list of every section is that shape exactly.
                answer=_hold(offer, yes="name_one", asks=_WHICH_SECTION),
                answer_about="menu",
                actions=actions,
                records=records,
                fallback_reason=None,
                elapsed_seconds=clock() - start,
            )
        # A branch with no sections has nothing better to offer than whatever
        # the pipeline makes of it, which is the one case the old behaviour
        # was right about.
        return TurnOutcome(
            answer=None, actions=actions, records=records,
            fallback_reason=None, elapsed_seconds=clock() - start,
        )

    # The branch's clock and any time it already offered, for the reading.
    now_local = branch_hours._localize_reference_datetime(None)
    standing_offer = None
    if scope.session_id is not None:
        offered_iso = order_draft.load(scope.session_id).offered_scheduled_at
        if offered_iso:
            try:
                standing_offer = datetime.fromisoformat(offered_iso).astimezone(
                    branch_hours.BUSINESS_TIMEZONE
                ).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                standing_offer = None
    # Whether this message asks for the order to go. Without it, a complete
    # draft meant every turn tried to place — so a closed branch answered
    # "No", "No" and "what can I have for lunch?" with the same offer.
    placing_wanted = False
    asked_before = _pending_choice()
    # What was last put in front of them, when no question of ours is
    # standing. The agent's own question wins where there is one: it is the
    # more specific thing outstanding.
    shown_before = None if asked_before else _last_shown()
    # The sections this branch actually sells, so "some drink" can find
    # Beverages. Rows, given to the reading; the mapping is meaning.
    sections: list[str] = []
    if db is not None and scope.restaurant_location_id:
        try:
            sections = tools_module.menu_categories(db, scope)
        except Exception:  # noqa: BLE001 - a menu we cannot list is not a broken turn
            sections = []
    # Details of theirs we are holding but which nobody has stood behind.
    unconfirmed = _details_to_confirm()
    # The question we ended the last turn on, if it is the thing outstanding.
    # Read once and dropped: every turn that ends on a question writes a
    # fresh one, so a question nobody answered never lingers into a third.
    # A time the kitchen offered, or details read back, are the more
    # specific thing outstanding and answer a "yes" first.
    standing = held_question if not standing_offer and not unconfirmed else None
    wanted = (
        {"add": None, "details": {}, "checkout": True, "when": None,
         "chose": None, "confirms": None, "browse": None, "asks_hours": False}
        if plain == "checkout"
        else read_order_intent(
            message,
            missing=collecting or (),
            generate=generate,
            now_local=now_local.strftime("%A %Y-%m-%d %H:%M"),
            offered=standing_offer,
            choice_question=(
                (asked_before or {}).get("question")
                or ("These were just shown to them." if shown_before else None)
            ),
            choice_options=[
                o["name"] for o in (asked_before or shown_before or {}).get("options", [])
            ],
            # Whatever a bare "yes" would be agreeing to. Measured: with a
            # time offered but nothing named as the question, the reading
            # answered "yes" with nothing at all, the turn fell through to
            # six planner rounds, and the same offer came back word for
            # word — the loop this is here to end.
            confirming=(
                unconfirmed
                or (f"the order for {standing_offer}" if standing_offer else None)
            ),
            # The question we ended the last turn on. A bare "yes" has no
            # meaning of its own; this is the meaning.
            #
            # Failing one of ours, the question the REPLY PIPELINE ended on.
            # It asks things in prose on most turns and records none of them,
            # so "yes" to "Would you prefer it with a side of naan?" reached
            # the reading with no referent at all, came back empty, and left
            # the planner to invent — on an empty cart — "you're ready to
            # proceed". Only the final sentence, and only if it is a short
            # question: see `question_asked_in`.
            asked=(
                (standing.get("asks") or standing["question"])
                if standing
                else question_asked_in(previous_reply) or _last_question()
            ),
            # The day they are choosing a time on, if that is the question.
            for_day=(
                standing.get("subject")
                if standing and standing.get("yes") == "time_on_day"
                else None
            ),
            categories=sections,
        )
    )

    # An optional group is an offer, not a gate, and this is the only window
    # in which that can be enforced: after the reading, and before the guard
    # below that re-asks a standing choice and returns. See
    # `docs/ordering-agent-turn-routing.md`.
    #
    # Resolved against the options HERE rather than from the reading, because
    # the reading is a model and does not agree with itself. Measured, with the
    # toppings question standing: "Mozzarella" came back as `chose` on one run
    # and "Mozzarella and mushroom" as an `add` for a dish of that name on the
    # next, while "no" read as `confirms: False` and "none" and "skip" set
    # nothing at all. The first version of this branched on those keys, and
    # lost pizzas: four questions answered, then "no", and the dish was never
    # added.
    #
    # Whatever the message was, the dish is added. The worst an optional group
    # may cost somebody is a pizza without toppings, never the pizza.
    if asked_before and asked_before.get("optional"):
        picked = options_named_in(message, asked_before)
        base_args = dict(asked_before.get("base") or {})
        # This dish is one WE put in front of them a turn ago, and the guard
        # that refuses a dish "the model never saw this turn" would otherwise
        # refuse our own offer back. Without it `_run_add` returned nothing
        # and the pizza was silently dropped on every refusal.
        guards.grow_seen_ids(seen, base_args)
        settled_now = (
            _answer_choice(asked_before, picked) if picked else _run_add(base_args)
        )
        if settled_now:
            actions.extend(settled_now)
            _forget_choice()
            asked_before = None

    # The model made nothing of a message that plainly says "I am done".
    # Measured: with a list standing, "that's all", "no", "nothing else" and
    # "that is all" every one came back empty, and the turn then told the
    # customer off for not answering.
    if (
        plain_before_holding == "checkout"
        and plain is None
        and not any(
            wanted.get(key)
            for key in (
                "add", "details", "chose", "when", "browse", "category",
                "wants_to_add", "cancel_order", "pay_now", "asks_hours",
            )
        )
        and wanted.get("confirms") is None
    ):
        wanted["checkout"] = True

    # "Yes" means the thing that was last put to them. With a time offered
    # and nothing else pending, that is the time — measured: a bare "yes"
    # was read as a confirmation of nothing and the same offer came back
    # word for word.
    if (
        wanted.get("confirms") is True
        and standing_offer
        and not unconfirmed
        and not wanted.get("when")
    ):
        wanted["when"] = standing_offer
        wanted["confirms"] = None

    # "Yes" means the question we ended on, whatever words it arrives in.
    if standing is not None and wanted.get("confirms") is not None:
        settled = _answer_standing(standing, wanted, agreed=wanted["confirms"] is True)
        if settled is not None:
            return settled
        wanted["confirms"] = None

    # An order already placed, and a time for it: they are moving that
    # order, not scheduling a basket they no longer have.
    if wanted.get("when") and not cart and db is not None:
        order = _waiting_order()
        if order is not None and len(str(wanted["when"]).strip()) > 10:
            try:
                moved_to = datetime.strptime(wanted["when"], "%Y-%m-%d %H:%M").replace(
                    tzinfo=branch_hours.BUSINESS_TIMEZONE
                )
            except ValueError:
                moved_to = None
            if moved_to is not None:
                moved, why_not = open_orders.move_to(db, order, when=moved_to)
                if moved:
                    return _answering(
                        _with_link(order, f"Moved — your order is now for {moved_to:%a %H:%M}.")
                    )
                return _answering(
                    f"I could not move it to then: {str(why_not or '').rstrip('.')}. "
                    "Tell me another time and I will try that."
                )

    if wanted.get("pay_now") and db is not None:
        order = _waiting_order()
        if order is not None:
            return _answering(_with_link(order, f"{_order_line(order)} and is waiting to be paid."))

    # Dropping an order is never assumed. A message naming a dish is a cart
    # edit however it is read — live, "remove the corn fritters" came back as
    # a cancellation — so only a message about nothing else gets this far,
    # and even then it is a question rather than a deletion.
    if (
        wanted.get("cancel_order")
        and not wanted["add"]
        and not wanted.get("browse")
        and db is not None
    ):
        order = _waiting_order()
        if order is not None:
            return _ask_about_waiting(order, they_asked_to_cancel=True)

        # No order to cancel, but a cart to edit. The comment above is the
        # whole reason: "a message naming a dish is a cart edit however it is
        # read". The reading collapses "remove the khaman", "take it off" and
        # "delete the dhokla" into `cancel_order` alike, so which line — if
        # any — is decided here from the cart's own rows. Live, before this,
        # all of those were answered by reading the cart back with the dish
        # still in it; whether anything came off depended on whether the
        # model's tool loop happened to call `remove_from_cart` by itself.
        cart_lines = (cart_result or {}).get("lines") if isinstance(cart_result, dict) else None
        if cart_lines:
            going = line_to_remove(message, cart_lines)
            if going is not None:
                taken = _run_remove(going)
                if taken:
                    actions.extend(taken)
                    return _settled()
            elif len(cart_lines) > 1:
                # Several to choose from and nothing named. Guessing throws
                # away something somebody chose.
                listed = ", ".join(str(line.get("name")) for line in cart_lines if line.get("name"))
                return _answering(
                    _hold(f"Which one shall I take off? {listed}.", yes="name_one")
                )

    if wanted.get("when") and scope.session_id is not None:
        _take_time(wanted["when"])
        placing_wanted = True

    if wanted.get("confirms") is True and scope.session_id is not None:
        kept = order_draft.load(scope.session_id)
        kept.confirmed = True
        order_draft.save(scope.session_id, kept)
        collecting = _still_missing() or []
        placing_wanted = True
        # Their details were read back in order to place the order, so
        # agreeing to them is agreeing to get on with it. Live: "yes" to
        # "Shall I use them?" ran no tool at all and the turn fell through to
        # a reply pipeline that said "please proceed to pay" — with nothing
        # to pay for and no link.
        if collecting == []:
            wanted["checkout"] = True
    elif wanted.get("confirms") is False and scope.session_id is not None:
        kept = order_draft.load(scope.session_id)
        if standing_offer and not unconfirmed:
            # "No" to a time is about the time. Read as a rejection of their
            # details it wiped the delivery address — every turn, four turns
            # running — and then asked for it again.
            kept.offered_scheduled_at = None
            order_draft.save(scope.session_id, kept)
            return TurnOutcome(
                answer=(
                    "No problem — I will hold it. Tell me a time that suits you, "
                    "or say what else you would like."
                ),
                answer_about="order",
                actions=actions,
                records=records,
                fallback_reason=None,
                elapsed_seconds=clock() - start,
            )
        # Otherwise it is the details they are rejecting, so what we hold is
        # dropped rather than argued about and asked for again from nothing.
        kept.delivery_address = None
        kept.confirmed = True
        kept.confirm_asks = 0
        order_draft.save(scope.session_id, kept)
        collecting = _still_missing() or []

    # Nothing in this message answered anything, AND it asked for nothing
    # else either. A question already asked is kept rather than dropped — and
    # never repeated word for word.
    #
    # The second half of that condition is the load-bearing half. This guard
    # used to weigh only the four fields that ANSWER a question, so a message
    # that plainly asked for something new — "is anything vegetarian", which
    # reads as `browse` — counted as "nothing" and was answered "Sorry, I did
    # not catch that. Just reply with one of these". A customer who changes
    # the subject has not failed to answer; they have moved on, and telling
    # them off for it is worse than dropping the question.
    #
    # It did not show before dish lists were recorded as choices, because
    # `pending_choice` was only ever set by a size question, which a customer
    # rarely wanders away from.
    if (
        asked_before
        and scope.session_id is not None
        and not any(
            wanted.get(key)
            for key in (
                # Ways of answering the question.
                "chose", "add", "details", "checkout", "when",
                # Ways of asking for something else entirely.
                "browse", "category", "wants_to_add", "cancel_order",
                "pay_now", "asks_hours",
            )
        )
        # Saying no IS answering. Live: "that's all", after a list of three
        # dishes, was answered "Sorry, I did not catch that. Just reply with
        # one of these" — told off for declining.
        and wanted.get("confirms") is None
    ):
        return _reask_or_give_up(asked_before)

    # "What do you recommend" and "what's your cheapest" are answerable from
    # this branch's own columns, and were being searched for as dish names:
    # "I could not find what do you recommend on the menu." Routed through the
    # same guard as `wants_to_add` so that a question of ours already on the
    # table still wins — see docs/ordering-agent-turn-routing.md.
    if plain == "cheapest" and db is not None and scope.restaurant_location_id:
        # Only a standing CHOICE defers this, not a list we merely showed. The
        # greeting lists four dishes, so guarding on `shown_before` too meant
        # "what's your cheapest item" was skipped on every turn after hello —
        # which is every real turn.
        if not asked_before:
            want_veg = True if (scope.diet or "").lower() == "veg" else None
            cheapest = tools_module.cheapest_dishes(db, scope, is_veg=want_veg)
            if cheapest:
                listed = "\n".join(
                    f"- {d['name']} - {_money(d['price'])}" for d in cheapest
                )
                asked_now = _hold("Which one would you like?", yes="name_one")
                _remember_dish_choice(asked_now, cheapest)
                return TurnOutcome(
                    answer=f"These are the cheapest we have:\n{listed}\n\n{asked_now}",
                    answer_about="menu",
                    actions=actions,
                    records=records,
                    fallback_reason=None,
                    elapsed_seconds=clock() - start,
                )
    if plain == "suggest" and not asked_before:
        # Answered here rather than by setting `wants_to_add`, because that
        # guard sits BELOW the browse branch, and "what do you recommend" also
        # reads as browsing — so browse answered first and searched the menu
        # for the question. `_suggest_more` reads this branch's own bestsellers
        # and popularity, one per section, minus what is in the cart.
        offered_now = _suggest_more()
        if offered_now is not None:
            return offered_now

    if wanted.get("chose") and not asked_before and shown_before:
        # They picked one of the dishes the reply pipeline showed them. Only
        # ever an add: there is no question of ours to answer here, so a
        # message that names nothing on that list simply carries on to the
        # planner.
        answered = _answer_dish_choice(shown_before, wanted["chose"])
        if answered:
            actions.extend(answered)
    elif wanted.get("chose") and asked_before:
        # Two kinds of question end on a list. A size or a customization
        # option carries the id that settles it; a dish carries only its
        # name, and is resolved against the menu when it is picked. Sending
        # one to the other's handler raised KeyError on `option_id`.
        answered = (
            _answer_dish_choice(asked_before, wanted["chose"])
            if asked_before.get("kind") == "dish"
            else _answer_choice(asked_before, wanted["chose"])
        )
        if answered:
            actions.extend(answered)

    # Only when they have not named one. "Make it 12:30" reads as both a
    # question about time and a time, and the time is the instruction.
    if (
        wanted.get("asks_hours")
        and not wanted.get("when")
        and db is not None
        and scope.restaurant_location_id
    ):
        said = _describe_hours()
        if said:
            return TurnOutcome(
                answer=said, answer_about="order", actions=actions, records=records,
                fallback_reason=None, elapsed_seconds=clock() - start,
            )

    # A dish they named beats a section the reading also guessed at: a
    # customer saying "add a thai iced tea too" wants the drink, not the
    # list of drinks they would choose it from.
    # ...unless what they "named" IS the section. "Corn Dhokla" is the name of
    # a nine-dish section, the reading reads it as a dish to add, and the add
    # path then asked "Did you mean Butter Corn Dhokla, Garlic Corn Dhokla,
    # Jain Corn Dhokla, Jeera Corn Dhokla or Vegetable Corn Dhokla?" — five of
    # the nine, because it matched dish NAMES. Somebody who says the name of a
    # section has not named a dish, so there is no dish to beat the section.
    #
    # Word-set equality, so the case the comment above describes is untouched:
    # "add a thai iced tea too" is not the Beverages section's words, and still
    # adds the drink.
    names_the_section = wanted.get("category") and tools_module.category_named_exactly(
        message, [wanted.get("category")]
    )
    if (
        (wanted.get("browse") or wanted.get("category"))
        and (not wanted["add"] or names_the_section)
        and db is not None
        and scope.restaurant_location_id
    ):
        # Their own words when the reading gave none. "Tom Yum Soup" came
        # back as the Soups SECTION with no phrase at all, so all eight
        # soups were read out and the two words that said which soup were
        # thrown away. The message is the phrase of last resort.
        shown = _show_dishes(
            wanted.get("browse") or message.strip(),
            wanted.get("category"),
            wanted.get("max_price"),
        )
        if shown:
            return shown

    # They want more and have not said what. A restaurant suggests; it does
    # not read the cart back at somebody who just asked to add to it.
    if (
        wanted.get("wants_to_add")
        and not wanted["add"]
        and not wanted.get("browse")
        and not wanted.get("category")
        # ...and nothing of ours is waiting. A question already on the table
        # is a better answer than three new dishes. Live, with eight dhoklas
        # listed and "Which one would you like?" standing, "1" and "actually
        # make it 3" both read as `wants_to_add`, landed here, and were
        # answered "Of course. These go quickly:" over three unrelated
        # bestsellers — the dhoklas thrown away and the question dropped.
        and not asked_before
        and not shown_before
        and db is not None
        and scope.restaurant_location_id
    ):
        offered = _suggest_more()
        if offered is not None:
            return offered

    for one_dish in wanted["add"] or []:
        # One sentence can order more than one thing — but not the same
        # thing twice, and a dish already added by answering our question is
        # not a second order for it.
        if one_dish[0].strip().casefold() in _picked_this_turn:
            continue
        added = _add_named_dish(*one_dish)
        if added:
            actions.extend(added)
            _order_changed_under_them()

    if wanted["details"] and scope.session_id is not None:
        placing_wanted = True
        draft, problems = order_draft.remember(
            order_draft.load(scope.session_id), **wanted["details"]
        )
        # Giving your name is starting to check out, whether or not anybody
        # called the tool that says so.
        draft.collecting = True
        order_draft.save(scope.session_id, draft)
        collecting = _still_missing() or []
        records.append(
            ToolCallRecord(
                tool="save_order_details",
                args=dict(wanted["details"]),
                result={"outcome": "saved", "problems": problems, "missing": collecting},
            )
        )
        if not collecting and not cart and not actions:
            # Everything they were asked for, and nothing to put it towards.
            # This turn had nothing further to do and said NOTHING, so the
            # reply pipeline filled the silence — live, a customer who had
            # just typed their name, email and address read "I didn't quite
            # catch that. Ask me about food, restaurants, menus...".
            return TurnOutcome(
                answer=(
                    "Thanks — I have your details. What would you like to order?"
                ),
                answer_about="order",
                actions=actions,
                records=records,
                fallback_reason=None,
                elapsed_seconds=clock() - start,
            )

    if wanted["checkout"] and not cart and not actions:
        # Nothing to check out. Said plainly rather than left to a planner
        # that answered "let me check the details to ensure everything is
        # correct" over an order with nothing in it. `cart` is the turn's
        # opening snapshot, so what this turn just added counts too —
        # without that, "haan bhai kar do" added a drink and was answered
        # "there is nothing in your order yet".
        return TurnOutcome(
            answer=_PLACE_FAILURE_LINES["empty_cart"],
            answer_about="cart",
            actions=actions,
            records=records,
            fallback_reason=None,
            elapsed_seconds=clock() - start,
        )

    if wanted["checkout"]:
        placing_wanted = True

    if wanted["checkout"] and scope.session_id is not None and cart:
        prepared, guard_error = guards.prepare_tool_call(
            "order_requirements", {}, cart=cart, seen=seen, diet=scope.diet
        )
        if guard_error is None:
            result = TOOLS["order_requirements"].handler(db, scope, prepared)
            records.append(ToolCallRecord(tool="order_requirements", args={}, result=result))
            collecting = _still_missing() or []

    if records:
        # Something was actually done. Place it if this channel has no button
        # and nothing is missing; otherwise say what happened and what is
        # still needed. Either way the turn is over — no planning round can
        # improve on rows that already answer the question.
        if _details_to_confirm():
            return _ask_to_confirm()
        if (
            auto_place
            and placing_wanted
            and cart
            and _still_missing() == []
            and not placed_order_in(records)
        ):
            if not _order_stood_behind():
                asked = _read_the_order_back()
                if asked is not None:
                    return asked
            _place_now()
        return _settled()

    # Nothing to do, and an order of theirs sitting unpaid. Saying so beats
    # handing the turn to a reply pipeline that knows nothing about orders
    # and would answer about the menu while their food never arrives.
    if not cart and db is not None and scope.session_id is not None:
        order = _waiting_order()
        # Counted against the CONVERSATION, not the draft. The draft is wiped
        # every time an order is placed or cancelled, so the old counter began
        # again at zero for each one — and a customer holding eighteen unpaid
        # orders (beat was not running, so the reaper had never fired) was
        # handed the next one every single message, for ever.
        if order is not None and order_draft.waiting_notices(scope.session_id) < 2:
            order_draft.note_waiting_notice(scope.session_id)
            return _ask_about_waiting(order)

    for _round_index in range(rounds):
        # Checked before every model call, per the brief — a turn that is
        # already out of time never spends more of it asking the model for
        # one more step.
        if clock() - start >= budget:
            return _capped("budget_exceeded")

        ready = collecting == [] and (_identifiable(scope) and bool(cart))
        # On a channel with no button, being ready IS the instruction: the
        # model will not reach for the tool (measured, repeatedly), and the
        # customer has already asked to order and handed over their details.
        # Only straight after the customer asked to check out, or answered
        # what checking out needed — with everything now held. Any other
        # message is read by the model first: "wait, add a coke too" with
        # the details already known must add the coke, not place the order
        # without it. If the model then answers rather than acts, the answer
        # path below places; the round cap places too. (Measured: without
        # save_order_details here the model spent a 3.5s round resending it.)
        after_checkout_request = bool(records) and records[-1].tool in (
            "order_requirements",
            "save_order_details",
        )
        if auto_place and after_checkout_request and _still_missing() == [] and not placed_order_in(records):
            if not _order_stood_behind():
                asked = _read_the_order_back()
                if asked is not None:
                    return asked
            step = PlanStep(tool="place_order", args={})
        else:
            step = plan_step(
                message,
                history=tuple(records),
                generate=generate,
                tool_names=_offered_tools(seen, collecting is not None, ready, retired),
                previous_reply=previous_reply,
                # The thread is dropped once the state says exactly what to do.
                # It exists to resolve "yes" and "the second one"; with nothing
                # left to collect there is nothing to resolve, and on a live turn
                # the model answered by copying its own earlier question out of
                # it word for word instead of placing the order.
                recent_history=None if ready else recent_history,
                diet=scope.diet,
                cart_summary=cart_summary,
                collecting=collecting or None,
                pending=pending,
                ready_to_place=ready,
            )

        if not step.ok:
            if step.error == "planner_unavailable":
                # The model itself is unreachable; asking it again next
                # round would just fail the same way, so this is the one
                # planner error that stops the turn outright rather than
                # being fed back for the model to correct.
                return TurnOutcome(
                    answer=None,
                    actions=actions,
                    records=records,
                    fallback_reason="planner_unavailable",
                    elapsed_seconds=clock() - start,
                )
            # Every other planner error (unknown_tool, scope_argument,
            # invalid_arguments, planner_unusable) is recoverable *within*
            # this turn: the model sees what it did wrong and gets another
            # round to correct it. Still counts toward `max_rounds` — a
            # model that keeps making the same mistake is still bounded.
            repaired = _repair_named_dish(db, scope, step, seen, records)
            if repaired is None:
                # The third place a call can be refused, and the third
                # place a verbatim resend means the model is stuck. No tool
                # name or arguments survive a planner refusal (see
                # `_error_record`), so "the same refusal, word for word" is
                # the comparison — and the detail names what was refused.
                record = _error_record(step)
                if any(earlier.error == record.error for earlier in records):
                    return _capped("repeated_call")
                records.append(record)
                continue
            step = repaired

        # An answer the model itself calls an order answer, with a cart to
        # order and nothing started yet, is not an answer — it is the moment
        # to find out what is still needed. Live on WhatsApp: "let's go for
        # checkout" called no tool at all, so nothing owned the turn and the
        # customer was told that checkout was outside our kitchen.
        if (
            step.answer is not None
            and step.answer_about == "order"
            and cart
            and collecting is None
            and "order_requirements" in TOOLS
        ):
            step = PlanStep(tool="order_requirements", args={})

        # The details landed during THIS turn, so the check at the top of the
        # round saw an incomplete draft. Without this the customer is asked to
        # confirm on the next message what they have just finished giving.
        if (
            auto_place
            and placing_wanted
            and step.answer is not None
            and cart
            and _still_missing() == []
            and not placed_order_in(records)
            and "place_order" in TOOLS
        ):
            if not _order_stood_behind():
                asked = _read_the_order_back()
                if asked is not None:
                    return asked
            step = PlanStep(tool="place_order", args={})

        if step.answer is not None:
            # An answer that says nothing is not an answer. The tool results
            # hold the cart; prefer saying it to shipping an empty string and
            # letting the caller fall through to a layer with no cart at all.
            placed = placed_order_in(records)
            # A turn that placed an order is about that order, whatever the
            # model called it, and the read-back is the order's own figures.
            # What the rows say, to check what the model says against.
            facts = " ".join(
                [cart_readback or ""]
                + [json.dumps(record.result, default=str) for record in records if record.result]
            )
            said = step.answer.strip()
            if said and invented_figures(said, facts):
                logger.warning(
                    "Ordering agent answer quoted a figure no row carries: %r", said[:160]
                )
                said = ""
            named = names_a_tool(said) if said else None
            if named:
                # The model wrote its plan instead of carrying it out. What
                # the rows say is below; this sentence is not fit to send.
                logger.warning(
                    "Ordering agent answer named the tool %r to the customer: %r",
                    named,
                    said[:160],
                )
                said = ""
            spoken = (
                describe_placed_order(placed)
                or said
                or describe_applied(records)
                or _choice_question_in(records)
                or describe_time_problem(records)
                or describe_place_failure(records)
                or describe_time_problem(records)
                or describe_place_failure(records)
            or describe_collecting(_still_missing())
                or (describe_ready() if _still_missing() == [] and collecting is not None and cart else None)
                or _cart_summary_in(records)
                or cart_readback
                or _choice_question_in(records)
            )
            return TurnOutcome(
                answer=spoken,
                placed_order=placed,
                ready_to_place=(
                    _still_missing() == [] and (_identifiable(scope) and bool(cart)) and placed is None
                ),
                answer_about=(
                    "order" if (placed or collecting is not None) else step.answer_about
                ),
                actions=actions,
                records=records,
                fallback_reason=None,
                elapsed_seconds=clock() - start,
            )

        # `step.ok` and no answer means `step.tool` is set (`PlanStep.ok`'s
        # own definition) — one more tool to run before the turn can end.
        tool_name = step.tool or ""

        # Checked again before every tool call, separately from the model
        # check above: a plan can arrive right at the edge of the budget,
        # and running one more (possibly slow) handler past it would be the
        # "partial answer" the brief rules out, just paid for in tool time
        # instead of model time.
        if clock() - start >= budget:
            return _capped("budget_exceeded")

        prepared, guard_error = guards.prepare_tool_call(tool_name, step.args, cart=cart, seen=seen, diet=scope.diet)
        if guard_error is not None:
            if _repeated_call(records, tool_name, step.args) is not None:
                retired.add(tool_name)
            records.append(ToolCallRecord(tool=tool_name, args=step.args, error=guard_error))
            continue

        # Seen live on 2026-09-16: `add_to_cart` answered `needs_choice`
        # (correctly — the dish has a required group) and the model called it
        # again with byte-identical arguments, then again, until the round
        # cap. The prompt now says not to; this is the deterministic half of
        # that rule, so a model that ignores it burns a record, not a handler
        # call, and gets told which earlier result to read.
        repeated = _repeated_call(records, tool_name, prepared.model_dump())
        if repeated is not None:
            # Retired, not refused. Ending the turn here stopped the waste
            # and stopped the work with it: live, "I want margherita pizza"
            # searched, searched again and added nothing — three times over,
            # for three different dishes, and the customer went on to give a
            # name and an address for an order with no food in it. Taking
            # the tool off the table forces the next round to choose
            # something else. The handler still never runs twice on the same
            # arguments, which is what the speed fix was actually for.
            retired.add(tool_name)
            records.append(
                ToolCallRecord(
                    tool=tool_name,
                    args=prepared.model_dump(),
                    error=f"repeated_call: identical to call {repeated}; that tool is done for this turn",
                )
            )
            continue

        spec = TOOLS[tool_name]
        try:
            result = spec.handler(db, scope, prepared)
        except Exception as error:  # noqa: BLE001 - a raising handler must not abort the turn
            logger.warning("Ordering agent tool %r raised: %s", tool_name, error)
            records.append(
                ToolCallRecord(tool=tool_name, args=prepared.model_dump(), error=f"tool_error: {error}")
            )
            continue

        result = guards.enforce_destructive_policy(result)
        guards.grow_seen_ids(seen, result)
        records.append(ToolCallRecord(tool=tool_name, args=prepared.model_dump(), result=result))

        # Two results that settle the turn by themselves. The read-backs say
        # what the rows say; a further model round only lets the model say it
        # worse or call the same tool again — both measured live, 2.5 and
        # 3.5 seconds apiece, on the two turns a customer is most likely to
        # be watching the clock.
        if tool_name == "place_order" and isinstance(result, dict) and result.get("outcome") == "placed":
            return _settled()
        if tool_name == "order_requirements":
            if _still_missing() or not auto_place:
                return _settled()
            # Everything held and a channel with no button: the next round's
            # opening check places it — with no model call in between.
            continue

        action = result.get("action") if isinstance(result, dict) else None
        if isinstance(action, dict):
            actions.append(action)
            # One mutation per turn, decided here rather than by the prompt.
            # Live on 2026-09-16: "add one more Margherita" produced an
            # applied add and then, rounds later, a second one — the customer
            # got three. A cart change is the end of the work; the client
            # names what happened from the action and the menu it holds, so
            # no further model round is spent phrasing it.
            # Said, not silent. The web client composes this sentence from the
            # action and the menu it holds; a chat thread has no client, and a
            # turn that added something and said nothing let the reply
            # pipeline answer instead — with "that one's outside my kitchen".
            return TurnOutcome(
                answer=describe_applied(records),
                actions=actions,
                records=records,
                fallback_reason=None,
                elapsed_seconds=clock() - start,
                answer_about="cart",
            )

    return _capped("round_cap")


__all__ = [
    "Clock",
    "TurnOutcome",
    "ask_for_choice",
    "describe_cart",
    "describe_placed_order",
    "placed_order_in",
    "run_turn",
]

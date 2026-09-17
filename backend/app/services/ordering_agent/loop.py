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

import re
import json
from datetime import datetime
from decimal import Decimal

import logging
import time
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import get_settings
from app.schemas.suggestions import CartLinePayload
from app.services import restaurant_locations as branch_hours
from app.services.ordering_agent import guards, order_draft
from app.services.ordering_agent import tools as tools_module
from app.services.ordering_agent.planner import (
    extract_cart_request,
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


def _money(value: Any) -> str:
    try:
        return f"${float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def ask_for_choice(result: Any) -> str | None:
    """The question a `needs_choice` tool result already contains, as prose.

    A dish that needs a size or a required group is the one case where the
    deterministic layer holds the complete answer — the dish, its sizes,
    its groups, their options and every price came from the tool's rows —
    and on the first live turn the model still spent four rounds on it and
    said nothing. So when the loop ends on a cap with that result in hand,
    it asks the question itself, from those rows and nothing else: the
    house rule's template fallback, applied to the one outcome that has a
    fixed shape. Returns None for anything that is not a needs_choice.
    """

    if not isinstance(result, dict) or result.get("outcome") != "needs_choice":
        return None
    name = result.get("name") or "that dish"
    parts: list[str] = []
    sizes = result.get("available_sizes") or []
    if result.get("needs_size") and sizes:
        listed = ", ".join(f"{s.get('name')} ({_money(s.get('price'))})" for s in sizes)
        parts.append(f"Which size for {name}? {listed}.")
    for group in result.get("customization_groups") or []:
        if not group.get("needs_selection"):
            continue
        options = []
        for option in group.get("options") or []:
            extra = option.get("extra_price") or 0
            try:
                extra_text = f" (+{_money(extra)})" if float(extra) > 0 else ""
            except (TypeError, ValueError):
                extra_text = ""
            options.append(f"{option.get('name')}{extra_text}")
        if options:
            parts.append(f"{group.get('title') or 'Choose'} for {name}: {', '.join(options)}.")
    if not parts:
        return None
    return " ".join(parts) + " Which would you like?"


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
        parts.append(f"{quantity} x {label} - {_money(total)}")
    said = "; ".join(parts)
    subtotal = _money(result.get("subtotal"))
    tail = " Ready to check out?"
    if result.get("needs_choice"):
        # A line still missing a size or a required choice cannot be priced
        # honestly, so the subtotal is not the whole story and saying "ready
        # to check out" would be.
        tail = " One of those still needs a choice before it can be ordered."
    return f"You have {said}. Subtotal {subtotal}.{tail}"


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


def describe_applied(records: list[ToolCallRecord]) -> str | None:
    """What the turn actually did to the cart, said from the tool's own rows.

    A turn that added something and then had nothing to say let the reply
    pipeline fill the silence — and asked about an address or a dish it had
    just added, that pipeline says "that one's outside my kitchen". An action
    that happened should always be able to speak for itself.
    """

    said = []
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
        elif action.get("kind") == "set_quantity":
            said.append(f"{name} is now x{quantity}.")
        elif action.get("kind") == "remove":
            said.append(f"Removed {name} from your order.")
    if not said:
        return None
    return " ".join(said) + " Anything else, or shall we get it on its way?"


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
    return (f"${subtotal:.2f}", f"${minimum:.2f}", f"${minimum - subtotal:.2f}")


def _clock(iso: str | None) -> str | None:
    """'Thu 10:30' from an ISO datetime, in the branch's own zone."""

    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).astimezone(branch_hours.BUSINESS_TIMEZONE).strftime("%a %H:%M")
    except ValueError:
        return None


def describe_time_problem(records: list[ToolCallRecord]) -> str | None:
    """A time that could not be kept, and the nearest one that could."""

    for record in reversed(records):
        if record.tool != "schedule_time":
            continue
        if isinstance(record.result, dict):
            if record.result.get("outcome") == "kept":
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
                return (
                    f"We are closed for {label} right now. The next time I can do is "
                    f"{nearest} — shall I place it for then, or would you like another time?"
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

    seen: set[uuid.UUID] = guards.seed_seen_ids(cart)
    # Tools this turn has already answered with identical arguments.
    retired: set[str] = set()
    # The cart resolved once, up front, by the same code the tool uses. It
    # goes into every prompt as a fact and costs one query per turn; the
    # alternative is a model that has to remember to look before it speaks,
    # and on a live turn it did not.
    cart_summary: str | None = None
    # The same read-back without the prompt's framing, for the customer.
    cart_readback: str | None = None
    if cart:
        try:
            cart_summary = describe_cart(TOOLS["view_cart"].handler(db, scope, ViewCartArgs(lines=_as_tool_lines(cart))))
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
            draft_now.fulfillment_type or branch_hours.OrderFulfillmentType.PICKUP.value
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
                alternative = branch_hours.next_available_slot_start(
                    location, fulfillment_type=fulfillment
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

    def _show_dishes(phrase: str) -> TurnOutcome | None:
        """Read the menu out: their words, our rows, their diet.

        The reply pipeline answers a menu question well when it is about
        flavour or a recommendation. It answers "do you have pizza" with
        Coconut Ice Cream, because semantic similarity matched dishes that
        take extras. When a customer names something the menu has, the menu
        is the answer.
        """

        want_veg = True if (scope.diet or "").lower() == "veg" else None
        shown = tools_module.dishes_to_show(db, scope, phrase, is_veg=want_veg)
        if not shown:
            return None
        listed = "\n".join(f"- {d['name']} - ${d['price']}" for d in shown)
        opening = "Here is what we have" if want_veg is None else "Here is what we have, all vegetarian"
        return TurnOutcome(
            answer=f"{opening}:\n{listed}\n\nWhich one would you like?",
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
            answer = (
                "Sorry — I did not follow that. Let's start that one again: tell me "
                "the dish you would like and I will set it up."
            )
        else:
            draft_now = order_draft.load(scope.session_id)
            asked["asks"] = int(asked.get("asks", 1)) + 1
            draft_now.pending_choice = json.dumps(asked)
            order_draft.save(scope.session_id, draft_now)
            question = str(asked.get("question") or "").rstrip()
            answer = (
                f"Sorry, I did not catch that. {question} "
                f"Just reply with one of these: {options}."
            )
        return TurnOutcome(
            answer=answer,
            answer_about="cart",
            actions=actions,
            records=records,
            fallback_reason=None,
            elapsed_seconds=clock() - start,
        )

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

    def _remember_choice(result: dict[str, Any], base: dict[str, Any] | None = None) -> None:
        """Write down the question just asked, with the ids behind it.

        A turn's records do not survive it. Without this the size question
        was asked correctly and the answer had nothing to land on.
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
        draft_now = order_draft.load(scope.session_id)
        draft_now.pending_choice = json.dumps({
            "base": {k: v for k, v in settled.items() if v is not None},
            "question": ask_for_choice(result) or "",
            "options": options,
            # How many times this has been put to the customer.
            "asks": int((_pending_choice() or {}).get("asks", 0)) + 1,
        })
        order_draft.save(scope.session_id, draft_now)

    def _forget_choice() -> None:
        if scope.session_id is None:
            return
        draft_now = order_draft.load(scope.session_id)
        if draft_now.pending_choice:
            draft_now.pending_choice = None
            order_draft.save(scope.session_id, draft_now)

    def _answer_choice(asked: dict[str, Any], chose: str) -> list[dict[str, Any]]:
        """Add the dish with the option the customer picked.

        The name is matched against the options that were OFFERED, never
        against the menu at large: an answer to a question nobody asked
        must not put something in somebody's cart.
        """

        wanted_name = chose.strip().casefold()
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
            return []
        args: dict[str, Any] = dict(asked.get("base") or {})
        args.setdefault("quantity", 1)
        if picked.get("size_id"):
            args["menu_item_size_id"] = picked["size_id"]
        else:
            chosen = list(args.get("selected_options") or [])
            chosen.append({"option_id": picked["option_id"]})
            args["selected_options"] = chosen
        guards.grow_seen_ids(seen, args)
        added = _run_add(args)
        if added:
            _forget_choice()
        return added

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

        question = (
            describe_placed_order(placed_order_in(records))
            or describe_applied(records)
            or _choice_question_in(records)
            or describe_time_problem(records)
            or describe_place_failure(records)
            or describe_collecting(_still_missing())
            or (describe_ready() if ready_now else None)
            or _choice_question_in(records)
            or _cart_summary_in(records)
            or cart_readback
        )
        if question is not None:
            logger.info("Ordering agent asked the needs_choice question itself after %s", reason)
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

    def _settled() -> TurnOutcome:
        """The turn as the rows alone can end it — no words from the model."""

        placed = placed_order_in(records)
        return TurnOutcome(
            answer=(
                describe_placed_order(placed)
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
            ),
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
    plain = quick_read(message)
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
        return _settled()
    if plain == "menu":
        # The reply pipeline answers about the menu, and better; this turn
        # simply has nothing to add and should not spend a model round
        # discovering that.
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
    # Details of theirs we are holding but which nobody has stood behind.
    unconfirmed = _details_to_confirm()
    wanted = (
        {"add": None, "details": {}, "checkout": True, "when": None,
         "chose": None, "confirms": None, "browse": None}
        if plain == "checkout"
        else read_order_intent(
            message,
            missing=collecting or (),
            generate=generate,
            now_local=now_local.strftime("%A %Y-%m-%d %H:%M"),
            offered=standing_offer,
            choice_question=(asked_before or {}).get("question"),
            choice_options=[o["name"] for o in (asked_before or {}).get("options", [])],
            # Whatever a bare "yes" would be agreeing to. Measured: with a
            # time offered but nothing named as the question, the reading
            # answered "yes" with nothing at all, the turn fell through to
            # six planner rounds, and the same offer came back word for
            # word — the loop this is here to end.
            confirming=unconfirmed or (f"the order for {standing_offer}" if standing_offer else None),
        )
    )

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

    if wanted.get("when") and scope.session_id is not None:
        _take_time(wanted["when"])
        placing_wanted = True

    if wanted.get("confirms") is True and scope.session_id is not None:
        kept = order_draft.load(scope.session_id)
        kept.confirmed = True
        order_draft.save(scope.session_id, kept)
        collecting = _still_missing() or []
        placing_wanted = True
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

    # Nothing in this message answered anything. A question already asked is
    # kept rather than dropped — and never repeated word for word.
    if (
        asked_before
        and not wanted.get("chose")
        and not wanted["add"]
        and not wanted["details"]
        and not wanted["checkout"]
        and not wanted.get("when")
        and scope.session_id is not None
    ):
        return _reask_or_give_up(asked_before)

    if wanted.get("chose") and asked_before:
        answered = _answer_choice(asked_before, wanted["chose"])
        if answered:
            actions.extend(answered)

    if wanted.get("browse") and db is not None and scope.restaurant_location_id:
        shown = _show_dishes(wanted["browse"])
        if shown:
            return shown

    if wanted["add"]:
        added = _add_named_dish(*wanted["add"])
        if added:
            actions.extend(added)

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
            _place_now()
        return _settled()

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

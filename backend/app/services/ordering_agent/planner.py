"""Task 4: decide the next step of a customer's ordering turn.

Sibling of `insights/tool_chat.py`'s planner, not a reuse of it. The owner
planner answers once: a whole question maps onto one skill or tool and it
stops. This planner is asked again and again within the same turn — Task 5's
loop calls `plan_step`, runs whatever tool comes back, feeds the result in
as history, and calls `plan_step` again — because "add the large margherita
with extra cheese" needs the model to see what `get_dish` returned before it
can decide whether `add_to_cart` is safe yet, or whether it still needs to
ask which size. So this module has no single-call cache the way
`tool_chat.plan_cache_key` does: a plan here depends on the cart and on what
already happened this turn, never on the wording alone, and caching by
wording would serve one customer's half-built cart to a different customer
who typed the same words.

The two JSON shapes a plan may take mirror the two things a turn can end in:
`{"tool": "<name>", "args": {...}}` asks the caller to run one more tool and
come back; `{"answer": "<text>"}` is the model's turn-ending reply, typed out
here because — unlike the owner side, whose answers are always
template-composed from tool data (see `tool_chat`'s formatters) — an
ordering agent's replies are conversational ("sure, that comes with fries
and a drink — want to add it?"), and a template for every sentence a
customer's question could provoke is not a template worth writing.

Validation here is strict, not the owner planner's trim-and-continue.
`tool_chat.clean_arguments` drops an argument its tool does not declare,
because over-supplying a real argument is harmless there. Here it is not:
this registry's `extra="forbid"` (`tools.py::ToolArgs`) exists specifically
so a smuggled `restaurant_id` fails loudly instead of being quietly
stripped — stripping it would mean the caller never learns the model tried.
So a planned call is instantiated straight through its real `args_model`,
and any undeclared argument, including a scope id, refuses the whole call
rather than being dropped from it. A scope id gets its own error code,
`scope_argument`, checked before the tool name is even looked up, so a call
that both smuggles an id and names an unknown tool is reported for the
smuggling — the more important defect — rather than as a plain typo.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Sequence

import httpx
from pydantic import ValidationError

from app.config import get_settings
from app.services.ollama_client import (
    GENERATE_ENDPOINT,
    build_client,
    local_only_options,
    think_option,
)
from app.services.ordering_agent.tools import (
    INJECTED_CART_FIELDS,
    FORBIDDEN_ARG_NAMES,
    TOOLS,
    describe_tools_for_prompt,
)

settings = get_settings()
logger = logging.getLogger(__name__)

# Same signature as the owner planner's generator (`tool_chat.Generate`), so a
# test drives this one the same way: a scripted callable, no Ollama host, no
# module internals patched.
Generate = Callable[[str, float, int], str]


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """One tool call already run this turn, fed back to the next `plan_step`
    call so the model can see what it learned before deciding what to do
    next. `result` and `error` are never both populated — a call either ran
    (and produced whatever dict the handler returned, `tools.py` never
    raises for a business-logic refusal) or it did not (a validation refusal
    from this module, before Task 5 ever reached a handler) — but both are
    optional here rather than a tagged union, because a hand-written test
    fixture is simpler to read as two plain fields than as a union type.
    """

    tool: str
    args: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass(slots=True)
class PlanStep:
    """What one `plan_step` call decided: exactly one of a tool to run next,
    a finished answer, or why neither could be produced. Mirrors
    `tool_chat.ToolPlan` field-for-field where the shape overlaps — `error`/
    `detail` read identically — but trades `skill` for `answer`, since this
    planner's terminal state is prose it wrote itself, not a named skill.
    """

    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    answer: str | None = None
    # What the model says its own answer is about. The caller routes on it:
    # a reply pipeline with no cart must not answer a cart question. Free
    # text, lowercased; anything unrecognised is treated as "other".
    answer_about: str = "other"
    error: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and (self.tool is not None or self.answer is not None)


# Fields a planner never needs and which dominate a result's size: prose the
# customer reads, images the client renders, bookkeeping the tools already
# applied. Dropping these is what keeps a six-round prompt inside the model's
# context window.
_NOISY_KEYS = frozenset(
    {
        "description",
        "image_url",
        "help_text",
        "sort_order",
        "is_countable",
        "is_active",
        "created_at",
        "updated_at",
        "cuisine_type",
        "category",
        "restaurant_id",
        "restaurant_location_id",
    }
)

# Enough of a list to choose from, few enough to stay small. A group with more
# options than this says so, so the model knows to ask rather than assume the
# list it can see is the whole list.
_MAX_LIST = 6
_MAX_STRING = 120
_MAX_RESULT_CHARS = 1400


def _compact(value: Any, depth: int = 0) -> Any:
    """A tool result reduced to what the next decision needs.

    Ids survive whole — they are the one thing the model must reproduce
    exactly, and a truncated id is worse than no id. Everything else is
    trimmed: long prose to a clause, long lists to a head plus a count.
    """

    if isinstance(value, dict):
        if depth >= 4:
            return "..."
        out = {}
        for key, item in value.items():
            if key in _NOISY_KEYS:
                continue
            out[key] = _compact(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        if depth >= 4:
            return "..."
        items = [_compact(item, depth + 1) for item in list(value)[:_MAX_LIST]]
        if len(value) > _MAX_LIST:
            items.append(f"...and {len(value) - _MAX_LIST} more")
        return items
    if isinstance(value, str) and len(value) > _MAX_STRING:
        return value[:_MAX_STRING] + "..."
    return value


def _serialize_history(history: Sequence[ToolCallRecord]) -> str:
    """Prior calls and their results, verbatim and compact — the model's only
    memory of this turn, since nothing else carries between `plan_step`
    calls. `default=str` covers the non-JSON-native types this registry's
    results and args routinely carry (`uuid.UUID`, `decimal.Decimal`),
    without pulling in `fastapi.encoders.jsonable_encoder` for one line.
    """

    if not history:
        return "(none yet)"
    lines = []
    for record in history:
        payload: dict[str, Any] = {"tool": record.tool, "args": record.args}
        if record.error is not None:
            payload["error"] = record.error
        else:
            payload["result"] = _compact(record.result)
        line = json.dumps(payload, default=str, separators=(",", ":"))
        if len(line) > _MAX_RESULT_CHARS:
            # A last backstop for a shape `_compact` did not anticipate. Better
            # a clipped record than a prompt that pushes the rules out of the
            # model's context window, which is the failure this exists for.
            line = line[:_MAX_RESULT_CHARS] + '..."}'
        lines.append(line)
    return "\n".join(lines)


def _collecting_facts(
    collecting: Sequence[str] | None,
    ready_to_place: bool = False,
    pending: Sequence[str] | None = None,
) -> str:
    """What this conversation is in the middle of.

    Live: the customer gave every missing detail in one message and the
    model called nothing, so nothing was saved. Saying the state plainly,
    with the field names, is cheaper than hoping it is inferred from eight
    lines of thread.
    """

    if ready_to_place:
        # The state after collecting, which was left unsaid once and cost a
        # customer a repeated question they had already answered.
        return (
            "Everything needed to place this order is held. Call place_order "
            "now; do not ask for details again.\n"
        )
    if not collecting:
        if pending:
            # There is a cart but nobody has asked to order yet. Saying what
            # placing it would need means the model can answer "let's check
            # out" with the question instead of stopping at the subtotal.
            return (
                "There is a cart. To place it as an order you would still "
                f"need: {', '.join(pending)}. When the customer wants to "
                "order, ask for those and pass what they say to "
                "save_order_details.\n"
            )
        return ""
    wanted = ", ".join(collecting)
    return (
        "You are collecting the details needed to place this order. Still "
        f"missing: {wanted}. Whatever the customer says next, pass it to "
        "save_order_details — it takes any of them, in any order.\n"
    )


def _cart_facts(cart_summary: str | None) -> str:
    """The cart the customer is holding, as a fact rather than a lookup.

    The browser sends the cart with every message and the loop resolves it
    against the branch before this is written, so the model can answer "what
    have I got?" without first deciding to call a tool — which on a live turn
    it simply did not do, and the customer was handed a menu search for a
    dish called "cart".
    """

    # An empty cart is a fact too, and it used to be the one thing the model
    # was told nothing about — `cart_summary` is only written when there IS a
    # cart, so an empty one left a silence the model filled with an
    # assumption. Measured: "yes", with nothing in the cart and nothing
    # pending, came back "Great! It looks like you're ready to proceed. Let
    # me check what details we need to finalize your order."
    return f"{cart_summary}\n" if cart_summary else (
        "The customer's order is EMPTY: nothing has been added yet. Do not "
        "say they are ready to check out, do not ask for their details, and "
        "do not refer to an order they have not started.\n"
    )


def _customer_facts(diet: str | None) -> str:
    """What the tools will enforce anyway, said up front so the model does
    not plan a search or an add it will only be refused for."""

    if diet == "veg":
        return "The customer is vegetarian: never offer, search for, or add a non-veg dish.\n"
    return ""


def _serialize_thread(recent_history: Sequence[dict[str, str]] | None, previous_reply: str | None) -> str:
    """The thread as the customer saw it, newest last — so "yes", "make it
    two" or "the second one" are read against what they answer. The client
    holds the thread and sends the tail; the older single-line form is kept
    for callers that only have that."""

    lines = []
    for entry in list(recent_history or [])[-8:]:
        role = "Customer" if entry.get("role") == "customer" else "You"
        text = (entry.get("text") or "").strip()[:500]
        if text:
            lines.append(f"{role}: {text}")
    if not lines and previous_reply:
        lines.append(f"You: {previous_reply.strip()[:600]}")
    return "\n".join(lines)


def build_planner_prompt(
    message: str,
    history: Sequence[ToolCallRecord],
    tool_names: tuple[str, ...] | None = None,
    previous_reply: str | None = None,
    recent_history: Sequence[dict[str, str]] | None = None,
    diet: str | None = None,
    cart_summary: str | None = None,
    collecting: Sequence[str] | None = None,
    ready_to_place: bool = False,
    pending: Sequence[str] | None = None,
) -> str:
    """Public so a test can assert on the prompt text directly, the same way
    `test_chat_tools.py` asserts on `tool_chat.build_planner_prompt`'s
    output rather than only on what a scripted model produces from it.
    """

    return f"""Decide the next step for this customer's order, from what the
tools can tell you and what you already found out this turn.

Return STRICT JSON only, one of these two shapes:
{{"tool": "<tool name>", "args": {{...}}}}
{{"answer": "<your reply to the customer>", "about": "cart" | "menu" | "other"}}

Tools (each returns one slice of data):
{describe_tools_for_prompt(tool_names)}

{_customer_facts(diet)}{_cart_facts(cart_summary)}{_collecting_facts(collecting, ready_to_place, pending)}
Conversation so far, most recent last (empty if this is the first message):
{_serialize_thread(recent_history, previous_reply)}

Calls already made this turn, and what they returned:
{_serialize_history(history)}

Rules:
- use a tool name exactly as spelled above, and nothing else
- pass only the arguments listed for that tool
- never include a restaurant, branch, customer or user id — a call
  containing one is discarded
- "about" says what your answer is about: "cart" for their cart, its
  prices, totals or placing the order; "menu" for dishes and the menu;
  "other" for anything else
- once you have enough to answer, reply with {{"answer": "..."}} instead of
  calling another tool
- selected_options and lines are JSON lists — pass [] when there is nothing
  to put in them, never {{}}
- never repeat a call you already made with the same arguments — its result
  is listed above; read it instead
- a result with "outcome": "needs_choice" means the dish is real but the
  customer must choose first: do not call the tool again — answer by asking
  which of the listed sizes or options they want, each with its price
- a result that carries an action (status "applied" or "proposed") is the
  end of the work: answer by telling the customer what was done, or what
  needs their confirmation
- a result with "outcome": "not_for_diet" means the dish is not vegetarian:
  say so and offer a vegetarian alternative from a search — never add it
- when the customer wants to order, pay, or finish: call
  order_requirements first. It says which contact details are held and
  which are missing
- ask for the missing details in one friendly message, and pass whatever
  they answer to save_order_details. Ask only for what "missing" lists
- when nothing is missing, call place_order. It creates the order and
  returns a link to pay it; say the total and that the link is below.
  NEVER write the payment link into your answer — it is shown separately
- a result with "outcome": "not_identified" means they must sign in first;
  "needs_details" means keep asking
- when the customer wants to order, pay, or finish: call
  order_requirements first. It says which contact details are held and
  which are missing
- ask for the missing details in one friendly message, and pass whatever
  they answer to save_order_details. Ask only for what "missing" lists
- when nothing is missing, call place_order. It creates the order and
  returns a link to pay it; say the total and that the link is below.
  NEVER write the payment link into your answer — it is shown separately
- a result with "outcome": "not_identified" means they must sign in first;
  "needs_details" means keep asking
- menu_item_id is an id from an earlier result, never a dish name. If you
  only know the name, call get_dish with it first and use the id it returns
- if the customer agrees to something you offered — adding a dish, ordering
  it — act on it: call the tool. Do not describe the dish again
- read the customer's message against the conversation so far. If you
  offered to add more or check out and they are agreeing to pay, finish,
  confirm the order, or check out — in whatever words — call go_to_checkout.
  If they are declining or want to keep ordering, answer by asking what to
  add. If their message is about something else, treat it on its own.

Customer: {message}

Answer now."""


def default_generate(prompt: str, timeout_seconds: float, max_tokens: int) -> str:
    """The real model. Public, because `run_turn` has to resolve it too.

    Every call site here takes `generate` and falls back to this when it is
    None, which is how a test injects a scripted model. That arrangement hid a
    bug: `run_turn` wrapped its own `generate` to cap each call at the time the
    turn had left, and in production that argument is always None, so the
    wrapper wrapped nothing and raised on every turn. Tests never saw it —
    they all inject. Naming this lets the wrapper resolve the default once,
    where the cap is applied, instead of six call sites resolving it after.
    """

    payload = {
        "model": settings.ordering_agent_model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        **think_option(),
        **local_only_options(),
        "options": {"temperature": 0.1, "num_predict": max_tokens},
    }
    timeout = httpx.Timeout(connect=5.0, read=timeout_seconds, write=10.0, pool=5.0)
    with build_client(timeout) as client:
        response = client.post(GENERATE_ENDPOINT, json=payload)
        response.raise_for_status()
        return str(response.json().get("response") or "")


def _extract_json(raw: str) -> dict[str, Any]:
    """Identical to `tool_chat._extract_json`, duplicated rather than
    imported: a few lines of JSON-object salvage, with no dependency on
    anything owner-specific — importing across that boundary for this would
    tie two otherwise-independent planners together for no benefit.
    """

    raw = (raw or "").strip()
    if not raw:
        raise ValueError("empty response")
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in response")
    payload = json.loads(raw[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("response JSON was not an object")
    return payload


def _validate_call(tool: Any, raw_args: Any, allowed: tuple[str, ...]) -> PlanStep:
    """Turn a model-authored `{"tool": ..., "args": ...}` into either a
    validated call or the specific reason it is refused. Order matters: a
    smuggled scope id is checked before the tool name is even looked up, so
    naming an unknown tool AND carrying a `restaurant_id` is reported as the
    scope violation, not as a typo.
    """

    args_obj: Any = raw_args if raw_args is not None else {}
    if not isinstance(args_obj, dict):
        return PlanStep(error="invalid_arguments", detail="arguments were not an object")

    smuggled = sorted(set(args_obj) & FORBIDDEN_ARG_NAMES)
    if smuggled:
        return PlanStep(
            error="scope_argument",
            detail=f"arguments named {smuggled}, which the model may never supply",
        )

    if not isinstance(tool, str) or tool.strip() not in allowed:
        return PlanStep(
            error="unknown_tool",
            detail=f"planner chose {tool!r}, which is not an offered tool",
        )
    tool_name = tool.strip()

    # `allowed` is always a subset of `TOOLS` (see `plan_step`), so this
    # lookup cannot miss for a name that just passed the check above.
    spec = TOOLS[tool_name]
    # Whatever the model wrote in a field the caller injects is discarded a
    # moment later, so judging the call on it refuses good plans for bad
    # reasons. Dropped before validation rather than after, because
    # `extra="forbid"` would otherwise reject the shape it invented.
    injected = INJECTED_CART_FIELDS.get(tool_name)
    if injected:
        args_obj = {key: value for key, value in args_obj.items() if key != injected}
    try:
        validated = spec.args_model.model_validate(args_obj)
    except ValidationError as error:
        # The refusal carries the tool and the arguments that caused it. A
        # caller that can do something about the reason — the loop resolving
        # a dish NAME sitting in an id field — needs to know what was tried,
        # and `ok` stays False either way because `error` is set.
        # `extra="forbid"` is what actually catches a smuggled id that is
        # NOT in `FORBIDDEN_ARG_NAMES` (an argument nobody thought to ban by
        # name, but that this specific tool still never declared) — the
        # second, narrower gate behind the first.
        detail = str(error)
        if "menu_item_id" in detail and "uuid" in detail.lower():
            # The model reaches for a name or a number when it has no id.
            # A validation dump does not tell it what to do; this does, and
            # it costs a fraction of the prompt space.
            detail = (
                "menu_item_id must be an id from an earlier tool result. "
                "Call get_dish with the dish's name first, then use the "
                "menu_item_id it returns."
            )
        return PlanStep(error="invalid_arguments", detail=detail, tool=tool_name, args=args_obj)

    return PlanStep(tool=tool_name, args=validated.model_dump())


def validate_call(tool: str, args: dict[str, Any]) -> PlanStep:
    """Re-run a call through its tool's argument model.

    Public so the loop can revalidate a call it repaired, rather than
    duplicating the ordering of checks that `_validate_call` documents.
    """

    return _validate_call(tool, args, tuple(TOOLS))


_DETAIL_QUESTIONS = {
    "contact_name": "the customer's name",
    "contact_email": "an email address",
    "contact_phone": "a phone number",
    "delivery_address": "a delivery address (street, area, city)",
    "fulfillment_type": '"DELIVERY" or "PICKUP" — whether the food is delivered or collected',
}


def extract_order_details(
    message: str,
    *,
    missing: Sequence[str],
    generate: Generate | None = None,
) -> dict[str, str]:
    """What the message says about the details an order still needs.

    A narrow reading, separate from planning: the planner is asked to decide
    what to do AND copy out an address in one JSON object, and on the details
    turn qwen3:8b answered "your details have been saved" having saved
    nothing. Asked only "what does this message say about these fields", it
    reads them out reliably — and what it reads is validated by the draft
    exactly as a tool argument would be, so a wrong email is still refused.

    Returns only fields present and non-empty. Never raises: a model that is
    unreachable or answers nonsense means an empty dict, and the planner
    round that follows can still ask.
    """

    wanted = [field for field in missing if field in _DETAIL_QUESTIONS]
    if not wanted or not message.strip():
        return {}
    lines = "\n".join(f'  "{field}": {_DETAIL_QUESTIONS[field]}, or null' for field in wanted)
    prompt = (
        "A customer is placing a food order over chat. Read ONLY what this message "
        "states about the details below. Do not guess, do not infer from names, "
        "do not fill in anything not written. Answer with one JSON object and "
        "nothing else.\n\n"
        f"Fields:\n{lines}\n\n"
        f"Message: {message.strip()!r}\n\nJSON:"
    )
    generate = generate or default_generate
    try:
        raw = generate(prompt, settings.ordering_agent_planner_timeout_seconds, 160)
        parsed = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
    except Exception:  # noqa: BLE001 - reading nothing is the safe failure
        logger.warning("Ordering agent could not read order details", exc_info=True)
        return {}
    if not isinstance(parsed, dict):
        return {}
    found: dict[str, str] = {}
    for field in wanted:
        value = parsed.get(field)
        if isinstance(value, str) and value.strip() and value.strip().lower() not in {"null", "none"}:
            found[field] = value.strip()
    return found


#: Words that carry no request of their own. Stripped before matching, so
#: "yeah ok let's do the checkout please bro" and "checkout" are one thing.
_FILLER = frozenset(
    """
    a an the my our me i we you u to for of in on is are am it that this
    yeah yah ya yes yep ok okay k please pls plz kindly now just only also too
    lets let us do does did can could would will shall want wanted need show
    see give get tell have has had on at with what whats where
    hey hi hello bro bhai ji sir maam
    thanks thank and then so well um uh na haan
    """.split()
)

#: What a sentence can plainly be. Each of these is a READ — see the module
#: docstring for why nothing that changes an order is in here.
_PLAIN = {
    "cart": (
        "cart", "cart status", "basket", "order", "order status", "order summary",
        "cart summary", "cart detail", "cart details", "order detail", "order details",
        "inside cart", "cart me kya hai", "kya hai cart me",
    ),
    "menu": (
        "menu", "menu card", "menu list", "food menu", "dishes", "dish list",
        "items", "item list", "options", "food", "food list", "menu items",
        # The other half of how people ask. Live, on a thread where "Show me
        # menu" worked perfectly: "Show me categories" and "Show me other
        # items" were both searched for as though they were dishes, and both
        # came back "I could not find categories on the menu" over eight
        # appetizers. The branch's own sections were the answer to all three.
        "categories", "category", "menu categories", "sections", "section",
        "other items", "more items", "other dishes", "more dishes",
        "other options", "anything else", "something else", "else",
        "full menu", "whole menu", "all items", "list of items",
    ),
    # Answered from this branch's own columns — `is_bestseller` and
    # `popularity_score` are what "what's good" means here. Live, at a branch
    # with 136 dishes, "what do you recommend" was searched for as a dish name
    # and answered "I could not find what do you recommend on the menu".
    "suggest": (
        "recommend", "recommends", "recommendation", "recommendations",
        "any recommendations", "what do you recommend", "what do you suggest",
        "suggest", "suggest something", "suggestion", "suggestions",
        "whats good", "whats nice", "whats popular", "popular", "most popular",
        "best", "what is the best dish", "bestseller", "bestsellers", "must try",
    ),
    # `price`, ordered. Same fault: "what's your cheapest item" came back
    # "I could not find cheapest item on the menu".
    "cheapest": (
        "cheapest", "cheapest item", "cheapest dish", "what is cheapest",
        "whats your cheapest item", "anything cheap", "something cheap", "cheap",
        "lowest price",
    ),
    # The bare question about whatever is already in front of them — a dish
    # just named, a list just read out, the cart. Live, with the size question
    # for a pizza standing, "how much" was searched for as a dish and answered
    # "Sorry, I did not catch that." The figure was on the row we were already
    # talking about. A price question that NAMES a dish ("how much is the
    # khaman") has content of its own and is not here; it goes to the reading.
    "price": (
        "price", "what is the price", "price kya hai", "how much", "hw much",
        "how much is it", "how much is that", "how much for that",
        "how much does it cost", "cost", "how much cost", "kitne ka hai",
        "kitna hai", "kitne ka", "kitna", "rate", "kya rate hai", "what rate",
    ),
    "checkout": (
        "checkout", "check out", "checkout order", "place order", "order place",
        "confirm order", "confirm", "book", "book order", "finish", "finish order",
        "done", "complete order", "proceed", "proceed checkout", "pay", "payment",
        "payment link", "pay now", "order kar do", "kar do", "chalo order kar do",
        "bas itna hi", "ho gaya", "itna hi", "thats all", "that all", "all",
    ),
}

#: A sentence that turns something down, or asks about it, is not a request
#: for it. Cheap to spot, and the difference between "checkout" and "I do not
#: want to checkout yet".
_NEGATIONS = frozenset(
    "no not dont don't nope never cancel stop wait without except neither nahi mat".split()
)


def _plainly(text: str) -> str:
    """A sentence reduced to the words that carry a request.

    Both sides of the comparison go through this, so the phrases above are
    written the way a customer says them rather than in whatever form
    survives the filter — "order kar do" stays readable there even though
    "do" is filler and never reaches the match.
    """

    # An apostrophe joins a word rather than breaking it: "what's" is one
    # word ("whats", filler), not "what" and a stray "s".
    without_apostrophes = text.lower().replace("'", "").replace("’", "")
    cleaned = "".join(
        character if character.isalnum() or character.isspace() else " "
        for character in without_apostrophes
    )
    return " ".join(word for word in cleaned.split() if word not in _FILLER)


#: The phrases above, reduced once at import so a match is a dictionary hit.
_PLAIN_BY_PHRASE = {
    _plainly(phrase): signal
    for signal, phrases in _PLAIN.items()
    for phrase in phrases
    if _plainly(phrase)
}


#: Longer than any question worth reading a "yes" against.
#:
#: The cap is the whole safety argument. `_hold` records a SHORT question on
#: purpose, because a long read-back handed to the model as "the question"
#: got mined for its contents: "yes" arrived carrying a delivery address,
#: which was read as a new instruction. A single interrogative sentence
#: cannot do that, and one this long is not a question anybody asked.
_ASKED_IN_PROSE_LIMIT = 160


def question_asked_in(reply: str | None) -> str | None:
    """The question a reply ended on, if it ended on one.

    The reply pipeline asks things constantly — "Would you prefer it with a
    side of naan?", "Shall I show you the desserts?" — in prose the model
    wrote, and nothing wrote them down. So a customer answering "yes" was
    answering nothing: the reading returns an empty object for a bare
    agreement with no referent (measured), the turn found nothing to do, and
    the planner filled the silence. Live, on an empty cart: "Great! It looks
    like you're ready to proceed. Let me check the details to ensure
    everything is set for your order." — about an order that did not exist.

    Only the LAST sentence, and only if it is a question: that is the thing
    being answered. Everything before it is context the customer has already
    read and is not replying to.

    Used only when no question of OURS is standing. One we asked through
    `_hold` is the more specific thing outstanding and carries what agreeing
    to it should DO, which prose cannot.
    """

    text = (reply or "").strip()
    cut = text.rfind("?")
    if cut == -1:
        return None
    # Only emoji, spaces and stray punctuation may follow the question mark.
    # The reply pipeline ends on one constantly — "Would you like the Butter
    # or Oil version? 🥟" — and an `endswith("?")` test missed every one.
    # A word after it means the reply carried on past the question, and the
    # question is no longer the thing being answered.
    if re.search(r"\w", text[cut + 1 :]):
        return None
    text = text[: cut + 1]
    # The tail after the previous sentence ender is the question itself.
    last = re.split(r"(?<=[.!?])\s+", text)[-1].strip()
    if len(last) > _ASKED_IN_PROSE_LIMIT:
        return None
    # Markdown emphasis reaches here from the reply pipeline; the model should
    # read the words, not the asterisks.
    return last.replace("**", "").replace("*", "").strip() or None


def quick_read(message: str) -> str | None:
    """What this sentence plainly asks for, or None to go and read it properly.

    Returns "cart", "menu", "suggest", "cheapest", "price", "checkout" or
    None. Each names something the branch's own rows can answer — "suggest"
    from `is_bestseller` and `popularity_score`, "cheapest" and "price" from
    `price` and the size rows — and
    nothing the menu has no column for: there is no jain flag and no spice
    level, so "anything jain" is deliberately not here.

    None is the common answer and
    the safe one: anything with content of its own — a dish, a name, an
    address, a negation — belongs to `read_order_intent`, which reads meaning
    rather than matching words.
    """

    words = message.lower().split()
    if not words or len(words) > 10:
        return None
    if _NEGATIONS & {word.strip(".,!?") for word in words}:
        return None
    return _PLAIN_BY_PHRASE.get(_plainly(message))


#: Words that cannot be the name of a dish, whatever the reading says.
#:
#: Not a list that decides MEANING — the prompt does that, and it is told the
#: same thing in words. This is a validity check on one field, the same shape
#: as the "null"/"none" check it grew out of: a model that answers `{"dish":
#: "one"}` has told us it found no name, in the only vocabulary it had.
#:
#: Measured: "add one", straight after four biryanis were read out, produced a
#: dish called "one". It resolved against the menu to nothing, spent 33
#: seconds doing so, and the customer was told their cart was empty. Dropping
#: it lets the same turn's `wants_to_add` do the right thing instead — ask
#: which one.
_NOT_A_DISH_NAME = frozenset(
    {"null", "none", "one", "it", "that", "this", "them", "some", "any", "more"}
)


def read_order_intent(
    message: str,
    *,
    missing: Sequence[str] = (),
    generate: Generate | None = None,
    now_local: str | None = None,
    offered: str | None = None,
    choice_question: str | None = None,
    choice_options: Sequence[str] = (),
    confirming: str | None = None,
    asked: str | None = None,
    for_day: str | None = None,
    categories: Sequence[str] = (),
) -> dict[str, Any]:
    """The three things a message can want from an order, read in one pass.

    Four, now: "when" as well — a clock time the customer named for the
    order, `"opening"` for "when you open", or None. `now_local` is the
    branch's clock, so "tomorrow at one" has a date; `offered` is a time the
    kitchen already proposed, so "yes" can mean that time.

    Returns {"add": (dish, quantity) | None, "details": {field: value},
    "checkout": bool}. Everything is what the message SAYS; nothing here is
    trusted as true. The dish is resolved against this branch's own menu by
    the caller and the details go through the draft's own validation, so a
    misread name or a malformed email is refused exactly as it would be
    coming from a planned tool call.

    Never raises. A model that is unreachable or answers nonsense means all
    three are empty and the planner takes the turn, which is where this
    agent started.
    """

    empty: dict[str, Any] = {
        "add": None, "details": {}, "checkout": False, "when": None,
        "chose": None, "confirms": None, "browse": None, "asks_hours": False,
        "category": None, "wants_to_add": False, "cancel_order": False,
        "pay_now": False, "max_price": None, "clear_cart": False,
    }
    if not message.strip():
        return empty
    fields = ", ".join(f'"{name}"' for name in _DETAIL_QUESTIONS)
    still = (
        f"They have already been asked for: {', '.join(missing)}.\n" if missing else ""
    )
    if now_local:
        still += f"The branch's local time now is {now_local}.\n"
    if offered:
        still += (
            f"The branch has offered to make the order for {offered}. If they accept "
            '(yes, ok, that works, fine) then "when" is exactly that time.\n'
        )
    if confirming:
        still += (
            f"These details were just read back to them: {confirming}. If this "
            'message accepts them (yes, correct, that is right, go ahead) then '
            '"confirms" is true. If it rejects them (no, wrong, change it) then '
            '"confirms" is false. New details they type belong in "details" as '
            "usual, and then \"confirms\" is null.\n"
        )
    if for_day:
        # They have been asked which time on a particular day, so a bare
        # time in this message belongs to that day. Live: asked "what time
        # would you like it?" about Friday, "3 PM" came back attached to
        # nothing and the turn answered about today.
        still += (
            f"They are choosing a time on {for_day}. A time in this message "
            '("3 PM", "at 7", "half seven", "around eight") is on THAT day: '
            f'"when" is "{for_day} HH:MM".\n'
        )
    if asked:
        # The question in our own words, so the model reads their reply
        # against what was actually put to them. It was being smuggled into
        # the details slot above, and "nothing else" came back as agreement.
        still += (
            f"You have just asked them: {asked!r}\n"
            'If this message agrees to that — "yes", "sure", "go ahead", "please '
            'do", "haan", "kar do" — then "confirms" is true. If it declines — '
            '"no", "not yet", "nothing else", "that is all", "nahi" — then '
            '"confirms" is false. If it is about something else entirely, '
            '"confirms" is null and the other fields say what the message wants.\n'
            # Measured: "no wait" and "hold on" were read as neither, and a
            # customer pausing a payment fell through to a reply pipeline that
            # asked whether they were ready to check out.
            'Pausing or hesitating is declining for now, not saying nothing: '
            '"no wait", "hold on", "one sec", "not now", "actually no" all '
            'make "confirms" false.\n'
        )
    if categories:
        # The branch's own sections, so a customer's word for a kind of food
        # is matched by meaning rather than by substring. "Some drink" is
        # Beverages; no amount of string matching gets there.
        still += (
            f"This branch's menu sections are: {', '.join(categories)}. If they "
            "are asking to see a kind of food that is one of these, however they "
            'say it, put that section in "category", copied exactly. A customer '
            'who names a particular dish ("I like Thai Iced Tea") is not asking '
            'for a section: "category" is null and the dish is what they want.\n'
        )
    if choice_question and choice_options:
        listed = "; ".join(choice_options)
        still += (
            f"They were just asked: {choice_question} The options are: {listed}. "
            'If this message answers that question — however loosely ("large", "the '
            'big one", "medium please", "mango and banana") — put every matching '
            'option in "chose" as a list, each copied exactly from that list. If it '
            'does not answer it, "chose" is null.\n'
            # The options are given in the order they were read out, so a
            # position IS a name. Measured: after six suggestions, "the first
            # one" resolved to nothing and was answered "your cart is empty".
            'That list is in the order it was shown, so a POSITION names an '
            'option: "the first one", "the 2nd", "the last one", "number 3" '
            "are picks, and the option at that position is what goes in "
            '"chose".\n'
            # Live: "All", to "Which one shall I take off?", came back as
            # nothing. Every option is an answer too.
            'If they mean all of them ("all", "everything", "both", "sab"), '
            '"chose" is the whole list.\n'
        )
    prompt = (
        "A customer is talking to a restaurant over chat. Read this ONE message and "
        "answer with one JSON object and nothing else.\n\n"
        "{\n"
        '  "add": [{"dish": "a dish they are asking for, exactly as written", '
        '"quantity": 1}]   // one entry per dish, [] if they are asking for none\n'
        f'  "details": {{{fields}}}   // each one as stated, or null\n'
        '  "checkout": true if they are asking to place the order, check out or pay; '
        "else false\n"
        '  "browse": what they are asking to SEE on the menu ("pizza", "desserts", '
        '"the menu"), else null\n'
        '  "category": the menu section they mean, copied exactly from the list '
        "below, else null\n"
        '  "max_price": the most they said ONE dish may cost, as a bare number, '
        "else null"
        "\n"
        '  "wants_to_add": true if they want to order something MORE but have not '
        "said what, else false\n"
        '  "cancel_order": true if they want to call off an order they have already placed, else false\n'
        '  "clear_cart": true if they want EVERYTHING taken out of their cart or basket '
        "— cleared, emptied, started over — else false\n"
        '  "pay_now": true if they are asking to pay, or for the payment link again, else false\n'
        '  "asks_hours": true if they are asking WHEN — when you open, when the '
        "order would arrive, what times are possible — else false\n"
        '  "chose": the options they picked from the list below, copied exactly, '
        "as a list — several if they named several, else null\n"
        '  "confirms": true if they accept the details read back to them, false '
        "if they reject them, null if this message is about neither\n"
        '  "when": "YYYY-MM-DD HH:MM" if they say when they want the order, just '
        '"YYYY-MM-DD" if they name a DAY without a clock time, the word "opening" '
        "if they mean whenever the branch next opens, else null\n"
        "}\n\n"
        "Rules:\n"
        "- Only what this message actually says. Never invent a dish, a name, an "
        "email or an address.\n"
        '- "add" is for asking for food ("add X", "I want X", "get me X", "X please"). '
        'A question about a dish ("what is X", "how much is X", "do you have X") is '
        "not an add.\n"
        '- "browse" is for being shown things: "do you have pizza", "show me the '
        'menu", "what desserts are there", "I am asking for pizza". Put the thing '
        "they want to see, in their own words. It is null when they are asking for "
        "one named dish to be added.\n"
        # Measured: "is anything vegetarian" read as nothing at all, so a dish
        # question standing from the turn before answered a perfectly clear
        # request with "Sorry, I did not catch that."
        '- Asking WHETHER a kind of food exists is browsing too: "is anything '
        'vegetarian", "do you have anything spicy", "got anything sweet", '
        '"anything under 200". Put what they are asking about in "browse".\n'
        # Measured: "add one", right after four biryanis were read out, came
        # back as a dish called "one" — which resolved to nothing, spent 33
        # seconds doing it, and answered "your cart is empty".
        # The number goes in its own field so the menu query can filter on it.
        # Left inside "browse" it was searched for as though it were a dish
        # name, matched nothing, and the reply listed the branch's whole menu
        # — for "a light lunch under $20", eight dishes all under twenty
        # dollars, under a sentence saying there were none.
        '- A price they name as a limit goes in "max_price" as a bare number: '
        '"anything under 200" is 200, "nothing over 15 dollars" is 15. "cheap" '
        'and "something affordable" name no number, so they are null. It is what '
        'ONE dish may cost, not the whole order. Say what they are looking for '
        'in "browse" as well, without the price.'
        "\n"
        '- "one", "it", "that", "this" and "some" are never the NAME of a '
        'dish. "Add one", "add it", "one please" name nothing: if the list '
        'below says which they mean, that goes in "chose"; otherwise '
        '"wants_to_add" is true and "add" is null.\n'
        # Measured: "I want to add more item in my cart" matched nothing at
        # all, so the turn had nothing to do and read the cart back — the
        # same cart, twice in a row.
        '- "cancel_order" is dropping an order already placed: "cancel my order", '
        '"forget it", "I do not want it any more". Removing one dish from a cart '
        "is not this.\n"
        # Live: "Clear cart" over four lines came back as `cancel_order` and
        # was handled as taking ONE line off. The reading is the only thing
        # that can tell "clear it" from "take the rice off", however either
        # is worded — no list of phrases decides this.
        '- "clear_cart" is wanting the whole cart gone, however they say it: '
        '"clear my cart", "empty the basket", "remove everything", "start over", '
        '"sab hata do". Taking one dish out is not this — "remove one", "take '
        'one off", "remove something" want ONE dish gone and are not "clear_cart" '
        "— and neither is cancelling a placed order.\n"
        '- "pay_now" is asking to pay or for the link again: "send the link", '
        '"how do I pay", "I want to pay now", "payment link".\n'
        '- "wants_to_add" is wanting more without saying what: "I want to add '
        'more items", "can I add something else", "add one more thing". If they '
        'name a dish it belongs in "add" and "wants_to_add" is false.\n'
        # Measured: "Please add four cheese pizza in my cart" was read as four
        # of a dish called "cheese pizza", and four Cheese Burst Pizzas went
        # into a cart — $1396 of the wrong thing. A number can belong to the
        # name.
        '- "dish" is copied exactly as the customer wrote it, including a '
        "number that is part of the name (Four Cheese Pizza, Two Egg Omelette, "
        "Seven Spice Chicken). Only treat a leading number as a quantity when "
        "what follows still names a dish by itself — \"2 corn fritters\" is two "
        "of Corn Fritters; \"four cheese pizza\" is one Four Cheese Pizza.\n"
        '- "fulfillment_type" is "DELIVERY" or "PICKUP" only if they say which.\n'
        # Measured: "do you deliver to vesu" was read as choosing delivery,
        # stored as the customer's fulfillment, and answered "Thanks. I still
        # need your name, an email address and the delivery address" — to
        # somebody who had asked a question and ordered nothing.
        '- A QUESTION about delivery is not a choice of it. "Do you deliver to '
        'X", "is delivery available", "how much is delivery", "can I collect" '
        'all leave "fulfillment_type" null — they are asking, not deciding.\n'
        # Measured: "chalo order kar do", "book it", "done" and "confirm my
        # order" all read as false while checkout was described only as
        # "place the order, check out or pay". Those customers are not saying
        # anything unusual; the description was narrow. What is spelled out is
        # the MEANING, in the prompt, where the model still reads the message
        # — never a list of words matched in code.
        '- "checkout" is any way of saying the order is finished and should go '
        "ahead: check out, place it, confirm it, book it, pay now, that is all, "
        "done, go ahead — in any language, Hinglish included (chalo order kar "
        "do, order kar do, ho gaya, bas itna hi).\n"
        '- "checkout" is false while they are still choosing, and false for a '
        "question.\n"
        '- "when" is only a time they CHOSE for the order. A bare time ("at 11", '
        '"11:30") is today if still ahead, otherwise tomorrow. "Tomorrow at one" '
        "is tomorrow 13:00. Nothing about timing means null.\n"
        # Measured: "Sorry! I need thos order tomorrow" came back as no time at
        # all plus a question about opening hours, and was answered with
        # today's.
        '- A DAY with no clock time is still a time they chose: "tomorrow", '
        '"18th Sep", "on Friday", "next Monday" are the date alone, '
        '"YYYY-MM-DD", with nothing after it. Never invent a clock time they '
        "did not say.\n"
        # Measured: "I'd like to know what time I'll receive my order" was
        # read as choosing a time, and answered "that time will not work".
        '- A QUESTION about time is not a time. "When will it arrive", "what '
        'time do you open", "suggest another time" set "asks_hours" true and '
        'leave "when" null. Naming a day or a time is not a question: '
        '"asks_hours" is false whenever "when" is filled in.\n'
        "- Anything not stated is null.\n"
        f"{still}\n"
        f"Message: {message.strip()!r}\n\nJSON:"
    )
    generate = generate or default_generate
    try:
        raw = generate(prompt, settings.ordering_agent_planner_timeout_seconds, 220)
        parsed = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
    except Exception:  # noqa: BLE001 - reading nothing is the safe failure
        logger.warning("Ordering agent could not read what a message wants", exc_info=True)
        return empty
    if not isinstance(parsed, dict):
        return empty

    # A list, because one English sentence orders more than one thing:
    # "add 2 corn fritters and a thai iced tea" added the fritters and
    # dropped the drink while this had room for a single dish.
    asked = parsed.get("add")
    if isinstance(asked, dict):
        asked = [asked]
    adds: list[tuple[str, int]] = []
    for one in asked or []:
        if not isinstance(one, dict):
            continue
        dish = one.get("dish")
        if not isinstance(dish, str) or not dish.strip():
            continue
        if dish.strip().lower() in _NOT_A_DISH_NAME:
            continue
        try:
            quantity = int(one.get("quantity") or 1)
        except (TypeError, ValueError):
            quantity = 1
        adds.append((dish.strip(), max(1, min(quantity, 20))))
    add = adds or None

    details: dict[str, str] = {}
    given = parsed.get("details")
    if isinstance(given, dict):
        for field in _DETAIL_QUESTIONS:
            value = given.get(field)
            if isinstance(value, str) and value.strip() and value.strip().lower() not in {"null", "none"}:
                details[field] = value.strip()

    when = parsed.get("when")
    if not isinstance(when, str) or not when.strip() or when.strip().lower() in {"null", "none"}:
        when = None
    else:
        when = when.strip()
        when = "opening" if when.lower() == "opening" else when

    asks_hours = parsed.get("asks_hours") is True
    wants_to_add = parsed.get("wants_to_add") is True
    cancel_order = parsed.get("cancel_order") is True
    clear_cart = parsed.get("clear_cart") is True
    pay_now = parsed.get("pay_now") is True

    category = parsed.get("category")
    if not isinstance(category, str) or category.strip().lower() in {"null", "none", ""}:
        category = None
    elif categories:
        # Only ever one of the branch's own sections. A model that answers with
        # a section this branch does not have has answered with nothing.
        category = next(
            (c for c in categories if c.casefold() == category.strip().casefold()), None
        )

    # A ceiling on ONE dish's price. Coerced rather than trusted: the model
    # answers "200", a currency-prefixed string, and 200.0 to the same
    # question, and a string reaching the query would be compared against a
    # numeric column. Anything that is not a positive number is no ceiling.
    max_price = parsed.get("max_price")
    if isinstance(max_price, bool):
        max_price = None
    elif isinstance(max_price, str):
        max_price = "".join(c for c in max_price if c.isdigit() or c == ".") or None
    if max_price is not None:
        try:
            max_price = Decimal(str(max_price))
        except (ArithmeticError, ValueError):
            max_price = None
        else:
            if max_price <= 0:
                max_price = None

    browse = parsed.get("browse")
    if not isinstance(browse, str) or not browse.strip() or browse.strip().lower() in {"null", "none"}:
        browse = None

    # A list, because a group can want three and a customer can name three.
    raw_chose = parsed.get("chose")
    if isinstance(raw_chose, str):
        raw_chose = [raw_chose]
    chose = [
        c.strip()
        for c in (raw_chose or [])
        if isinstance(c, str) and c.strip() and c.strip().lower() not in {"null", "none"}
    ] or None

    confirms = parsed.get("confirms")
    if not isinstance(confirms, bool):
        confirms = None

    return {
        "add": add,
        "details": details,
        "checkout": parsed.get("checkout") is True,
        "when": when,
        "chose": chose,
        "confirms": confirms,
        "browse": browse.strip() if browse else None,
        "category": category,
        "asks_hours": asks_hours,
        "wants_to_add": wants_to_add,
        "cancel_order": cancel_order,
        "clear_cart": clear_cart,
        "pay_now": pay_now,
        "max_price": max_price,
    }


def extract_cart_request(
    message: str,
    *,
    generate: Generate | None = None,
) -> tuple[str, int] | None:
    """The dish this message asks to have, if it asks for one.

    Narrow on purpose. Asked to plan, qwen3:8b answered "I want margherita
    pizza" by searching the menu, then searching again with the same
    arguments, and adding nothing — three of four real phrasings failed that
    way. Asked only "is this a request for food, and for what", it answers.

    Returns (dish as the customer named it, quantity) or None. The name is
    still resolved against this branch's menu by the caller, so a dish that
    does not exist cannot be added by saying it convincingly.
    """

    if not message.strip():
        return None
    prompt = (
        "A customer is talking to a restaurant. Decide whether this message asks to "
        "put a dish INTO their order, and which dish.\n\n"
        'Answer with one JSON object: {"wants": true/false, "dish": "the dish named, '
        'exactly as written, or null", "quantity": a number, default 1}\n\n'
        "Rules:\n"
        '- "wants" is true only if they are asking for food to be added, however they '
        'phrase it ("add X", "I want X", "get me X", "X please", "put X in my cart").\n'
        '- "wants" is false for questions ("what do you have", "is X spicy", "how much '
        'is X"), for browsing, and for anything about payment, delivery or their '
        "details.\n"
        "- Never invent a dish. If no dish is named, dish is null.\n\n"
        f"Message: {message.strip()!r}\n\nJSON:"
    )
    generate = generate or default_generate
    try:
        raw = generate(prompt, settings.ordering_agent_planner_timeout_seconds, 120)
        parsed = json.loads(raw[raw.index("{") : raw.rindex("}") + 1])
    except Exception:  # noqa: BLE001 - reading nothing is the safe failure
        logger.warning("Ordering agent could not read a cart request", exc_info=True)
        return None
    if not isinstance(parsed, dict) or parsed.get("wants") is not True:
        return None
    dish = parsed.get("dish")
    if not isinstance(dish, str) or not dish.strip():
        return None
    try:
        quantity = int(parsed.get("quantity") or 1)
    except (TypeError, ValueError):
        quantity = 1
    return dish.strip(), max(1, min(quantity, 20))


def plan_step(
    message: str,
    *,
    history: Sequence[ToolCallRecord],
    tool_names: tuple[str, ...] | None = None,
    generate: Generate | None = None,
    previous_reply: str | None = None,
    recent_history: Sequence[dict[str, str]] | None = None,
    diet: str | None = None,
    cart_summary: str | None = None,
    collecting: Sequence[str] | None = None,
    ready_to_place: bool = False,
    pending: Sequence[str] | None = None,
) -> PlanStep:
    """One planner call: run one more tool, answer, or refuse and say why.

    Never single-shot by itself — Task 5's loop is what turns repeated calls
    into a conversation, feeding each round's `ToolCallRecord`s back in as
    `history`. This function only ever decides the ONE next step; it has no
    memory of its own and reads nothing but what `history` hands it.
    """

    allowed = tuple(name for name in (tool_names or tuple(TOOLS)) if name in TOOLS)
    generator = generate or default_generate
    try:
        raw = generator(
            build_planner_prompt(
                message, history, tool_names, previous_reply, recent_history, diet,
                cart_summary, collecting, ready_to_place, pending,
            ),
            settings.ordering_agent_planner_timeout_seconds,
            settings.ordering_agent_planner_max_tokens,
        )
        parsed = _extract_json(raw)
    except (httpx.TimeoutException, httpx.HTTPError) as error:
        logger.warning("Ordering agent planner unavailable: %s", error)
        return PlanStep(error="planner_unavailable", detail=str(error))
    except (ValueError, json.JSONDecodeError) as error:
        return PlanStep(error="planner_unusable", detail=str(error))

    if "answer" in parsed:
        answer = parsed.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            return PlanStep(error="planner_unusable", detail="answer was not a non-empty string")
        about = parsed.get("about")
        return PlanStep(
            answer=answer.strip(),
            answer_about=about.strip().lower() if isinstance(about, str) else "other",
        )

    if "tool" in parsed:
        return _validate_call(parsed.get("tool"), parsed.get("args"), allowed)

    # A subject and nothing else. The model has said what the turn is about
    # and has nothing to add — and for a cart or an order the deterministic
    # read-back for that subject is the answer. Measured live, treating this
    # as an error spent a 2.4-second round before the model said, in its own
    # words, what the rows already said.
    about = parsed.get("about")
    if isinstance(about, str) and about.strip():
        return PlanStep(answer="", answer_about=about.strip().lower())

    return PlanStep(
        error="planner_unusable",
        detail="response JSON had neither 'tool' nor 'answer'",
    )


__all__ = [
    "Generate",
    "PlanStep",
    "ToolCallRecord",
    "build_planner_prompt",
    "plan_step",
]

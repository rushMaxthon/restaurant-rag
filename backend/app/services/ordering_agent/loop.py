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

import logging
import time
from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import get_settings
from app.schemas.suggestions import CartLinePayload
from app.services.ordering_agent import guards, order_draft
from app.services.ordering_agent import tools as tools_module
from app.services.ordering_agent.planner import (
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


def describe_ready(total: str | None = None) -> str:
    """Everything is gathered and only the confirmation is left.

    Said deterministically because the model would not: offered place_order
    as its only tool it still answered "proceed to checkout" and placed
    nothing. The customer gets a sentence and a button instead.
    """

    return "That is everything I need. Tap Place order below and I will send you a payment link."


def _cart_summary_in(records: list[ToolCallRecord]) -> str | None:
    """The most recent cart this turn, read back — or None."""

    for record in reversed(records):
        said = describe_cart(record.result)
        if said is not None:
            return said
    return None


def _choice_question_in(records: list[ToolCallRecord]) -> str | None:
    """The most recent needs_choice result this turn, as a question — or None."""

    for record in reversed(records):
        question = ask_for_choice(record.result)
        if question is not None:
            return question
    return None


def _repeated_call(records: list[ToolCallRecord], tool: str, args: dict[str, Any]) -> int | None:
    """The 1-based index of an earlier call this turn with the same tool and
    the same arguments that actually ran, or None. Only calls that produced
    a result count: a call that was refused (an error record) is fair to
    retry with the same arguments once the model has fixed what it can.
    """

    for index, record in enumerate(records, 1):
        if record.tool == tool and record.error is None and record.args == args:
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
_COLLECTING_TOOLS = ("order_requirements", "save_order_details", "place_order", "view_cart")


def _offered_tools(
    seen: set[uuid.UUID], ordering: bool = False, ready: bool = False
) -> tuple[str, ...]:
    """Which tools this round may choose from.

    With nothing seen — an empty cart and no lookup yet — a cart tool has no
    id it could legitimately carry, and a model asked for one anyway will
    invent one; it invented "123" six rounds running on a live turn. So the
    rule is enforced by what is on offer rather than by refusing what comes
    back: look something up, and the cart tools appear.
    """

    if ready:
        # One tool, and the prompt says to call it. Offered four and told
        # plainly that everything was in hand, the model still answered
        # "ready to be placed, proceed to pay" and placed nothing — twice.
        # A choice it cannot make wrongly is worth more than a clearer rule.
        return ("place_order",) if "place_order" in TOOLS else ()
    if ordering:
        return tuple(name for name in _COLLECTING_TOOLS if name in TOOLS)
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

    seen = guards.seed_seen_ids(cart)
    # The cart resolved once, up front, by the same code the tool uses. It
    # goes into every prompt as a fact and costs one query per turn; the
    # alternative is a model that has to remember to look before it speaks,
    # and on a live turn it did not.
    cart_summary: str | None = None
    if cart:
        try:
            cart_summary = describe_cart(TOOLS["view_cart"].handler(db, scope, ViewCartArgs(lines=_as_tool_lines(cart))))
        except Exception:  # noqa: BLE001 - a prompt fact is never worth failing a turn for
            logger.warning("Ordering agent could not resolve the cart for the prompt", exc_info=True)
        if cart_summary:
            cart_summary = "In the cart right now: " + cart_summary

    # What this conversation is in the middle of, if anything. Stated as a
    # fact for the same reason the cart is: a model that has to infer it
    # from the thread sometimes does not.
    # None while the customer is still browsing; a list of field names once
    # they have been asked for their details; empty once nothing is missing
    # and the order can be placed.
    collecting: list[str] | None = None
    if scope.session_id is not None:
        draft = tools_module._draft_for(scope)
        if draft.collecting:
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

    def _capped(reason: str) -> TurnOutcome:
        # A cap with a needs_choice result in hand is not a failed turn: the
        # question is asked from the tool's rows (see `ask_for_choice`), and
        # the turn ends as a success. Any other cap keeps the brief's rule —
        # no partial answer, the caller falls back to today's reply.
        ready_now = _still_missing() == [] and scope.customer is not None
        question = (
            describe_placed_order(placed_order_in(records))
            or describe_collecting(_still_missing())
            or (describe_ready() if ready_now else None)
            or _choice_question_in(records)
            or _cart_summary_in(records)
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

    for _round_index in range(rounds):
        # Checked before every model call, per the brief — a turn that is
        # already out of time never spends more of it asking the model for
        # one more step.
        if clock() - start >= budget:
            return _capped("budget_exceeded")

        ready = collecting == [] and scope.customer is not None
        # On a channel with no button, being ready IS the instruction: the
        # model will not reach for the tool (measured, repeatedly), and the
        # customer has already asked to order and handed over their details.
        if auto_place and _still_missing() == [] and not placed_order_in(records):
            step = PlanStep(tool="place_order", args={})
        else:
            step = plan_step(
                message,
                history=tuple(records),
                generate=generate,
                tool_names=_offered_tools(seen, collecting is not None, ready),
                previous_reply=previous_reply,
                # The thread is dropped once the state says exactly what to do.
                # It exists to resolve "yes" and "the second one"; with nothing
                # left to collect there is nothing to resolve, and on a live turn
                # the model answered by copying its own earlier question out of
                # it word for word instead of placing the order.
                recent_history=None if ready else recent_history,
                diet=scope.diet,
                cart_summary=cart_summary,
                collecting=collecting,
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
                records.append(_error_record(step))
                continue
            step = repaired

        if step.answer is not None:
            # An answer that says nothing is not an answer. The tool results
            # hold the cart; prefer saying it to shipping an empty string and
            # letting the caller fall through to a layer with no cart at all.
            placed = placed_order_in(records)
            # A turn that placed an order is about that order, whatever the
            # model called it, and the read-back is the order's own figures.
            spoken = (
                describe_placed_order(placed)
                or step.answer.strip()
                or describe_collecting(_still_missing())
                or (describe_ready() if _still_missing() == [] and collecting is not None else None)
                or _cart_summary_in(records)
                or _choice_question_in(records)
            )
            return TurnOutcome(
                answer=spoken,
                placed_order=placed,
                ready_to_place=(
                    _still_missing() == [] and scope.customer is not None and placed is None
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
            records.append(
                ToolCallRecord(
                    tool=tool_name,
                    args=prepared.model_dump(),
                    error=f"repeated_call: identical to call {repeated}; read its result instead of calling again",
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

        action = result.get("action") if isinstance(result, dict) else None
        if isinstance(action, dict):
            actions.append(action)
            # One mutation per turn, decided here rather than by the prompt.
            # Live on 2026-09-16: "add one more Margherita" produced an
            # applied add and then, rounds later, a second one — the customer
            # got three. A cart change is the end of the work; the client
            # names what happened from the action and the menu it holds, so
            # no further model round is spent phrasing it.
            return TurnOutcome(
                answer=None, actions=actions, records=records,
                fallback_reason=None, elapsed_seconds=clock() - start,
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

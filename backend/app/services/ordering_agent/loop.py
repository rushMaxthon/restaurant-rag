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
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.config import get_settings
from app.schemas.suggestions import CartLinePayload
from app.services.ordering_agent import guards
from app.services.ordering_agent.planner import Generate, PlanStep, ToolCallRecord, plan_step
from app.services.ordering_agent.tools import TOOLS, OrderingScope

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
    records: list[ToolCallRecord] = []
    actions: list[dict[str, Any]] = []

    def _capped(reason: str) -> TurnOutcome:
        # A cap with a needs_choice result in hand is not a failed turn: the
        # question is asked from the tool's rows (see `ask_for_choice`), and
        # the turn ends as a success. Any other cap keeps the brief's rule —
        # no partial answer, the caller falls back to today's reply.
        question = _choice_question_in(records)
        if question is not None:
            logger.info("Ordering agent asked the needs_choice question itself after %s", reason)
            return TurnOutcome(
                answer=question, actions=actions, records=records,
                fallback_reason=None, elapsed_seconds=clock() - start,
            )
        return TurnOutcome(
            answer=None, actions=actions, records=records,
            fallback_reason=reason, elapsed_seconds=clock() - start,
        )

    for _round_index in range(rounds):
        # Checked before every model call, per the brief — a turn that is
        # already out of time never spends more of it asking the model for
        # one more step.
        if clock() - start >= budget:
            return _capped("budget_exceeded")

        step = plan_step(message, history=tuple(records), generate=generate)

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
            records.append(_error_record(step))
            continue

        if step.answer is not None:
            return TurnOutcome(
                answer=step.answer,
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

        prepared, guard_error = guards.prepare_tool_call(tool_name, step.args, cart=cart, seen=seen)
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

    return _capped("round_cap")


__all__ = ["Clock", "TurnOutcome", "ask_for_choice", "run_turn"]

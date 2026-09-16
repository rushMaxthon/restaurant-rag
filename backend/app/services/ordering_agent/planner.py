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
from dataclasses import dataclass, field
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
    error: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and (self.tool is not None or self.answer is not None)


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
            payload["result"] = record.result
        lines.append(json.dumps(payload, default=str, separators=(",", ":")))
    return "\n".join(lines)


def build_planner_prompt(
    message: str,
    history: Sequence[ToolCallRecord],
    tool_names: tuple[str, ...] | None = None,
) -> str:
    """Public so a test can assert on the prompt text directly, the same way
    `test_chat_tools.py` asserts on `tool_chat.build_planner_prompt`'s
    output rather than only on what a scripted model produces from it.
    """

    return f"""Decide the next step for this customer's order, from what the
tools can tell you and what you already found out this turn.

Return STRICT JSON only, one of these two shapes:
{{"tool": "<tool name>", "args": {{...}}}}
{{"answer": "<your reply to the customer>"}}

Tools (each returns one slice of data):
{describe_tools_for_prompt(tool_names)}

Calls already made this turn, and what they returned:
{_serialize_history(history)}

Rules:
- use a tool name exactly as spelled above, and nothing else
- pass only the arguments listed for that tool
- never include a restaurant, branch, customer or user id — a call
  containing one is discarded
- once you have enough to answer, reply with {{"answer": "..."}} instead of
  calling another tool
- never repeat a call you already made with the same arguments — its result
  is listed above; read it instead
- a result with "outcome": "needs_choice" means the dish is real but the
  customer must choose first: do not call the tool again — answer by asking
  which of the listed sizes or options they want, each with its price
- a result that carries an action (status "applied" or "proposed") is the
  end of the work: answer by telling the customer what was done, or what
  needs their confirmation

Customer: {message}

Answer now."""


def _ollama_generate(prompt: str, timeout_seconds: float, max_tokens: int) -> str:
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
    try:
        validated = spec.args_model.model_validate(args_obj)
    except ValidationError as error:
        # `extra="forbid"` is what actually catches a smuggled id that is
        # NOT in `FORBIDDEN_ARG_NAMES` (an argument nobody thought to ban by
        # name, but that this specific tool still never declared) — the
        # second, narrower gate behind the first.
        return PlanStep(error="invalid_arguments", detail=str(error))

    return PlanStep(tool=tool_name, args=validated.model_dump())


def plan_step(
    message: str,
    *,
    history: Sequence[ToolCallRecord],
    tool_names: tuple[str, ...] | None = None,
    generate: Generate | None = None,
) -> PlanStep:
    """One planner call: run one more tool, answer, or refuse and say why.

    Never single-shot by itself — Task 5's loop is what turns repeated calls
    into a conversation, feeding each round's `ToolCallRecord`s back in as
    `history`. This function only ever decides the ONE next step; it has no
    memory of its own and reads nothing but what `history` hands it.
    """

    allowed = tuple(name for name in (tool_names or tuple(TOOLS)) if name in TOOLS)
    generator = generate or _ollama_generate
    try:
        raw = generator(
            build_planner_prompt(message, history, tool_names),
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
        return PlanStep(answer=answer.strip())

    if "tool" in parsed:
        return _validate_call(parsed.get("tool"), parsed.get("args"), allowed)

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

"""The two prompts an analyst run uses, and how a tool result is shown to it.

Explore and conclude are separate calls on purpose. A single prompt that asks
for both the next question and the final answer invites the model to answer
before it has looked, and on a CPU host a wrong turn costs a minute. Splitting
them also means the conclude step sees the whole transcript at once, which is
where a cross-tool conclusion has to come from.

The instructions are written against the failures this system has actually
produced rather than against a general idea of good analysis:

* A branch closure read as a declining dish, so the catalogue leads with the
  branch tools and the prompt says explicitly that a whole branch outranks
  anything inside it.
* Confident conclusions from four trading days, so coverage is the first thing
  the model is told to check and "not enough data" is named as a valid answer.
* Correlation stated as cause, so observation and explanation are separate
  fields, and the prompt says which one may contain a "because".
"""

from __future__ import annotations

import json
from typing import Any

from app.config import get_settings
from app.services.insights.analyst.registry import TOOL_LIST
from app.services.insights.analyst.schemas import ALLOWED_WINDOW_DAYS

settings = get_settings()


def render_tool_catalogue(compact: bool = False) -> str:
    """The tools, their arguments, and one line each on what they answer.

    `compact` drops the descriptions to their first clause. The explore prompt
    is re-sent on every turn, and on a CPU host every kilobyte of prompt is
    latency paid again — the model needs to know a tool exists and what it
    takes, not the full rationale.
    """

    lines = []
    for spec in TOOL_LIST:
        fields = spec.args_model.model_fields
        if fields:
            args = ", ".join(
                f"{name}: {field.annotation.__name__ if hasattr(field.annotation, '__name__') else field.annotation}"
                for name, field in fields.items()
            )
        else:
            args = "no arguments"
        if compact:
            summary = spec.description.split(".")[0]
            lines.append(f"- {spec.name}({args}): {summary}")
        else:
            lines.append(f"- {spec.name}({args})\n    {spec.description}")
    return "\n".join(lines)


def truncate_result(payload: Any, limit: int | None = None) -> str:
    """A tool result, rendered small enough to be worth reading.

    Truncation only affects what the model sees. The ledger keeps every number
    the call returned, so a figure trimmed out of the prompt is still a figure
    the model cannot cite — it never saw it — and one that would be accepted if
    it somehow did.
    """

    resolved = limit or settings.analyst_max_result_chars
    rendered = json.dumps(payload, default=str, separators=(",", ":"))
    if len(rendered) <= resolved:
        return rendered
    return rendered[:resolved] + f"…[truncated, {len(rendered)} chars total]"


def build_explore_prompt(
    *,
    period_label: str,
    coverage_summary: str,
    transcript: list[dict[str, Any]],
    calls_remaining: int,
    window_days: int,
) -> str:
    history = "\n".join(
        f"{entry['call_id']}: {entry['tool']}({json.dumps(entry['args'], default=str)}) -> {entry['result']}"
        for entry in transcript
    ) or "(nothing yet)"

    return f"""You are a restaurant analyst deciding what to look at next.

Return STRICT JSON only, one of these two shapes:
{{"tool": "<tool name>", "args": {{...}}, "reason": "<why, one short sentence>"}}
{{"done": true, "reason": "<why you have enough, one short sentence>"}}

Rules:
- choose ONE tool from the catalogue below, spelled exactly
- ALWAYS pass window_days={window_days}. The period below is that long, and a
  different window would answer a different question from the one being asked
- do not repeat a call you have already made with the same arguments
- you have {calls_remaining} calls left; stop early if you have enough
- start from coverage and the headline numbers, then follow the largest movement
  in money terms, not the largest percentage
- a whole branch opening or closing outranks anything inside it: if branch
  figures moved, look there before looking at dishes or times of day

Period under analysis: {period_label}
Coverage: {coverage_summary}

Catalogue:
{render_tool_catalogue(compact=True)}

What you have looked at so far:
{history}

Choose the next call now.
"""


def build_conclude_prompt(
    *,
    period_label: str,
    coverage_summary: str,
    transcript: list[dict[str, Any]],
    result_chars: int | None = None,
) -> str:
    # The conclude prompt carries every result at once, so it is the largest
    # single input of the run and the one that decides how long the slowest
    # generation takes. Results are trimmed harder here than during
    # exploration: a finding needs the headline figures, not every row.
    limit = result_chars or settings.analyst_conclude_result_chars
    history = "\n".join(
        f"{entry['call_id']}: {entry['tool']}({json.dumps(entry['args'], default=str)}) -> "
        f"{entry['result'][:limit]}"
        for entry in transcript
    ) or "(no data was gathered)"

    return f"""You are writing the findings of a restaurant analysis.

Return STRICT JSON only with this exact shape:
{{
  "insufficient_data": false,
  "summary": "one or two sentences",
  "findings": [
    {{
      "category": "short label, e.g. payments or branches",
      "title": "one line",
      "body": "what the data shows, no causes",
      "interpretation": "what might explain it, or null",
      "severity": "INFO|LOW|MEDIUM|HIGH",
      "confidence": "LOW|MEDIUM|HIGH",
      "subject": "the branch, dish, or area, or null",
      "metrics": [
        {{"name": "revenue", "current": 0, "previous": 0,
          "absolute_change": 0, "percent_change": 0,
          "unit": "money|count|percent|minutes|days"}}
      ],
      "evidence": ["call_1"]
    }}
  ],
  "recommendations": [
    {{
      "title": "one line",
      "rationale": "why, referring to the finding",
      "requested_action_type": "PROMOTE_ITEM|PROMOTE_CATEGORY|DAYPART_OFFER|WINBACK_INACTIVE|WELCOME_NEW_CUSTOMERS|CROSS_SELL_COMBO|OPERATIONAL_REVIEW|PROTECT_SUPPLY",
      "discount_percent": null,
      "minimum_order_amount": null,
      "expected_impact_amount": null,
      "expected_impact_basis": null,
      "priority": 0,
      "confidence": "LOW|MEDIUM|HIGH",
      "evidence": ["call_1"]
    }}
  ]
}}

Hard rules, all of them checked afterwards:
- every number you write must appear in the results below; never estimate,
  extrapolate, or carry a figure over from your own knowledge
- every finding and recommendation must cite the calls it came from, by id
- "body" states only what was measured. It must not contain "because",
  "caused by", "due to", "led to", or any other claim about cause
- "interpretation" is where an explanation belongs, and it must read as a
  possibility rather than a fact
- if a metric moved, state current and previous and let the change follow from
  them; do not state a change that is not their difference
- rank by the SIZE OF THE MONEY CHANGE, not by percentage. A percentage on a
  small base is not a large movement: a rise from 31 to 1031 is worth less than
  a fall from 2427 to 230, and the larger money movement must be among your
  findings even when a smaller one has the more dramatic percentage
- when something fell and something else rose, report the fall first; an owner
  can act on a loss, and good news that hides a larger loss is worse than
  silence
- if the data is too thin to support conclusions, set "insufficient_data": true
  and return no findings. That is a correct answer, not a failure
- do not recommend a discount unless you name the action type it belongs to
- return at most 2 findings and 1 recommendation, the most important first,
  with at most 2 metrics each. Keep every string to one short sentence:
  output length is what makes a run slow, and a truncated reply wastes it

Period under analysis: {period_label}
Coverage: {coverage_summary}

Everything you looked at:
{history}

Write the analysis now.
"""


__all__ = [
    "build_conclude_prompt",
    "build_explore_prompt",
    "render_tool_catalogue",
    "truncate_result",
]

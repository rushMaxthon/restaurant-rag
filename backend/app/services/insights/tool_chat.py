"""Tier 2: one extraction call that may reach the read-only data tools.

Tier 1 answers the questions the rules recognise, in about fifty milliseconds.
This is what happens when they do not recognise one. A single generation maps
the question onto either an existing skill or one of the analyst tools built in
Phase 8A, the backend executes it, and the answer is composed in code.

Three decisions shape everything here:

* **One call, not a loop.** Phase 8C's exploration loop took 328–441 seconds on
  this host and was measured worse than the rules engine. A single extraction
  returning two fields takes 6–8 seconds warm, and is the whole reason this is
  usable in a chat.
* **The model maps intent; it never writes the answer.** Phase 8E established
  that it is poor at judgement and unnecessary for phrasing. It picks a tool.
  The formatter states the figures, so no generated text carries a number.
* **Every failure is a refusal.** An unknown tool, an argument that will not
  validate, an empty result, a timeout — all end in Tier 3 saying so, never in a
  neighbouring answer offered as though it were the one asked for.

Scope is not a consideration for the planner because it cannot express one: no
tool argument accepts a restaurant, branch, or user id, and the registry refuses
to load a tool that declares one. The scope comes from the authenticated user,
as it does everywhere else.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx

from app.config import get_settings
from app.services.cache import cache_get_json, cache_set_json
from app.services.insights.analyst.registry import TOOLS
from app.services.insights.analyst.schemas import ALLOWED_WINDOW_DAYS
from app.services.insights.rules import money
from app.services.insights.presentation import (
    action,
    blocks,
    bold,
    bullets,
    labelled,
    numbered,
)

settings = get_settings()
logger = logging.getLogger(__name__)

from app.services.ollama_client import (
    think_option,
    GENERATE_ENDPOINT,
    build_client,
    local_only_options,
)

# Same signature as the analyst runner's, so tests drive this without an Ollama
# host and without patching module internals.
Generate = Callable[[str, float, int], str]

# The tools chat may reach in 2A.1. Deliberately a subset: each one needs a
# formatter, and six is enough to measure whether the planner picks well before
# writing the other fourteen.
CHAT_TOOLS: tuple[str, ...] = (
    "get_stockouts",
    "get_payment_failures",
    "get_branch_status",
    "get_menu_health",
    "get_data_coverage",
    "get_anomalies",
    "get_period_metrics",
    "get_metric_deltas",
    "get_breakdown",
    "get_daily_series",
    "get_location_performance",
    "get_branch_metrics",
    "compare_locations",
    "get_cancellations",
    "get_order_operations",
    "get_offer_performance",
    "get_customer_cohorts",
    "get_recent_briefing",
    "get_insight_history",
    "get_open_recommendations",
    "get_fulfillment_mix",
    "get_payment_mix",
    "get_order_economics",
    "get_payment_health",
    "get_offer_catalogue",
    "get_combos",
    "get_schedule",
    "get_notification_campaigns",
)

# Argument names that would let a question choose whose data it reads. The
# registry already refuses to load a tool declaring one; this is the second
# gate, on the way in rather than at import, because a planned call is the first
# place model-authored text meets a tool.
FORBIDDEN_ARG_NAMES = frozenset(
    {
        "restaurant_id",
        "restaurant_location_id",
        "location_id",
        "branch_id",
        "owner_id",
        "user_id",
        "customer_id",
        "tenant_id",
        "scope",
        "sql",
        "query",
    }
)


@dataclass(slots=True)
class ToolPlan:
    """What one planner call decided."""

    tool: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    skill: str | None = None
    error: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and (self.tool is not None or self.skill is not None)


def tools_enabled_for(scope: Any) -> bool:
    """Whether the tool path is live. One switch, and it is not per-restaurant.

    There used to be an allowlist of restaurant ids beside this. It was meant as
    a rollout dial and became a permanent split: one restaurant got the data
    tools and every other owner got a thinner assistant, with nothing on screen
    to explain why. Whether the AI manager works is a property of the build, not
    of which restaurant you happen to own.

    `scope` is kept in the signature because callers pass it and because it
    documents that the decision is *about* a scope — it simply no longer varies
    by one.
    """

    return settings.enable_ai_manager_chat_tools


def _describe_chat_tools() -> str:
    lines = []
    for name in CHAT_TOOLS:
        spec = TOOLS.get(name)
        if spec is None:
            continue
        fields = spec.args_model.model_fields
        # The tool's real arguments, not a generic example. A generic one made
        # the planner pass `window_days` to a tool that takes nothing, which
        # `extra="forbid"` then rejected.
        args = ", ".join(fields) if fields else "no arguments"
        summary = spec.description.split(".")[0].strip()
        lines.append(f"- {name}({args}) — {summary}")
    return "\n".join(lines)


def build_planner_prompt(question: str, skills: tuple[str, ...]) -> str:
    return f"""Choose what answers the restaurant owner's question.

Return STRICT JSON only, one of these two shapes:
{{"skill": "<skill name>"}}
{{"tool": "<tool name>", "args": {{...}}}}

Prefer a skill when one fits. Use a tool only for what no skill covers.

Skills (each writes a full answer):
{chr(10).join(f"- {name}" for name in skills)}

Tools (each returns one slice of data):
{_describe_chat_tools()}

Rules:
- use a name exactly as spelled above, and nothing else
- pass only the arguments listed for that tool; pass {{}} when it takes none
- window_days must be one of {list(ALLOWED_WINDOW_DAYS)}
- never include a restaurant, branch, customer or user id: you do not choose
  whose data is read, and a call containing one is discarded

Question: {question}

Answer now."""


def _ollama_generate(prompt: str, timeout_seconds: float, max_tokens: int) -> str:
    payload = {
        "model": settings.chat_tool_planner_model,
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


def clean_arguments(tool: str, raw_args: Any) -> tuple[dict[str, Any], str | None]:
    """Keep the arguments this tool declares, and refuse the ones nobody may pass.

    A planner routinely over-supplies — it passed `window_days` to a tool taking
    none in the first live measurement. Dropping an argument the tool does not
    declare costs nothing, so it is dropped. A scope-bearing name is different:
    it is the one thing a question must never choose, so it fails the call
    outright rather than being quietly removed.
    """

    if raw_args is None:
        return {}, None
    if not isinstance(raw_args, dict):
        return {}, "arguments were not an object"

    smuggled = sorted(set(raw_args) & FORBIDDEN_ARG_NAMES)
    if smuggled:
        return {}, f"arguments named {smuggled}, which a question may never choose"

    spec = TOOLS.get(tool)
    if spec is None:
        return {}, f"unknown tool {tool!r}"

    declared = set(spec.args_model.model_fields)
    return {key: value for key, value in raw_args.items() if key in declared}, None


# A plan is a property of the wording, not of the restaurant: "was anything out
# of stock" maps to the stockout tool whoever asks it. So the cache key is the
# question alone, and — this is the point — **no tenant data is ever written to
# this cache**, which is why sharing entries across restaurants is safe rather
# than merely convenient. The scope is applied when the tool runs, long after
# the plan is read back.
PLAN_CACHE_PREFIX = "insights:chat:plan"

# Bumped whenever the tool set or the prompt changes, so a stale mapping cannot
# outlive the thing it was mapping onto.
PLAN_CACHE_VERSION = "phase-a"


def plan_cache_key(question: str) -> str:
    digest = hashlib.sha256(" ".join(question.lower().split()).encode()).hexdigest()[:32]
    return f"{PLAN_CACHE_PREFIX}:{PLAN_CACHE_VERSION}:{digest}"


def _cached_plan(question: str) -> ToolPlan | None:
    payload = cache_get_json(plan_cache_key(question))
    if not isinstance(payload, dict):
        return None

    tool = payload.get("tool")
    skill = payload.get("skill")
    # Re-validated on the way out, never trusted because it was stored. The tool
    # set can shrink between writing an entry and reading it.
    if tool is not None:
        if tool not in CHAT_TOOLS:
            return None
        args, error = clean_arguments(tool, payload.get("args") or {})
        if error is not None:
            return None
        return ToolPlan(tool=tool, args=args)
    if isinstance(skill, str) and skill:
        return ToolPlan(skill=skill)
    return None


def _store_plan(question: str, plan: ToolPlan) -> None:
    cache_set_json(
        plan_cache_key(question),
        {"tool": plan.tool, "args": plan.args, "skill": plan.skill},
        ttl_seconds=settings.chat_tool_plan_cache_ttl_seconds,
    )


def plan_question(
    question: str,
    *,
    skills: tuple[str, ...],
    generate: Generate | None = None,
    use_cache: bool = True,
) -> ToolPlan:
    """One call. Returns a plan, or a plan carrying why there isn't one.

    A repeated question skips the call entirely, which is the difference between
    six seconds and none for the phrasings an owner actually reuses.
    """

    if use_cache:
        cached = _cached_plan(question)
        if cached is not None:
            # Only a validated plan is stored, and it is validated again above,
            # so a cache hit cannot introduce a tool the current build refuses.
            if cached.skill and cached.skill not in skills:
                cached = None
            if cached is not None:
                logger.info("Chat tool plan served from cache")
                return cached

    generator = generate or _ollama_generate
    try:
        raw = generator(
            build_planner_prompt(question, skills),
            settings.chat_tool_planner_timeout_seconds,
            settings.chat_tool_planner_max_tokens,
        )
        parsed = _extract_json(raw)
    except (httpx.TimeoutException, httpx.HTTPError) as error:
        logger.warning("Chat tool planner unavailable: %s", error)
        return ToolPlan(error="planner_unavailable", detail=str(error))
    except (ValueError, json.JSONDecodeError) as error:
        return ToolPlan(error="planner_unusable", detail=str(error))

    skill = parsed.get("skill")
    if isinstance(skill, str) and skill.strip() in skills:
        plan = ToolPlan(skill=skill.strip())
        if use_cache:
            _store_plan(question, plan)
        return plan

    tool = parsed.get("tool")
    if not isinstance(tool, str) or tool.strip() not in CHAT_TOOLS:
        # Either a name that does not exist or one outside what chat may reach.
        # Both are refusals: guessing a near neighbour is how a question about
        # one thing gets answered with another.
        return ToolPlan(
            error="unknown_tool",
            detail=f"planner chose {tool!r}, which chat cannot use",
        )

    args, arg_error = clean_arguments(tool.strip(), parsed.get("args"))
    if arg_error is not None:
        return ToolPlan(error="invalid_arguments", detail=arg_error)

    plan = ToolPlan(tool=tool.strip(), args=args)
    if use_cache:
        _store_plan(question, plan)
    return plan


# --- answer composition ----------------------------------------------------
#
# One formatter per tool. Deterministic, so no figure in an answer was ever
# written by a model, and the tool it came from is always named — a wrong tool
# choice should be visible to the reader rather than silent.


def _format_stockouts(data: dict[str, Any]) -> str | None:
    items = data.get("items") or []
    period = (data.get("period") or {}).get("label", "this period")
    if not items:
        return f"No dishes were switched off during {period}."
    listed = []
    for row in items[:5]:
        switch_offs = row.get("switch_offs", 0)
        hours = row.get("hours_unavailable", 0)
        listed.append(
            labelled(
                row.get("item_name", "A dish"),
                f"unavailable for {bold(f'{hours} hours')}, switched off "
                f"{switch_offs} time{'s' if switch_offs != 1 else ''}",
            )
        )
    return blocks(f"Dishes switched off during {period}:", bullets(listed))


def _format_payment_failures(data: dict[str, Any]) -> str | None:
    period = (data.get("period") or {}).get("label", "this period")
    lost_orders = data.get("lost_orders") or 0
    if not lost_orders:
        return f"No orders were lost at the payment step in {period}."

    share = data.get("lost_value_share_of_revenue_percent")
    lead = (
        f"{bold(_count(lost_orders, 'order'))} worth "
        f"{bold(_money(data.get('lost_value')))} were lost at the payment step in {period}"
        + (f", {share}% of counted revenue." if share is not None else ".")
    )
    reasons = [
        labelled(
            row["reason"].replace("_", " ").capitalize(),
            f"{_count(row['orders'], 'order')} worth {_money(row['value'])}",
        )
        for row in data.get("current") or []
    ]
    return blocks(lead, bullets(reasons))


def _format_branch_status(data: dict[str, Any]) -> str | None:
    branches = data.get("branches") or []
    if not branches:
        return "No branches are set up for this restaurant."
    listed = []
    for row in branches:
        if not row.get("is_active"):
            state = "not active on the platform"
        elif row.get("is_open"):
            state = "open"
        else:
            reason = row.get("temporary_closed_reason")
            state = f"closed ({reason})" if reason else "closed, with no reason recorded"
        hours = ""
        if row.get("opening_time") and row.get("closing_time"):
            hours = f", hours {row['opening_time'][:5]}–{row['closing_time'][:5]}"
        listed.append(labelled(row["branch_name"], f"{bold(state)}{hours}"))
    return blocks("Your branches right now:", bullets(listed))


def _format_menu_health(data: dict[str, Any]) -> str | None:
    items = data.get("items") or []
    if not items:
        return "There are no menu items set up for this restaurant."

    unavailable = data.get("unavailable_count") or 0
    lead = (
        f"{bold(len(items))} menu item{'s' if len(items) != 1 else ''} across your "
        f"branches, {bold(unavailable)} currently switched off."
    )
    flags = [
        part
        for part in (
            f"{data['veg_count']} vegetarian" if data.get("veg_count") else "",
            f"{data['bestseller_count']} marked bestseller" if data.get("bestseller_count") else "",
            f"{data['new_launch_count']} new" if data.get("new_launch_count") else "",
        )
        if part
    ]
    if flags:
        lead += " " + ", ".join(flags).capitalize() + "."
    sections = [lead]

    # A short menu is listed; a long one is summarised by category. Printing
    # sixty dishes at an owner who asked what is on the menu is not an answer.
    if len(items) <= 10:
        sections.append(
            bullets(
                labelled(
                    row.get("name", "Unnamed"),
                    f"{row.get('branch_name')}, {row.get('category')}"
                    + ("" if row.get("is_available", True) else " — switched off"),
                )
                for row in items
            )
        )
    else:
        by_category: dict[str, int] = {}
        for row in items:
            by_category[row.get("category", "Uncategorised")] = (
                by_category.get(row.get("category", "Uncategorised"), 0) + 1
            )
        sections.append(
            blocks(
                "By category:",
                bullets(
                    labelled(category, f"{count} item{'s' if count != 1 else ''}")
                    for category, count in sorted(
                        by_category.items(), key=lambda pair: -pair[1]
                    )
                ),
            )
        )
        off = [row for row in items if not row.get("is_available", True)]
        if off:
            sections.append(
                blocks(
                    "Switched off:",
                    bullets(
                        labelled(row["name"], f"{row['branch_name']}, {row['category']}")
                        for row in off[:5]
                    ),
                )
            )

    gaps = data.get("category_gaps_by_branch") or []
    if gaps:
        sections.append(
            blocks(
                "Categories one branch carries and another does not:",
                bullets(
                    labelled(
                        row["branch_name"],
                        f"missing {', '.join(row['missing_categories'])}",
                    )
                    for row in gaps
                ),
            )
        )
    return blocks(*sections)


def _format_data_coverage(data: dict[str, Any]) -> str | None:
    period = (data.get("period") or {}).get("label", "this period")
    current = data.get("current") or {}
    trading = current.get("trading_days")
    days = current.get("days_in_window")
    if trading is None or days is None:
        return None

    lead = (
        f"In {period} you traded on {bold(trading)} of {days} days, taking "
        f"{bold(current.get('orders'))} orders from "
        f"{bold(current.get('customers'))} customers."
    )
    caveat = (
        "That is below the volume where percentage comparisons are reliable, so "
        "read any percentage from this period with care."
        if (current.get("orders") or 0) < (data.get("minimum_orders_for_reliable_percentages") or 0)
        else ""
    )
    return blocks(lead, caveat)


def _format_anomalies(data: dict[str, Any]) -> str | None:
    period = (data.get("period") or {}).get("label", "this period")
    report = data.get("anomalies") or {}
    if not report.get("evaluated"):
        note = report.get("note") or "there was not enough daily history to compare against"
        return f"I could not check {period} for unusual days: {note}."

    points = report.get("points") or []
    if not points:
        return f"No day in {period} stood out against the recent baseline."

    listed = [
        labelled(
            row.get("day", "a day"),
            f"{row.get('value')} against a baseline of {row.get('baseline')}",
        )
        for row in points[:5]
    ]
    return blocks(f"Days in {period} that stood out:", bullets(listed))


def _period_of(data: dict[str, Any]) -> str:
    return (data.get("period") or {}).get("label", "this period")


def _money(value: Any) -> str:
    """A currency figure, rendered the way the rest of the product renders one.

    Safe for the number check because `money` rounds and the guardrail already
    allows a value's rounded forms — the same allowance that lets the skills
    write "₹1,235" for 1234.56.
    """

    try:
        return money(float(value))
    except (TypeError, ValueError):
        return str(value)


def _count(value: Any, noun: str) -> str:
    """A count with its noun agreeing, so nothing reads "1 orders"."""

    try:
        number = int(value)
    except (TypeError, ValueError):
        return f"{value} {noun}s"
    return f"{number} {noun}{'s' if number != 1 else ''}"


def _format_period_metrics(data: dict[str, Any]) -> str | None:
    current = data.get("current") or {}
    previous = data.get("previous") or {}
    if not current:
        return None
    rows = [
        labelled("Revenue", f"{bold(_money(current.get('gross_revenue')))} against {_money(previous.get('gross_revenue'))} before"),
        labelled("Orders", f"{bold(current.get('orders'))} against {previous.get('orders')} before"),
        labelled("Average order", f"{bold(_money(current.get('average_order_value')))} against {_money(previous.get('average_order_value'))} before"),
        labelled("Customers", f"{bold(current.get('customers'))} against {previous.get('customers')} before"),
    ]
    return blocks(f"Totals for {_period_of(data)}:", bullets(rows))


def _format_metric_deltas(data: dict[str, Any]) -> str | None:
    headline = data.get("headline") or []
    if not headline:
        return None
    wanted = {"gross_revenue", "orders", "average_order_value", "customers"}
    rows = []
    for row in headline:
        if row.get("metric") not in wanted:
            continue
        name = row["metric"].replace("_", " ").capitalize()
        change = row.get("percent_change")
        movement = (
            f"{bold(row.get('current'))}, {row.get('direction')} {abs(change)}% from {row.get('previous')}"
            if change is not None
            else f"{bold(row.get('current'))}, no prior period to compare"
        )
        rows.append(labelled(name, movement))
    return blocks(f"How {_period_of(data)} compares:", bullets(rows))


def _format_breakdown(data: dict[str, Any]) -> str | None:
    breakdown = data.get("breakdown") or {}
    contributions = breakdown.get("contributions") or []
    if not contributions:
        return None
    dimension = (breakdown.get("dimension") or "").replace("_", " ")
    rows = [
        labelled(
            row.get("label", "—"),
            f"{bold(_money(row.get('current')))} against {_money(row.get('previous'))} before, "
            f"a change of {_money(row.get('absolute_change'))}",
        )
        for row in contributions[:5]
    ]
    note = breakdown.get("note") or ""
    return blocks(f"{_period_of(data)} broken down by {dimension}:", bullets(rows), note)


def _format_daily_series(data: dict[str, Any]) -> str | None:
    days = data.get("days_with_orders") or []
    period = _period_of(data)
    if not days:
        return f"No orders were recorded on any day in {period}."
    rows = [
        labelled(
            str(row.get("day")),
            f"{bold(_count(row.get('orders'), 'order'))}, {_money(row.get('revenue'))}",
        )
        for row in days[:10]
    ]
    total_days = data.get("days_in_window")
    lead = (
        f"You traded on {bold(len(days))} of {total_days} days in {period}:"
        if total_days
        else f"Daily trade in {period}:"
    )
    return blocks(lead, bullets(rows))


def _format_location_performance(data: dict[str, Any]) -> str | None:
    branches = data.get("branches") or []
    if not branches:
        return None
    rows = []
    for row in branches:
        current, previous = row.get("current") or {}, row.get("previous") or {}
        if row.get("stopped_trading"):
            detail = (
                f"{bold('no orders')} this period, against "
                f"{_count(previous.get('orders'), 'order')} worth "
                f"{_money(previous.get('revenue'))} before"
            )
        else:
            detail = (
                f"{bold(_count(current.get('orders'), 'order'))} worth "
                f"{bold(_money(current.get('revenue')))}, against "
                f"{_money(previous.get('revenue'))} before"
            )
        rows.append(labelled(row.get("branch_name", "—"), detail))
    return blocks(f"Each branch in {_period_of(data)}:", bullets(rows))


def _format_branch_metrics(data: dict[str, Any]) -> str | None:
    name = data.get("branch_name")
    current, previous = data.get("current") or {}, data.get("previous") or {}
    if not name or not current:
        return None
    state = "" if data.get("is_open") else " It is currently marked closed."
    coverage = data.get("coverage") or {}
    return blocks(
        f"{bold(name)} in {_period_of(data)}:",
        bullets(
            [
                labelled("Revenue", f"{bold(_money(current.get('gross_revenue')))} against {_money(previous.get('gross_revenue'))} before"),
                labelled("Orders", f"{bold(current.get('orders'))} against {previous.get('orders')} before"),
                labelled("Trading days", str(coverage.get("trading_days"))),
            ]
        ),
        state.strip(),
    )


def _format_compare_locations(data: dict[str, Any]) -> str | None:
    branches = data.get("branches") or []
    if len(branches) < 2:
        return None
    rows = []
    for row in branches:
        current = row.get("current") or {}
        closed = "" if row.get("is_open") else " (currently closed)"
        rows.append(
            labelled(
                f"{row.get('branch_name')}{closed}",
                f"{bold(_count(current.get('orders'), 'order'))} worth "
                f"{bold(_money(current.get('gross_revenue')))}, across "
                f"{_count(row.get('trading_days'), 'trading day')}",
            )
        )
    return blocks(f"Side by side in {_period_of(data)}:", bullets(rows))


def _format_cancellations(data: dict[str, Any]) -> str | None:
    current = data.get("current") or {}
    total = current.get("cancelled_orders") or 0
    period = _period_of(data)
    if not total:
        return f"No orders were cancelled in {period}."
    rows = [
        labelled(
            row["reason"].replace("_", " ").capitalize(),
            f"{row['orders']} order{'s' if row['orders'] != 1 else ''} worth {row['value']}",
        )
        for row in data.get("by_reason") or []
    ]
    lead = (
        f"{bold(_count(total, 'order'))} worth "
        f"{bold(_money(current.get('cancelled_value')))} were cancelled in {period}."
    )
    return blocks(lead, bullets(rows))


def _format_order_operations(data: dict[str, Any]) -> str | None:
    acceptance = data.get("acceptance_latency") or {}
    preparation = data.get("preparation_time") or {}
    rows = []
    if acceptance.get("median_minutes") is not None:
        rows.append(
            labelled(
                "Time to accept",
                f"a median of {bold(str(acceptance['median_minutes']) + ' minutes')} "
                f"across {acceptance.get('sample_size')} orders",
            )
        )
    if preparation.get("median_minutes") is not None:
        rows.append(
            labelled(
                "Time to prepare",
                f"a median of {bold(str(preparation['median_minutes']) + ' minutes')} "
                f"across {preparation.get('sample_size')} orders",
            )
        )
    if not rows:
        return f"No order timings were recorded for {_period_of(data)}."
    return blocks(f"Order timings for {_period_of(data)}:", bullets(rows))


def _format_offer_performance(data: dict[str, Any]) -> str | None:
    offers = data.get("offers") or []
    period = _period_of(data)
    if not offers:
        return f"No orders in {period} were placed with an offer."
    rows = [
        labelled(
            row.get("offer_name", "An offer"),
            f"{bold(_count(row.get('orders'), 'order'))} worth "
            f"{bold(_money(row.get('gross_revenue')))}, at a discount cost of "
            f"{_money(row.get('discount_cost'))}",
        )
        for row in offers[:5]
    ]
    return blocks(f"Offers used in {period}:", bullets(rows), data.get("caveat") or "")


def _format_customer_cohorts(data: dict[str, Any]) -> str | None:
    current = data.get("current") or []
    if not current:
        return None
    rows = [
        labelled(
            row.get("cohort", "").capitalize() + " customers",
            f"{bold(_count(row.get('customers'), 'customer'))}, "
            f"{_count(row.get('orders'), 'order')}, {bold(_money(row.get('revenue')))}",
        )
        for row in current
    ]
    return blocks(f"Customer groups in {_period_of(data)}:", bullets(rows))


def _format_recent_briefing(data: dict[str, Any]) -> str | None:
    briefing = data.get("briefing")
    if not briefing:
        return "No briefing has been generated for this restaurant yet."
    return blocks(
        bold(briefing.get("headline", "")),
        briefing.get("narrative", ""),
        f"Covering {briefing.get('period_start')} to {briefing.get('period_end')}.",
    )


def _format_insight_history(data: dict[str, Any]) -> str | None:
    insights = data.get("insights") or []
    if not insights:
        return "No findings have been raised for this restaurant yet."
    rows = [
        labelled(row.get("title", "A finding"), row.get("body", ""))
        for row in insights[:5]
    ]
    return blocks("Findings raised recently:", bullets(rows))


def _format_open_recommendations(data: dict[str, Any]) -> str | None:
    recommendations = data.get("recommendations") or []
    if not recommendations:
        return (
            "There are no open recommendations right now. They come from the "
            "nightly analysis, so new ones appear when something moves enough "
            "to act on."
        )
    rows = []
    for row in recommendations[:5]:
        impact = row.get("expected_impact_amount")
        detail = row.get("rationale", "")
        if impact is not None:
            detail = f"{detail} Estimated recovery {bold(_money(impact))}."
        rows.append(action(row.get("title", "An action"), detail))
    return blocks(
        "Recommendations waiting on you:",
        numbered(rows),
        "Nothing runs until you approve it.",
    )


def _format_fulfillment_mix(data: dict[str, Any]) -> str | None:
    splits = data.get("splits") or []
    period = _period_of(data)
    if not splits:
        return f"No counted orders in {period}, so there is no split to report."
    rows = [
        labelled(
            f"{row['fulfillment_type'].title()}, {row['schedule_type'].lower()}",
            f"{bold(_count(row['orders'], 'order'))} worth {bold(_money(row['revenue']))}"
            + (f" — {row['share_percent']}% of orders" if row.get("share_percent") is not None else ""),
        )
        for row in splits
    ]
    return blocks(f"How orders were fulfilled in {period}:", bullets(rows))


def _format_payment_mix(data: dict[str, Any]) -> str | None:
    methods = data.get("methods") or []
    period = _period_of(data)
    if not methods:
        return f"No counted orders in {period}, so there is nothing to split by payment method."
    rows = [
        labelled(
            row["payment_method"].replace("_", " ").title(),
            f"{bold(_count(row['orders'], 'order'))} worth {bold(_money(row['revenue']))}"
            + (f" — {row['share_percent']}% of orders" if row.get("share_percent") is not None else ""),
        )
        for row in methods
    ]
    return blocks(f"How customers paid in {period}:", bullets(rows))


def _format_order_economics(data: dict[str, Any]) -> str | None:
    period = _period_of(data)
    if not data.get("orders"):
        return f"No counted orders in {period}, so there are no fees or discounts to report."
    rows = [
        labelled("Subtotal", bold(_money(data.get("subtotal")))),
        labelled("Delivery fees", bold(_money(data.get("delivery_fee")))),
        labelled("Tax", bold(_money(data.get("tax_amount")))),
        labelled("Discounts given", bold(_money(data.get("discount_amount")))),
        labelled("Customers paid", bold(_money(data.get("total_amount")))),
    ]
    return blocks(
        f"What made up your order totals in {period}:",
        bullets(rows),
        data.get("note") or "",
    )


def _format_payment_health(data: dict[str, Any]) -> str | None:
    rows = data.get("transactions") or []
    period = _period_of(data)
    if not rows:
        return (
            f"No card or wallet payments were processed in {period}. Cash on "
            "delivery orders do not create a payment transaction."
        )
    listed = []
    for row in rows:
        detail = f"{bold(_count(row['count'], 'transaction'))} worth {_money(row['amount'])}"
        if row.get("failure_code"):
            detail += f", failure code {row['failure_code']}"
        listed.append(labelled(f"{row['provider'].title()} — {row['status'].title()}", detail))
    return blocks(f"Payment outcomes in {period}:", bullets(listed))


def _format_offer_catalogue(data: dict[str, Any]) -> str | None:
    offers = data.get("offers") or []
    if not offers:
        return "There are no offers set up for this restaurant."

    live_now = data.get("live_now")
    stale = data.get("active_but_expired") or 0
    rows = []
    # Live ones first: an owner asking what is running wants those, and burying
    # them under a list sorted by nothing is how a real answer reads as noise.
    ordered = sorted(offers, key=lambda offer: not offer.get("is_live"))
    for offer in ordered[:8]:
        state = "live" if offer.get("is_live") else "not live"
        parts = [f"{offer['discount_value']} {offer['discount_type'].lower()} off"]
        if offer.get("expires_at"):
            parts.append(f"expires {str(offer['expires_at'])[:10]}")
        else:
            parts.append("no expiry recorded")
        if offer.get("conversions") is not None:
            parts.append(
                f"{offer['views']} views, {offer['clicks']} clicks, "
                f"{offer['conversions']} conversions"
            )
        rows.append(labelled(f"{offer['name']} ({state})", ", ".join(parts)))

    lead = (
        f"{bold(live_now)} of {data.get('total')} offers are live right now."
        if live_now
        else f"None of the {bold(data.get('total'))} offers on this restaurant are live right now."
    )
    caveat = (
        f"{stale} are still marked active but their expiry date has passed, so "
        "customers cannot use them."
        if stale
        else ""
    )
    return blocks(lead, bullets(rows), caveat)


def _format_combos(data: dict[str, Any]) -> str | None:
    combos = data.get("combos") or []
    if not combos:
        return (
            "No item pairings have been found yet. They come from baskets that "
            "repeatedly contain the same items together."
        )
    rows = [
        labelled(
            row["combo_name"],
            f"seen in {bold(_count(row['orders_seen'], 'order'))} from "
            f"{_count(row['customers_seen'], 'customer')}, suggested at "
            f"{bold(_money(row['suggested_combo_price']))} against "
            f"{_money(row['original_total_price'])} separately",
        )
        for row in combos[:5]
    ]
    return blocks("Item pairings found in real baskets:", bullets(rows))


def _format_schedule(data: dict[str, Any]) -> str | None:
    branches = data.get("branches") or []
    if not branches:
        return "No branches are set up for this restaurant."

    sections = []
    for branch in branches:
        opening, closing = branch.get("opening_time"), branch.get("closing_time")
        hours = (
            f"{str(opening)[:5]}–{str(closing)[:5]}" if opening and closing else "no hours set"
        )
        detail = [labelled("Hours", hours)]
        if branch.get("future_order_enabled"):
            detail.append(
                labelled(
                    "Advance orders",
                    f"up to {_count(branch.get('max_future_days'), 'day')} ahead, "
                    f"{branch.get('slot_interval_minutes')}-minute slots",
                )
            )
        slots = branch.get("slots") or []
        if slots:
            active = [row for row in slots if row.get("is_active")]
            detail.append(
                labelled("Fulfilment slots", _count(len(active), "active slot"))
            )
        sections.append(blocks(bold(branch["branch_name"]), bullets(detail)))
    return blocks("Opening times and slots:", *sections)


def _format_notification_campaigns(data: dict[str, Any]) -> str | None:
    campaigns = data.get("campaigns") or []
    if not campaigns:
        return "No push campaigns have been sent for this restaurant."
    rows = [
        labelled(
            f"{row['title']} ({row['status'].lower()})",
            f"{bold(_count(row['sent'], 'sent'))}, {row['delivered']} delivered, "
            f"{row['opened']} opened, {row['failed']} failed",
        )
        for row in campaigns[:5]
    ]
    return blocks("Push campaigns:", bullets(rows))


TOOL_FORMATTERS: dict[str, Callable[[dict[str, Any]], str | None]] = {
    "get_stockouts": _format_stockouts,
    "get_payment_failures": _format_payment_failures,
    "get_branch_status": _format_branch_status,
    "get_menu_health": _format_menu_health,
    "get_data_coverage": _format_data_coverage,
    "get_anomalies": _format_anomalies,
    "get_period_metrics": _format_period_metrics,
    "get_metric_deltas": _format_metric_deltas,
    "get_breakdown": _format_breakdown,
    "get_daily_series": _format_daily_series,
    "get_location_performance": _format_location_performance,
    "get_branch_metrics": _format_branch_metrics,
    "compare_locations": _format_compare_locations,
    "get_cancellations": _format_cancellations,
    "get_order_operations": _format_order_operations,
    "get_offer_performance": _format_offer_performance,
    "get_customer_cohorts": _format_customer_cohorts,
    "get_recent_briefing": _format_recent_briefing,
    "get_insight_history": _format_insight_history,
    "get_open_recommendations": _format_open_recommendations,
    "get_fulfillment_mix": _format_fulfillment_mix,
    "get_payment_mix": _format_payment_mix,
    "get_order_economics": _format_order_economics,
    "get_payment_health": _format_payment_health,
    "get_offer_catalogue": _format_offer_catalogue,
    "get_combos": _format_combos,
    "get_schedule": _format_schedule,
    "get_notification_campaigns": _format_notification_campaigns,
}


__all__ = [
    "CHAT_TOOLS",
    "PLAN_CACHE_PREFIX",
    "PLAN_CACHE_VERSION",
    "FORBIDDEN_ARG_NAMES",
    "Generate",
    "TOOL_FORMATTERS",
    "ToolPlan",
    "build_planner_prompt",
    "clean_arguments",
    "tools_enabled_for",
    "plan_cache_key",
    "plan_question",
]

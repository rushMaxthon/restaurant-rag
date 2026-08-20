"""Turns a fact pack into a short owner-facing narrative.

The model's only job is wording. Every figure it may use is handed to it, and
anything numeric it writes is checked back against that pack afterwards. A
timeout, a malformed reply, or one invented number all lead to the same place:
the deterministic template, which is assembled from the same facts and is always
correct.

Follows the contract already used by `ai_offer_generation` — `format: "json"`,
pydantic validation, hard fallback — with two additions: `think: False` (this
model discards its reasoning tokens, so paying for them is waste on a CPU host)
and the numeric guardrail.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.config import get_settings
from app.models.enums import InsightNarrationSource
from app.services.insights.facts import FactPack, allowed_numbers, unsupported_numbers
from app.services.insights.rules import (
    CandidateInsight,
    is_material_change,
    money,
    percent,
    percent_is_misleading,
)

settings = get_settings()
logger = logging.getLogger(__name__)

# Endpoint and auth come from the shared client module, so the bearer token for
# Ollama Cloud is attached in one place rather than repeated per call site.
from app.services.ollama_client import (
    think_option,
    GENERATE_ENDPOINT,
    HTTP_LIMITS,
    build_client,
    local_only_options,
)

GENERATE_TIMEOUT = httpx.Timeout(
    connect=5.0,
    read=settings.ai_manager_narration_timeout_seconds,
    write=10.0,
    pool=5.0,
)
GENERATE_CLIENT = build_client(GENERATE_TIMEOUT, limits=HTTP_LIMITS)

MAX_HEADLINE_CHARS = 120
MAX_NARRATIVE_CHARS = 900


class LLMNarrationPayload(BaseModel):
    headline: str = Field(min_length=1)
    narrative: str = Field(min_length=1)


@dataclass(slots=True)
class Narration:
    headline: str
    narrative: str
    source: InsightNarrationSource
    fallback_reason: str | None = None


def build_prompt(pack: FactPack) -> str:
    payload = json.dumps(pack.to_payload(), indent=2, default=str)
    return f"""You are writing a short business briefing for a restaurant owner.

Return STRICT JSON only with this exact shape:
{{
  "headline": "string",
  "narrative": "string"
}}

Hard rules:
- use ONLY the numbers that appear in the data below
- never estimate, extrapolate, or invent a figure
- if you are unsure of a number, describe it in words instead of writing a digit
- do not include markdown, bullet points, or headings
- keep the headline under {MAX_HEADLINE_CHARS} characters
- keep the narrative to 2-4 plain sentences
- lead with what changed most, then what caused it
- be direct and factual, and do not give advice or recommendations

Data:
{payload}

Write the briefing now.
"""


def _revenue_headline(pack: FactPack) -> tuple[str, str]:
    """The headline and opening sentence for a briefing.

    Two rules learned from a real run:

    * Revenue alone is not a summary of the business. A period where revenue
      rose while orders fell is a *worse* period than the revenue suggests, and
      an owner told only "revenue is up" will conclude the opposite. Whenever
      the two disagree, both are stated.
    * The headline uses the same materiality gate as the insight rules. Without
      that, a movement the rules had judged too small to mention could still
      become the headline of the briefing.
    """

    revenue = pack.headline.get("gross_revenue") or {}
    orders = pack.headline.get("orders") or {}
    aov = pack.headline.get("average_order_value") or {}

    current = float(revenue.get("current") or 0.0)
    previous = float(revenue.get("previous") or 0.0)
    change = float(revenue.get("change") or 0.0)
    percent_change = revenue.get("percent_change")
    direction = revenue.get("direction", "flat")

    if not revenue:
        return (
            f"No trading recorded in {pack.period_label}",
            f"No counted orders were recorded in {pack.period_label}.",
        )

    orders_current = int(orders.get("current") or 0)
    orders_direction = orders.get("direction", "flat")
    orders_percent = orders.get("percent_change")
    orders_change = float(orders.get("change") or 0.0)
    revenue_material = is_material_change(change, percent_change)

    # Orders falling is material in its own right. Judging that only by the
    # money would hide a halving of order count behind a flat revenue line —
    # which is how the first real run produced a reassuring headline for a
    # period that had lost half its customers.
    orders_material = (
        orders_direction == "down"
        and orders_percent is not None
        and abs(orders_percent) >= settings.insight_revenue_change_percent
        and abs(orders_change) >= settings.insights_min_orders_for_contribution
    )

    # Revenue and orders disagreeing is the case a revenue-only headline gets
    # badly wrong, so it is called out before anything else.
    if direction == "up" and orders_material:
        lead = (
            f"Revenue is up {percent(percent_change)} but orders are down "
            f"{percent(orders_percent)}"
            if revenue_material
            else f"Orders are down {percent(orders_percent)}"
        )
        revenue_clause = (
            f"Revenue was {money(current)}, up {money(change)} from {money(previous)}"
            if revenue_material
            else f"Revenue held at {money(current)} against {money(previous)}"
        )
        opening = (
            f"{revenue_clause} in {pack.period_label}, but orders fell "
            f"{percent(orders_percent)} to {orders_current}. The average order "
            f"rose to {money(float(aov.get('current') or 0.0))}, so similar money "
            "came from fewer customers."
        )
        return lead, opening

    if orders_material and not revenue_material:
        return (
            f"Orders are down {percent(orders_percent)}",
            f"Orders fell {percent(orders_percent)} to {orders_current} in "
            f"{pack.period_label}, while revenue was {money(current)} against "
            f"{money(previous)}.",
        )

    if not revenue_material:
        # Deliberately makes no percentage claim: the movement did not clear the
        # bar the rules use, so presenting it as a headline would contradict them.
        return (
            f"No major change in {pack.period_label}",
            f"Revenue was {money(current)} in {pack.period_label}, against "
            f"{money(previous)} in the period before. Nothing moved enough to flag.",
        )

    movement = "down" if direction == "down" else "up"
    # A percentage off a near-empty period describes the quiet week, not this
    # one: "Revenue is up 2859.6%" was the largest text on the screen and told
    # an owner nothing they could act on. The money says it properly.
    headline = (
        f"Revenue is {movement} {money(change)}"
        if percent_is_misleading(previous, percent_change)
        else f"Revenue is {movement} {percent(percent_change)}"
    )
    opening = (
        f"Revenue was {money(current)} in {pack.period_label}, {movement} "
        f"{money(change)} from {money(previous)} in the period before."
    )
    return headline, opening


def _template_narration(
    pack: FactPack,
    candidates: list[CandidateInsight],
    *,
    reason: str | None = None,
) -> Narration:
    """The deterministic briefing, used when narration is off or unusable."""

    headline, opening = _revenue_headline(pack)

    sentences = [opening]
    for candidate in candidates[:3]:
        sentences.append(candidate.body)
    if not candidates:
        sentences.append("Nothing else moved enough this period to flag.")

    return Narration(
        headline=headline[:MAX_HEADLINE_CHARS],
        narrative=" ".join(sentences)[:MAX_NARRATIVE_CHARS],
        source=InsightNarrationSource.TEMPLATE,
        fallback_reason=reason,
    )


def _extract_json_payload(raw_reply: str) -> dict[str, Any]:
    raw_reply = raw_reply.strip()
    if not raw_reply:
        raise ValueError("Empty narration response")
    try:
        payload = json.loads(raw_reply)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    start = raw_reply.find("{")
    end = raw_reply.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No JSON object found in narration response")
    payload = json.loads(raw_reply[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Narration response JSON was not an object")
    return payload


def _call_model(prompt: str) -> str:
    payload = {
        "model": settings.ai_manager_narration_model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        # qwen3 discards its reasoning tokens here, so generating them is pure
        # cost on a CPU-only host.
        **think_option(),
        **local_only_options(),
        "options": {
            "temperature": 0.2,
            "num_predict": settings.ai_manager_narration_max_tokens,
        },
    }
    response = GENERATE_CLIENT.post(GENERATE_ENDPOINT, json=payload)
    response.raise_for_status()
    return str(response.json().get("response") or "")


def narrate(
    pack: FactPack,
    candidates: list[CandidateInsight],
    *,
    period_dates: tuple = (),
    enabled: bool | None = None,
) -> Narration:
    """Produce a briefing narrative, falling back to the template on any doubt."""

    use_llm = settings.enable_ai_manager_narration if enabled is None else enabled
    if not use_llm:
        return _template_narration(pack, candidates)

    try:
        raw_reply = _call_model(build_prompt(pack))
        parsed = LLMNarrationPayload.model_validate(_extract_json_payload(raw_reply))
    except (httpx.TimeoutException, httpx.HTTPError, ValidationError, ValueError) as error:
        logger.warning("Insight narration failed, using template: %s", error)
        return _template_narration(pack, candidates, reason=str(error))

    headline = parsed.headline.strip()
    narrative = parsed.narrative.strip()

    if len(headline) > MAX_HEADLINE_CHARS or len(narrative) > MAX_NARRATIVE_CHARS:
        return _template_narration(
            pack, candidates, reason="Narration exceeded the allowed length"
        )

    allowed = allowed_numbers(pack, period_dates=period_dates)
    offenders = unsupported_numbers(f"{headline} {narrative}", allowed)
    if offenders:
        # The model produced a figure the data does not support. Nothing about
        # the rest of the text can be trusted either, so the whole generation is
        # discarded rather than patched.
        logger.warning(
            "Insight narration invented numbers=%s, using template", offenders
        )
        return _template_narration(
            pack,
            candidates,
            reason=f"Narration contained unsupported numbers: {offenders}",
        )

    return Narration(
        headline=headline,
        narrative=narrative,
        source=InsightNarrationSource.LLM,
    )


__all__ = [
    "LLMNarrationPayload",
    "MAX_HEADLINE_CHARS",
    "MAX_NARRATIVE_CHARS",
    "Narration",
    "build_prompt",
    "narrate",
]

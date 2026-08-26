"""Owner Q&A: one turn from question to answer.

The pipeline is question -> routed skill/tool -> database -> structured facts ->
business calculations and validation -> Qwen writes the reply -> guardrail ->
persist.

The division of labour is the whole design. The backend owns *truth*: which
restaurant may be read, which tool runs, what the figures are, and whether the
data supports an answer at all. Qwen owns *wording*: it is handed the owner's
question and the facts that were already validated, and it writes the reply.

It follows that Qwen is given no way to affect truth. It never sees the
database, never writes SQL, never chooses a scope, and never runs a calculation
whose result is quoted — every figure it may use is handed to it, and anything
numeric it writes is checked back against exactly what it was given. One
unsupported figure discards the whole generation and the deterministic answer is
sent instead, because a reply that invented one number cannot be trusted about
the others either.

Facts reach the model only once they are validated. A refusal, a failed tool, or
an empty period never gets dressed up in natural language: there is nothing
truthful to say, so the safe answer is sent as-is.

Scope never comes from the message text. It is resolved from the authenticated
user before the question is even read, so no phrasing — however insistent — can
reach another restaurant's data.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Iterator

import httpx
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.cache import cache_get_json, cache_set_json
from app.models.enums import ChatMessageRole, InsightNarrationSource
from app.models.owner_chat import OwnerChatMessage
from app.services.insights.branch_scope import narrow_scope, resolve_branch_mentions
from app.services.insights.facts import (
    allowed_from_payload,
    allowed_numbers,
    extract_numbers,
    unsupported_numbers,
)
from app.services.ollama_client import (
    think_option,
    GENERATE_ENDPOINT,
    HTTP_LIMITS,
    build_client,
    local_only_options,
)
from app.services.insights.memory import latest_memory, resolve_with_memory
from app.services.insights.router import (
    STRUCTURALLY_ROUTED_SKILLS,
    RoutedQuestion,
    detect_direction,
    detect_limit,
    detect_metric,
    detect_rank_basis,
    parse_period,
    route_question,
    route_with_rules,
)
from app.services.insights.skills import SKILL_NAMES
from app.services.insights.tool_chat import plan_question, tools_enabled_for
from app.services.insights.scope import InsightsScope
from app.services.insights.skills import SkillResult, run_skill

settings = get_settings()
logger = logging.getLogger(__name__)

MAX_ANSWER_CHARS = 900

ANSWER_SOURCE_TEMPLATE = "TEMPLATE"
ANSWER_SOURCE_LLM = "LLM"

# The same Ollama endpoint the briefing narrator uses — one service, one model
# host — but its own client, because writing a whole answer needs a longer read
# timeout than a two-sentence briefing and sharing one would force the briefing
# to wait just as long before giving up.
ANSWER_CLIENT = build_client(
    httpx.Timeout(
        connect=5.0,
        read=settings.ai_manager_chat_answer_timeout_seconds,
        write=10.0,
        pool=5.0,
    ),
    limits=HTTP_LIMITS,
)


class LLMAnswerPayload(BaseModel):
    answer: str = Field(min_length=1)


@dataclass(slots=True)
class ChatTurn:
    session_id: uuid.UUID
    question: str
    answer: str
    skill: str
    answer_source: str
    routed_by: str
    fallback_reason: str | None = None
    facts: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    # Actionable cards the client renders beside the answer. Carried on the turn
    # and stored inside `facts`, so a restored conversation keeps its cards.
    suggestions: list[dict[str, Any]] = field(default_factory=list)
    # The parameters this turn resolved, so the next one can inherit them.
    skill_params: dict[str, Any] | None = None


# Keys that name the machinery rather than the business. An owner asked about
# delivery does not want to read "get_fulfillment_mix", and naming the tool
# invites the model to describe how the answer was obtained instead of what it
# says.
INTERNAL_DATA_KEYS = frozenset(
    {
        "tool",
        "args",
        "tool_args",
        "window_days",
        # The raw diagnostics snapshot the frontend renders. The fact pack is
        # its summary, so sending both meant a 10KB prompt carrying internal
        # identifiers — including restaurant_id, which the model has no reason
        # to see and no way to act on.
        "snapshot",
        "scope",
    }
)

# How much of a fact pack is worth sending. A full revenue diagnosis carries
# every contribution row for every dimension — a 12KB payload that took the
# model past its timeout on a CPU host, so the owner waited a minute and got the
# template anyway. These are the rows already ranked most significant, and the
# verified summary names the top movers regardless, so the tail costs seconds
# per answer and adds nothing an owner would read.
MAX_FINDINGS = 6
MAX_LIST_ITEMS = 5

# A percentage change measured against a near-zero base is arithmetically
# correct and useless: a quiet week followed by a normal one reads as "up
# 2859.6%", which tells an owner nothing they can act on and buries the fact
# that actually matters — the money. Above this, the percentage is withheld and
# the absolute change speaks instead. It is a presentation decision, made in the
# backend rather than left to the model's judgement.
MISLEADING_PERCENT_CHANGE = 300.0

# Matches the "(2859.6%)" the deterministic formatter writes, so a percentage
# withheld from the facts is not handed back through the reference answer.
PERCENT_PARENTHETICAL = re.compile(r"\s*\(\d[\d,]*(?:\.\d+)?%\)")

# "10.0% off" reads like a machine wrote it, and the model copies the reference
# verbatim. Trailing ".0" is dropped from the copy it is shown; the owner-facing
# fallback keeps whatever the formatter wrote.
TRAILING_ZERO_PERCENT = re.compile(r"\b(\d[\d,]*)\.0%")


def _percentage_is_misleading(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    percent = entry.get("percent_change")
    if percent is None:
        return False
    try:
        previous = float(entry.get("previous") or 0.0)
        return previous == 0.0 or abs(float(percent)) >= MISLEADING_PERCENT_CHANGE
    except (TypeError, ValueError):
        return False


def _drop_misleading_percentages(headline: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Withhold percentages that would mislead. Returns the facts and whether any went."""

    cleaned: dict[str, Any] = {}
    dropped = False
    for metric, entry in headline.items():
        if _percentage_is_misleading(entry):
            cleaned[metric] = {
                key: value for key, value in entry.items() if key != "percent_change"
            }
            dropped = True
        else:
            cleaned[metric] = entry
    return cleaned, dropped


def _is_internal(key: Any) -> bool:
    """Keys that name the system rather than the business.

    Identifiers are dropped wherever they appear, not just at the top level: an
    id is never something an owner asked about, and a model that cannot see one
    cannot repeat it back into an answer.
    """

    if not isinstance(key, str):
        return False
    return key in INTERNAL_DATA_KEYS or key == "id" or key.endswith("_id")


def _trim(value: Any) -> Any:
    """Cap the long tails inside a fact payload, drop internals, tidy counts."""

    # A count arrives as 1.0 because the metrics layer works in floats, and the
    # model writes back exactly what it is shown — "up from 1.0 orders". Fixing
    # it here is reliable in a way that asking the model not to do it is not.
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        # Same reasoning for the paise: shown 1348.37 the model writes
        # "₹1,348.37", which no owner would say out loud. Below a hundred the
        # decimals can carry real meaning (0.3 minutes to accept an order), so
        # only larger figures are rounded. The guardrail already treats a
        # rounded form as the same figure, so nothing becomes unquotable.
        if abs(value) >= 100:
            return round(value)
    # Facts carry prose too ("Promote Pad Thai Veg at 10.0% off"), and the model
    # copies the figure exactly as written. Cleaning the reference answer alone
    # left this one coming straight through the data.
    if isinstance(value, str):
        return TRAILING_ZERO_PERCENT.sub(r"\1%", value)
    if isinstance(value, dict):
        return {
            key: _trim(item) for key, item in value.items() if not _is_internal(key)
        }
    if isinstance(value, list):
        return [_trim(item) for item in value[:MAX_LIST_ITEMS]]
    return value


def _dimension_of(finding: Any) -> str | None:
    """What a finding is a breakdown *of* — "daypart", "weekday", "cohort"."""

    if not isinstance(finding, dict):
        return None
    for key in finding:
        if key not in {"numbers", "part", "statement", "severity", "type"}:
            return key if isinstance(finding.get(key), str) else None
    return None


def _grouped_findings(findings: list[Any]) -> dict[str, Any]:
    """Split findings by what they break the period down by.

    A flat list mixing "daypart: Afternoon" with "weekday: Friday" invites the
    model to fuse them, and it did: "you were busiest on Friday afternoon" is a
    figure nothing measured — the ₹1,091 is every afternoon, not Friday's.
    Grouping them makes them two answers to two questions, which is what they
    are.

    A single dimension stays a plain `findings` list, so nothing changes for the
    skills that only ever produce one.
    """

    trimmed = [_trim(row) for row in findings[:MAX_FINDINGS]]
    dimensions = {_dimension_of(row) for row in trimmed}
    if len(dimensions) < 2 or None in dimensions:
        return {"findings": trimmed}

    grouped: dict[str, Any] = {}
    for row in trimmed:
        grouped.setdefault(f"by_{_dimension_of(row)}", []).append(row)
    return grouped


def _shareable_facts(result: SkillResult) -> dict[str, Any]:
    """Exactly what the model is allowed to see, and nothing else.

    This is also what the numeric guardrail is built from, so the two can never
    drift: a figure is quotable if and only if it was handed over here. Trimming
    therefore narrows what may be quoted as well as what is sent, which is the
    safe direction to err in.
    """

    payload = result.fact_pack.to_payload()
    headline, _ = _drop_misleading_percentages(payload.get("headline") or {})
    facts: dict[str, Any] = {
        "period": payload.get("period"),
        "previous_period": payload.get("previous_period"),
        "headline": _trim(headline),
        **_grouped_findings(payload.get("findings") or []),
        "caveats": payload.get("caveats") or [],
    }
    extra = {
        key: _trim(value)
        for key, value in (result.data or {}).items()
        if not _is_internal(key)
    }
    if extra:
        facts["details"] = extra
    return facts


def _reference_answer(result: SkillResult) -> str:
    """The deterministic answer as the model sees it.

    Withholding a misleading percentage from the facts achieves nothing if the
    reference answer still spells it out — the model copies what it is shown. So
    the same percentage comes out of both, or out of neither.

    The result object itself is untouched: this is the text sent to the model,
    while the fallback an owner would read stays exactly as the formatter wrote
    it.
    """

    reference = TRAILING_ZERO_PERCENT.sub(r"\1%", result.answer)
    _, dropped = _drop_misleading_percentages(result.fact_pack.to_payload().get("headline") or {})
    if dropped:
        reference = PERCENT_PARENTHETICAL.sub("", reference)
    return reference


def _coverage_clause(result: SkillResult) -> str:
    """The instruction that stops a multi-part question getting a one-part answer.

    A model handed four metrics will happily write beautifully about one of
    them. Naming the parts and demanding all of them is what makes the answer
    match the question — and demanding they be *brief* is what makes four parts
    fit in the time this host has to write them.
    """

    parts = (result.data or {}).get("parts")
    if not isinstance(parts, dict) or len(parts) < 2:
        return ""

    from app.services.insights.multipart import PARTS_BY_KEY

    labels = [PARTS_BY_KEY[key].label for key in parts if key in PARTS_BY_KEY]
    unavailable = (result.data or {}).get("unavailable") or []

    clause = (
        f"\n0. THIS QUESTION HAS {len(labels)} PARTS: {', '.join(labels)}.\n"
        "   Cover EVERY one, in that order, ONE sentence each. Answering some of\n"
        "   them well is answering the question badly — the owner asked for all\n"
        "   of them. One tight sentence per part, and no closing summary.\n"
    )
    if unavailable:
        clause += (
            f"   {', '.join(unavailable)} could not be answered from the records.\n"
            "   Say so plainly rather than leaving it out.\n"
        )
    return clause


def _build_prompt(question: str, result: SkillResult) -> str:
    payload = json.dumps(_shareable_facts(result), indent=2, default=str)
    coverage = _coverage_clause(result)
    return f"""You are a sharp restaurant business assistant talking to the owner of
this restaurant. They asked you a question. Answer it.

Return STRICT JSON only with this exact shape:
{{
  "answer": "string"
}}

HARD RULES — breaking any one of these makes the answer unusable
- Use ONLY figures that appear in the facts below. Never estimate, extrapolate,
  calculate a new number, or invent one. If a number you want is not there,
  describe the point in words instead of writing a digit.
- Never invent information that is not in the facts. If the facts do not answer
  what was asked, say plainly that you do not have that data, and say what you
  do have. A clear "I don't have that" is a good answer; a guess is not.
- If something the question asks about is absent from the facts, it was not
  found in the records. Absence is not a yes and it is not a no — say it is not
  there. Never answer a yes/no question "yes" using a figure about something
  else. (Asked whether customers are returning, with only new customers in the
  facts, the honest answer is that no returning customers were recorded.)
- The caveats list real limits on this data. If a caveat undercuts the answer —
  few trading days, too little volume — say so in the reply rather than
  presenting the figure as settled.
- These facts are for THIS restaurant only, and for the period and branch stated
  in them. Never widen that, never compare to other restaurants or to industry
  averages, and never talk about a branch that is not in the facts.
- Do not mention tools, databases, queries, tables, ids, or how the answer was
  produced. The owner is asking about their business, not about the system.
- Do not claim something caused something else. The facts show what moved
  together, not why. Say "contributed most of", "alongside", or "which may be
  related to" rather than "because of" or "driven by", unless the facts state
  the cause outright.
- Advice must come from these facts alone. Recommend what the figures actually
  point at, and say briefly why. Never suggest a tactic the data says nothing
  about.
- Do not overstate certainty. An observation over a short period is a signal,
  not proof.

The owner asked:
{question}

Verified facts:
{payload}

The system's own answer to this, for its figures only.
Trust them and never contradict them.
Do NOT copy its wording, its sentence order, or its layout — it is written to
one fixed template, which is the thing you are replacing:
{_reference_answer(result)}

NOW WRITE YOUR OWN ANSWER. How:
{coverage}
ALWAYS SAY WHICH PERIOD THE FIGURES COVER, in the owner's own words — "over the
last three months", "last week", "in June". It is in the facts as the period.
This matters most when they named none: the answer then covers the last three
months, and an owner reading a figure has to know what it is a figure of.

1. ANSWER THE QUESTION IN THE FIRST SENTENCE.
   No preamble, no restating the question, no describing how you looked.
   Asked how many orders — give the number. Asked why something moved — give
   the reason. Asked which dish is best — name it. Asked whether to do
   something — say yes or no.

2. THEN FINISH THE THOUGHT. Never stop at the headline.
   A "why" question needs the answer AND the two or three biggest things behind
   it. A comparison needs both sides. Correcting a wrong assumption in the
   question still needs the explanation of what really happened. A bare figure
   with no sentence around it is not an answer — say what it counts and over
   what period.

3. LET THE QUESTION PICK THE SHAPE. There is no house format.
   Simple fact -> a sentence or two. Yes/no -> yes or no, then the evidence.
   Comparison -> the two sides in plain words. Ranking or several findings -> a
   short list. Recommendation -> what to do, then why. Complex -> structure it.
   Never open with "Summary:", "Details:", "Analysis:" or "Conclusion:", and
   never reuse the same opening or layout twice.

4. HANDLE THE NUMBERS WELL.
   Write money as an owner writes it: rupee sign, thousands separated, no
   trailing decimals. Write counts as whole numbers — orders and customers come
   as "20" and "1", never "20.0" or "1.0". Lead with the figures that answer the
   question and leave the rest out. Two or three numbers a sentence at most. Say each one once.
   Use a percentage only where it carries business meaning — if none is
   supplied for a figure, that is deliberate, so do not go looking for one.
   Do not call a level a change. "Revenue was ₹X, up ₹Y from ₹Z" is right;
   "revenue up ₹X" when ₹X is the total reads as the increase and overstates it
   several times over.
   Keep every figure with the label the facts give it. If the facts say the
   afternoon took one amount and lunch took another, do not report lunch as
   having taken the afternoon's — the number is right and the sentence is
   false, which is the hardest kind of error for an owner to catch.
   Never fuse two separate findings into one. The busiest daypart and the
   busiest weekday are different breakdowns of the same period: "Afternoon" and
   "Friday" do not combine into "Friday afternoon", which is a figure the data
   never measured. Report them as the two facts they are.
   Call a measure exactly what the facts call it. A median is not an average.
   Time to accept an order is not time to prepare or serve it. If the facts say
   a measure was not recorded, it was not recorded — do not answer with a
   different one and let the owner think it is what they asked about.

5. NEVER WRITE "driven by", "drove", "because of", "caused by", "due to" or
   "thanks to". You are looking at figures that moved together, not at a cause.
   Write "contributed", "added", "made up most of", or "alongside" instead.
   This is not a matter of taste: claiming a cause the data cannot show is how
   an owner ends up acting on a reason that was never there.

6. SOUND LIKE SOMEONE WHO KNOWS THE BUSINESS.
   Write in English, every word of it — no Chinese characters anywhere, not
   even one word mid-sentence.
   Plain business English, not a report or a dashboard read aloud. Where the
   facts support it, say what they mean for the restaurant — which period is
   trading strongest, where the money is really coming from. That is the part
   an owner cannot get from a table of numbers.
   BE BRIEF. Two or three sentences answers almost everything — an owner
   reading this is between service, not settling in with a report. Say the
   thing, add what matters, stop. Only a genuinely multi-part question earns
   more, and then only one or two sentences per part.
   **Bold** a figure that matters, sparingly.
   Stay under {settings.ai_manager_chat_answer_max_chars} characters.

Write the answer now.
"""


def _extract_json(raw_reply: str) -> dict:
    raw_reply = raw_reply.strip()
    if not raw_reply:
        raise ValueError("Empty answer response")
    try:
        payload = json.loads(raw_reply)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    start = raw_reply.find("{")
    end = raw_reply.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No JSON object found in answer response")
    payload = json.loads(raw_reply[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Answer response JSON was not an object")
    return payload


def _token_budget(result: SkillResult) -> int:
    """How many tokens this answer is allowed, from how much it has to cover.

    Every token costs about a third of a second on this host, so a fixed budget
    sized for the worst case makes every simple question slow. A one-part answer
    needs three sentences; a four-part answer needs four times as much, and
    nothing else needs the difference.
    """

    parts = (result.data or {}).get("parts")
    extra = max(len(parts) - 1, 0) if isinstance(parts, dict) else 0
    return (
        settings.ai_manager_chat_answer_max_tokens
        + extra * settings.ai_manager_chat_answer_tokens_per_part
    )


def _call_model(prompt: str, *, max_tokens: int | None = None) -> str:
    payload = {
        "model": settings.ai_manager_chat_answer_model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        **think_option(),
        **local_only_options(),
        "options": {
            "temperature": 0.3,
            "num_predict": max_tokens or settings.ai_manager_chat_answer_max_tokens,
            # The prompt is ~2k tokens and the answer is capped well below this.
            # Pinning it stops Ollama sizing a larger context than the call can
            # possibly use, which is memory and setup time spent on nothing.
            "num_ctx": 4096,
        },
    }
    response = ANSWER_CLIENT.post(GENERATE_ENDPOINT, json=payload)
    response.raise_for_status()
    return str(response.json().get("response") or "")


def _allowed_for(result: SkillResult) -> set[float]:
    """Numbers the answer may contain.

    Built from precisely what the prompt hands over — the shared facts and the
    verified summary — so a figure is quotable if and only if the model was
    actually shown it. Widening this to data the model never saw would let an
    invented number pass by coincidence.

    The summary's own figures are folded in because it rounds for readability
    ("₹1,235" from 1234.56), and that rounded form is what a reader expects.
    """

    facts = _shareable_facts(result)
    # Built from the shared facts alone, NOT from the full pack. Starting from
    # the pack put back everything the prompt deliberately withheld — the
    # misleading percentage among it — so a figure the model was never shown
    # would still have passed as supported.
    allowed = allowed_from_payload(facts)
    # Numbers living inside strings count too: the period labels read
    # "04 Aug - 10 Aug 2026", and naming the period being compared against is
    # both natural and correct. Without this the guardrail rejected the dates it
    # had itself supplied, and a good answer was thrown away for quoting them.
    for value in extract_numbers(json.dumps(facts, default=str)):
        allowed |= {value, float(round(value))}
    # The reference text as the model saw it, not as the formatter wrote it: a
    # percentage withheld from the prompt must not be quotable either.
    for value in extract_numbers(_reference_answer(result)):
        allowed |= {value, float(round(value))}
    return allowed


MEAN_WORDS = re.compile(r"\b(average|mean|avg)\b", re.IGNORECASE)

# qwen3 is trained heavily on Chinese and occasionally reaches for a Chinese
# word mid-sentence — a live answer came back reading "the afternoon时段, which
# added ₹1,046". The figures were right and the sentence was unreadable, which
# no guardrail about numbers would ever have caught.
NON_LATIN_SCRIPT = re.compile(
    "["
    "\u3000-\u303f"
    "\u3040-\u30ff"
    "\u3400-\u4dbf"
    "\u4e00-\u9fff"
    "\uac00-\ud7af"
    "\uff00-\uffef"
    "]"
)


def _renames_the_measure(answer: str, reference: str) -> bool:
    """Whether the reply reports a median as an average.

    A narrow, deterministic check for one misstatement the prompt could not
    stop: asked how fast orders are served, the model repeatedly turned "a
    median of 0.3 minutes" into "an average of 0.3 minutes". Same figure,
    different statistic, and an owner has no way to tell it was changed.

    Only fires when the facts talk about a median and never about an average —
    so a genuine "average order value" answer is untouched.
    """

    lowered = reference.lower()
    if "median" not in lowered or MEAN_WORDS.search(reference):
        return False
    return bool(MEAN_WORDS.search(answer))


# Phrases that assert one thing CAUSED another. The facts show what moved
# together, never why, so any of these turns a correlation into a causal claim an
# owner may act on — "revenue fell because of the Tuesday closure" invites a
# decision the data cannot support.
#
# Rule 5 of the prompt already forbids these in as many words. That was enough
# for qwen3 and is NOT enough for gpt-oss, which wrote "driven by" in 2 of 4
# accepted answers during cloud validation. A rule the product actually depends
# on cannot live only in a prompt the model is free to ignore.
#
# Word-boundary anchored so "overdue tomorrow" or a dish called "Due Drop" cannot
# trip it.
CAUSAL_CLAIM = re.compile(
    r"\b(driven by|drove|because of|caused by|due to|thanks to|as a result of|"
    r"led to|resulted in|attributable to)\b",
    re.IGNORECASE,
)


def _claims_causation(answer: str) -> bool:
    """Whether the reply asserts a cause the facts cannot show."""

    return bool(CAUSAL_CLAIM.search(answer))


ANSWER_CACHE_PREFIX = "insights:chat:answer"
# Bumped whenever the prompt changes, so yesterday's wording cannot outlive the
# instructions that produced it.
ANSWER_CACHE_VERSION = "v2"


def _answer_cache_key(
    question: str, result: SkillResult, scope: InsightsScope | None
) -> str:
    """Keyed on the restaurant, the question, AND the facts behind it.

    Caching an answer is only safe while the thing it describes has not moved.
    Folding the facts into the key means new orders produce a new key, so a
    stale figure can never be served — the entry simply stops being found.

    The restaurant is in the key as well. Facts alone would usually differ
    between two restaurants, but "usually" is not a tenancy guarantee: two quiet
    restaurants asking the same question can produce byte-identical fact packs —
    a zero period looks the same everywhere — and would then have shared an
    entry. Scoping the key means that can never be the mechanism by which one
    owner reads another's answer.
    """

    tenant = "unscoped"
    if scope is not None:
        tenant = f"{scope.restaurant_id}:{scope.restaurant_location_id or 'all'}"
    facts = json.dumps(_shareable_facts(result), sort_keys=True, default=str)
    digest = hashlib.sha256(
        f"{tenant}|{' '.join(question.lower().split())}|{result.skill}|{facts}".encode()
    ).hexdigest()[:32]
    return f"{ANSWER_CACHE_PREFIX}:{ANSWER_CACHE_VERSION}:{digest}"


def answers_enabled_for(scope: InsightsScope | None) -> bool:
    """Whether Qwen writes the final reply. Same for every restaurant.

    The per-restaurant allowlist that used to sit here is gone: it meant one
    owner read answers written in plain English while everyone else got the
    template, which is a difference in the product, not a rollout stage. Kept
    separate from the tool switch because writing the answer and choosing the
    tool are still different risks and may need to move independently.
    """

    return settings.enable_ai_manager_chat_answers


def _has_facts(result: SkillResult) -> bool:
    """Whether there is anything validated to write from.

    An empty pack means the skill found nothing to say. Handing that to the
    model invites it to fill the silence, which is the one thing it must not do.
    """

    payload = result.fact_pack.to_payload()
    return bool(payload.get("headline") or payload.get("findings") or result.data)


def reword_answer(
    question: str,
    result: SkillResult,
    *,
    enabled: bool | None = None,
    scope: InsightsScope | None = None,
    use_cache: bool = True,
) -> tuple[str, str, str | None]:
    """Have Qwen write the reply. Returns (answer, source, fallback_reason).

    Falls back to the deterministic answer — which is always correct, because it
    was built from the same validated facts — on any doubt at all: the feature
    being off, nothing validated to write from, a timeout, malformed output, an
    over-length reply, or a single unsupported number.
    """

    use_llm = answers_enabled_for(scope) if enabled is None else enabled
    if not use_llm:
        return result.answer, ANSWER_SOURCE_TEMPLATE, None

    # A refusal is already exactly what it needs to be, and there is no
    # validated data behind it for a rewrite to stay faithful to. Sending it
    # would be asking the model to make something out of nothing.
    if result.unsupported:
        return result.answer, ANSWER_SOURCE_TEMPLATE, None
    if not _has_facts(result):
        return result.answer, ANSWER_SOURCE_TEMPLATE, "No validated facts to write from"

    # An answer already written for this exact question against these exact
    # facts is still correct, and re-earning it costs the owner half a minute.
    cache_key = _answer_cache_key(question, result, scope)
    if use_cache:
        cached = cache_get_json(cache_key)
        if isinstance(cached, str) and cached.strip():
            logger.info("Chat answer served from cache")
            return cached, ANSWER_SOURCE_LLM, None

    prompt = _build_prompt(question, result)
    try:
        parsed = LLMAnswerPayload.model_validate(
            _extract_json(_call_model(prompt, max_tokens=_token_budget(result)))
        )
    except (httpx.TimeoutException, httpx.HTTPError, ValidationError, ValueError) as error:
        # Logged rather than swallowed: falling back is silent to the owner, so
        # the only way anyone learns the model is failing is this line.
        logger.warning("Chat answer generation failed, using prepared answer: %s", error)
        return result.answer, ANSWER_SOURCE_TEMPLATE, str(error)

    answer = parsed.answer.strip()

    # One retry, and only for causal phrasing.
    #
    # Every other guardrail failure means the model misread the facts, and asking
    # again is unlikely to help. This one is different: the wording is wrong
    # while the figures behind it are right, and it is a known habit of some
    # models rather than a misreading — gpt-oss wrote a banned phrase in roughly
    # a third of answers during cloud validation despite the prompt forbidding it
    # twice. Naming the offending phrase back to the model fixes it far more
    # often than not, and the alternative is discarding a correct answer.
    #
    # Bounded at one extra call. The guardrail below still has the final say, so
    # a second violation falls back exactly as before.
    if _claims_causation(answer):
        offenders = sorted({match.lower() for match in CAUSAL_CLAIM.findall(answer)})
        logger.info("Chat answer used causal phrasing %s, retrying once", offenders)
        try:
            parsed = LLMAnswerPayload.model_validate(
                _extract_json(
                    _call_model(
                        f"{prompt}\n\nYour previous attempt was REJECTED for writing "
                        f"{', '.join(repr(word) for word in offenders)}. These facts show "
                        "what moved together, not what caused what. Write the answer "
                        "again without any claim of cause: use 'contributed', 'added', "
                        "'made up most of', or 'alongside' instead.\n",
                        max_tokens=_token_budget(result),
                    )
                )
            )
            answer = parsed.answer.strip()
        except (httpx.TimeoutException, httpx.HTTPError, ValidationError, ValueError) as error:
            logger.warning("Chat answer retry failed, using prepared answer: %s", error)
            return result.answer, ANSWER_SOURCE_TEMPLATE, str(error)
    if not answer:
        return result.answer, ANSWER_SOURCE_TEMPLATE, "Empty answer"
    if len(answer) > settings.ai_manager_chat_answer_max_chars:
        return result.answer, ANSWER_SOURCE_TEMPLATE, "Answer exceeded the allowed length"

    if NON_LATIN_SCRIPT.search(answer):
        logger.warning("Chat answer contained non-Latin script, using prepared answer")
        return (
            result.answer,
            ANSWER_SOURCE_TEMPLATE,
            "Answer contained non-Latin script",
        )

    if _renames_the_measure(answer, _reference_answer(result)):
        logger.warning("Chat answer renamed a median as an average, using prepared answer")
        return (
            result.answer,
            ANSWER_SOURCE_TEMPLATE,
            "Answer reported a median as an average",
        )

    if _claims_causation(answer):
        # Same policy as the numeric guardrail: discard the whole generation
        # rather than edit it. A reply that asserted a cause the data cannot show
        # has misread what it was given, and patching the phrase out would leave
        # the reasoning behind it intact.
        logger.warning("Chat answer claimed causation, using prepared answer")
        return (
            result.answer,
            ANSWER_SOURCE_TEMPLATE,
            "Answer claimed a cause the facts do not establish",
        )

    offenders = unsupported_numbers(answer, _allowed_for(result))
    if offenders:
        logger.warning("Chat answer invented numbers=%s, using prepared answer", offenders)
        return (
            result.answer,
            ANSWER_SOURCE_TEMPLATE,
            f"Answer contained unsupported numbers: {offenders}",
        )

    # Written only after every guardrail has passed, so nothing unvalidated can
    # ever be replayed from here.
    if use_cache:
        cache_set_json(
            cache_key, answer, ttl_seconds=settings.ai_manager_chat_answer_cache_ttl_seconds
        )
    return answer, ANSWER_SOURCE_LLM, None


def _persist_turn(
    db: Session,
    *,
    scope: InsightsScope,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    question: str,
    turn: ChatTurn,
) -> None:
    db.add(
        OwnerChatMessage(
            id=uuid.uuid4(),
            restaurant_id=scope.restaurant_id,
            restaurant_location_id=scope.restaurant_location_id,
            user_id=user_id,
            session_id=session_id,
            role=ChatMessageRole.USER,
            sequence=0,
            message=question,
            facts={},
        )
    )
    db.add(
        OwnerChatMessage(
            id=uuid.uuid4(),
            restaurant_id=scope.restaurant_id,
            restaurant_location_id=scope.restaurant_location_id,
            user_id=user_id,
            session_id=session_id,
            role=ChatMessageRole.ASSISTANT,
            sequence=1,
            message=turn.answer,
            skill=turn.skill,
            answer_source=turn.answer_source,
            fallback_reason=turn.fallback_reason,
            skill_params=turn.skill_params or {},
            facts=turn.facts or {},
        )
    )
    db.commit()


def resolve_route(
    question: str,
    *,
    scope: InsightsScope | None = None,
    generate: Any | None = None,
) -> RoutedQuestion:
    """Tier 1 first, then Tier 2, then whatever the old path decides.

    The order is the point. Rules answer the questions they recognise in about
    fifty milliseconds, and a planner call costs six to eight seconds, so the
    planner is only reached when the rules genuinely do not know. Tier 2 can
    return a skill as well as a tool, which is why it replaces the model skill
    router rather than running after it — two generations for one question would
    double the wait for no gain.
    """

    # Decided once, from the restaurant this question belongs to, and used for
    # both the deterministic tool patterns and the planner.
    tools_live = tools_enabled_for(scope) if scope is not None else (
        settings.enable_ai_manager_chat_tools
    )

    routed = route_with_rules(question, allow_tools=tools_live)
    if routed is not None:
        return routed

    if tools_live:
        plan = plan_question(
            question,
            skills=tuple(name for name in SKILL_NAMES if name not in STRUCTURALLY_ROUTED_SKILLS),
            generate=generate,
        )
        if plan.ok:
            params = parse_period(question)
            params.direction = detect_direction(question)
            params.rank_by = detect_rank_basis(question)
            params.limit = detect_limit(question)
            if plan.tool:
                params.tool = plan.tool
                params.tool_args = plan.args
                return RoutedQuestion(skill="tool_answer", params=params, source="llm")
            if plan.skill == "metric_lookup":
                params.metric = detect_metric(question)
            return RoutedQuestion(skill=plan.skill, params=params, source="llm")

        logger.info("Chat tool planner produced no plan: %s", plan.error)

    # The pre-existing path: model skill router, then the low-confidence
    # diagnosis. The rollout decision travels with it, or this becomes the way
    # around it.
    #
    # `allow_model=False` once the planner has already run. It was left at the
    # default, so a question the planner could not resolve then paid for a
    # SECOND generation — the planner's 45-second timeout followed by the
    # router's 20 — before falling through to the same place. That is over a
    # minute of waiting for two model calls that both gave up, and it is exactly
    # the double round-trip the tier order exists to avoid.
    return route_question(question, allow_tools=tools_live, allow_model=not tools_live)


def apply_branch_scope(
    db: Session,
    *,
    scope: InsightsScope,
    question: str,
    routed: RoutedQuestion,
) -> tuple[RoutedQuestion, InsightsScope, str, str | None]:
    """Narrow an answer to the branch the question named, if it named one.

    Three outcomes, and the difference between them is the whole point:

    * No branch named — nothing changes, and the answer covers the restaurant.
    * One branch named — the skill runs against that branch alone, and the reply
      says so. Previously the branch was dropped without a word and the owner was
      shown restaurant-wide figures in answer to a branch question.
    * A branch the current scope may not read — refused outright, rather than
      answered at a scope the owner did not ask about.

    Two or more branches route to the comparison skill, which is the only shape
    a single scope cannot express.
    """

    mention = resolve_branch_mentions(db, scope, question)

    if mention.conflict is not None:
        known = ", ".join(mention.known_branches)
        return (
            routed,
            scope,
            "",
            (
                f"This conversation is scoped to a single branch, so I cannot "
                f"answer for {mention.conflict}. Branches on this restaurant: {known}."
            ),
        )

    if not mention.matches:
        return routed, scope, "", None

    if mention.is_comparison:
        params = replace(
            routed.params,
            branches=tuple(match.branch_name for match in mention.matches),
        )
        return (
            RoutedQuestion(
                skill="branch_comparison",
                params=params,
                source=routed.source,
                confidence="high",
            ),
            scope,
            "",
            None,
        )

    match = mention.matches[0]
    params = replace(routed.params, branches=(match.branch_name,))
    routed = RoutedQuestion(
        skill=routed.skill,
        params=params,
        source=routed.source,
        confidence=routed.confidence,
    )
    return routed, narrow_scope(scope, match), f"For {match.branch_name}:", None


def _refusal_turn(
    db: Session,
    *,
    scope: InsightsScope,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    question: str,
    routed: RoutedQuestion,
    message: str,
    persist: bool,
) -> ChatTurn:
    """A turn that answers nothing on purpose, and is recorded as such."""

    turn = ChatTurn(
        session_id=session_id,
        question=question,
        answer=message,
        skill="unsupported",
        answer_source=InsightNarrationSource.TEMPLATE.value,
        routed_by=routed.source,
        fallback_reason="branch outside the current scope",
        facts={},
        data={},
        skill_params=routed.params.to_dict(),
    )
    if persist:
        _persist_turn(
            db,
            scope=scope,
            user_id=user_id,
            session_id=session_id,
            question=question,
            turn=turn,
        )
    return turn


def answer_question(
    db: Session,
    *,
    scope: InsightsScope,
    user_id: uuid.UUID,
    question: str,
    session_id: uuid.UUID | None = None,
    persist: bool = True,
    routed: RoutedQuestion | None = None,
) -> ChatTurn:
    """Answer one owner question end to end."""

    resolved_session = session_id or uuid.uuid4()
    trimmed = question.strip()[: settings.ai_manager_chat_max_question_chars]

    if routed is not None:
        resolved_route = routed
    elif session_id is not None:
        # Only a continuing session has anything to inherit. Memory carries the
        # analysis and window; the restaurant comes from `scope`, which was
        # resolved from the authenticated user before this question was read.
        history = get_chat_history(db, scope=scope, session_id=session_id)
        resolved_route = resolve_with_memory(trimmed, memory=latest_memory(history))
    else:
        resolved_route = resolve_route(trimmed, scope=scope)

    resolved_route, skill_scope, branch_prefix, refusal = apply_branch_scope(
        db, scope=scope, question=trimmed, routed=resolved_route
    )

    if refusal is not None:
        return _refusal_turn(
            db,
            scope=scope,
            user_id=user_id,
            session_id=resolved_session,
            question=trimmed,
            routed=resolved_route,
            message=refusal,
            persist=persist,
        )

    result = run_skill(
        db, scope=skill_scope, skill=resolved_route.skill, params=resolved_route.params
    )

    prepared = result.answer
    if resolved_route.confidence == "low" and not result.unsupported:
        # Say what was assumed rather than answering a possibly different
        # question as though it were the one asked.
        prepared = (
            "I was not sure exactly what you were asking, so here is how trading "
            f"has moved. {prepared} You can also ask about dishes, busy times, "
            "customers, offers, or what to do next."
        )
        result = SkillResult(
            skill=result.skill,
            answer=prepared,
            fact_pack=result.fact_pack,
            data=result.data,
            unsupported=result.unsupported,
        )

    # `scope`, not `skill_scope`: the rollout is a property of the restaurant,
    # and a branch-narrowed question belongs to the same restaurant.
    answer, source, fallback_reason = reword_answer(trimmed, result, scope=scope)
    if branch_prefix:
        # Stated, not assumed. An owner who named a branch has to be able to see
        # that the figures are that branch's and not the whole restaurant's.
        answer = f"{branch_prefix} {answer}"

    # Cards ride inside the stored facts rather than in a column of their own:
    # `facts` is already the JSONB record of what this turn was built from, and
    # the narrator never reads it (it is given `_shareable_facts`, built freshly
    # from the fact pack), so nothing the model sees changes.
    turn_facts = result.fact_pack.to_payload()
    if result.suggestions:
        turn_facts["suggestions"] = result.suggestions

    turn = ChatTurn(
        session_id=resolved_session,
        question=trimmed,
        answer=answer,
        skill=result.skill,
        answer_source=source,
        routed_by=resolved_route.source,
        fallback_reason=fallback_reason,
        facts=turn_facts,
        data=result.data,
        suggestions=result.suggestions,
        skill_params=resolved_route.params.to_dict(),
    )

    if persist:
        _persist_turn(
            db,
            scope=scope,
            user_id=user_id,
            session_id=resolved_session,
            question=trimmed,
            turn=turn,
        )

    logger.info(
        "Owner chat turn restaurant_id=%s skill=%s routed_by=%s source=%s",
        scope.restaurant_id,
        turn.skill,
        turn.routed_by,
        turn.answer_source,
    )
    return turn


def chunk_answer(answer: str) -> Iterator[str]:
    """Split a finished answer into stream-sized pieces without breaking it.

    The old split was on ". ", which re-appended a full stop to every piece. That
    was harmless for one paragraph of prose and destructive for a structured
    answer: a heading arrived as "### Here is what moved most. " and a bullet
    lost the line break that made it a bullet.

    Splitting on lines instead keeps every newline exactly where the formatter
    put it, so what the client renders is what the skill wrote. Prose lines are
    still broken at sentence boundaries, because a paragraph appearing a sentence
    at a time is the point of streaming.
    """

    for line in answer.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            yield line
            continue
        # A list item or heading is one unit: breaking it mid-line would render
        # as a broken list until the rest arrived.
        if stripped.startswith(("-", "#")) or stripped[:2].rstrip(".").isdigit():
            yield line
            continue

        remainder = line
        while remainder:
            stop = remainder.find(". ")
            if stop < 0:
                yield remainder
                break
            yield remainder[: stop + 2]
            remainder = remainder[stop + 2 :]


def _sse_frame(event: str, payload: dict[str, Any]) -> str:
    """Same frame shape as the customer assistant, so clients can share a parser."""

    return f"event: {event}\ndata: {json.dumps(payload, default=str)}\n\n"


def stream_answer(
    db: Session,
    *,
    scope: InsightsScope,
    user_id: uuid.UUID,
    question: str,
    session_id: uuid.UUID | None = None,
) -> Iterator[str]:
    """Stream one turn as SSE: meta, then the answer, then done.

    The answer is produced whole and then chunked. Token-by-token streaming
    would mean emitting text before the guardrail had seen it, and an
    unsupported figure cannot be recalled once an owner has read it.
    """

    resolved_session = session_id or uuid.uuid4()

    try:
        turn = answer_question(
            db,
            scope=scope,
            user_id=user_id,
            question=question,
            session_id=resolved_session,
        )
    except Exception as error:  # noqa: BLE001 - a stream must end cleanly
        logger.exception("Owner chat stream failed restaurant_id=%s", scope.restaurant_id)
        yield _sse_frame(
            "error",
            {"session_id": str(resolved_session), "detail": "Unable to answer right now"},
        )
        yield _sse_frame("done", {"session_id": str(resolved_session)})
        return

    yield _sse_frame(
        "meta",
        {
            "session_id": str(turn.session_id),
            "skill": turn.skill,
            "answer_source": turn.answer_source,
            "routed_by": turn.routed_by,
        },
    )

    for chunk in chunk_answer(turn.answer):
        yield _sse_frame("token", {"text": chunk})

    yield _sse_frame(
        "done",
        {
            "session_id": str(turn.session_id),
            "skill": turn.skill,
            "answer": turn.answer,
            "facts": turn.facts,
            "suggestions": turn.suggestions,
        },
    )


def get_chat_history(
    db: Session,
    *,
    scope: InsightsScope,
    session_id: uuid.UUID | None = None,
    limit: int | None = None,
) -> list[OwnerChatMessage]:
    query = select(OwnerChatMessage).where(
        OwnerChatMessage.restaurant_id == scope.restaurant_id
    )
    if session_id is not None:
        query = query.where(OwnerChatMessage.session_id == session_id)

    resolved_limit = limit or settings.ai_manager_chat_history_messages
    # `sequence` breaks the tie between the question and answer of one turn,
    # which share a timestamp because they commit together.
    rows = db.scalars(
        query.order_by(
            OwnerChatMessage.created_at.desc(), OwnerChatMessage.sequence.desc()
        ).limit(resolved_limit)
    ).all()
    return list(reversed(rows))


def clear_chat_history(
    db: Session,
    *,
    scope: InsightsScope,
    session_id: uuid.UUID | None = None,
) -> int:
    statement = delete(OwnerChatMessage).where(
        OwnerChatMessage.restaurant_id == scope.restaurant_id
    )
    if session_id is not None:
        statement = statement.where(OwnerChatMessage.session_id == session_id)

    deleted = db.execute(statement).rowcount or 0
    db.commit()
    return int(deleted)


__all__ = [
    "chunk_answer",
    "ANSWER_SOURCE_LLM",
    "ANSWER_SOURCE_TEMPLATE",
    "ChatTurn",
    "answer_question",
    "answers_enabled_for",
    "clear_chat_history",
    "get_chat_history",
    "reword_answer",
    "stream_answer",
]

"""The bounded loop: Qwen chooses what to look at, the backend decides what it saw.

The model's freedom here is real and narrow. It picks the next question from a
fixed catalogue and it writes the conclusions — that is the analysis. It never
touches the database, never sees a restaurant id, never chooses a scope, and
never has a claim accepted that the 8B validator did not check.

Three budgets bound a run, because on a CPU-only Ollama host an unbounded loop
is indistinguishable from a hang:

* **calls** — at most `analyst_max_tool_calls` questions
* **time** — the whole run, including generation, inside
  `analyst_time_budget_seconds`
* **result size** — each result truncated before it reaches the prompt

And three loop guards, because a model that has stopped making progress will
happily keep going:

* repeating a call it already made is refused and counted
* an unknown tool name or unusable JSON is fed back once, then ends exploration
* running out of any budget goes straight to the conclude step with whatever was
  gathered, rather than abandoning the run

Every ending is a recorded run. A timeout, a malformed reply, and a clean
analysis all produce an audit row; the difference is the status and the failure
reason. Failure falls back to the rules engine, which has already produced the
briefing an owner will actually see — the analyst never had to succeed for the
product to work, which is the property that makes running it safe.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from typing import Any, Callable

import httpx
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import AnalysisRunStatus
from app.models.owner_analysis_run import OwnerAnalysisRun
from app.services.insights import metrics as metrics_layer
from app.services.insights.analyst.ledger import FactLedger
from app.services.insights.analyst.output import AnalysisVerdict, AnalystCommentary
from app.services.insights.analyst.additive import (
    ValidatedCommentary,
    brief_ledger,
    build_brief,
    build_commentary_prompt,
    validate_commentary,
)
from app.services.insights.analyst.persistence import persist_outcome, record_run
from app.services.insights.analyst.prompts import (
    build_conclude_prompt,
    build_explore_prompt,
    truncate_result,
)
from app.services.insights.analyst.registry import TOOLS, call_tool
from app.services.insights.analyst.schemas import ALLOWED_WINDOW_DAYS
from app.services.insights.analyst.validation import (
    CoverageContext,
    ValidationOutcome,
    validate_verdict,
)
from app.services.insights.periods import PeriodComparison, resolve_period_comparison
from app.services.insights.generation import _attach_root_causes
from app.services.insights.rules import evaluate_rules
from app.services.insights.scope import InsightsScope
from app.services.insights.service import build_diagnostics_snapshot

settings = get_settings()
logger = logging.getLogger(__name__)

from app.services.ollama_client import (
    think_option,
    GENERATE_ENDPOINT,
    build_client,
    local_only_options,
)

# A generation function, so tests can drive the loop without an Ollama host and
# without patching module internals.
Generate = Callable[[str, float, int], str]


class AnalystError(RuntimeError):
    """A run that cannot continue. Always recorded, never raised to a caller."""


@dataclass(slots=True)
class AnalysisRunResult:
    status: AnalysisRunStatus
    run_id: Any = None
    outcome: ValidationOutcome = field(default_factory=ValidationOutcome)
    tool_calls: int = 0
    elapsed_ms: int = 0
    failure_reason: str | None = None
    insights_written: int = 0
    proposals_written: int = 0
    # Additive mode only; the exploring mode leaves these unset.
    commentary: Any = None
    brief: Any = None
    # True when the run ended without a usable analysis and the rules engine's
    # output stands alone.
    fell_back: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "run_id": str(self.run_id) if self.run_id else None,
            "tool_calls": self.tool_calls,
            "elapsed_ms": self.elapsed_ms,
            "findings_accepted": len(self.outcome.findings),
            "findings_rejected": sum(
                1 for row in self.outcome.rejections if row.kind == "finding"
            ),
            "recommendations_accepted": len(self.outcome.recommendations),
            "insufficient_data": self.outcome.insufficient_data,
            "failure_reason": self.failure_reason,
            "fell_back": self.fell_back,
            "insights_written": self.insights_written,
            "proposals_written": self.proposals_written,
        }


def _ollama_generate(prompt: str, timeout_seconds: float, max_tokens: int) -> str:
    """One generation, following the contract narration already uses."""

    payload = {
        "model": settings.analyst_model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        # qwen3 discards its reasoning tokens here, so generating them is pure
        # cost on a CPU-only host.
        **think_option(),
        **local_only_options(),
        "options": {
            "temperature": settings.analyst_temperature,
            "num_predict": max_tokens,
        },
    }
    timeout = httpx.Timeout(connect=5.0, read=timeout_seconds, write=10.0, pool=5.0)
    with build_client(timeout) as client:
        response = client.post(GENERATE_ENDPOINT, json=payload)
        response.raise_for_status()
        return str(response.json().get("response") or "")


def _repair_truncated_json(text: str) -> str:
    """Close a reply that ran out of tokens mid-structure.

    A generation cut off at the token limit is not a wrong answer, it is an
    incomplete one, and the salvageable part is usually the whole analysis bar
    the last half-written finding. This drops the incomplete tail and closes the
    open brackets.

    It cannot weaken any guarantee: what comes out still has to parse, still has
    to satisfy the output schema, and every finding in it still faces the same
    evidence, number, arithmetic, causality, coverage and safety gates. The only
    thing recovered is well-formedness.
    """

    depth = 0
    in_string = False
    escaped = False
    # The last position where the structure was complete enough to close.
    safe_end = None
    stack: list[str] = []

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char in "{[":
            stack.append("}" if char == "{" else "]")
            depth += 1
        elif char in "}]":
            if stack:
                stack.pop()
            depth -= 1
        elif char == "," and depth <= 2:
            # A comma at the top or one level in ends a complete element.
            safe_end = index

    if not stack:
        return text
    if safe_end is None:
        safe_end = len(text)

    trimmed = text[:safe_end].rstrip().rstrip(",")
    # Recompute what is still open after trimming.
    depth_stack: list[str] = []
    in_string = False
    escaped = False
    for char in trimmed:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "{[":
            depth_stack.append("}" if char == "{" else "]")
        elif char in "}]" and depth_stack:
            depth_stack.pop()

    if in_string:
        trimmed += '"'
    return trimmed + "".join(reversed(depth_stack))


def _extract_json(raw_reply: str) -> dict[str, Any]:
    raw_reply = (raw_reply or "").strip()
    if not raw_reply:
        raise ValueError("empty response")
    try:
        payload = json.loads(raw_reply)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    start = raw_reply.find("{")
    end = raw_reply.rfind("}")
    candidate = raw_reply[start : end + 1] if start >= 0 and end > start else None
    if candidate is not None:
        try:
            payload = json.loads(candidate)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass

    if start < 0:
        raise ValueError("no JSON object in response")

    repaired = _repair_truncated_json(raw_reply[start:])
    payload = json.loads(repaired)
    if not isinstance(payload, dict):
        raise ValueError("response JSON was not an object")
    logger.info("Recovered a truncated analyst reply by closing its structure")
    return payload


def _coverage_for(
    db: Session, scope: InsightsScope, comparison: PeriodComparison
) -> CoverageContext:
    """The backend's own view of whether this window supports conclusions."""

    coverage = metrics_layer.fetch_coverage(db, scope, comparison.current)
    previous = metrics_layer.fetch_coverage(db, scope, comparison.previous)
    return CoverageContext(
        orders=coverage.orders,
        trading_days=coverage.trading_days,
        days_in_window=coverage.days_in_window,
        sufficient_volume=(
            coverage.orders >= settings.insights_min_orders_for_delta
            and previous.orders >= settings.insights_min_orders_for_delta
        ),
    )


def _coverage_summary(coverage: CoverageContext) -> str:
    return (
        f"{coverage.orders} counted orders across {coverage.trading_days} trading "
        f"days of {coverage.days_in_window}"
    )


@dataclass(slots=True)
class _Budget:
    """What is left of the three limits, in one place."""

    started: float
    seconds: float
    max_calls: int
    calls_used: int = 0

    @property
    def elapsed(self) -> float:
        return monotonic() - self.started

    @property
    def calls_remaining(self) -> int:
        return max(0, self.max_calls - self.calls_used)

    def exhausted(self) -> str | None:
        if self.calls_used >= self.max_calls:
            return "call budget exhausted"
        if self.elapsed >= self.seconds:
            return "time budget exhausted"
        return None

    def time_left(self) -> float:
        return max(0.0, self.seconds - self.elapsed)


# The opening two calls are the same in every competent analysis: how much data
# is there, and what moved. Asking the model to choose them costs two
# generations — two minutes on this host — for a decision with one right answer.
# They are executed directly and handed over as already-done, which leaves the
# model's freedom where it matters: what to look at once it knows what moved.
SEEDED_CALLS: tuple[tuple[str, bool], ...] = (
    ("get_data_coverage", True),
    ("get_metric_deltas", True),
)


def _seed_calls(
    db: Session,
    *,
    scope: InsightsScope,
    ledger: FactLedger,
    comparison: PeriodComparison,
    budget: _Budget,
) -> list[dict[str, Any]]:
    """Run the fixed opening calls and return them as transcript entries."""

    window_days = comparison.current.day_count
    if window_days not in ALLOWED_WINDOW_DAYS:
        # A custom date range cannot be expressed as a tool window, so the model
        # picks its own opening instead of being handed a mismatched one.
        return []

    transcript: list[dict[str, Any]] = []
    for name, takes_window in SEEDED_CALLS:
        if budget.exhausted() is not None:
            break
        args = {"window_days": window_days} if takes_window else {}
        result = call_tool(db, scope, name, args)
        budget.calls_used += 1
        entry = ledger.record(result)
        transcript.append(
            {
                "call_id": entry.call_id,
                "tool": name,
                "args": result.args,
                "result": truncate_result(
                    result.data
                    if result.ok
                    else {"error": result.error, "detail": result.detail}
                ),
                "seeded": True,
            }
        )
    return transcript


def _explore(
    db: Session,
    *,
    scope: InsightsScope,
    ledger: FactLedger,
    coverage: CoverageContext,
    comparison: PeriodComparison,
    budget: _Budget,
    generate: Generate,
    transcript: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Ask, look, repeat — until the model stops or a budget does.

    Returns the transcript shown to the conclude step and the reason exploring
    ended. Exploration ending early is normal: a run with three good calls is
    better than one with twelve, and the conclude step works from whatever the
    transcript holds.
    """

    transcript = list(transcript or [])
    seen_calls: dict[str, int] = {
        f"{entry['tool']}:{json.dumps(entry['args'], sort_keys=True, default=str)}": 1
        for entry in transcript
    }
    malformed_replies = 0

    while True:
        stop = budget.exhausted()
        if stop is not None:
            return transcript, stop

        prompt = build_explore_prompt(
            period_label=comparison.current.label(),
            coverage_summary=_coverage_summary(coverage),
            transcript=transcript,
            calls_remaining=budget.calls_remaining,
            window_days=comparison.current.day_count,
        )

        try:
            raw = generate(
                prompt,
                min(settings.analyst_explore_timeout_seconds, budget.time_left()),
                settings.analyst_explore_max_tokens,
            )
            step = _extract_json(raw)
        except (httpx.TimeoutException, httpx.HTTPError) as error:
            # A timeout mid-exploration is not fatal: whatever was gathered is
            # still worth concluding from.
            return transcript, f"explore generation failed: {error}"
        except (ValueError, json.JSONDecodeError) as error:
            malformed_replies += 1
            if malformed_replies > 1:
                return transcript, f"explore returned unusable JSON twice: {error}"
            continue

        if step.get("done") is True:
            return transcript, "model stopped"

        name = str(step.get("tool") or "").strip()
        args = step.get("args") if isinstance(step.get("args"), dict) else {}

        if name not in TOOLS:
            # Fed back rather than fatal — an unknown name is usually a typo the
            # model corrects when it sees the catalogue again.
            malformed_replies += 1
            transcript.append(
                {
                    "call_id": "-",
                    "tool": name or "(none)",
                    "args": args,
                    "result": f'{{"error":"unknown_tool. Choose from the catalogue."}}',
                }
            )
            if malformed_replies > 1:
                return transcript, f"unknown tool requested twice: {name!r}"
            continue

        signature = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
        seen_calls[signature] = seen_calls.get(signature, 0) + 1
        if seen_calls[signature] > 1:
            # A model that has stopped making progress will repeat itself
            # indefinitely. Two identical requests is enough to know.
            if seen_calls[signature] > settings.analyst_max_repeated_calls:
                return transcript, "repeated the same call too many times"
            transcript.append(
                {
                    "call_id": "-",
                    "tool": name,
                    "args": args,
                    "result": '{"error":"already_asked. Ask something different or set done."}',
                }
            )
            continue

        result = call_tool(db, scope, name, args)
        budget.calls_used += 1
        entry = ledger.record(result)
        transcript.append(
            {
                "call_id": entry.call_id,
                "tool": name,
                "args": result.args,
                "result": truncate_result(
                    result.data if result.ok else {"error": result.error, "detail": result.detail}
                ),
            }
        )


def run_analysis(
    db: Session,
    *,
    scope: InsightsScope,
    comparison: PeriodComparison | None = None,
    generate: Generate | None = None,
    enabled: bool | None = None,
    commit: bool = True,
) -> AnalysisRunResult:
    """One shadow analysis, from first question to audit row.

    Never raises. Every path — success, timeout, malformed output, budget
    exhaustion — ends in a recorded run, because a failure that leaves no trace
    is a failure nobody can measure.
    """

    use_analyst = settings.enable_ai_manager_analyst if enabled is None else enabled
    resolved_comparison = comparison or resolve_period_comparison(
        window_days=settings.insights_default_window_days
    )
    started_at = datetime.now(UTC)
    budget = _Budget(
        started=monotonic(),
        seconds=settings.analyst_time_budget_seconds,
        max_calls=settings.analyst_max_tool_calls,
    )
    ledger = FactLedger()
    coverage = _coverage_for(db, scope, resolved_comparison)

    if not use_analyst:
        logger.info(
            "Analyst run skipped, flag disabled restaurant_id=%s", scope.restaurant_id
        )
        return AnalysisRunResult(
            status=AnalysisRunStatus.SKIPPED,
            failure_reason="analyst disabled",
            fell_back=True,
        )

    generator = generate or _ollama_generate
    outcome = ValidationOutcome(insufficient_data=not coverage.is_sufficient)
    status = AnalysisRunStatus.COMPLETED
    failure_reason: str | None = None

    seeded = _seed_calls(
        db, scope=scope, ledger=ledger, comparison=resolved_comparison, budget=budget
    )
    transcript, stop_reason = _explore(
        db,
        scope=scope,
        ledger=ledger,
        coverage=coverage,
        comparison=resolved_comparison,
        budget=budget,
        generate=generator,
        transcript=seeded,
    )

    if not ledger.entries:
        # Nothing was gathered, so there is nothing to conclude from. Concluding
        # anyway would be asking the model to write findings out of thin air.
        status = AnalysisRunStatus.FAILED
        failure_reason = f"no tool calls completed ({stop_reason})"
    else:
        try:
            raw = generator(
                build_conclude_prompt(
                    period_label=resolved_comparison.current.label(),
                    coverage_summary=_coverage_summary(coverage),
                    transcript=transcript,
                ),
                min(settings.analyst_conclude_timeout_seconds, max(budget.time_left(), 30.0)),
                settings.analyst_conclude_max_tokens,
            )
            verdict = AnalysisVerdict.model_validate(_extract_json(raw))
        except (httpx.TimeoutException, httpx.HTTPError) as error:
            status = AnalysisRunStatus.FAILED
            failure_reason = f"conclude generation failed: {error}"
        except (ValueError, ValidationError, json.JSONDecodeError) as error:
            status = AnalysisRunStatus.FAILED
            failure_reason = f"conclude returned unusable output: {error}"
        else:
            outcome = validate_verdict(verdict, ledger=ledger, coverage=coverage)
            if outcome.rejections and not outcome.findings and not outcome.recommendations:
                # Everything the model produced was thrown out. Recorded as
                # REJECTED rather than COMPLETED so the distinction survives in
                # the audit table.
                status = AnalysisRunStatus.REJECTED
                failure_reason = "every finding failed validation"

    # Both facts matter and they are different facts. A conclude failure must
    # not hide that exploration ended because the model was looping — that is
    # the more useful half of the diagnosis, and it is the half that gets
    # overwritten if one field has to carry both.
    if failure_reason and stop_reason and stop_reason not in failure_reason:
        failure_reason = f"{failure_reason} (exploration ended: {stop_reason})"

    elapsed_ms = int(budget.elapsed * 1000)
    run = record_run(
        db,
        scope=scope,
        comparison=resolved_comparison,
        ledger=ledger,
        outcome=outcome,
        coverage=coverage,
        status=status,
        started_at=started_at,
        elapsed_ms=elapsed_ms,
        model_name=settings.analyst_model,
        failure_reason=failure_reason or stop_reason,
        extra_transcript={"exploration_ended": stop_reason},
        commit=commit,
    )

    insights_written = proposals_written = 0
    if status == AnalysisRunStatus.COMPLETED:
        insights_written, proposals_written = persist_outcome(
            db,
            scope=scope,
            comparison=resolved_comparison,
            outcome=outcome,
            run=run,
            model_name=settings.analyst_model,
            commit=commit,
        )

    logger.info(
        "Analyst run finished restaurant_id=%s status=%s calls=%s elapsed_ms=%s "
        "accepted=%s rejected=%s shadow=%s",
        scope.restaurant_id,
        status.value,
        len(ledger.entries),
        elapsed_ms,
        len(outcome.findings),
        len(outcome.rejections),
        settings.ai_manager_analyst_shadow_mode,
    )

    return AnalysisRunResult(
        status=status,
        run_id=run.id,
        outcome=outcome,
        tool_calls=len(ledger.entries),
        elapsed_ms=elapsed_ms,
        failure_reason=failure_reason,
        insights_written=insights_written,
        proposals_written=proposals_written,
        fell_back=status != AnalysisRunStatus.COMPLETED,
    )


def run_additive_analysis(
    db: Session,
    *,
    scope: InsightsScope,
    comparison: PeriodComparison | None = None,
    generate: Generate | None = None,
    enabled: bool | None = None,
    commit: bool = True,
) -> AnalysisRunResult:
    """One additive pass: rules findings in, interpretation out.

    A single generation. The exploration loop existed to discover facts, and in
    this mode the facts arrive already discovered, already ranked, and already
    correct — so the only thing left to generate is the commentary.

    Falls back exactly as the exploring mode does: any failure leaves the rules
    briefing standing on its own, which is what an owner sees either way.
    """

    use_analyst = settings.enable_ai_manager_analyst if enabled is None else enabled
    resolved_comparison = comparison or resolve_period_comparison(
        window_days=settings.insights_default_window_days
    )
    started_at = datetime.now(UTC)
    started = monotonic()

    if not use_analyst:
        return AnalysisRunResult(
            status=AnalysisRunStatus.SKIPPED,
            failure_reason="analyst disabled",
            fell_back=True,
        )

    coverage = _coverage_for(db, scope, resolved_comparison)
    snapshot = build_diagnostics_snapshot(db, scope=scope, comparison=resolved_comparison)
    candidates = evaluate_rules(snapshot)
    # The deterministic explanations — "this branch is marked closed" — live in
    # the generation path rather than in the rules themselves. Without this the
    # model is asked to explain something the system already knows.
    candidates = _attach_root_causes(
        db, scope=scope, comparison=resolved_comparison, candidates=candidates
    )
    brief = build_brief(snapshot, candidates, coverage)
    ledger = brief_ledger(brief)

    outcome = ValidationOutcome(insufficient_data=not coverage.is_sufficient)
    commentary = ValidatedCommentary()
    status = AnalysisRunStatus.COMPLETED
    failure_reason: str | None = None

    if not brief.findings:
        # The rules engine found nothing worth raising, so there is nothing to
        # interpret. Generating anyway would be asking the model to find meaning
        # in an absence, which is exactly where it invents.
        status = AnalysisRunStatus.SKIPPED
        failure_reason = "rules produced no findings to interpret"
    else:
        generator = generate or _ollama_generate
        try:
            raw = generator(
                build_commentary_prompt(brief),
                settings.analyst_commentary_timeout_seconds,
                settings.analyst_commentary_max_tokens,
            )
            parsed = AnalystCommentary.model_validate(_extract_json(raw))
        except (httpx.TimeoutException, httpx.HTTPError) as error:
            status = AnalysisRunStatus.FAILED
            failure_reason = f"commentary generation failed: {error}"
        except (ValueError, ValidationError, json.JSONDecodeError) as error:
            status = AnalysisRunStatus.FAILED
            failure_reason = f"commentary was unusable: {error}"
        else:
            commentary = validate_commentary(parsed, brief=brief, ledger=ledger)
            if commentary.rejections and commentary.accepted_count == 0:
                status = AnalysisRunStatus.REJECTED
                failure_reason = "every comment failed validation"

    outcome.rejections.extend(commentary.rejections)
    elapsed_ms = int((monotonic() - started) * 1000)

    run = record_run(
        db,
        scope=scope,
        comparison=resolved_comparison,
        ledger=ledger,
        outcome=outcome,
        coverage=coverage,
        status=status,
        started_at=started_at,
        elapsed_ms=elapsed_ms,
        model_name=settings.analyst_model,
        failure_reason=failure_reason,
        extra_transcript={
            "mode": "additive",
            "rules_findings": len(brief.findings),
            "commentary": commentary.to_payload(),
        },
        commit=commit,
    )

    logger.info(
        "Additive analyst run restaurant_id=%s status=%s rules=%s accepted=%s "
        "rejected=%s elapsed_ms=%s",
        scope.restaurant_id,
        status.value,
        len(brief.findings),
        commentary.accepted_count,
        len(commentary.rejections),
        elapsed_ms,
    )

    result = AnalysisRunResult(
        status=status,
        run_id=run.id,
        outcome=outcome,
        tool_calls=0,
        elapsed_ms=elapsed_ms,
        failure_reason=failure_reason,
        fell_back=status != AnalysisRunStatus.COMPLETED,
    )
    result.commentary = commentary
    result.brief = brief
    return result


__all__ = [
    "AnalysisRunResult",
    "SEEDED_CALLS",
    "AnalystError",
    "Generate",
    "GENERATE_ENDPOINT",
    "run_additive_analysis",
    "run_analysis",
]

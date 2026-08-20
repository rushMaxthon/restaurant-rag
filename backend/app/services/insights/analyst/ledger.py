"""The fact ledger: every number the data actually produced, and where from.

Phase 2 gave narration a fixed `FactPack` — the figures were known before the
model wrote a word, so checking its output against them was straightforward. An
analyst that chooses its own questions has no such pack: the set of legitimate
numbers is not known until the run is over, because it is exactly the set the
tools returned along the way.

So the ledger accumulates. Each tool result is recorded under a call id, with
every number it contained. Two things fall out of that:

* A generated figure is legitimate only if some call actually returned it. Same
  rule as narration's guardrail, with a set that grows during the run.
* A claim can be traced. "Revenue fell 40%" citing `call_3` is checkable against
  what `call_3` returned; a claim citing nothing is not a finding, it is an
  assertion, and is treated as such.

Numbers are collected recursively and stored both exactly and in the rounded
forms prose legitimately uses, reusing `facts._expand_allowed` so the ledger and
the older guardrail agree on what "the same number" means.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable

from app.services.insights.analyst.schemas import ToolResult
from app.services.insights.facts import _expand_allowed

# Values that carry no factual weight and would only widen the allowed set:
# counts of 0 and 1, and the identity multiplier. Letting these through means a
# model can write "1" or "0" freely, which it should be able to.
TRIVIAL_NUMBERS = frozenset({0.0, 1.0})


@dataclass(slots=True)
class LedgerEntry:
    """One tool call and the numbers it returned."""

    call_id: str
    tool: str
    args: dict[str, Any]
    ok: bool
    values: set[float] = field(default_factory=set)
    error: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool": self.tool,
            "args": self.args,
            "ok": self.ok,
            "error": self.error,
            "value_count": len(self.values),
        }


def collect_numbers(payload: Any, sink: set[float]) -> None:
    """Every numeric value anywhere in a tool result.

    Booleans are excluded on purpose: `True` is not the number 1, and treating
    it as one would quietly authorise "1" for any result containing a flag.
    Date parts are collected, since a period is routinely written out in prose.
    """

    if isinstance(payload, bool) or payload is None:
        return
    if isinstance(payload, (int, float)):
        sink.add(float(payload))
        return
    if isinstance(payload, Decimal):
        sink.add(float(payload))
        return
    if isinstance(payload, (datetime, date)):
        sink.update({float(payload.day), float(payload.month), float(payload.year)})
        return
    if isinstance(payload, str):
        # ISO dates arrive as strings from the tool layer's JSON rendering.
        try:
            parsed = date.fromisoformat(payload[:10])
        except ValueError:
            return
        sink.update({float(parsed.day), float(parsed.month), float(parsed.year)})
        return
    if isinstance(payload, dict):
        for value in payload.values():
            collect_numbers(value, sink)
        return
    if isinstance(payload, (list, tuple, set)):
        for value in payload:
            collect_numbers(value, sink)


@dataclass(slots=True)
class FactLedger:
    """Everything one run is allowed to say, indexed by where it came from."""

    entries: list[LedgerEntry] = field(default_factory=list)

    def record(self, result: ToolResult) -> LedgerEntry:
        """Add one tool result and return its entry.

        Failed calls are recorded too, with no values. A model that cites a call
        which errored is citing an absence of data, and the validator needs to
        be able to see that rather than find nothing at all.
        """

        call_id = f"call_{len(self.entries) + 1}"
        values: set[float] = set()
        if result.ok:
            collect_numbers(result.data, values)

        entry = LedgerEntry(
            call_id=call_id,
            tool=result.tool,
            args=dict(result.args),
            ok=result.ok,
            values=values,
            error=result.error,
        )
        self.entries.append(entry)
        return entry

    def entry(self, call_id: str) -> LedgerEntry | None:
        for entry in self.entries:
            if entry.call_id == call_id:
                return entry
        return None

    def known_call_ids(self) -> set[str]:
        return {entry.call_id for entry in self.entries}

    def successful_call_ids(self) -> set[str]:
        return {entry.call_id for entry in self.entries if entry.ok}

    def values_for(self, call_ids: Iterable[str]) -> set[float]:
        """The raw values returned by the named calls."""

        wanted = set(call_ids)
        values: set[float] = set()
        for entry in self.entries:
            if entry.call_id in wanted:
                values |= entry.values
        return values

    def allowed_numbers(self, call_ids: Iterable[str] | None = None) -> set[float]:
        """Numbers that may legitimately appear in prose.

        Scoped to the cited calls when `call_ids` is given, which is stricter
        than the run as a whole: a finding about payment failures should not be
        able to borrow a figure from an unrelated menu query it never cited.
        """

        if call_ids is None:
            raw = {value for entry in self.entries for value in entry.values}
        else:
            raw = self.values_for(call_ids)

        allowed: set[float] = set(TRIVIAL_NUMBERS)
        for value in raw:
            allowed |= _expand_allowed(value)
        return allowed

    def to_transcript(self) -> dict[str, Any]:
        """The audit record: what was asked, in order, and whether it worked."""

        return {"calls": [entry.to_payload() for entry in self.entries]}


__all__ = ["FactLedger", "LedgerEntry", "TRIVIAL_NUMBERS", "collect_numbers"]

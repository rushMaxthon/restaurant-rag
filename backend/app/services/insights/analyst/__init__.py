"""The secure read-only data layer an AI analyst is allowed to reach.

Phase 8A builds the boundary and nothing else: a fixed registry of scoped,
read-only functions over the restaurant's own data. No model is involved at this
stage, and nothing here writes, so the layer can be tested to completion before
anything is allowed to call it autonomously.

Two rules hold for every tool, and both are enforced by tests rather than by
convention:

* Scope is supplied by the caller, never by the tool's arguments. No argument
  model may carry a restaurant, location, or user id, so a caller that later
  passes model-generated arguments has nowhere to smuggle one.
* Nothing writes. The module imports no offer, action, or persistence helper,
  and holds no path to `Session.add`.
"""

from app.services.insights.analyst.ledger import FactLedger
from app.services.insights.analyst.registry import (
    TOOLS,
    ToolNotFound,
    call_tool,
    describe_tools,
    tool_names,
)
from app.services.insights.analyst.schemas import ToolResult, ToolSpec
from app.services.insights.analyst.validation import CoverageContext, validate_verdict

__all__ = [
    "CoverageContext",
    "FactLedger",
    "TOOLS",
    "ToolNotFound",
    "ToolResult",
    "ToolSpec",
    "call_tool",
    "describe_tools",
    "tool_names",
    "validate_verdict",
]

# `runner` is deliberately not imported here. It reaches the persistence layer,
# which reaches the models, and importing it eagerly would drag that whole graph
# into anything that only wanted to call a tool. Import it by module.

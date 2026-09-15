"""The customer-facing ordering agent: understanding is the model's job,
validating is not.

`docs/superpowers/plans/2026-09-15-ordering-agent.md` builds this in tasks;
this package accumulates them. Task 1 builds the boundary and nothing else: a
fixed registry of scoped, read-only tools. No model is involved at this
stage, and nothing here writes, so the layer can be tested to completion
before a planner is allowed to call it with model-generated arguments.

Two rules hold for every tool, both enforced by tests rather than by
convention, mirroring `insights/analyst/__init__.py`:

* Scope is supplied by the caller, never by the tool's arguments. No argument
  model may carry a restaurant, branch, location, customer, user or
  app-client id, so a caller that later passes model-generated arguments has
  nowhere to smuggle one.
* Nothing writes, and nothing that merely answers a question about payment
  can be extended into performing one without visibly changing its argument
  model — `payment_options` takes no arguments at all.
"""

from app.services.ordering_agent.tools import (
    FORBIDDEN_ARG_NAMES,
    TOOL_LIST,
    TOOLS,
    ToolArgs,
    ToolSpec,
    describe_tools_for_prompt,
)

__all__ = [
    "FORBIDDEN_ARG_NAMES",
    "TOOL_LIST",
    "TOOLS",
    "ToolArgs",
    "ToolSpec",
    "describe_tools_for_prompt",
]

"""Task 5: the boundary between a model's plan and a tool actually running.

`tools.py`'s `OrderingScope` docstring already named this module as the place
its construction belongs; this is that place, plus the three other checks
the loop needs run on every planned call before a handler ever sees it:

* **Scope** (`scope_for`) — the caller decides which branch and which
  customer a turn is about, never the model. A `GuestPrincipal` (see
  `chat_principal.py`) becomes `customer=None`; a signed-in `User` becomes
  `scope.customer` directly, matching what `price_quote`'s handler already
  expects (`OrderingScope.customer is None` means "sign in for an exact
  price", never an exception).

* **Id provenance** (`seed_seen_ids`, `grow_seen_ids`, `prepare_tool_call`) —
  the plan's rule, in general form: "the model never supplies an id" is not
  special to `remove_from_cart`/`set_quantity` (Task 3's own constraint), it
  is true of every id-shaped argument on every tool. A `seen` set starts with
  every id the request's own cart carries (those are legitimately known —
  the browser told us) and grows with every UUID-shaped value found anywhere
  in every tool result this turn, walked by *shape*, not by key name: a
  future tool that names its id field something nobody anticipated is still
  caught, where a key-name allowlist would silently miss it.

* **Cart injection** (also `prepare_tool_call`) — the browser's cart reaches
  a tool through the loop, never by the model retyping 36-character ids by
  hand. `view_cart`/`remove_from_cart`/`set_quantity` always get the request
  cart in place of whatever the model wrote; `price_quote` keeps the model's
  own lines only when every id in them already passed provenance and the
  list is non-empty (so "how much for a large one?", built from what
  `get_dish` just returned, can still be priced without echoing the whole
  cart back) — otherwise it falls back to the request cart, and only refuses
  outright when that is empty too.

* **Destructive policy** (`enforce_destructive_policy`) — defence in depth,
  not the actual rule. The rule already lives in `tools.py`'s handlers
  (`_clear_cart` is unconditionally `proposed`; `_remove_from_cart`/
  `_set_quantity` are `proposed` on any ambiguous match): this gate exists so
  a future change to one of those handlers cannot silently relax it without
  also breaking a loop-level assertion, not because either handler is
  expected to violate it today.

`prepare_tool_call` is the one function the loop actually calls per round;
the smaller pieces above are exported mainly so tests can exercise each
concern in isolation, the way `tools.py` exports its own building blocks.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.schemas.suggestions import CartLinePayload
from app.services.chat_principal import ChatPrincipal, is_guest
from app.services.ordering_agent.tools import TOOLS, OrderingScope, ToolArgs
from pydantic import ValidationError

logger = logging.getLogger(__name__)

# The tools whose args model carries the browser's cart verbatim, and the
# field name it lives under in that tool's own args model (`tools.py`:
# `ViewCartArgs.lines`, `RemoveFromCartArgs.existing_lines`,
# `SetQuantityArgs.existing_lines`). `price_quote` is deliberately absent —
# its `lines` field is conditional on provenance, handled separately below,
# because unlike these three it is the one cart-shaped argument this agent
# is allowed to price from the model's OWN words ("price a large one") once
# every id in them is already known.
_ALWAYS_INJECTED_CART_FIELD: dict[str, str] = {
    "view_cart": "lines",
    "remove_from_cart": "existing_lines",
    "set_quantity": "existing_lines",
    "go_to_checkout": "lines",
}


def scope_for(
    principal: ChatPrincipal,
    restaurant_id: uuid.UUID,
    restaurant_location_id: uuid.UUID,
    diet: str | None = None,
) -> OrderingScope:
    """The half of every tool call the model never supplies, built from the
    caller's already-authenticated session — never from anything the model
    wrote. A guest's `customer` is `None`, matching what every handler in
    `tools.py` already treats a signless customer as (browsing and hours
    work; `price_quote` asks the guest to sign in instead of raising).
    """

    customer = None if is_guest(principal) else principal
    return OrderingScope(
        restaurant_id=restaurant_id,
        restaurant_location_id=restaurant_location_id,
        customer=customer,
        diet=diet,
    )


def _collect_uuids(value: Any, sink: set[uuid.UUID]) -> None:
    """Walk any nested dict/list/tuple, adding every UUID-*shaped* value.

    Matches on shape, per the brief, not on key name: a real `uuid.UUID`
    instance (what a validated `args_model.model_dump()` or a handler's own
    dataclass field actually holds) or a string that parses as one (what a
    tool result serializes ids to via `default=str` upstream, and what a
    freshly-built `CartLinePayload.model_dump()` never needs since it is
    already typed). A plain string that happens to parse — a stray 32-hex
    token that is not really an id — is treated as one anyway; the brief
    accepts that over depending on which key it came from.
    """

    if isinstance(value, uuid.UUID):
        sink.add(value)
    elif isinstance(value, str):
        try:
            sink.add(uuid.UUID(value))
        except ValueError:
            pass
    elif isinstance(value, dict):
        for item in value.values():
            _collect_uuids(item, sink)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _collect_uuids(item, sink)
    # Anything else (int, float, bool, Decimal, None, datetime, ...) is not
    # UUID-shaped and carries no ids to find.


def seed_seen_ids(cart: list[CartLinePayload]) -> set[uuid.UUID]:
    """The ids a turn starts with: every menu item, size and option id the
    request's own cart carries. Legitimately known before any tool ever
    runs — the browser is the one place the cart lives, and reporting it is
    the caller's job, not the model's guess.
    """

    seen: set[uuid.UUID] = set()
    for line in cart:
        _collect_uuids(line.model_dump(), seen)
    return seen


def grow_seen_ids(seen: set[uuid.UUID], result: Any) -> None:
    """Every id-shaped value a tool result just taught the model, folded
    into the running set in place. Called after every successful handler
    call, on the whole result dict — never on only the fields a caller
    guesses might carry an id, per the brief's "walk nested dicts/lists"
    instruction.
    """

    _collect_uuids(result, seen)


def _cart_line_dict(line: CartLinePayload) -> dict[str, Any]:
    """One request cart line, reshaped for `CartLineArgs.model_validate` —
    `CartLinePayload` (`app/schemas/suggestions.py`) and `CartLineArgs`
    (`tools.py`) describe the same browser cart line but do not share field
    names (`size_id`/`customization_option_ids` vs.
    `menu_item_size_id`/`selected_options`), so this is a field-for-field
    translation, not a re-validation of an already-typed payload. Quantity
    and portion on each option default to 1/`WHOLE`
    (`SelectedOptionArgs`'s own defaults) because `CartLinePayload` never
    carries either for an option — it names which options are chosen, not
    how many of each — matching what the browser cart already implies.
    """

    return {
        "menu_item_id": line.menu_item_id,
        "quantity": line.quantity,
        "menu_item_size_id": line.size_id,
        "selected_options": [{"option_id": option_id} for option_id in line.customization_option_ids],
    }


def _request_cart_lines(cart: list[CartLinePayload]) -> list[dict[str, Any]]:
    return [_cart_line_dict(line) for line in cart]


def _inject_cart(tool_name: str, args: dict[str, Any], cart: list[CartLinePayload], seen: set[uuid.UUID]) -> tuple[dict[str, Any] | None, str | None]:
    """Replace whatever cart-shaped argument the model wrote with the real
    one, per tool. Returns `(merged_args, None)` normally, or `(None,
    reason)` for the one refusal this step can produce on its own:
    `price_quote` with nothing left to price once the model's own lines are
    rejected and the request cart is empty too.
    """

    field = _ALWAYS_INJECTED_CART_FIELD.get(tool_name)
    if field is not None:
        return {**args, field: _request_cart_lines(cart)}, None

    if tool_name != "price_quote":
        return args, None

    model_lines = args.get("lines")
    if isinstance(model_lines, list) and model_lines:
        model_line_ids: set[uuid.UUID] = set()
        _collect_uuids(model_lines, model_line_ids)
        if model_line_ids <= seen:
            return args, None

    cart_lines = _request_cart_lines(cart)
    if not cart_lines:
        return None, "empty_cart: nothing to price"
    return {**args, "lines": cart_lines}, None


def prepare_tool_call(
    tool_name: str,
    args: dict[str, Any],
    *,
    cart: list[CartLinePayload],
    seen: set[uuid.UUID],
    diet: str | None = None,
) -> tuple[ToolArgs, None] | tuple[None, str]:
    """Everything that must happen to a planner-validated call between the
    plan and the handler: inject the real cart where one applies, re-validate
    through the tool's own `args_model` (per the brief, done AFTER injection
    and BEFORE the provenance check below — the injected dicts are plain
    values, not yet the typed objects a handler expects), then refuse if any
    id-shaped value in the fully-resolved args was never seen this turn.

    Returns `(validated_args, None)` when the call may run, or `(None,
    reason)` when it may not — `reason` is fed back to the model as a
    `ToolCallRecord.error` so it can correct itself, never raised.
    """

    spec = TOOLS.get(tool_name)
    if spec is None:
        # Defensive only: `plan_step` already refuses a tool name outside
        # its `allowed` set (itself a subset of `TOOLS`) with `unknown_tool`
        # before the loop ever calls this. Reached only if a caller invokes
        # this function directly with a name the planner never blessed.
        return None, "unknown_tool"

    if diet == "veg" and tool_name == "search_menu":
        # The customer's diet is not the model's to forget: a vegetarian's
        # search is veg-only whatever `is_veg` the plan carried.
        args = {**args, "is_veg": True}
    merged, refusal = _inject_cart(tool_name, args, cart, seen)
    if refusal is not None:
        return None, refusal

    try:
        validated = spec.args_model.model_validate(merged)
    except ValidationError as error:
        return None, f"invalid_arguments: {error}"

    missing = sorted(_unseen_ids(validated.model_dump(), seen), key=str)
    if missing:
        return None, "unknown_id: " + ", ".join(str(item) for item in missing)

    return validated, None


def _unseen_ids(value: Any, seen: set[uuid.UUID]) -> list[uuid.UUID]:
    found: set[uuid.UUID] = set()
    _collect_uuids(value, found)
    return list(found - seen)


def enforce_destructive_policy(result: dict[str, Any]) -> dict[str, Any]:
    """Defence in depth for the plan's "destructive is always proposed,
    never applied" rule. `tools.py`'s handlers already enforce this
    (`_clear_cart` never returns anything else; `_remove_from_cart`/
    `_set_quantity` downgrade to `proposed` on any ambiguous match) — this
    function exists so a future handler regression cannot silently slip an
    `applied` `clear`, an `applied` ambiguous `remove`, or an `applied`
    ambiguous `set_quantity` past the loop without at least a warning and a
    downgrade.

    Gates on the PROPERTY, not on one reason string a handler happens to
    use today: `kind == "clear"` is always disallowed, and for `kind` in
    `{"remove", "set_quantity"}` the only reason a handler ever attaches to
    a legitimately applied action is `"named"` (`tools.py:1225, 1263,
    1299`) — a real, unambiguous match against the browser's own cart. Any
    other reason on those two kinds (`"destructive"`, `"ambiguous"`, or
    anything a future handler invents) is exactly the shape a mutation is
    never supposed to self-report as applied, so it is downgraded too.
    Checking `reason == "ambiguous"` alone (an earlier version of this gate)
    missed `_remove_from_cart`'s own multi-match case, which uses
    `reason="destructive"`, not `"ambiguous"` — the fix here is to name the
    one reason that IS safe, rather than enumerate every reason that is not.

    A no-op for any result without an `"action"` dict (every read-only tool,
    and `add_to_cart`'s own non-destructive `applied` path) — safe to call
    after every successful tool call rather than only after the four
    mutation tools by name.
    """

    action = result.get("action") if isinstance(result, dict) else None
    if not isinstance(action, dict):
        return result

    kind = action.get("kind")
    violates = action.get("status") == "applied" and (
        kind in ("clear", "checkout") or (kind in ("remove", "set_quantity") and action.get("reason") != "named")
    )
    if not violates:
        return result

    logger.warning(
        "Ordering agent guard downgraded a %s %s action reported as applied "
        "(handler should never emit this; defence in depth)",
        action.get("reason"),
        action.get("kind"),
    )
    return {**result, "action": {**action, "status": "proposed"}}


__all__ = [
    "enforce_destructive_policy",
    "grow_seen_ids",
    "prepare_tool_call",
    "scope_for",
    "seed_seen_ids",
]

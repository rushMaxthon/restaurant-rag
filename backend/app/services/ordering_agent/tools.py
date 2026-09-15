"""The tool contract for the customer-facing ordering agent.

Sibling of `insights/tool_chat.py`: a `TOOL_LIST` of Pydantic argument models,
a `TOOLS` registry built by `_validate_registry` at import time (mirroring
`insights/analyst/registry.py`, which enforces the same rule for the
owner-facing planner), and a description helper the planner prompt is built
from. There is only one registry here, not a bigger one with a whitelisted
subset the way `analyst` feeds `tool_chat`'s `CHAT_TOOLS` — every tool defined
in this module IS customer-facing, so there is no second tier to select from.

The rule that matters more than any of the others: **no argument model here
may accept a restaurant, branch, location, customer, user or app-client id.**
Scope is injected by the caller from the authenticated session — the model
does not choose whose data is read. `_validate_registry` fails the import,
not a test run later, if a tool violates this, exactly as
`analyst/registry.py::_validate_registry` does for the owner-side planner.

Handlers raise `NotImplementedError` in this task on purpose. Task 2 wires
each one to the existing service that already does the real work — retrieval
in `rag.py`, pricing in `orders.py::validate_order_draft`, hours in
`restaurant_locations.py` — because "no new business logic" only holds if the
handler bodies do not exist yet to invent any.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import time
from decimal import Decimal
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.models.enums import MenuItemPortion, OrderFulfillmentType

# Argument names that would let a customer's sentence choose whose data gets
# read, or let a "read-only" tool masquerade as a write. The five the brief
# names explicitly (restaurant/branch/location/customer/user) plus the
# app-scoping id this repo's identity model adds on top of them
# (`docs/per-app-identity.md`: the same phone in two apps is two accounts),
# plus the fields that would turn `payment_options` from a question into an
# action. Deliberately narrower than `analyst/registry.py`'s
# `FORBIDDEN_ARGUMENT_NAMES`: that set also bans `sql` and `query` because an
# analyst tool answering an owner's free-form question could otherwise be
# tricked into naming a raw query; `search_menu` legitimately needs a `query`
# field for the customer's search text, and no tool here executes SQL a
# caller supplies, so banning it would remove a real argument to prevent a
# risk that does not exist in this registry.
FORBIDDEN_ARG_NAMES = frozenset(
    {
        "restaurant_id",
        "restaurant_location_id",
        "location_id",
        "branch_id",
        "owner_id",
        "user_id",
        "customer_id",
        "app_client_id",
        "tenant_id",
        "scope",
        "db",
        "session",
        # Never a consideration for a *read-only* tool, but forbidden here too
        # so a later tool cannot quietly grow the power to spend money or name
        # somebody else's order.
        "amount",
        "payment_method",
        "order_id",
        "card_number",
        "payment_token",
    }
)


class ToolArgs(BaseModel):
    """Base for every ordering-agent tool's arguments.

    `extra="forbid"` matters more than it looks: a key the model invented —
    most dangerously a scope id — is rejected outright rather than silently
    dropped, so a bad call fails loudly instead of quietly running with less
    scope-checking than it looks like it has. Mirrors
    `insights/analyst/schemas.py::ToolArgs`.
    """

    model_config = ConfigDict(extra="forbid")


class NoArgs(ToolArgs):
    """A tool that needs nothing beyond the scope the caller already injects."""


class SelectedOptionArgs(ToolArgs):
    """One chosen customization option, in the exact shape checkout already
    uses (`OrderCreateItemCustomizationOption`, `app/schemas/order.py`). An
    identifier only — Task 2's handlers re-resolve it against the branch's
    real customization groups, the same way checkout re-resolves every id a
    client sends rather than trusting its price or name.
    """

    option_id: uuid.UUID
    quantity: int = Field(default=1, ge=1, le=99)
    portion: MenuItemPortion = MenuItemPortion.WHOLE


class CartLineArgs(ToolArgs):
    """One line of the cart the browser is holding, mirroring `OrderCreateItem`
    field-for-field so Task 2 can hand this straight to the pricing path that
    already exists rather than translating between two cart shapes that could
    drift apart. No name, no price: those are looked up, never trusted from
    here — the cart lives in the browser, not the database, so describing it
    is the only way a tool can see it at all.
    """

    menu_item_id: uuid.UUID
    quantity: int = Field(ge=1, le=99)
    menu_item_size_id: uuid.UUID | None = None
    selected_options: list[SelectedOptionArgs] = Field(default_factory=list)


class SearchMenuArgs(ToolArgs):
    """What a customer is looking for on the menu they are already browsing.

    No branch id: retrieval is already scoped to the branch the session is
    bound to, the same way `rag.py`'s retrieval tiers take a restaurant scope
    as a keyword argument rather than reading one off the message. `is_veg`
    mirrors `MenuItem.is_veg` directly — there is no vegan tri-state in this
    schema, only veg/non-veg — and `max_price` is a ceiling against
    `MenuItem.price`, the same figure `_resolve_budget_limit` already reads
    out of a sentence like "under 300".
    """

    query: str = Field(min_length=1, max_length=500)
    is_veg: bool | None = Field(
        default=None,
        description="True for vegetarian only, False for non-veg only, omit for either.",
    )
    max_price: Decimal | None = Field(default=None, ge=0)
    limit: int = Field(default=5, ge=1, le=20)


class GetDishArgs(ToolArgs):
    """A dish named in conversation, resolved the way
    `apply_dish_name_guardrail`/`classify_dish_reference` already resolve one:
    by name and retrieval confidence against the branch's real menu, never by
    an id the model invented on the strength of a name it typed.
    """

    name: str = Field(min_length=1, max_length=255)


class ViewCartArgs(ToolArgs):
    """The cart the request carried. There is no server-side cart to look up
    by id — the browser is the only place it lives — so the only way this
    tool can see it is to be told, and Task 2's handler re-resolves every
    line against the branch's current menu rather than trusting it.
    """

    lines: list[CartLineArgs] = Field(default_factory=list)


class CheckHoursArgs(ToolArgs):
    """Whether, and until when, the branch can take an order — mirrors what
    `schedule_slot_is_available`/`get_location_fulfillment_status`
    (`restaurant_locations.py`) already check at checkout, so a chat answer
    and the order path can never disagree about whether the kitchen is open.
    A time that works for pickup but not delivery is a real, separate answer,
    which is why `fulfillment_type` is here rather than assumed.
    """

    fulfillment_type: OrderFulfillmentType | None = None
    requested_time: time | None = Field(
        default=None,
        description="A clock time the customer named, e.g. 21:30, if any.",
    )


class PriceQuoteArgs(ToolArgs):
    """A cart to price, not an order to place — describes what checkout would
    need to run `orders.py::validate_order_draft`, minus the fields that are
    about the *order* rather than the *price*: no address, no contact details,
    no payment method. Those belong to placing an order, which this agent
    never does; a quote is answered from the same arithmetic checkout uses,
    never invented here, which is the whole reason it delegates rather than
    computing a subtotal itself.
    """

    lines: list[CartLineArgs] = Field(min_length=1)
    fulfillment_type: OrderFulfillmentType = OrderFulfillmentType.DELIVERY


class RestaurantInfoArgs(NoArgs):
    """The branch the customer is already on. Nothing to parametrize: this
    answers "where are you" / "how long for delivery", not "tell me about a
    restaurant I name" — there is exactly one branch this call can ever be
    about, and it is the one the session is scoped to.
    """


class PaymentOptionsArgs(NoArgs):
    """Which payment methods the branch accepts — nothing else. Deliberately
    `NoArgs`: there is no field here an amount, a method-to-charge or an order
    id could occupy, so this tool cannot be extended into initiating a
    payment without someone visibly changing its argument model first. It
    answers "do you take card", it never processes one.
    """


# The second positional argument every handler receives is the caller's
# authenticated scope (which branch, which cart, which customer) once
# `guards.py` (Task 5) gives it a real shape. Left as `Any` here rather than
# invented early: a handler signature that already looked id-shaped would be
# exactly the defect this task's tests check the argument MODELS for, just
# moved one parameter to the right.
OrderingScope = Any

ToolHandler = Callable[[Session, OrderingScope, ToolArgs], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """One callable slice of ordering data. Mirrors
    `insights/analyst/schemas.py::ToolSpec` field-for-field.
    """

    name: str
    description: str
    args_model: type[ToolArgs]
    handler: ToolHandler


def _search_menu(db: Session, scope: OrderingScope, args: SearchMenuArgs) -> dict[str, Any]:
    raise NotImplementedError("Task 2: wire to rag.py's retrieval tiers, branch-scoped")


def _get_dish(db: Session, scope: OrderingScope, args: GetDishArgs) -> dict[str, Any]:
    raise NotImplementedError(
        "Task 2: wire to apply_dish_name_guardrail/classify_dish_reference"
    )


def _view_cart(db: Session, scope: OrderingScope, args: ViewCartArgs) -> dict[str, Any]:
    raise NotImplementedError("Task 2: re-resolve args.lines against the branch's menu")


def _check_hours(db: Session, scope: OrderingScope, args: CheckHoursArgs) -> dict[str, Any]:
    raise NotImplementedError(
        "Task 2: wire to restaurant_locations.get_location_fulfillment_status / "
        "schedule_slot_is_available"
    )


def _price_quote(db: Session, scope: OrderingScope, args: PriceQuoteArgs) -> dict[str, Any]:
    raise NotImplementedError("Task 2: delegate to orders.validate_order_draft, never compute here")


def _restaurant_info(db: Session, scope: OrderingScope, args: RestaurantInfoArgs) -> dict[str, Any]:
    raise NotImplementedError("Task 2: read RestaurantLocation columns for the injected branch")


def _payment_options(db: Session, scope: OrderingScope, args: PaymentOptionsArgs) -> dict[str, Any]:
    raise NotImplementedError(
        "Task 2: wire to restaurant_locations.get_enabled_payment_methods, read-only"
    )


TOOL_LIST: tuple[ToolSpec, ...] = (
    ToolSpec(
        "search_menu",
        "Search the branch's menu by free text, with an optional veg-only "
        "filter and price ceiling.",
        SearchMenuArgs,
        _search_menu,
    ),
    ToolSpec(
        "get_dish",
        "Resolve one dish named in conversation to the row it refers to, "
        "with its real price, sizes and customizations.",
        GetDishArgs,
        _get_dish,
    ),
    ToolSpec(
        "view_cart",
        "Re-resolve the cart the browser is holding against the branch's "
        "current menu, prices and availability.",
        ViewCartArgs,
        _view_cart,
    ),
    ToolSpec(
        "check_hours",
        "Whether the branch can take an order now, or at a time the "
        "customer named, for delivery or pickup.",
        CheckHoursArgs,
        _check_hours,
    ),
    ToolSpec(
        "price_quote",
        "Price a cart the same way checkout would, without placing an "
        "order.",
        PriceQuoteArgs,
        _price_quote,
    ),
    ToolSpec(
        "restaurant_info",
        "The branch's own facts: address, phone, whether delivery and "
        "pickup are each available, estimated delivery and prep time, "
        "minimum order amount and delivery fee.",
        RestaurantInfoArgs,
        _restaurant_info,
    ),
    ToolSpec(
        "payment_options",
        "Which payment methods this branch accepts right now. Never "
        "initiates, authorises or captures a payment.",
        PaymentOptionsArgs,
        _payment_options,
    ),
)


def _validate_registry(specs: tuple[ToolSpec, ...]) -> dict[str, ToolSpec]:
    registry: dict[str, ToolSpec] = {}
    for spec in specs:
        if spec.name in registry:
            raise RuntimeError(f"Duplicate ordering agent tool name: {spec.name}")
        offending = sorted(set(spec.args_model.model_fields) & FORBIDDEN_ARG_NAMES)
        if offending:
            # Loud at import, not discovered by a test someone forgot to add:
            # a tool that lets its caller name a tenant, or spend money, is
            # not a defect to be caught in review later.
            raise RuntimeError(
                f"Ordering agent tool {spec.name} exposes forbidden arguments: {offending}"
            )
        registry[spec.name] = spec
    return registry


TOOLS: dict[str, ToolSpec] = _validate_registry(TOOL_LIST)


def describe_tools_for_prompt(names: "tuple[str, ...] | None" = None) -> str:
    """Render the tools' real argument names into planner-prompt lines.

    Mirrors `insights/tool_chat.py::_describe_chat_tools`, made public and
    moved here (rather than living beside the prompt in `planner.py`) because
    the description is a property of the registry, not of any one planner
    call — a generic example argument list is exactly what made the owner-side
    planner pass `window_days` to a tool that took nothing, which
    `extra="forbid"` then rejected.
    """

    lines = []
    for name in names or tuple(TOOLS):
        spec = TOOLS.get(name)
        if spec is None:
            continue
        fields = spec.args_model.model_fields
        args = ", ".join(fields) if fields else "no arguments"
        summary = spec.description.split(".")[0].strip()
        lines.append(f"- {name}({args}) — {summary}")
    return "\n".join(lines)


__all__ = [
    "FORBIDDEN_ARG_NAMES",
    "TOOL_LIST",
    "TOOLS",
    "CartLineArgs",
    "CheckHoursArgs",
    "GetDishArgs",
    "NoArgs",
    "OrderingScope",
    "PaymentOptionsArgs",
    "PriceQuoteArgs",
    "RestaurantInfoArgs",
    "SearchMenuArgs",
    "SelectedOptionArgs",
    "ToolArgs",
    "ToolHandler",
    "ToolSpec",
    "ViewCartArgs",
    "describe_tools_for_prompt",
]

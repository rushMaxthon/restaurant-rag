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

Task 2 wires every handler to the existing service that already does the real
work, and adds nothing else: retrieval cascades from `rag.py`, dish
confidence from `apply_dish_name_guardrail`/`classify_dish_reference`, cart
and price resolution from `menu_item_customizations.py` and
`orders.py::validate_order_draft`, hours from `restaurant_locations.py`. A
handler that computes a price or a discount itself would be the bug this
module exists to avoid — see `_price_quote`, which delegates the arithmetic
outright rather than reading `validate_order_draft`'s formula and copying it.

`OrderingScope` (below) gives Task 1's placeholder `Any` its real shape: the
half of every call that comes from the caller's authenticated session, never
from the model. Every handler signature is `(db, scope, args)` so a reader
can tell which half is which without reading the body — `scope` is never
mentioned in an `args_model`, and no `args` field is ever fed back into a
query that chooses whose data comes out.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import MenuItemPortion, OrderFulfillmentType
from app.models.menu_item import MenuItem
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.schemas.order import (
    OrderCreateItem,
    OrderCreateItemCustomizationOption,
    OrderCreateRequest,
)
from app.services import rag as ordering_rag
from app.services.menu_item_customizations import (
    ResolvedMenuItemSelection,
    SelectedCustomizationOptionInput,
    menu_item_query_with_customizations,
    resolve_menu_item_selection,
)
from app.services.orders import validate_order_draft
from app.services.restaurant_locations import (
    get_enabled_payment_methods,
    get_location_fulfillment_status,
    schedule_slot_is_available,
)

settings = get_settings()
BUSINESS_TIMEZONE = settings.business_timezone_info
TWO_PLACES = Decimal("0.01")

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


@dataclass(frozen=True, slots=True)
class OrderingScope:
    """The half of every tool call that the model never supplies.

    Built by the caller from the authenticated session (Task 5's `guards.py`
    is where that construction will live; Task 2 only needs the shape to
    write handlers against). `restaurant_id`/`restaurant_location_id` pin
    every handler to one branch — the same pair `AppScopeDep` and
    `ensure_restaurant_readable`/`ensure_restaurant_writable` already use
    elsewhere in this codebase to scope a request server-side. `customer` is
    `None` for a signed-out guest, who can still browse the menu and check
    hours; only `price_quote` needs a real one, because it delegates to
    `validate_order_draft`, which is customer-only
    (`orders.py::_prepare_order_draft` raises 403 for anyone else) — a guest
    gets a graceful refusal from the handler, not that exception.
    """

    restaurant_id: uuid.UUID
    restaurant_location_id: uuid.UUID
    customer: User | None = None

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


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _load_branch_location(db: Session, scope: OrderingScope) -> RestaurantLocation | None:
    """The one branch a call may ever be about, or `None` if it has vanished.

    A plain `db.get` plus an ownership check rather than a query filtered by
    both ids: the row is looked up by its own primary key and then checked
    against the injected restaurant, so a location id that is real but
    belongs to a *different* restaurant is refused the same way an id that
    does not exist at all is — never distinguished in the response, which
    would leak which case it was.
    """

    location = db.get(RestaurantLocation, scope.restaurant_location_id)
    if location is None or location.restaurant_id != scope.restaurant_id:
        return None
    return location


def _load_branch_menu_items(db: Session, scope: OrderingScope) -> dict[uuid.UUID, MenuItem]:
    """Every purchasable item at the caller's branch, keyed by id.

    Loaded independently of anything `args` says, eager-loaded with the sizes
    and customization groups `resolve_menu_item_selection` needs. Mirrors
    `suggestion_for_cart`'s own comment on this exact pattern
    (`suggestions.py`): a cart line naming an id that is not a key in this
    dict is not on this branch's menu, full stop — cheaper to build once here
    for `view_cart` and `price_quote` alike than to re-derive it in each.
    """

    return {
        item.id: item
        for item in db.scalars(
            menu_item_query_with_customizations().where(
                MenuItem.restaurant_id == scope.restaurant_id,
                MenuItem.restaurant_location_id == scope.restaurant_location_id,
                MenuItem.is_available.is_(True),
            )
        ).all()
    }


@dataclass(frozen=True, slots=True)
class ResolvedCartLine:
    """One line of `args.lines` that survived branch scoping and customization
    validation, paired with the real row and price it resolved to.
    """

    line: CartLineArgs
    menu_item: MenuItem
    selection: ResolvedMenuItemSelection


def _resolve_cart_lines(
    menu_items: dict[uuid.UUID, MenuItem], lines: list[CartLineArgs]
) -> list[ResolvedCartLine]:
    """The browser's word about its cart, filtered down to what is real.

    Two ways a line can fail to survive, both silent rather than raised: its
    `menu_item_id` is not a key in `menu_items` (wrong branch, or simply
    invented), or it resolves but with a size/option combination
    `resolve_menu_item_selection` refuses (its own `HTTPException`, e.g. "no
    size chosen for an item that requires one"). Either way the line is
    dropped, not the whole cart — a browser session that has drifted from the
    real menu degrades to what is still valid instead of failing the turn,
    matching the requirement that a malformed cart degrades rather than
    raises.
    """

    resolved: list[ResolvedCartLine] = []
    for line in lines:
        menu_item = menu_items.get(line.menu_item_id)
        if menu_item is None:
            continue
        try:
            selection = resolve_menu_item_selection(
                menu_item,
                menu_item_size_id=line.menu_item_size_id,
                selected_options=[
                    SelectedCustomizationOptionInput(
                        option_id=option.option_id,
                        quantity=option.quantity,
                        portion=option.portion,
                    )
                    for option in line.selected_options
                ],
            )
        except HTTPException:
            continue
        resolved.append(ResolvedCartLine(line=line, menu_item=menu_item, selection=selection))
    return resolved


def _serialize_menu_item(menu_item: MenuItem) -> dict[str, Any]:
    return {
        "menu_item_id": menu_item.id,
        "name": menu_item.name,
        "category": menu_item.category,
        "price": menu_item.price,
        "is_veg": menu_item.is_veg,
        "description": menu_item.description,
        "has_sizes": menu_item.has_sizes,
        "has_customizations": menu_item.has_customizations,
    }


def _search_menu(db: Session, scope: OrderingScope, args: SearchMenuArgs) -> dict[str, Any]:
    """Delegates to the exact cascade a chat turn already runs
    (`rag._resolve_final_candidates`): vector first when an embedding is
    available, then keyword, fuzzy-name and popularity tiers when it is not
    or comes up empty. `ExtractedIntent` is normally built by parsing a
    sentence; here the tool's own typed fields (`is_veg`, `max_price`) ARE
    the parse, so it is constructed directly rather than re-deriving it from
    `args.query` text. `strict_budget=args.max_price is not None` mirrors the
    same rule the chat turn uses (`resolved_intent.budget is not None`) —
    an explicit ceiling is enforced, an absent one is not.
    """

    intent = ordering_rag.ExtractedIntent(
        intent="search",
        budget=args.max_price,
        diet=None if args.is_veg is None else ("veg" if args.is_veg else "non_veg"),
    )
    query_embedding = ordering_rag._embed_query(args.query)
    candidates, source, _ = ordering_rag._resolve_final_candidates(
        db,
        message=args.query,
        restaurant_id=scope.restaurant_id,
        restaurant_location_id=scope.restaurant_location_id,
        budget_limit=args.max_price,
        strict_budget=args.max_price is not None,
        intent=intent,
        query_embedding=query_embedding,
        limit=args.limit,
    )
    return {
        "source": source,
        "results": [_serialize_menu_item(candidate.menu_item) for candidate in candidates],
    }


def _get_dish(db: Session, scope: OrderingScope, args: GetDishArgs) -> dict[str, Any]:
    """Resolves a named dish exactly as the chat turn's dish-name guardrail
    would: run the same retrieval cascade `search_menu` uses, then read the
    same confidence signal (`classify_dish_reference`, via
    `apply_dish_name_guardrail`) rather than trusting whatever the cascade's
    fallback tiers surfaced. `verdict == "absent"` means nothing on this
    menu resembles the name closely enough to answer with, which this tool
    reports honestly instead of returning a distant fallback match under the
    customer's name.

    Deliberately does not gate on `settings.enable_dish_name_guardrail`: that
    flag controls whether the *existing chat pipeline* is allowed to erase a
    dish reference it dislikes, a decision this tool never makes since it
    never mutates a shared intent. Here the same threshold is used to decide,
    unconditionally, whether to report a match at all — the tool's entire
    purpose is that judgement, not a side effect gated behind flipping chat
    behaviour on.

    `source` gates the answer alongside `verdict`, not instead of it. The
    guardrail's own comment explains why: with no embedding to measure
    against (Ollama unreachable, or nothing vector-derived survived),
    `classify_dish_reference` reads `None` and returns `"unknown"` — evidence
    of nothing, not evidence of a match. Left ungated, a name nothing on the
    menu resembles would still return the cascade's own last-resort tier
    (`popular_fallback`/`emergency_db_fallback`, this branch's bestsellers
    regardless of what was asked) as if it were the dish asked for. Only the
    tiers that matched the name itself — `vector`, `keyword`, `fuzzy_name` —
    are allowed to answer "found".
    """

    intent = ordering_rag.ExtractedIntent(intent="dish_lookup", dish=args.name)
    query_embedding = ordering_rag._embed_query(args.name)
    candidates, source, _count = ordering_rag._resolve_final_candidates(
        db,
        message=args.name,
        restaurant_id=scope.restaurant_id,
        restaurant_location_id=scope.restaurant_location_id,
        budget_limit=None,
        strict_budget=False,
        intent=intent,
        query_embedding=query_embedding,
        limit=3,
    )
    verdict = ordering_rag.apply_dish_name_guardrail(
        intent,
        candidates,
        message=args.name,
        db=db,
        query_embedding=query_embedding,
        restaurant_id=scope.restaurant_id,
        restaurant_location_id=scope.restaurant_location_id,
    )
    name_matched_tier = source in {"vector", "keyword", "fuzzy_name"}
    if verdict == "absent" or not candidates or not name_matched_tier:
        return {"found": False, "confidence": verdict}
    return {"found": True, "confidence": verdict, **_serialize_menu_item(candidates[0].menu_item)}


def _view_cart(db: Session, scope: OrderingScope, args: ViewCartArgs) -> dict[str, Any]:
    """Re-resolves the browser's cart against this branch's real menu.

    Nothing here is priced independently of `resolve_menu_item_selection` —
    `unit_price`/`total_price` are its numbers, quantized the same way
    `orders.py` quantizes every line total, never a second formula.
    """

    menu_items = _load_branch_menu_items(db, scope)
    resolved = _resolve_cart_lines(menu_items, args.lines)

    lines_out: list[dict[str, Any]] = []
    subtotal = Decimal("0.00")
    for entry in resolved:
        total_price = _quantize(entry.selection.unit_price * entry.line.quantity)
        subtotal += total_price
        lines_out.append(
            {
                "menu_item_id": entry.menu_item.id,
                "name": entry.menu_item.name,
                "size_name": entry.selection.size_name,
                "quantity": entry.line.quantity,
                "unit_price": entry.selection.unit_price,
                "total_price": total_price,
            }
        )

    return {
        "lines": lines_out,
        "subtotal": _quantize(subtotal),
        # Never negative, never a count the caller can't already derive — but
        # spelled out anyway, so an agent surfacing "2 items dropped" doesn't
        # have to infer it by subtracting two lengths itself.
        "dropped_line_count": len(args.lines) - len(resolved),
    }


def _check_hours(db: Session, scope: OrderingScope, args: CheckHoursArgs) -> dict[str, Any]:
    """Delegates to the same two functions checkout itself calls
    (`restaurant_locations.get_location_fulfillment_status` for "now",
    `schedule_slot_is_available` for a named time) so a chat answer and the
    order path can never disagree about whether the kitchen is open. A bare
    "are you open" with no `fulfillment_type` answers for both delivery and
    pickup, since a customer asking that has not chosen one yet.
    """

    location = _load_branch_location(db, scope)
    if location is None:
        return {"branch_found": False}

    fulfillment_types: tuple[OrderFulfillmentType, ...] = (
        (args.fulfillment_type,)
        if args.fulfillment_type is not None
        else (OrderFulfillmentType.DELIVERY, OrderFulfillmentType.PICKUP)
    )

    # A clock time with no date is "today" in the branch's own timezone — the
    # only reading available from a bare time, and the same one a customer
    # means by "are you open at 9". If that has already passed today,
    # `schedule_slot_is_available`'s own "at least N minutes from now" check
    # reports that; this tool does not guess they meant tomorrow.
    scheduled_at: datetime | None = None
    if args.requested_time is not None:
        today_local = datetime.now(BUSINESS_TIMEZONE).date()
        scheduled_at = datetime.combine(today_local, args.requested_time, tzinfo=BUSINESS_TIMEZONE)

    windows: dict[str, dict[str, Any]] = {}
    for fulfillment_type in fulfillment_types:
        if scheduled_at is not None:
            available, reason = schedule_slot_is_available(
                location,
                fulfillment_type=fulfillment_type,
                scheduled_at=scheduled_at,
            )
        else:
            available, reason = get_location_fulfillment_status(
                location,
                fulfillment_type=fulfillment_type,
            )
        windows[fulfillment_type.value] = {"available": available, "reason": reason}

    return {
        "branch_found": True,
        "branch_open": location.is_open,
        "fulfillment": windows,
    }


def _price_quote(db: Session, scope: OrderingScope, args: PriceQuoteArgs) -> dict[str, Any]:
    """The one price path: builds an `OrderCreateRequest` from the injected
    branch and the cart's *branch-resolved* lines, then hands it to
    `orders.validate_order_draft` — the same function `POST /api/orders/validate`
    calls — for every figure. Nothing here adds, multiplies or rounds a price;
    that would be the second pricing path this codebase already avoids.

    Two refusals are handled here rather than left to raise, both about
    *whether* to ask the question, not about the arithmetic: no signed-in
    customer (`validate_order_draft` is customer-only), and a cart that
    resolves to nothing on this branch. A `validate_order_draft` refusal for
    any other reason (below minimum order, branch closed) is relayed as-is —
    its `detail` string, not a re-derived one.
    """

    if scope.customer is None:
        return {"priced": False, "reason": "Sign in to get an exact price."}

    menu_items = _load_branch_menu_items(db, scope)
    resolved = _resolve_cart_lines(menu_items, args.lines)
    if not resolved:
        return {"priced": False, "reason": "None of these items are on this branch's menu."}

    payload = OrderCreateRequest(
        restaurant_id=scope.restaurant_id,
        restaurant_location_id=scope.restaurant_location_id,
        fulfillment_type=args.fulfillment_type,
        items=[
            OrderCreateItem(
                menu_item_id=entry.menu_item.id,
                menu_item_size_id=entry.line.menu_item_size_id,
                quantity=entry.line.quantity,
                selected_options=[
                    OrderCreateItemCustomizationOption(
                        option_id=option.option_id,
                        quantity=option.quantity,
                        portion=option.portion,
                    )
                    for option in entry.line.selected_options
                ],
            )
            for entry in resolved
        ],
        # Pricing never reads this field — `_prepare_order_draft` stores it on
        # the order and never touches it computing a total — so a placeholder
        # satisfies the schema's presence check without inventing an address
        # the model was never given.
        delivery_address="Address pending",
    )
    try:
        quote = validate_order_draft(db, scope.customer, payload)
    except HTTPException as exc:
        return {"priced": False, "reason": exc.detail}

    return {
        "priced": True,
        "subtotal": quote.subtotal,
        "delivery_fee": quote.delivery_fee,
        "tax_amount": quote.tax_amount,
        "discount_amount": quote.discount_amount,
        "total_amount": quote.total_amount,
        "currency": quote.currency,
        "item_count": quote.item_count,
    }


def _restaurant_info(db: Session, scope: OrderingScope, args: RestaurantInfoArgs) -> dict[str, Any]:
    """Plain `RestaurantLocation` columns for the injected branch — no
    computation, no default invented for a column that is genuinely `None`
    (e.g. `phone_number`, `preparation_time_minutes`).
    """

    location = _load_branch_location(db, scope)
    if location is None:
        return {"branch_found": False}

    address_parts = [
        location.address_line_1,
        location.address_line_2,
        location.city,
        location.state,
        location.postal_code,
    ]
    return {
        "branch_found": True,
        "branch_name": location.branch_name,
        "address": ", ".join(part for part in address_parts if part),
        "phone_number": location.phone_number,
        "delivery_enabled": location.delivery_enabled,
        "pickup_enabled": location.pickup_enabled,
        "estimated_delivery_time_minutes": location.estimated_delivery_time,
        "estimated_pickup_time_minutes": location.estimated_pickup_time,
        "minimum_order_amount": location.minimum_order_amount,
        "delivery_fee": location.delivery_fee,
        "preparation_time_minutes": location.preparation_time_minutes,
    }


def _payment_options(db: Session, scope: OrderingScope, args: PaymentOptionsArgs) -> dict[str, Any]:
    """Read-only by construction, not just by convention: `get_enabled_payment_methods`
    takes only a location and returns a list, so there is nothing here that
    could initiate, authorise or capture anything even if asked to.
    """

    location = _load_branch_location(db, scope)
    if location is None:
        return {"branch_found": False, "payment_methods": []}
    return {
        "branch_found": True,
        "payment_methods": [method.value for method in get_enabled_payment_methods(location)],
    }


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

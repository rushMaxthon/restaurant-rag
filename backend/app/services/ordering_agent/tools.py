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

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, get_args, Callable, Sequence

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.enums import MenuItemPortion, OrderFulfillmentType
from app.models.menu_item import MenuItem
from app.models.menu_item_customization_group import MenuItemCustomizationGroup
from app.models.menu_item_size import MenuItemSize
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.schemas.order import (
    OrderCreateItem,
    OrderCreateItemCustomizationOption,
    OrderCreateRequest,
)
from app.services import rag as ordering_rag
from app.services import short_links
from app.services import restaurant_locations as branch_hours
from app.services.cart_actions import CartAction, ExistingCartLine, _matching_lines
from app.services.ordering_agent import order_channel, order_draft
from app.services.ordering_agent.verified_phone import (
    EmailAlreadyUsed,
    PhoneNotVerified,
    customer_for_verified_phone,
)
from app.models.enums import OrderScheduleType, PaymentMethod
from app.schemas.order import (
    OrderCreateItem,
    OrderCreateItemCustomizationOption,
    OrderCreateRequest,
)
from app.services.orders import create_order
from app.services.payments import create_payment_link
from app.services.menu_item_customizations import (
    ResolvedMenuItemSelection,
    SelectedCustomizationOptionInput,
    _get_active_customization_groups,
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
logger = logging.getLogger(__name__)
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

    @model_validator(mode="before")
    @classmethod
    def _nothing_is_none(cls, data):
        """"" and "null" in a field mean nothing, not the string "null".

        The model writes `"menu_item_size_id": ""` for a dish with no size —
        JSON's way of saying so, from a model that has seen a lot of JSON —
        and validation refused it as not a UUID, three times in one
        afternoon, each a wasted round or a lost add. No real argument is
        the empty string or the word null, so reading them as None loses
        nothing.
        """

        if not isinstance(data, dict):
            return data
        cleaned = dict(data)
        for key, value in data.items():
            field = cls.model_fields.get(key)
            if field is None or not isinstance(value, str):
                continue
            # Only where None is a value the field can hold. `query: str`
            # takes "" as itself — it is how "show me the menu" is asked.
            if value.strip().lower() in {"", "null", "none"} and type(None) in get_args(field.annotation):
                cleaned[key] = None
        return cleaned

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

    # Empty means "show me the menu": a browse of the branch, by category,
    # under the same veg and price filters. Requiring a query refused every
    # form of that request the model produced — none, "", "" again — and
    # the customer asking to see the menu got a line about their empty cart.
    query: str = Field(default="", max_length=500)
    is_veg: bool | None = Field(
        default=None,
        description="True for vegetarian only, False for non-veg only, omit for either.",
    )
    max_price: Decimal | None = Field(default=None, ge=0)
    limit: int = Field(default=5, ge=1, le=30)


class GetDishArgs(ToolArgs):
    """A dish named in conversation, resolved the way
    `apply_dish_name_guardrail`/`classify_dish_reference` already resolve one:
    by name and retrieval confidence against the branch's real menu, never by
    an id the model invented on the strength of a name it typed.

    `customization_groups` is always in the response now (fix round 3,
    2026-09-16) — every group that applies dish-wide, plus, once
    `menu_item_size_id` narrows it, that size's own groups too
    (`MenuItemCustomizationGroup.menu_item_size_id` scopes some groups to one
    specific size rather than the whole dish). `menu_item_size_id` is
    optional and purely a filter: step 1 of the customer's flow ("small or
    large, and what do they cost") is answered by `sizes` on the base
    response regardless of whether a size is named here; naming one only
    narrows which size-specific groups are included alongside the dish-wide
    ones. No price is computed by this narrowing — `price_quote` is where a
    size-plus-selections total comes from.
    """

    name: str = Field(min_length=1, max_length=255)
    menu_item_size_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "A size already chosen for this dish (from an earlier get_dish "
            "or search_menu result), if any. Narrows `customization_groups` "
            "to the dish-wide groups plus this size's own; omit to see only "
            "the dish-wide ones."
        ),
    )


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


class AddToCartArgs(CartLineArgs):
    """A dish the customer has fully or partially specified, to add.

    Field-for-field identical to `CartLineArgs` — an addition IS a cart line
    — kept as its own class rather than a bare alias so the registry has a
    distinct, self-documenting name for the tool's argument model, the same
    way `RestaurantInfoArgs`/`PaymentOptionsArgs` are distinct `NoArgs`
    subclasses above.
    """


class RemoveFromCartArgs(ToolArgs):
    """Which line to remove, identified the only way it honestly can be.

    There is no server-side cart, so there is no server-issued line id to
    hand back from an earlier call the way a database row would have one.
    `menu_item_id` must be an id the model read off a *previous* tool
    result (`view_cart`, `get_dish`, `search_menu`) — never one it invented
    from a name — and `existing_lines` is the browser's cart, echoed back
    exactly as `view_cart`/`price_quote` already require, so this handler can
    count how many of the customer's current lines that id actually matches.

    That count is the whole safety mechanism, reused rather than
    reinvented from `cart_actions.resolve_cart_actions`: zero matches means
    nothing to remove (silence, not an error), exactly one is unambiguous
    enough to apply, and more than one — the customer has this dish in more
    than one size or with different toppings — is exactly the ambiguity
    `cart_actions.py` already treats as destructive-so-always-proposed. A
    `menu_item_size_id` field was deliberately left off: matching stays at
    the same granularity `cart_actions._matching_lines` already uses (by
    `menu_item_id` alone), so "remove the pizza" behaves identically whether
    it came from the old regex tier or this tool, and two different sizes of
    the same dish correctly reads as ambiguous rather than as two unrelated
    items.
    """

    menu_item_id: uuid.UUID
    existing_lines: list[CartLineArgs] = Field(default_factory=list)


class SetQuantityArgs(ToolArgs):
    """Change one line's quantity — same identification rule as
    `RemoveFromCartArgs`, plus the target quantity itself. `quantity` here is
    the FINAL count the customer wants, not a delta, matching
    `extract_requested_quantity`'s own semantics ("make it two" means the
    line should read two afterwards).
    """

    menu_item_id: uuid.UUID
    quantity: int = Field(ge=1, le=99)
    existing_lines: list[CartLineArgs] = Field(default_factory=list)


class GoToCheckoutArgs(ToolArgs):
    """The customer is done adding and wants to pay. `lines` is the browser's
    cart, injected by the loop like `view_cart`'s, so an empty cart can be
    refused here rather than handing someone to a checkout with nothing in
    it. Nothing else: no address, no slot, no payment method — those are
    /checkout's questions, and the spec keeps this agent out of them.
    """

    lines: list[CartLineArgs] = Field(default_factory=list)


class OrderRequirementsArgs(NoArgs):
    """What is still needed before this order can be placed.

    The customer and the draft are scope, not arguments. The cart is
    injected — an order needs food before it needs an address, and without
    it this collected a name, an email and a delivery address for an empty
    cart while the customer's pizza was never added.
    """

    lines: list[CartLineArgs] = Field(default_factory=list)


class SaveOrderDetailsArgs(ToolArgs):
    """The contact details a customer just gave, as they said them.

    Every field optional because they arrive a sentence at a time. Each is
    validated before it is kept, and a refusal names the field so the agent
    can ask again for that one rather than starting over.

    This is the only tool that takes a customer's own words as data rather
    than as an id, and it is why: a name, an email and an address cannot be
    looked up from a menu. They are validated here and stored out of the
    model's reach — `order_requirements` afterwards reports only that a field
    is filled, never what is in it.
    """

    contact_name: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=32)
    contact_email: str | None = Field(default=None, max_length=320)
    delivery_address: str | None = Field(default=None, max_length=2000)
    fulfillment_type: OrderFulfillmentType | None = None


class PlaceOrderArgs(ToolArgs):
    """Place the order the conversation has been building.

    `lines` is the browser's cart, injected by the loop like `view_cart`'s —
    the model never retypes what is being bought. Nothing else: who it is
    for, where it goes and what it costs all come from the draft and the
    database, so there is no argument here a customer could use to order in
    somebody else's name or at somebody else's price.
    """

    lines: list[CartLineArgs] = Field(default_factory=list)


class ClearCartArgs(NoArgs):
    """Empty the cart. `NoArgs` on purpose — there is no field a model could
    fill in that would make this any less destructive, so none exists to
    tempt it. Always returns a `proposed` action; see `_clear_cart`.
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
    # The diet the reply pipeline already applies ("veg" / "non_veg" / None,
    # from `preference_diet_for_cache`). Carried here so the tools enforce
    # it deterministically: a vegetarian's search is veg-only and an add of
    # a non-veg dish is refused, whatever the model planned.
    diet: str | None = None
    # Which conversation this is. The order draft is keyed by it, so the
    # details a customer gives over several turns find each other again.
    # Caller-supplied like the rest of the scope: the model never chooses
    # whose details it is filling in.
    session_id: uuid.UUID | None = None
    # A phone number the CHANNEL has verified belongs to this person —
    # WhatsApp's, not one typed into a web chat. It is what lets an order be
    # placed without a sign-in; see `verified_phone`.
    verified_phone: str | None = None
    # Which app the customer is reaching this through. Identity is scoped by
    # it, so provisioning must be too.
    app_client_id: uuid.UUID | None = None

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
    """One line of `args.lines` that is real, at this branch, and fully
    specified — paired with the real row and price it resolved to.

    `groups` still carries every applicable optional group even though this
    line is complete: rule 2 of the second fix ("show the defaults for that
    size, and the price of size + defaults, in the same step") needs both the
    price (`selection.unit_price`, from `resolve_menu_item_selection`, never
    computed here) and what the customer is defaulting into, together — not
    a price now and a customization list on some later call.
    """

    line: CartLineArgs
    menu_item: MenuItem
    selection: ResolvedMenuItemSelection
    groups: list[MenuItemCustomizationGroup]


@dataclass(frozen=True, slots=True)
class CartLineChoice:
    """A real, branch-available line that is not yet complete enough to
    price — never confused with a line that does not exist here (Fix round 1,
    2026-09-15: reporting a real, sized dish as "not on this branch's menu"
    because no size was named is the same class of bug as Phase 1's
    Add-vs-Choose confusion). Carries the actual choices available so the
    agent can ask a real question rather than a vague one.

    `groups` holds every active group applicable given whatever size IS
    known (all of the item's, or just its item-level ones if the size
    itself is still unresolved) — not only the required-and-unmet ones —
    so a single response can carry "small or large?" alongside "keep the
    default (no extra toppings) or add some?" in one turn, per rule 2 of the
    fix. `needs_selection_group_ids` marks which of those actually block a
    price; the rest are optional and already complete as-is (rule 3: an
    optional group's default IS the empty selection, never invented as a
    specific pre-picked option that does not exist on this schema).
    """

    line: CartLineArgs
    menu_item: MenuItem
    needs_size: bool
    available_sizes: list[MenuItemSize]
    groups: list[MenuItemCustomizationGroup]
    needs_selection_group_ids: frozenset[uuid.UUID]


@dataclass(frozen=True, slots=True)
class CartLineResolution:
    resolved: list[ResolvedCartLine]
    needs_choice: list[CartLineChoice]
    # Silently absent for either of two reasons this API does not
    # distinguish, on purpose: `menu_item_id` does not belong to this branch
    # (an invented or foreign id — genuinely does not exist in this
    # conversation), or it belongs here but `resolve_menu_item_selection`
    # still refuses it for a reason that is not "needs a choice" (a
    # duplicate option, an inactive option id, a size named on an item that
    # does not have sizes). Both are the browser's cart having drifted from
    # the real menu in a way no follow-up question fixes, which is exactly
    # what "not on the menu" ought to mean — reserved for that now that
    # "needs a choice" has its own outcome.
    dropped_count: int


def _active_size(menu_item: MenuItem, menu_item_size_id: uuid.UUID | None) -> MenuItemSize | None:
    if menu_item_size_id is None:
        return None
    return next(
        (size for size in menu_item.sizes if size.id == menu_item_size_id and size.is_active),
        None,
    )


def _applicable_groups_and_unmet(
    menu_item: MenuItem, selected_size: MenuItemSize | None, line: CartLineArgs
) -> tuple[list[MenuItemCustomizationGroup], frozenset[uuid.UUID]]:
    """Every active group this line could be asked about, and which of those
    are *required* and still unsatisfied.

    Reuses `menu_item_customizations._get_active_customization_groups` — the
    same "item-level groups plus this size's own groups, deduped" rule
    `resolve_menu_item_selection` itself applies — rather than re-deriving
    which groups apply to a size. A group counts as unmet exactly the way
    that function would reject it: fewer selections than
    `max(min_selection, 1)` once `is_required` is set. An optional group is
    never unmet: rule 3 of the fix ("toppings default, they do not block")
    is already true of this schema without inventing a "default option"
    flag that does not exist on `MenuItemCustomizationOption` — an optional
    group's default IS the empty selection `resolve_menu_item_selection`
    already accepts. Optional groups are still returned in the first list,
    because the agent asking "keep the default or change it?" needs to know
    they exist at all.
    """

    active_groups = _get_active_customization_groups(menu_item, selected_size=selected_size)
    chosen_option_ids = {option.option_id for option in line.selected_options}
    unmet_ids: set[uuid.UUID] = set()
    for group in active_groups:
        if not group.is_required:
            continue
        active_option_ids = {option.id for option in group.options if option.is_active}
        if len(chosen_option_ids & active_option_ids) < max(group.min_selection, 1):
            unmet_ids.add(group.id)
    return active_groups, frozenset(unmet_ids)


def _resolve_cart_lines(
    menu_items: dict[uuid.UUID, MenuItem], lines: list[CartLineArgs]
) -> CartLineResolution:
    """The browser's word about its cart, sorted into the three outcomes a
    real dish can be in — never collapsing "needs a choice" into "not on the
    menu", which was Fix round 1's whole finding.

    Size is checked before customizations because an unresolved size makes
    size-specific groups unknowable (`_get_active_customization_groups`
    cannot tell which size's groups apply); item-level required groups are
    still checked and surfaced alongside a missing size, since those apply
    regardless of which size is eventually chosen and there is no reason to
    make the customer resolve one incomplete thing at a time when both are
    already knowable in one turn.
    """

    resolved: list[ResolvedCartLine] = []
    needs_choice: list[CartLineChoice] = []
    dropped_count = 0

    for line in lines:
        menu_item = menu_items.get(line.menu_item_id)
        if menu_item is None:
            dropped_count += 1
            continue

        selected_size = _active_size(menu_item, line.menu_item_size_id)
        needs_size = menu_item.has_sizes and selected_size is None
        groups, needs_selection_group_ids = _applicable_groups_and_unmet(menu_item, selected_size, line)

        if needs_size or needs_selection_group_ids:
            needs_choice.append(
                CartLineChoice(
                    line=line,
                    menu_item=menu_item,
                    needs_size=needs_size,
                    available_sizes=(
                        [size for size in menu_item.sizes if size.is_active] if needs_size else []
                    ),
                    groups=groups,
                    needs_selection_group_ids=needs_selection_group_ids,
                )
            )
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
            # Real and sized/customized correctly per the checks above, but
            # refused for some other reason (a duplicate option, an option
            # id that isn't active) — genuinely malformed rather than
            # "hasn't decided yet", so it stays silently dropped like an
            # unresolvable id, not promoted to a choice with nothing useful
            # to ask about.
            dropped_count += 1
            continue
        resolved.append(ResolvedCartLine(line=line, menu_item=menu_item, selection=selection, groups=groups))

    return CartLineResolution(resolved=resolved, needs_choice=needs_choice, dropped_count=dropped_count)


def _serialize_size(size: MenuItemSize) -> dict[str, Any]:
    return {"size_id": size.id, "name": size.name, "price": size.price}


def _default_option_ids_for_group(group: MenuItemCustomizationGroup) -> frozenset[uuid.UUID]:
    """Options marked as what a customer gets without changing anything
    (`MenuItemCustomizationOption.is_default`, migration 0061). Backfilled
    only for groups that are both required and single-choice — the one shape
    where the customer cannot end up with nothing, so there is an honest
    default to name (the cheapest active option, already priced into the
    base price). Every other group's options are all `is_default=False` by
    design, so this returns an empty set for them rather than guessing one.
    """

    return frozenset(option.id for option in group.options if option.is_active and option.is_default)


def _serialize_customization_group(
    group: MenuItemCustomizationGroup,
    *,
    needs_selection: bool,
    selected_option_ids: frozenset[uuid.UUID] = frozenset(),
) -> dict[str, Any]:
    """Fix round 3 (2026-09-16): `default_selection`/`at_default` used to be a
    placeholder ("optional groups default to empty, required groups have no
    default") because no per-option default existed on this schema. Migration
    `0061` added `MenuItemCustomizationOption.is_default`, backfilled for
    every required+single-choice group (the cheapest active option); this now
    reads that real column instead of guessing from `is_required` alone — a
    required group can genuinely have a marked default now, and reports it.
    """

    default_ids = _default_option_ids_for_group(group)
    return {
        "group_id": group.id,
        "title": group.title,
        "is_required": group.is_required,
        # True only when nothing satisfies this group yet AND it is
        # required — the one case where an answer cannot be deferred.
        "needs_selection": needs_selection,
        # The real `is_default` option ids for this group — empty for an
        # optional or multi-select group (migration 0061 never marks one
        # there, by design: a free choice is never pre-decided), one id for
        # a backfilled required+single group, and still empty for a
        # required group nobody ever ran the backfill against (honestly
        # reported as "no default", not guessed).
        "default_selection": sorted(default_ids, key=str),
        # What is actually selected on THIS line for this group right now —
        # empty for an untouched optional group (that emptiness IS the
        # default being accepted, stated out loud here rather than applied
        # silently), or the customer's real picks otherwise. `at_default`
        # compares the two sets directly, so it is equally true of an
        # optional group left untouched and a required group where the
        # customer's pick happens to match the marked default.
        "selected_option_ids": sorted(selected_option_ids, key=str),
        "at_default": frozenset(selected_option_ids) == default_ids,
        "min_selection": group.min_selection,
        "max_selection": group.max_selection,
        "selection_type": group.selection_type.value,
        "options": [
            {"option_id": option.id, "name": option.name, "extra_price": option.extra_price}
            for option in group.options
            if option.is_active
        ],
    }


def _selected_option_ids_for_group(
    group: MenuItemCustomizationGroup, line: CartLineArgs
) -> frozenset[uuid.UUID]:
    active_option_ids = {option.id for option in group.options if option.is_active}
    chosen_ids = {option.option_id for option in line.selected_options}
    return frozenset(chosen_ids & active_option_ids)


def _serialize_choice(entry: CartLineChoice) -> dict[str, Any]:
    """The real question the agent should ask, not a vague "couldn't price
    it": which sizes exist and what they cost, and every applicable
    customization group — required or not — with its options, prices, and
    whether it actually blocks a price or is just offered ("keep the default
    or change it?"). Everything rules 2 and 3 of the fix demand the tool
    hand back in one place.

    `needs_size`/`needs_customization` are reported as two separate booleans
    on purpose (second fix round): size and toppings are different questions
    asked at different steps of the flow the customer specified, and a
    single undifferentiated "needs a choice" cannot drive that — the caller
    needs to know *which* step it is still on.
    """

    return {
        "menu_item_id": entry.menu_item.id,
        "name": entry.menu_item.name,
        "quantity": entry.line.quantity,
        "needs_size": entry.needs_size,
        "needs_customization": bool(entry.needs_selection_group_ids),
        "available_sizes": [_serialize_size(size) for size in entry.available_sizes],
        "customization_groups": [
            _serialize_customization_group(
                group,
                needs_selection=group.id in entry.needs_selection_group_ids,
                selected_option_ids=_selected_option_ids_for_group(group, entry.line),
            )
            for group in entry.groups
        ],
    }


def _serialize_resolved_groups(entry: ResolvedCartLine) -> list[dict[str, Any]]:
    """The same "what's included, what's changeable" picture as
    `_serialize_choice`, but for a line that is already priced — step 2 of
    the flow ("that comes with X and Y, that's $N") needs the defaults and
    the price in the SAME response, not a price now and a customization list
    on a follow-up call.
    """

    return [
        _serialize_customization_group(
            group,
            needs_selection=False,
            selected_option_ids=_selected_option_ids_for_group(group, entry.line),
        )
        for group in entry.groups
    ]


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
        # Each size's own absolute price, never a delta off `price` above —
        # `get_dish` answering "small or large, and what do they cost" from
        # this one call is step 1 of the size -> defaults -> price flow the
        # customer specified, and must not need a second round trip.
        "sizes": (
            [_serialize_size(size) for size in menu_item.sizes if size.is_active]
            if menu_item.has_sizes
            else []
        ),
    }


def _serialize_catalog_group(group: MenuItemCustomizationGroup) -> dict[str, Any]:
    """A customization group as pure catalog fact — title, whether it is
    required, its selection type and min/max, every active option with its
    real `extra_price` and whether it is the marked default
    (`MenuItemCustomizationOption.is_default`, migration 0061). No price is
    computed here: `get_dish` answers "what could this be", never "what
    would THIS combination cost" — that number comes from `price_quote`
    (fix round 3, 2026-09-16), the one price path, same as everywhere else
    in this module.

    `menu_item_size_id` is the group's own scoping column, passed straight
    through: `None` means the group applies to the dish at every size, a
    real id means the schema itself restricts it to one specific size.
    """

    return {
        "group_id": group.id,
        "title": group.title,
        "is_required": group.is_required,
        "min_selection": group.min_selection,
        "max_selection": group.max_selection,
        "selection_type": group.selection_type.value,
        "menu_item_size_id": group.menu_item_size_id,
        "options": [
            {
                "option_id": option.id,
                "name": option.name,
                "extra_price": option.extra_price,
                "is_default": option.is_default,
            }
            for option in group.options
            if option.is_active
        ],
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

    if not args.query.strip():
        return _browse_menu(db, scope, args)

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


def _browse_menu(db: Session, scope: OrderingScope, args: SearchMenuArgs) -> dict[str, Any]:
    """The branch's menu with nothing in particular asked for.

    Straight from the rows, grouped by category — no embedding of an empty
    string, no vector search for nothing. Availability, branch scope and the
    veg and price filters are the same ones retrieval applies; the category
    list rides along so the answer can say what kinds of thing there are
    before naming dishes.
    """

    stmt = (
        select(MenuItem)
        .where(
            MenuItem.restaurant_location_id == scope.restaurant_location_id,
            MenuItem.is_available.is_(True),
        )
        .order_by(MenuItem.category, MenuItem.name)
    )
    if args.is_veg is not None:
        stmt = stmt.where(MenuItem.is_veg.is_(args.is_veg))
    if args.max_price is not None:
        stmt = stmt.where(MenuItem.price <= args.max_price)
    rows = list(db.scalars(stmt.limit(200)))
    categories: list[str] = []
    for row in rows:
        if row.category not in categories:
            categories.append(row.category)
    return {
        "source": "browse",
        "categories": categories,
        "results": [_serialize_menu_item(row) for row in rows[: args.limit]],
    }


def _find_exact_name_match(db: Session, scope: OrderingScope, name: str) -> MenuItem | None:
    """A case-insensitive, exact match against this branch's own
    `MenuItem.name` — the strongest signal a customer can give, stronger
    than any embedding distance (fix round 4, 2026-09-16).

    Why semantic similarity was the wrong tool for this: the document side
    of the vector index is not the name alone —
    `app/tasks/embed.py::_format_embedding_text` embeds
    `"{name} | {cuisine} | {category} | {description} | {price} | {veg_label}"` —
    while the query side embeds only what the customer typed
    (`_embed_query`, asymmetric document/query embedding). For most dishes
    the name still dominates the resulting vector closely enough to clear
    `DISH_NAME_MAX_DISTANCE`, but for some it does not, and a customer who
    typed the dish's real name verbatim was told it does not exist. An exact
    text match sidesteps that dilution entirely — checked first, against
    the database, before any embedding is computed or any cascade tier
    runs.

    `.limit(1)` guards against `MultipleResultsFound` if two rows at a
    branch ever share a name; picking one deterministically over raising is
    consistent with this module degrading rather than erroring wherever an
    id or a name does not resolve cleanly.
    """

    return db.scalars(
        select(MenuItem)
        .where(
            MenuItem.restaurant_id == scope.restaurant_id,
            MenuItem.restaurant_location_id == scope.restaurant_location_id,
            MenuItem.is_available.is_(True),
            func.lower(MenuItem.name) == name.strip().lower(),
        )
        .limit(1)
    ).first()


def _build_dish_result(menu_item: MenuItem, *, confidence: str, args: GetDishArgs) -> dict[str, Any]:
    result = {"found": True, "confidence": confidence, **_serialize_menu_item(menu_item)}
    # An id that doesn't resolve (foreign, inactive, invented) degrades to
    # `None`, which `_get_active_customization_groups` already treats the
    # same as "no size given" — dish-wide groups only, never an exception.
    selected_size = _active_size(menu_item, args.menu_item_size_id)
    applicable_groups = _get_active_customization_groups(menu_item, selected_size=selected_size)
    result["customization_groups"] = [_serialize_catalog_group(group) for group in applicable_groups]
    return result


def dishes_matching_words(
    db: Session,
    scope: OrderingScope,
    phrase: str,
    *,
    is_veg: bool | None = None,
    limit: int = 8,
) -> list[tuple[str, str]]:
    """Every dish at this branch whose NAME contains all of these words.

    Text, not similarity. `get_dish` answers with one dish and reports
    `confidence: "named"` for a near miss as readily as for the real thing,
    which is how "cheese pizza" became Cheese Burst Pizza and "pizza"
    became Build Your Own Pizza. When money is about to be spent, the
    question "which dishes could they have meant?" has to be answered from
    the menu's own words.

    Returns (menu_item_id, name) pairs, alphabetically, capped — a customer
    asked to choose between fifteen dishes has not been helped.
    """

    words = [w for w in "".join(
        c if c.isalnum() or c.isspace() else " " for c in phrase.lower()
    ).split() if len(w) > 1]
    if not words:
        return []
    stmt = select(MenuItem).where(
        MenuItem.restaurant_location_id == scope.restaurant_location_id,
        MenuItem.is_available.is_(True),
    )
    if is_veg is not None:
        # A vegetarian asking for pizza wants the vegetarian pizzas. The
        # filter belongs in the query, not in whatever the model remembers.
        stmt = stmt.where(MenuItem.is_veg.is_(is_veg))
    for word in words:
        stmt = stmt.where(MenuItem.name.ilike(f"%{word}%"))
    rows = list(db.scalars(stmt.order_by(MenuItem.name).limit(limit)))
    return [(str(row.id), row.name) for row in rows]


def prices_of(
    db: Session,
    scope: OrderingScope,
    *,
    names: Sequence[str] = (),
    menu_item_id: str | None = None,
) -> list[dict[str, Any]]:
    """The price rows of dishes already in front of the customer.

    For "how much" asked about a dish just named or a list just read out. The
    names are OURS — they were written down when the list was said — so they
    are matched exactly against this branch's `menu_items.name`, one query,
    and returned in the order asked for. A sized dish carries each size's own
    absolute price, the same as `get_dish` reports it, because a sized dish
    has no single figure to quote (see `describe_single_dish`).

    Nothing here is a search: a name the branch does not sell under exactly
    that name is simply absent from the answer.
    """

    stmt = select(MenuItem).where(
        MenuItem.restaurant_location_id == scope.restaurant_location_id,
        MenuItem.is_available.is_(True),
    )
    if menu_item_id:
        try:
            stmt = stmt.where(MenuItem.id == uuid.UUID(str(menu_item_id)))
        except ValueError:
            return []
    elif names:
        stmt = stmt.where(func.lower(MenuItem.name).in_([n.strip().lower() for n in names if n]))
    else:
        return []
    rows = list(db.scalars(stmt))
    by_name = {row.name.strip().lower(): row for row in rows}
    ordered = (
        rows if menu_item_id
        else [by_name[n.strip().lower()] for n in names if n and n.strip().lower() in by_name]
    )
    return [
        {
            "name": row.name,
            "price": row.price,
            "has_sizes": bool(row.has_sizes),
            "sizes": (
                [{"size_id": str(size.id), "name": size.name, "price": size.price}
                 for size in row.sizes if size.is_active]
                if row.has_sizes
                else []
            ),
        }
        for row in ordered
    ]


def cheapest_dishes(
    db: Session,
    scope: OrderingScope,
    *,
    is_veg: bool | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """The least expensive dishes AT THIS BRANCH, cheapest first.

    `price` ordered, and scoped to `restaurant_location_id` like everything
    else here — a branch's prices are its own, and answering "what is your
    cheapest" with another branch's menu would be wrong in the one way a
    price question cannot afford to be.

    Live, before this: "what's your cheapest item" was searched for as a dish
    name and answered "I could not find cheapest item on the menu."
    """

    query = select(MenuItem).where(
        MenuItem.restaurant_location_id == scope.restaurant_location_id,
        MenuItem.is_available.is_(True),
    )
    if is_veg is not None:
        query = query.where(MenuItem.is_veg.is_(is_veg))
    rows = db.scalars(query.order_by(MenuItem.price.asc(), MenuItem.name).limit(limit))
    return [
        {"name": row.name, "price": f"{row.price:.2f}", "has_sizes": bool(row.has_sizes)}
        for row in rows
    ]


def dishes_to_suggest(
    db: Session,
    scope: OrderingScope,
    *,
    in_cart: Sequence[Any] = (),
    is_veg: bool | None = None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """A few things to offer a customer who wants more but has not said what.

    What people actually order here — bestsellers first, then popularity —
    from the parts of the menu this cart does not already cover: somebody
    holding a pizza is offered a drink and a dessert, not another pizza.
    Rows, ordered by the branch's own columns; nothing here is a guess about
    taste.
    """

    base = select(MenuItem).where(
        MenuItem.restaurant_location_id == scope.restaurant_location_id,
        MenuItem.is_available.is_(True),
    )
    if is_veg is not None:
        base = base.where(MenuItem.is_veg.is_(is_veg))
    ids = [i for i in in_cart if i]
    if ids:
        base = base.where(MenuItem.id.not_in(ids))
    order = (
        MenuItem.is_bestseller.desc(),
        MenuItem.popularity_score.desc().nullslast(),
        MenuItem.name,
    )
    def spread(found: Sequence[MenuItem]) -> list[MenuItem]:
        """At most one per section, so three suggestions are three ideas.

        Ordered by popularity alone they came back as three main courses to
        a customer who already had a pizza. A waiter offers a drink, a side
        and something sweet — variety is the suggestion.
        """

        picked: list[MenuItem] = []
        seen_sections: set[str] = set()
        for row in found:
            section = row.category or ""
            if section in seen_sections:
                continue
            seen_sections.add(section)
            picked.append(row)
            if len(picked) == limit:
                break
        return picked

    # Enough rows that one per section can still fill the list.
    reach = max(limit * 8, 24)
    rows: list[MenuItem] = []
    if ids:
        covered = [
            c
            for c in db.scalars(
                select(MenuItem.category).where(MenuItem.id.in_(ids)).distinct()
            )
            if c
        ]
        if covered:
            rows = spread(
                list(db.scalars(base.where(MenuItem.category.not_in(covered)).order_by(*order).limit(reach)))
            )
    if not rows:
        rows = spread(list(db.scalars(base.order_by(*order).limit(reach))))
    return [{"name": row.name, "price": f"{row.price:.2f}"} for row in rows]


def menu_categories(db: Session, scope: OrderingScope) -> list[str]:
    """The names of the categories this branch actually sells.

    Given to the reading so a customer's own word for a kind of food can be
    matched to one of them by meaning. Live: "Do you have some drink?" was
    matched by substring against a category called Beverages, matched
    nothing, and fell through to the first eight dishes on the menu — eight
    appetizers, in answer to a question about drinks.
    """

    rows = db.scalars(
        select(MenuItem.category)
        .where(
            MenuItem.restaurant_location_id == scope.restaurant_location_id,
            MenuItem.is_available.is_(True),
            MenuItem.category.is_not(None),
        )
        .distinct()
        .order_by(MenuItem.category)
    )
    return [c for c in rows if c]


#: A section is a complete thing and its size belongs to the menu, not to
#: whoever asked. Still bounded, because one pathological category should not
#: become a thousand-line message: past this the caller says how many more.
WHOLE_SECTION_CAP = 40

#: Words that carry no meaning when deciding whether a phrase names a section.
#: Not a vocabulary — every one of these is grammar, and the SECTION names
#: themselves come from the menu, so no word here decides what anything means.
_SECTION_FILLER = {
    "and", "the", "any", "some", "you", "have", "got", "show", "see", "want",
    "like", "give", "for", "with", "your", "our", "all", "what", "whats",
    "which", "there", "that", "this", "please", "menu", "list", "options",
    "option", "item", "items", "dish", "dishes", "food", "section", "category",
    "order", "get", "can", "could", "would", "about", "tell", "know", "need",
}


def _section_words(text: str) -> frozenset[str]:
    """The words of a phrase that decide whether it names a section.

    Singularised the same way `dishes_to_show` does it, so "noodles" reaches
    the "Noodles" section and "soups" reaches "Soup".
    """

    words = []
    for raw in "".join(c if c.isalnum() or c.isspace() else " " for c in text.lower()).split():
        if len(raw) < 3 or raw in _SECTION_FILLER:
            continue
        words.append(raw[:-1] if len(raw) > 4 and raw.endswith("s") and not raw.endswith("ss") else raw)
    return frozenset(words)


def category_named_exactly(phrase: str, categories: list[str]) -> str | None:
    """The section this phrase names, or None if it names none of them.

    A word SET, not a substring. The difference is the whole rule:

    * "Corn Dhokla" names the nine-dish section of that name. Dish-name
      matching found four of those nine — a strict subset — and because it
      found SOMETHING the section tier below it never ran, so five dishes were
      invisible to anyone who asked for them by section.
    * "Manchow Soup" names a dish, and its words are not the Soup section's
      words. Reading it as the section would answer with all three soups and
      throw away the word that said which one.
    * "dhokla" is a word inside one section's name and inside dish names in
      several others. Reading it as "Corn Dhokla" would hide the rest of the
      dhoklas this branch sells, so a partial word names nothing.
    * "taste" belongs to four sections at this branch. Choosing one would be a
      guess, and nothing here guesses.

    The sections come from the menu, so a restaurant that adds a Pizza section
    answers "pizza" with its pizzas the moment it does, with no code change.
    """

    wanted = _section_words(phrase)
    if not wanted:
        return None
    matches = [
        category
        for category in categories
        if category and _section_words(category) == wanted
    ]
    return matches[0] if len(matches) == 1 else None


#: How many sections fit in a message somebody reads on a phone. Past this the
#: offer says how many more there are, because stopping silently is a claim
#: that the menu ends there.
_SECTIONS_OFFERED = 18


def branch_sections(db: Session, scope: OrderingScope) -> list[str]:
    """This branch's section names, for when there is nothing else to say.

    Deliberately NOT used by `dishes_to_show`: which section a customer means
    is decided by the reading, from this same list, and re-fetching it on every
    menu question would be a query per turn to rediscover something already
    known. This is the give-up path, which is rare and has nothing else left.
    """

    try:
        rows = db.scalars(
            select(MenuItem.category)
            .where(
                MenuItem.restaurant_location_id == scope.restaurant_location_id,
                MenuItem.is_available.is_(True),
                MenuItem.category.is_not(None),
            )
            .distinct()
        )
        return [section for section in rows if section]
    except Exception:  # noqa: BLE001
        # This is already the last thing the turn has to say. A database that
        # will not answer must cost the customer a better sentence, never the
        # reply itself — and the caller keeps its own words when this is empty.
        logger.warning("Could not read this branch's sections for the give-up reply", exc_info=True)
        return []


def offer_of_sections(sections: list[str | None]) -> str | None:
    """What we serve, as a question the customer can actually answer.

    The sentence this replaces asked them to try again unaided — "tell me the
    dish you would like" — to somebody who had just sent something we could not
    read. Offering 136 dish names instead would be no better; offering the 21
    sections is what a restaurant hands across the table, and for the same
    reason: nobody holds 136 names in their head.

    Numbered, one per line, because a comma-joined line of 18 sections is a
    paragraph to read and nothing to answer: "Salads, Curry, Rice, Beverages,
    Combo, Main Course, Appetizer, Pizza, ..." asks somebody to type a name
    they have to pick out of prose first. A number is the shortest possible
    answer and the list carries its own numbering, so both "2" and "Curry"
    reach the same section — see `sections_offered` for the half that reads
    the answer.

    None when the menu has no sections, so the caller keeps its own words
    rather than introducing a list with nothing in it.
    """

    shown = sections_offered(sections)
    if not shown:
        return None
    listed = "\n".join(f"{position}. {name}" for position, name in enumerate(shown, 1))
    total = len({(s or "").strip() for s in sections if (s or "").strip()})
    more = f"\n\n...and {total - len(shown)} more." if total > len(shown) else ""
    return (
        f"Here is what we serve:\n{listed}{more}\n\n"
        "Which one would you like to see? Reply with the number or the name."
    )


def sections_offered(sections: list[str | None]) -> list[str]:
    """The sections `offer_of_sections` will actually list, in that order.

    Split out because the answer has to be read against exactly what was
    shown: the caller records THIS list, so "2" means the second line the
    customer read rather than the second row the query returned.
    """

    seen: list[str] = []
    for section in sections:
        name = (section or "").strip()
        if name and name not in seen:
            seen.append(name)
    return seen[:_SECTIONS_OFFERED]


def dishes_to_show(
    db: Session,
    scope: OrderingScope,
    phrase: str,
    *,
    is_veg: bool | None = None,
    limit: int = 8,
    category: str | None = None,
    max_price: Decimal | None = None,
    report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Dishes to read out to a customer: name, price, and whether veg.

    `report`, when given, is filled with `found_by`: "named" when the words
    matched dish names, "category" a section, "close" a shorter form of the
    phrase, "budget" when a price ceiling is what selected them, "over_budget"
    when nothing came under that ceiling, and "fallback" when nothing matched
    and these are simply the branch's menu. The caller needs it to write a
    true sentence above the list — "Here is what we have" over the whole menu,
    to somebody who asked for a dish this branch does not sell, reads as
    having been ignored.

    `max_price` is a ceiling, and it narrows the BASE query rather than being
    a search of its own: a customer who says "paneer under 200" means both
    things at once, and every branch below — by name, by section, by a shorter
    phrase, or the whole menu — inherits it for free. It arrives as a number
    the reading extracted, never parsed out of the words here, so no list of
    words like "under" or "cheap" decides what a message meant.

    By name when the word they used is a dish's word ("pizza"), and by the
    branch's whole menu when it is not ("the menu", "something vegetarian").
    Either way the rows answer, because a question about the menu is not a
    search problem — semantic retrieval answered "do you have pizza with
    extra cheese" with Coconut Ice Cream, having matched dishes that take
    extras rather than the word the customer said.
    """

    at_this_branch = select(MenuItem).where(
        MenuItem.restaurant_location_id == scope.restaurant_location_id,
        MenuItem.is_available.is_(True),
    )
    if is_veg is not None:
        at_this_branch = at_this_branch.where(MenuItem.is_veg.is_(is_veg))
    # Kept separately from `stmt` so the over-budget answer below can reach
    # the menu the customer priced themselves out of.
    stmt = at_this_branch
    if max_price is not None:
        stmt = stmt.where(MenuItem.price <= max_price)
    words = [
        # Singular, because a menu is written in the singular and customers
        # do not order one pizza: "vegetarian pizzas" matched no dish called
        # "pizzas" and no category called "pizzas" either, and answered with
        # the whole vegetarian menu.
        w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w
        for w in "".join(c if c.isalnum() or c.isspace() else " " for c in phrase.lower()).split()
        if len(w) > 2
    ]
    # A section named exactly, BEFORE dish names — because dish-name matching
    # answers a section with a strict subset of it and then stops. "Corn
    # Dhokla" matched four dish names out of that section's nine, and the
    # section tier further down never ran, so five dishes this branch sells
    # were invisible to anyone who asked for them by name of section. Read out
    # complete, because a section's size is a property of the menu and not of
    # how many rows a caller felt like asking for.
    # The section comes from the READING, which was handed this branch's own
    # list of them — so "some drink" reaches Beverages, which no amount of
    # string matching gets to. All that is decided here is whether the phrase
    # names that section and nothing narrower.
    section = category_named_exactly(phrase, [category] if category else [])
    if section is not None:
        rows = list(
            db.scalars(
                stmt.where(MenuItem.category == section)
                .order_by(MenuItem.name)
                .limit(WHOLE_SECTION_CAP + 1)
            )
        )
        if rows:
            if report is not None:
                report["found_by"] = "section"
                report["section"] = section
            return [
                {"name": row.name, "price": f"{row.price:.2f}", "is_veg": bool(row.is_veg),
                 # So a read-back of ONE dish knows not to quote a single
                 # price for a dish that has three. A column on the row,
                 # so it costs no query.
                 "has_sizes": bool(row.has_sizes)}
                for row in rows
            ]

    named = stmt
    for word in words:
        named = named.where(MenuItem.name.ilike(f"%{word}%"))
    rows = list(db.scalars(named.order_by(MenuItem.name).limit(limit))) if words else []
    if not rows and category:
        # No dish by that name, so the section they meant. Named by the
        # reading from this branch's own list, so it is matched exactly
        # rather than searched for — "some drink" is Beverages, which no
        # amount of string matching gets to.
        rows = list(
            db.scalars(stmt.where(MenuItem.category == category).order_by(MenuItem.name).limit(limit))
        )
    found_by = "named" if rows else ""
    if not rows and len(words) > 1:
        # The words that DO name something here, dropped one at a time from
        # the end — BEFORE the section below, because the words are more
        # specific than the section they belong to. "Tom Yum Soup" at a
        # branch selling Tom Yum Goong matched no dish name at all; read as
        # the Soups section it answered with all eight soups, throwing away
        # the two words that said which soup. "tom yum" finds the three.
        for keep in range(len(words) - 1, 0, -1):
            narrowed = stmt
            for word in words[:keep]:
                narrowed = narrowed.where(MenuItem.name.ilike(f"%{word}%"))
            rows = list(db.scalars(narrowed.order_by(MenuItem.name).limit(limit)))
            if rows:
                found_by = "close"
                break
    if not rows:
        # Nothing in the names. The section, then the menu itself — both of
        # which are still the rows, never a guess about what they meant.
        by_category = stmt
        for word in words:
            by_category = by_category.where(MenuItem.category.ilike(f"%{word}%"))
        rows = list(db.scalars(by_category.order_by(MenuItem.name).limit(limit))) if words else []
        found_by = "category" if rows else ""
    if not rows:
        rows = list(db.scalars(stmt.order_by(MenuItem.category, MenuItem.name).limit(limit)))
        # With a ceiling set, these rows are everything under it — a real
        # answer to what was asked, not the shrug that "fallback" describes.
        found_by = "budget" if max_price is not None else "fallback"
    if not rows and max_price is not None:
        # Nothing at this branch comes in under their figure. The cheapest
        # dishes are the useful reply and the caller says the budget was
        # missed, which beats an empty list that reads as no menu at all.
        rows = list(db.scalars(at_this_branch.order_by(MenuItem.price).limit(limit)))
        found_by = "over_budget"
    listed = [
        {"name": row.name, "price": f"{row.price:.2f}", "is_veg": bool(row.is_veg),
                 # So a read-back of ONE dish knows not to quote a single
                 # price for a dish that has three. A column on the row,
                 # so it costs no query.
                 "has_sizes": bool(row.has_sizes)}
        for row in rows
    ]
    if report is not None:
        report["found_by"] = found_by
    return listed


def _get_dish(db: Session, scope: OrderingScope, args: GetDishArgs) -> dict[str, Any]:
    """Resolves a named dish, exact name first, then exactly as the chat
    turn's dish-name guardrail would.

    Fix round 4 (2026-09-16): an exact (case-insensitive) match against
    `MenuItem.name` at this branch short-circuits straight to `found: True,
    confidence: "named"` — see `_find_exact_name_match` for why semantic
    similarity is the wrong tool to route an exact name through. This
    resolved a real defect: dishes named straight out of `menu_items.name`
    (~20% of a sample at one branch) were coming back `absent`, and several
    more resolved with `confidence: "unknown"` despite existing, on-menu
    dishes — a verdict Task 3's mutation tools gate on, so an exact name
    reading as `unknown` would never produce an `applied` action. Neither
    failure is possible once an exact match is checked first; the cascade
    below is now reached only for a name that is NOT an exact match (a
    near-miss, a typo, a partial name), where its existing behaviour is
    unchanged byte for byte — this fix adds a path in front of it, it does
    not alter it.

    The cascade path (unchanged): run the same retrieval cascade
    `search_menu` uses, then read the same confidence signal
    (`classify_dish_reference`, via `apply_dish_name_guardrail`) rather than
    trusting whatever the cascade's fallback tiers surfaced. `verdict ==
    "absent"` means nothing on this menu resembles the name closely enough
    to answer with, which this tool reports honestly instead of returning a
    distant fallback match under the customer's name.

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

    `customization_groups` is always populated (fix round 3) via
    `_build_dish_result`, shared by both this exact-match path and the
    cascade path below so neither can drift from the other's shape.
    """

    exact_match = _find_exact_name_match(db, scope, args.name)
    if exact_match is not None:
        return _build_dish_result(exact_match, confidence="named", args=args)

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

    matched_item = candidates[0].menu_item

    # They named the SECTION, not a dish in it. Costs no query: the row that
    # came back says which section it belongs to, and the words asked for are
    # compared against that.
    #
    # Live, this is what it prevents, with nobody having confirmed anything:
    #
    #     >>> Tandoori Starter
    #         Added 1 x Paneer Pahadi Tikka Dry to your order. Anything else?
    #
    # Retrieval was not wrong — Paneer Pahadi Tikka Dry IS a Tandoori Starter,
    # and the guardrail measured it as a confident match, which it is. The
    # mistake is answering "show me the Tandoori Starters" with one of them.
    # `section` is returned so the caller can show the section rather than
    # telling somebody who named a real part of the menu that we do not have it.
    section = category_named_exactly(args.name, [getattr(matched_item, "category", None)])
    if section is not None:
        return {"found": False, "confidence": "section", "section": section}

    return _build_dish_result(matched_item, confidence=verdict, args=args)


def _view_cart(db: Session, scope: OrderingScope, args: ViewCartArgs) -> dict[str, Any]:
    """Re-resolves the browser's cart against this branch's real menu.

    Nothing here is priced independently of `resolve_menu_item_selection` —
    `unit_price`/`total_price` are its numbers, quantized the same way
    `orders.py` quantizes every line total, never a second formula.

    Fix round 1 (2026-09-15): a sized dish with no size chosen used to be
    indistinguishable from a dish that plain does not exist here — both
    vanished into the same dropped-line count. `needs_choice` is now its own
    key, separate from `lines`, carrying the sizes/groups an agent needs to
    ask a real question. `subtotal` only ever totals `lines` — the priced,
    complete ones — never anything from `needs_choice`.

    Fix round 2 (2026-09-15): each priced line also carries
    `customization_groups` — step 2 of the customer's specified flow ("that
    comes with X and Y, that's $N") needs the price AND what it defaults to
    in the one response, not a price now and a separate call to learn what
    was included.
    """

    menu_items = _load_branch_menu_items(db, scope)
    resolution = _resolve_cart_lines(menu_items, args.lines)

    lines_out: list[dict[str, Any]] = []
    subtotal = Decimal("0.00")
    for entry in resolution.resolved:
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
                "customization_groups": _serialize_resolved_groups(entry),
            }
        )

    return {
        "lines": lines_out,
        "needs_choice": [_serialize_choice(entry) for entry in resolution.needs_choice],
        "subtotal": _quantize(subtotal),
        # Genuinely absent from this branch or otherwise malformed — see
        # `CartLineResolution.dropped_count`. Never counts a `needs_choice`
        # line: that one is real and answerable, just not priced yet.
        "dropped_line_count": resolution.dropped_count,
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

    Fix round 1 (2026-09-15): a cart with three complete lines and one that
    needs a size used to refuse the whole quote — "None of these items are on
    this branch's menu" was simply false about the three that were. Pricing
    now runs on `resolution.resolved` alone; `needs_choice` rides alongside
    every response (priced or not) so the caller always has whatever is left
    to ask about. Only a cart with NO complete line at all fails to produce a
    `priced: True` response, because `validate_order_draft`/`OrderCreateRequest`
    both require at least one item — there is no number to delegate to.
    """

    if scope.customer is None:
        return {"priced": False, "reason": "Sign in to get an exact price.", "needs_choice": []}

    menu_items = _load_branch_menu_items(db, scope)
    resolution = _resolve_cart_lines(menu_items, args.lines)
    needs_choice_out = [_serialize_choice(entry) for entry in resolution.needs_choice]

    if not resolution.resolved:
        reason = (
            "Some items need a choice before they can be priced."
            if resolution.needs_choice
            else "None of these items are on this branch's menu."
        )
        return {"priced": False, "reason": reason, "needs_choice": needs_choice_out}

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
            for entry in resolution.resolved
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
        return {"priced": False, "reason": exc.detail, "needs_choice": needs_choice_out}

    return {
        "priced": True,
        "subtotal": quote.subtotal,
        "delivery_fee": quote.delivery_fee,
        "tax_amount": quote.tax_amount,
        "discount_amount": quote.discount_amount,
        "total_amount": quote.total_amount,
        "currency": quote.currency,
        "item_count": quote.item_count,
        # Priced ignores these lines entirely (they are not in `items`
        # above) — surfaced so a mixed cart's response still tells the
        # agent there is more to ask about, per rule 4 of the fix.
        "needs_choice": needs_choice_out,
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


def reference_for_next_slot(scheduled_for, *, now=None):
    """Where to count the next available slot from.

    The time the customer asked for, when it is still ahead — somebody asking
    for tomorrow lunch is not helped by being offered this morning. But a time
    already gone by is not a reference, it is history: measured from a stale
    11:00 at 14:57, the "nearest" slot was 11:30, which the validator then
    refused as being in the past, and the customer was told no to the very
    time we had just offered them.

    So it is the LATER of what they asked for and now.
    """

    from datetime import datetime

    current = now or datetime.now(branch_hours.BUSINESS_TIMEZONE)
    if scheduled_for is None:
        return current
    if scheduled_for.tzinfo is None:
        scheduled_for = scheduled_for.replace(tzinfo=branch_hours.BUSINESS_TIMEZONE)
    return max(scheduled_for, current)


def _parse_iso(value: str | None):
    """An ISO datetime with a zone, or None — the draft only ever stores it
    that way (`order_draft._parse_when`), so anything else is not ours."""

    if not value:
        return None
    from datetime import datetime

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _draft_for(scope: OrderingScope):
    """The draft, with everything already known filled in.

    A signed-in customer's account supplies most of it. On a channel that
    verified the caller's number, that number is a detail too — asking a
    customer on WhatsApp for the phone they are typing from is the kind of
    question that makes software feel unaware of itself.
    """

    draft = order_draft.seed_from_profile(order_draft.load(scope.session_id), scope.customer)
    if scope.verified_phone:
        # The channel's number wins over the account's. Meta verified this
        # one and it is written the way an order is written; an account
        # provisioned before that was true holds the plus-less wa_id, and
        # seeding from it put '916353100362' on the order, which the schema
        # reads as a malformed local number and refuses.
        draft.contact_phone = scope.verified_phone
    return draft


def _order_requirements(
    db: Session, scope: OrderingScope, args: OrderRequirementsArgs
) -> dict[str, Any]:
    """What is known, what is missing, and whether this order could be placed.

    Reports the NAMES of the details held, never their values. A customer's
    address belongs on the order and in the kitchen ticket, not in a model's
    context window on every later turn — see `order_draft`.
    """

    if scope.session_id is None:
        return {"outcome": "no_session"}
    # An order needs food before it needs an address. Live, this collected a
    # name, an email and a delivery address for an empty cart, and the
    # customer never noticed their pizza had not been added — the agent had
    # stopped talking about food and started taking details.
    if not args.lines:
        return {"outcome": "empty_cart"}
    draft = _draft_for(scope)
    # Asking is what starts the collection. Recorded so the next turn knows
    # what this conversation is in the middle of.
    if draft.missing_fields():
        stored = order_draft.load(scope.session_id)
        stored.collecting = True
        order_draft.save(scope.session_id, stored)
    return {
        "outcome": "requirements",
        "identified": scope.customer is not None,
        "have": draft.known_fields(),
        "missing": draft.missing_fields(),
        "fulfillment_type": draft.fulfillment_type,
        "ready_to_place": draft.is_complete and scope.customer is not None,
    }


def _save_order_details(
    db: Session, scope: OrderingScope, args: SaveOrderDetailsArgs
) -> dict[str, Any]:
    """Keep what the customer just gave, and say what is still wanted."""

    if scope.session_id is None:
        return {"outcome": "no_session"}
    draft = order_draft.load(scope.session_id)
    draft, problems = order_draft.remember(
        draft,
        contact_name=args.contact_name,
        contact_phone=args.contact_phone,
        contact_email=args.contact_email,
        delivery_address=args.delivery_address,
        fulfillment_type=args.fulfillment_type.value if args.fulfillment_type else None,
    )
    order_draft.save(scope.session_id, draft)
    # Seeded only for the report: what the account holds counts as known, but
    # it is not written into the draft the customer is building.
    seeded = _draft_for(scope)
    return {
        "outcome": "saved",
        "have": seeded.known_fields(),
        "missing": seeded.missing_fields(),
        "problems": problems,
        "ready_to_place": seeded.is_complete and scope.customer is not None,
    }


def _place_order(db: Session, scope: OrderingScope, args: PlaceOrderArgs) -> dict[str, Any]:
    """Create the order, and hand back a link to pay it.

    Everything this needs has already been gathered and checked: the cart is
    the browser's, the contact details are the draft's (validated as they
    arrived), and the price is `create_order`'s own — the same arithmetic
    checkout runs, never a figure from here or from the model.

    The order is created unpaid. That is what makes this safe to do from a
    sentence rather than a button: nothing is charged until the customer
    opens the link and enters a card on Stripe's page, and an unpaid order
    is the most reversible thing in this system.
    """

    if scope.session_id is None:
        return {"outcome": "no_session"}
    if not args.lines:
        return {"outcome": "empty_cart"}

    draft = _draft_for(scope)
    missing = draft.missing_fields()
    if missing:
        # Names only. The agent asks for what is missing; it never learns
        # what is already held.
        return {"outcome": "needs_details", "missing": missing}
    customer = scope.customer
    if customer is None and scope.verified_phone:
        # A channel that has verified the number is the only way to be
        # somebody without signing in. The account is made at this moment
        # rather than at "hello", because `full_name` and `email` are
        # required columns and the conversation has only just collected them.
        try:
            customer = customer_for_verified_phone(
                db,
                phone_number=scope.verified_phone,
                app_client_id=scope.app_client_id,
                verified=True,
                full_name=draft.contact_name or "",
                email=draft.contact_email or "",
            )
        except EmailAlreadyUsed:
            # Answerable by the customer, so it is said rather than logged
            # and swallowed.
            return {"outcome": "email_in_use"}
        except PhoneNotVerified as error:
            logger.warning("Could not identify a WhatsApp customer: %s", error)
            return {"outcome": "not_identified"}
    if customer is None:
        # Identity is the account, never the details typed into a chat.
        return {"outcome": "not_identified"}

    fulfillment = OrderFulfillmentType(draft.fulfillment_type or OrderFulfillmentType.DELIVERY.value)
    # For later, when the customer said so. Every scheduled time has already
    # been through the branch's slot rules once (`loop._take_time`); the
    # backend checks it again on creation, which is the rule, not the UI.
    scheduled_for = _parse_iso(draft.scheduled_at)
    payload = OrderCreateRequest(
        restaurant_id=scope.restaurant_id,
        restaurant_location_id=scope.restaurant_location_id,
        fulfillment_type=fulfillment,
        schedule_type=OrderScheduleType.SCHEDULED if scheduled_for else OrderScheduleType.ASAP,
        scheduled_at=scheduled_for,
        items=[
            OrderCreateItem(
                menu_item_id=line.menu_item_id,
                quantity=line.quantity,
                menu_item_size_id=line.menu_item_size_id,
                selected_options=[
                    OrderCreateItemCustomizationOption(
                        option_id=option.option_id,
                        quantity=option.quantity,
                        portion=option.portion,
                    )
                    for option in line.selected_options
                ],
            )
            for line in args.lines
        ],
        # Required by the schema even for pickup; the branch's own address is
        # where a pickup order is collected, and `missing_fields` has already
        # stopped asking the customer for one.
        delivery_address=draft.delivery_address or "Pickup at the restaurant",
        contact_name=draft.contact_name,
        contact_phone=draft.contact_phone,
        payment_method=PaymentMethod.CARD,
    )

    try:
        order = create_order(db, customer, payload)
    except HTTPException as error:
        # A closed branch, an item that went unavailable, a minimum not met:
        # all things the customer can act on, so they are told rather than
        # swallowed. The two numbers behind the commonest of them travel
        # with the refusal, because "the minimum is 16.00" without what the
        # order came to leaves the customer doing arithmetic they cannot do
        # — they cannot see the subtotal.
        refusal: dict[str, Any] = {"outcome": "refused", "reason": str(error.detail)}
        try:
            priced = _view_cart(db, scope, ViewCartArgs(lines=list(args.lines)))
            location = db.get(RestaurantLocation, scope.restaurant_location_id)
            refusal["subtotal"] = priced.get("subtotal")
            refusal["minimum"] = (
                str(location.minimum_order_amount) if location is not None else None
            )
        except Exception:  # noqa: BLE001 - a refusal must still be returned
            logger.warning("Could not price a refused order for the customer", exc_info=True)
        # Closed now but open later is an invitation, not a wall: the next
        # slot the branch could actually take rides on the refusal, and is
        # remembered so that "yes" on the next turn means that time. Decided
        # from the branch's status, never from the wording of the reason.
        try:
            if scope.restaurant_location_id and scope.session_id:
                location = db.get(RestaurantLocation, scope.restaurant_location_id)
                # Whether the time in question can be kept. For an ASAP order
                # that is "are you open now"; for a scheduled one it is the
                # branch's own slot rule, asked about the moment they chose.
                #
                # It used to run only when they had named NO time, so naming
                # one the branch could not keep skipped the offer entirely
                # and the customer got "I could not place that: ..." — the
                # wall this whole path exists to avoid.
                if location is None:
                    workable = True
                elif scheduled_for is None:
                    workable, _ = branch_hours.get_location_fulfillment_status(
                        location, fulfillment_type=fulfillment
                    )
                else:
                    workable, _ = branch_hours.schedule_slot_is_available(
                        location,
                        fulfillment_type=fulfillment,
                        scheduled_at=scheduled_for,
                    )
                if location is not None and not workable:
                    # Measured from the time they ASKED for, so the offer is
                    # the nearest one to what they wanted rather than the
                    # nearest one to now. Somebody asking for tomorrow lunch
                    # is not helped by being offered this morning.
                    nearest = branch_hours.next_available_slot_start(
                        location,
                        fulfillment_type=fulfillment,
                        # ...and never from a time already gone by: that offered
                        # Wed 11:30 at 14:57, which was then refused as past.
                        reference_dt=reference_for_next_slot(scheduled_for),
                    )
                    if nearest is not None:
                        refusal["next_open"] = nearest.isoformat()
                        refusal["fulfillment_label"] = fulfillment.value.lower()
                        # What they asked for, so the reply can name it back
                        # rather than saying "that time" about nothing.
                        if scheduled_for is not None:
                            refusal["wanted_time"] = scheduled_for.isoformat()
                        stored = order_draft.load(scope.session_id)
                        stored.offered_scheduled_at = nearest.isoformat()
                        order_draft.save(scope.session_id, stored)
        except Exception:  # noqa: BLE001 - the refusal still stands without an offer
            logger.warning("Could not offer a later time for a refused order", exc_info=True)
        return refusal

    if scope.verified_phone:
        # This order came out of a conversation, so there is somebody to
        # tell when the payment lands. A web order records nothing here and
        # is never messaged. See `order_channel`.
        order_channel.remember(order.id, phone_number=scope.verified_phone)

    # What they settled on, kept for next time. The account had ordered
    # several times with `default_address` still empty, because nothing ever
    # wrote it — so every conversation asked for it again. The email is left
    # alone deliberately: it identifies the account, and changing it here
    # could collide with somebody else's.
    try:
        if draft.fulfillment_type == OrderFulfillmentType.DELIVERY.value and draft.delivery_address:
            customer.default_address = draft.delivery_address
        if draft.contact_name and not (getattr(customer, "full_name", "") or "").strip():
            customer.full_name = draft.contact_name[:255]
        db.add(customer)
        db.commit()
    except Exception:  # noqa: BLE001 - the order stands whether or not we remember
        logger.warning("Could not save a customer's details for next time", exc_info=True)
        if db is not None:
            db.rollback()

    result: dict[str, Any] = {
        "outcome": "placed",
        "order_id": order.id,
        "total": order.total_amount,
        "currency": getattr(order, "currency", None),
        "scheduled_at": scheduled_for.isoformat() if scheduled_for else None,
    }
    try:
        link = create_payment_link(db, customer, order.id)
        # The chat's copy is the short one. Web clients get the real URL from
        # `create_payment_link` directly and render it as a button; a phone
        # has to read this one as a line of text.
        result["payment_url"] = short_links.shorten(link.url)
    except HTTPException as error:
        # The order exists and is theirs; only the link failed. Saying so is
        # better than pretending the order did not happen.
        logger.warning("Payment link failed for order %s: %s", order.id, error.detail)
        result["payment_problem"] = str(error.detail)

    # The details live on the order now. There is no reason for a copy of
    # somebody's address to outlive it in a cache.
    order_draft.clear(scope.session_id)
    return result


def _serialize_action(action: CartAction) -> dict[str, Any]:
    """Identifiers and a quantity, never a name or a price — the whole point
    of Task 3. The client already has the branch menu loaded and renders
    from that, which is why there is exactly one place `MenuItem.name`/
    `MenuItem.price` are read for a cart-mutating response: nowhere.
    """

    return {
        "kind": action.kind,
        "status": action.status,
        "reason": action.reason,
        "menu_item_id": action.menu_item_id,
        "menu_item_size_id": action.menu_item_size_id,
        "selected_option_ids": list(action.selected_options),
        "quantity": action.quantity,
    }


def _add_to_cart(db: Session, scope: OrderingScope, args: AddToCartArgs) -> dict[str, Any]:
    """One line to add, resolved through the exact same three-outcome sieve
    `view_cart`/`price_quote` already run every line through
    (`_load_branch_menu_items` + `_resolve_cart_lines`), reused rather than
    reimplemented so "is this dish real, sized, customizable" can never
    answer differently for `view_cart` than it does here.

    Not on this branch -> `not_on_menu`, and nothing else — the "say
    nothing" outcome the plan requires, not an error. Needs a size or a
    required group -> `needs_choice`, carrying exactly what `_serialize_choice`
    already returns for `view_cart`'s `needs_choice` lines, so the agent asks
    a real question instead of guessing. Only a fully specified line ever
    becomes an `applied` action; a line that DID specify a size/options still
    carries them onto the action, since those are the identifiers the client
    needs to add exactly the row that was resolved, not the base dish.
    """

    menu_items = _load_branch_menu_items(db, scope)
    resolution = _resolve_cart_lines(menu_items, [args])

    if resolution.dropped_count:
        return {"outcome": "not_on_menu"}
    if resolution.needs_choice:
        return {"outcome": "needs_choice", **_serialize_choice(resolution.needs_choice[0])}

    entry = resolution.resolved[0]
    if scope.diet == "veg" and not entry.menu_item.is_veg:
        # Reported live: a vegetarian asked for a dish by name and the agent
        # added it. The reply pipeline never offers it; the cart must not
        # take it either. The name goes back so the agent can say why.
        return {"outcome": "not_for_diet", "name": entry.menu_item.name, "diet": "vegetarian"}
    action = CartAction(
        kind="add",
        status="applied",
        reason="named",
        menu_item_id=entry.menu_item.id,
        quantity=entry.line.quantity,
        menu_item_size_id=entry.line.menu_item_size_id,
        selected_options=tuple(option.option_id for option in entry.line.selected_options),
    )
    # `name` is for the agent to speak with, never for the wire: the action
    # itself stays identifiers-only, and the client renders from its own
    # menu. Without it a turn that added something had nothing to say, and
    # the reply pipeline filled the silence with "outside my kitchen".
    return {
        "outcome": "action",
        "action": _serialize_action(action),
        "name": entry.menu_item.name,
        "quantity": entry.line.quantity,
    }


def _existing_lines_for(args_lines: list[CartLineArgs]) -> list[ExistingCartLine]:
    return [ExistingCartLine(menu_item_id=line.menu_item_id) for line in args_lines]


def _matching_full_lines(args_lines: list[CartLineArgs], menu_item_id: uuid.UUID) -> list[CartLineArgs]:
    return [line for line in args_lines if line.menu_item_id == menu_item_id]


def _remove_from_cart(db: Session, scope: OrderingScope, args: RemoveFromCartArgs) -> dict[str, Any]:
    """Destructive-when-ambiguous, reused verbatim from `cart_actions.py`:
    `_matching_lines` is the exact function `resolve_cart_actions` already
    calls to decide between `applied` and `proposed` for a `remove`, applied
    here to a model-supplied id instead of a regex-classified message. No
    branch lookup: a line the browser is holding is real by construction —
    it is describing its own cart, not naming an id it hopes exists.
    """

    matches = _matching_lines(_existing_lines_for(args.existing_lines), args.menu_item_id)
    if not matches:
        return {"outcome": "not_found"}

    if len(matches) > 1:
        action = CartAction(kind="remove", status="proposed", reason="destructive", menu_item_id=args.menu_item_id)
        return {"outcome": "action", "action": _serialize_action(action)}

    line = _matching_full_lines(args.existing_lines, args.menu_item_id)[0]
    action = CartAction(
        kind="remove",
        status="applied",
        reason="named",
        menu_item_id=args.menu_item_id,
        menu_item_size_id=line.menu_item_size_id,
        selected_options=tuple(option.option_id for option in line.selected_options),
    )
    return {"outcome": "action", "action": _serialize_action(action)}


def _set_quantity(db: Session, scope: OrderingScope, args: SetQuantityArgs) -> dict[str, Any]:
    """Same identification and ambiguity rule as `_remove_from_cart` — the
    only difference is the resulting `kind`/`quantity` and that
    `cart_actions.resolve_cart_actions` uses `reason="ambiguous"`, not
    `"destructive"`, for a multi-match `set_quantity`: overwriting the wrong
    line's count is a mistake to confirm, not the same irrecoverable class of
    harm as deleting the wrong one, and the reason string is what the client
    uses to choose its wording.
    """

    matches = _matching_lines(_existing_lines_for(args.existing_lines), args.menu_item_id)
    if not matches:
        return {"outcome": "not_found"}

    if len(matches) > 1:
        action = CartAction(
            kind="set_quantity",
            status="proposed",
            reason="ambiguous",
            menu_item_id=args.menu_item_id,
            quantity=args.quantity,
        )
        return {"outcome": "action", "action": _serialize_action(action)}

    line = _matching_full_lines(args.existing_lines, args.menu_item_id)[0]
    action = CartAction(
        kind="set_quantity",
        status="applied",
        reason="named",
        menu_item_id=args.menu_item_id,
        quantity=args.quantity,
        menu_item_size_id=line.menu_item_size_id,
        selected_options=tuple(option.option_id for option in line.selected_options),
    )
    return {"outcome": "action", "action": _serialize_action(action)}


def _go_to_checkout(db: Session, scope: OrderingScope, args: GoToCheckoutArgs) -> dict[str, Any]:
    """Hand the customer to /checkout. Proposed, never applied: the client
    renders it as a "Go to checkout" card, and the page that opens is the one
    that collects delivery/pickup, the slot and the card today. The agent
    neither places nor pays for an order — `FORBIDDEN_ARG_NAMES` makes that
    structurally impossible, and this tool has no arguments a customer could
    use to try.
    """

    if not args.lines:
        return {"outcome": "empty_cart"}
    return {
        "outcome": "action",
        "action": {
            "kind": "checkout",
            "status": "proposed",
            "reason": "named",
            "menu_item_id": None,
            "menu_item_size_id": None,
            "selected_option_ids": [],
            "quantity": None,
        },
    }


def _clear_cart(db: Session, scope: OrderingScope, args: ClearCartArgs) -> dict[str, Any]:
    """Always `proposed`, unconditionally — no argument, no confidence level
    and no cart content could ever change that, per the plan's "destructive
    is always proposed, never applied" rule. Needs neither `db` nor `scope`;
    kept in the `(db, scope, args)` shape only so every handler in the
    registry reads alike.
    """

    action = CartAction(kind="clear", status="proposed", reason="destructive")
    return {"outcome": "action", "action": _serialize_action(action)}


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
    ToolSpec(
        "add_to_cart",
        "Add a dish to the cart. Never applied for a dish that still needs "
        "a size or a required choice — that returns the choices instead.",
        AddToCartArgs,
        _add_to_cart,
    ),
    ToolSpec(
        "remove_from_cart",
        "Remove a dish from the cart by its menu item id. Proposed for "
        "confirmation, rather than applied, whenever that id matches more "
        "than one current cart line.",
        RemoveFromCartArgs,
        _remove_from_cart,
    ),
    ToolSpec(
        "set_quantity",
        "Change how many of a dish are in the cart. Proposed for "
        "confirmation, rather than applied, whenever the id matches more "
        "than one current cart line.",
        SetQuantityArgs,
        _set_quantity,
    ),
    ToolSpec(
        "clear_cart",
        "Empty the entire cart. Always proposed for the customer's "
        "confirmation, never applied automatically.",
        ClearCartArgs,
        _clear_cart,
    ),
    ToolSpec(
        "order_requirements",
        "What is still needed before this order can be placed: which contact "
        "details are held and which are missing.",
        OrderRequirementsArgs,
        _order_requirements,
    ),
    ToolSpec(
        "save_order_details",
        "Keep the name, phone, email, address or delivery choice the "
        "customer just gave, and report what is still missing.",
        SaveOrderDetailsArgs,
        _save_order_details,
    ),
    ToolSpec(
        "place_order",
        "Place the order the conversation has built and return a link to pay "
        "it. Creates the order unpaid; nothing is charged until the customer "
        "opens the link.",
        PlaceOrderArgs,
        _place_order,
    ),
    ToolSpec(
        "go_to_checkout",
        "The customer is finished adding and wants to pay: hands them to "
        "the checkout page. Never places or pays for an order.",
        GoToCheckoutArgs,
        _go_to_checkout,
    ),
)


# The cart-shaped arguments the caller fills in from the request, whatever
# the model wrote there. Named here, beside the arg models, because three
# places need to agree about them: the guards that inject them, the prompt
# that must not advertise them, and the validation that must not judge the
# model on a value nobody will read.
INJECTED_CART_FIELDS: dict[str, str] = {
    "view_cart": "lines",
    "order_requirements": "lines",
    "remove_from_cart": "existing_lines",
    "set_quantity": "existing_lines",
    "go_to_checkout": "lines",
    "place_order": "lines",
}


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
        # An injected field is not something the model chooses, so listing it
        # only invites it to invent one — which it did, and the call was
        # refused before the real cart could replace it.
        injected = INJECTED_CART_FIELDS.get(name)
        fields = [f for f in spec.args_model.model_fields if f != injected]
        args = ", ".join(fields) if fields else "no arguments"
        summary = spec.description.split(".")[0].strip()
        lines.append(f"- {name}({args}) — {summary}")
    return "\n".join(lines)


__all__ = [
    "FORBIDDEN_ARG_NAMES",
    "INJECTED_CART_FIELDS",
    "TOOL_LIST",
    "TOOLS",
    "AddToCartArgs",
    "CartLineArgs",
    "CheckHoursArgs",
    "ClearCartArgs",
    "GoToCheckoutArgs",
    "GetDishArgs",
    "OrderRequirementsArgs",
    "PlaceOrderArgs",
    "SaveOrderDetailsArgs",
    "NoArgs",
    "OrderingScope",
    "PaymentOptionsArgs",
    "PriceQuoteArgs",
    "RemoveFromCartArgs",
    "RestaurantInfoArgs",
    "SearchMenuArgs",
    "SelectedOptionArgs",
    "SetQuantityArgs",
    "ToolArgs",
    "ToolHandler",
    "ToolSpec",
    "ViewCartArgs",
    "describe_tools_for_prompt",
]

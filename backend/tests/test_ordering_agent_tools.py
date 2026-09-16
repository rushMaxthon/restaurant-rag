"""Tests for the ordering agent's tool registry (Task 1).

No database, no Ollama: this is the contract, not an implementation. Every
handler in `tools.py` is still free to raise `NotImplementedError` at this
stage — Task 2 fills them in. What has to be right now is the shape a planner
will read and the guarantee a scope id can never travel through it.

Mirrors `test_analyst_tools.py`'s registry-guard half, which asserts the same
two properties for the owner-facing planner: no tool may accept a tenant
identifier, and nothing is callable outside the registry.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from pydantic import ValidationError

from app.services.ordering_agent.tools import (
    FORBIDDEN_ARG_NAMES,
    TOOL_LIST,
    TOOLS,
    CartLineArgs,
    CheckHoursArgs,
    GetDishArgs,
    NoArgs,
    PriceQuoteArgs,
    RestaurantInfoArgs,
    PaymentOptionsArgs,
    SearchMenuArgs,
    SelectedOptionArgs,
    ToolArgs,
    ToolSpec,
    ViewCartArgs,
    describe_tools_for_prompt,
)

EXPECTED_TOOL_NAMES = frozenset(
    {
        "search_menu",
        "get_dish",
        "view_cart",
        "check_hours",
        "price_quote",
        "restaurant_info",
        "payment_options",
        # Task 3: the four cart-mutating tools.
        "add_to_cart",
        "remove_from_cart",
        "set_quantity",
        "clear_cart",
        # The hand-off to /checkout, added with the "add more or check out?" flow.
        "go_to_checkout",
        # The details an order needs, gathered over several turns.
        "order_requirements",
        "save_order_details",
    }
)


class RegistryLookupTests(unittest.TestCase):
    """Every registered tool is retrievable by name; an unknown name is not."""

    def test_registry_contains_exactly_the_tools_the_agent_is_given(self) -> None:
        self.assertEqual(set(TOOLS), EXPECTED_TOOL_NAMES)

    def test_each_expected_tool_is_retrievable_by_name(self) -> None:
        for name in EXPECTED_TOOL_NAMES:
            spec = TOOLS.get(name)
            self.assertIsInstance(spec, ToolSpec)
            self.assertEqual(spec.name, name)

    def test_unknown_tool_name_is_not_in_the_registry(self) -> None:
        for bogus in ("delete_restaurant", "search_menu_v2", "", "SEARCH_MENU"):
            self.assertNotIn(bogus, TOOLS)

    def test_tool_list_has_no_duplicate_names(self) -> None:
        names = [spec.name for spec in TOOL_LIST]
        self.assertEqual(len(names), len(set(names)))


class ExtraForbidTests(unittest.TestCase):
    """Every arg model rejects a key it does not declare."""

    def test_every_registered_tool_rejects_an_unknown_argument(self) -> None:
        for name, spec in TOOLS.items():
            with self.subTest(tool=name):
                with self.assertRaises(ValidationError):
                    spec.args_model(this_argument_does_not_exist="x")

    def test_extra_forbid_is_set_on_every_arg_model_config(self) -> None:
        for name, spec in TOOLS.items():
            with self.subTest(tool=name):
                self.assertEqual(
                    spec.args_model.model_config.get("extra"),
                    "forbid",
                    f"{name}'s args model must set extra='forbid'",
                )

    def test_cart_line_args_rejects_an_unknown_argument(self) -> None:
        with self.assertRaises(ValidationError):
            CartLineArgs(menu_item_id=uuid.uuid4(), extra_field=True)

    def test_selected_option_args_rejects_an_unknown_argument(self) -> None:
        with self.assertRaises(ValidationError):
            SelectedOptionArgs(option_id=uuid.uuid4(), sneaky="x")


class NoScopeIdAnywhereTests(unittest.TestCase):
    """The rule that matters most, asserted structurally over the whole registry.

    A tool added later that declares `restaurant_id` (or any of its synonyms)
    must fail this test without anyone having to remember to check for it by
    hand — the same guarantee `analyst/registry.py` enforces at import time.
    """

    def test_no_tool_arg_model_declares_a_forbidden_field_name(self) -> None:
        for name, spec in TOOLS.items():
            offending = set(spec.args_model.model_fields) & FORBIDDEN_ARG_NAMES
            with self.subTest(tool=name):
                self.assertFalse(
                    offending,
                    f"{name} exposes scope-bearing arguments: {sorted(offending)}",
                )

    def test_forbidden_names_cover_every_scope_dimension_named_in_the_brief(self) -> None:
        # restaurant, branch, location, customer, user — the five the brief
        # names explicitly — plus the app-scoping id this repo's identity
        # model adds on top of them (see docs/per-app-identity.md).
        for required in (
            "restaurant_id",
            "restaurant_location_id",
            "branch_id",
            "location_id",
            "customer_id",
            "user_id",
            "app_client_id",
        ):
            self.assertIn(required, FORBIDDEN_ARG_NAMES)

    def test_nested_cart_line_model_is_also_free_of_scope_ids(self) -> None:
        offending = set(CartLineArgs.model_fields) & FORBIDDEN_ARG_NAMES
        self.assertFalse(offending)
        offending = set(SelectedOptionArgs.model_fields) & FORBIDDEN_ARG_NAMES
        self.assertFalse(offending)

    def test_payment_options_cannot_structurally_initiate_a_payment(self) -> None:
        # The boundary is stricter than "no scope id": this tool must not be
        # able to name an amount, a method to charge, or an order, because
        # answering "do you take card?" and processing a card are different
        # actions and only one of them belongs to a read-only tool.
        fields = set(PaymentOptionsArgs.model_fields)
        self.assertEqual(fields, set())
        for dangerous in ("amount", "payment_method", "order_id"):
            self.assertIn(dangerous, FORBIDDEN_ARG_NAMES)


class DescriptionTests(unittest.TestCase):
    """The planner prompt is built from these; a blank one degrades it silently."""

    def test_every_tool_has_a_non_empty_description(self) -> None:
        for name, spec in TOOLS.items():
            with self.subTest(tool=name):
                self.assertTrue(spec.description.strip())

    def test_descriptions_do_not_merely_repeat_the_name(self) -> None:
        for name, spec in TOOLS.items():
            with self.subTest(tool=name):
                self.assertNotEqual(spec.description.strip().lower(), name.replace("_", " "))


class PromptDescriptionHelperTests(unittest.TestCase):
    """`describe_tools_for_prompt` renders each tool's real argument names."""

    def test_renders_every_tool_name(self) -> None:
        rendered = describe_tools_for_prompt()
        for name in EXPECTED_TOOL_NAMES:
            self.assertIn(name, rendered)

    def test_renders_real_argument_names_not_a_generic_placeholder(self) -> None:
        rendered = describe_tools_for_prompt()
        self.assertIn("search_menu(query", rendered)
        self.assertIn("price_quote(lines", rendered)

    def test_a_no_args_tool_says_it_takes_no_arguments(self) -> None:
        rendered = describe_tools_for_prompt()
        for line in rendered.splitlines():
            if line.startswith("- restaurant_info("):
                self.assertIn("no arguments", line)
                break
        else:
            self.fail("restaurant_info was not rendered")

    def test_can_render_a_subset(self) -> None:
        rendered = describe_tools_for_prompt(("search_menu",))
        self.assertIn("search_menu", rendered)
        self.assertNotIn("price_quote", rendered)


class HandlerSignatureTests(unittest.TestCase):
    """Task 1 left every handler raising `NotImplementedError`; Task 2 wired
    each one to a real service (see `test_ordering_agent_readonly.py` for the
    behavioural coverage). The only thing left to pin here structurally is
    that none of them regressed back to a stub — real handlers legitimately
    raise on nonsense inputs like a `None` session, which is not the same
    thing and is no longer this file's concern.
    """

    def test_every_handler_is_callable(self) -> None:
        for name, spec in TOOLS.items():
            with self.subTest(tool=name):
                self.assertTrue(callable(spec.handler))

    def test_no_handler_is_still_a_task_1_stub(self) -> None:
        import inspect

        for name, spec in TOOLS.items():
            with self.subTest(tool=name):
                source = inspect.getsource(spec.handler)
                self.assertNotIn(
                    "NotImplementedError",
                    source,
                    f"{name} is still Task 1's placeholder",
                )


class ArgModelShapeTests(unittest.TestCase):
    """Sanity checks that each tool asks for what it plausibly needs, and
    nothing that would let it choose whose data it reads."""

    def test_search_menu_takes_free_text_and_optional_filters(self) -> None:
        args = SearchMenuArgs(query="spicy noodles under 200")
        self.assertEqual(args.query, "spicy noodles under 200")
        self.assertIsNone(args.is_veg)
        self.assertIsNone(args.max_price)

    def test_search_menu_requires_a_query(self) -> None:
        with self.assertRaises(ValidationError):
            SearchMenuArgs()

    def test_get_dish_takes_a_name_not_an_id(self) -> None:
        args = GetDishArgs(name="pad thai")
        self.assertEqual(args.name, "pad thai")
        self.assertNotIn("menu_item_id", GetDishArgs.model_fields)

    def test_view_cart_describes_lines_the_browser_is_holding(self) -> None:
        args = ViewCartArgs(
            lines=[CartLineArgs(menu_item_id=uuid.uuid4(), quantity=2)]
        )
        self.assertEqual(len(args.lines), 1)

    def test_price_quote_requires_at_least_one_line(self) -> None:
        with self.assertRaises(ValidationError):
            PriceQuoteArgs(lines=[])

    def test_price_quote_never_takes_a_price(self) -> None:
        self.assertNotIn("price", PriceQuoteArgs.model_fields)
        self.assertNotIn("total_amount", PriceQuoteArgs.model_fields)
        self.assertNotIn("price", CartLineArgs.model_fields)

    def test_check_hours_takes_no_scope_and_an_optional_requested_time(self) -> None:
        args = CheckHoursArgs()
        self.assertIsNone(args.requested_time)

    def test_restaurant_info_and_payment_options_take_nothing(self) -> None:
        self.assertEqual(RestaurantInfoArgs.model_fields, NoArgs.model_fields)
        self.assertEqual(PaymentOptionsArgs.model_fields, NoArgs.model_fields)


class ImportCleanlinessTests(unittest.TestCase):
    def test_module_exposes_toolspec_dataclass_shape(self) -> None:
        spec = TOOLS["search_menu"]
        self.assertTrue(hasattr(spec, "name"))
        self.assertTrue(hasattr(spec, "description"))
        self.assertTrue(hasattr(spec, "args_model"))
        self.assertTrue(hasattr(spec, "handler"))
        self.assertTrue(issubclass(spec.args_model, ToolArgs))


if __name__ == "__main__":
    unittest.main()

"""Tests for the ordering agent's planner (Task 4).

No Ollama, no database: `plan_step` takes its generator as an argument, so a
scripted model drives every path, the same way `test_chat_tools.py` drives
the owner planner. What has to be right at this layer, in order of how much
getting it wrong would cost:

* a planned call can never widen scope, even when the tool name is also wrong
* an unusable plan refuses with a specific reason rather than answering
  something adjacent
* history actually reaches the model, so a multi-round turn can build on what
  an earlier tool call found
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import httpx

from app.services.ordering_agent.planner import (
    PlanStep,
    ToolCallRecord,
    build_planner_prompt,
    plan_step,
)


class ScriptedModel:
    """Replays fixed replies; anything past the end repeats the last."""

    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt: str, timeout_seconds: float, max_tokens: int) -> str:
        self.prompts.append(prompt)
        reply = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply


def plan_with(reply, message: str = "do you have any pizza?", **kwargs) -> tuple[PlanStep, ScriptedModel]:
    model = ScriptedModel(reply)
    step = plan_step(message, history=kwargs.pop("history", ()), generate=model, **kwargs)
    return step, model


class ValidPlanTests(unittest.TestCase):
    def test_a_valid_tool_call_parses(self) -> None:
        step, _ = plan_with(json.dumps({"tool": "search_menu", "args": {"query": "pizza"}}))
        self.assertTrue(step.ok)
        self.assertEqual(step.tool, "search_menu")
        self.assertEqual(step.args.get("query"), "pizza")
        self.assertIsNone(step.error)
        self.assertIsNone(step.answer)

    def test_a_valid_answer_parses(self) -> None:
        step, _ = plan_with(json.dumps({"answer": "We have a great margherita pizza."}))
        self.assertTrue(step.ok)
        self.assertEqual(step.answer, "We have a great margherita pizza.")
        self.assertIsNone(step.tool)
        self.assertIsNone(step.error)


class RefusalTests(unittest.TestCase):
    def test_an_unknown_tool_name_is_discarded(self) -> None:
        step, _ = plan_with(json.dumps({"tool": "delete_everything", "args": {}}))
        self.assertFalse(step.ok)
        self.assertEqual(step.error, "unknown_tool")

    def test_a_call_carrying_a_scope_id_is_discarded(self) -> None:
        step, _ = plan_with(
            json.dumps({"tool": "search_menu", "args": {"query": "pizza", "restaurant_id": "x"}})
        )
        self.assertFalse(step.ok)
        self.assertEqual(step.error, "scope_argument")

    def test_a_scope_id_wins_over_an_unknown_tool_name(self) -> None:
        # Both defects are present at once; the more important one (a
        # smuggled id) must be the one reported, per the brief's ordering.
        step, _ = plan_with(
            json.dumps({"tool": "delete_everything", "args": {"user_id": "x"}})
        )
        self.assertFalse(step.ok)
        self.assertEqual(step.error, "scope_argument")

    def test_malformed_json_degrades_to_no_plan(self) -> None:
        step, _ = plan_with("sure, let me check that for you")
        self.assertFalse(step.ok)
        self.assertEqual(step.error, "planner_unusable")

    def test_empty_response_degrades_to_no_plan(self) -> None:
        step, _ = plan_with("")
        self.assertFalse(step.ok)
        self.assertEqual(step.error, "planner_unusable")

    def test_extra_arguments_are_rejected_by_extra_forbid(self) -> None:
        # `restaurant_info` is `NoArgs` — anything at all is undeclared.
        step, _ = plan_with(json.dumps({"tool": "restaurant_info", "args": {"foo": "bar"}}))
        self.assertFalse(step.ok)
        self.assertEqual(step.error, "invalid_arguments")

    def test_a_missing_required_argument_is_rejected(self) -> None:
        # get_dish, not search_menu: a search with no query is now a browse.
        step, _ = plan_with(json.dumps({"tool": "get_dish", "args": {}}))
        self.assertFalse(step.ok)
        self.assertEqual(step.error, "invalid_arguments")

    def test_a_model_unreachable_error_is_refused_not_raised(self) -> None:
        step, _ = plan_with(httpx.TimeoutException("read timed out"))
        self.assertFalse(step.ok)
        self.assertEqual(step.error, "planner_unavailable")

    def test_an_http_error_is_refused_not_raised(self) -> None:
        request = httpx.Request("POST", "http://example.test")
        response = httpx.Response(500, request=request)
        step, _ = plan_with(httpx.HTTPStatusError("server error", request=request, response=response))
        self.assertFalse(step.ok)
        self.assertEqual(step.error, "planner_unavailable")

    def test_a_non_string_answer_is_refused(self) -> None:
        step, _ = plan_with(json.dumps({"answer": 12345}))
        self.assertFalse(step.ok)
        self.assertEqual(step.error, "planner_unusable")

    def test_an_empty_string_answer_is_refused(self) -> None:
        step, _ = plan_with(json.dumps({"answer": "   "}))
        self.assertFalse(step.ok)
        self.assertEqual(step.error, "planner_unusable")

    def test_a_json_object_with_neither_key_is_refused(self) -> None:
        step, _ = plan_with(json.dumps({"skill": "some_owner_thing"}))
        self.assertFalse(step.ok)
        self.assertEqual(step.error, "planner_unusable")

    def test_non_object_arguments_are_refused(self) -> None:
        step, _ = plan_with(json.dumps({"tool": "search_menu", "args": ["pizza"]}))
        self.assertFalse(step.ok)
        self.assertEqual(step.error, "invalid_arguments")


class PromptTests(unittest.TestCase):
    def test_the_prompt_carries_each_tool_s_real_arguments(self) -> None:
        prompt = build_planner_prompt("anything", ())
        self.assertIn("restaurant_info(no arguments)", prompt)
        self.assertIn("search_menu(query, is_veg, max_price, limit)", prompt)

    def test_the_prompt_states_the_scope_rule(self) -> None:
        prompt = build_planner_prompt("anything", ())
        self.assertIn(
            "never include a restaurant, branch, customer or user id", prompt
        )

    def test_tool_names_restricts_the_tools_listed(self) -> None:
        prompt = build_planner_prompt("anything", (), tool_names=("search_menu",))
        self.assertIn("search_menu(", prompt)
        self.assertNotIn("get_dish(", prompt)
        self.assertNotIn("restaurant_info(", prompt)

    def test_history_is_rendered_into_the_prompt(self) -> None:
        record = ToolCallRecord(
            tool="search_menu",
            args={"query": "pizza"},
            result={"results": [{"menu_item_id": "11111111-1111-1111-1111-111111111111"}]},
        )
        prompt = build_planner_prompt("do you have pizza?", (record,))
        self.assertIn("11111111-1111-1111-1111-111111111111", prompt)
        self.assertIn("search_menu", prompt)

    def test_no_history_reads_as_none_yet(self) -> None:
        prompt = build_planner_prompt("anything", ())
        self.assertIn("(none yet)", prompt)

    def test_an_errored_history_entry_carries_its_error_not_a_result(self) -> None:
        record = ToolCallRecord(tool="search_menu", args={}, error="invalid_arguments")
        prompt = build_planner_prompt("anything", (record,))
        self.assertIn("invalid_arguments", prompt)


class MultiRoundTests(unittest.TestCase):
    """The planner is fed a *sequence* of prior calls, not asked once."""

    def test_a_second_round_sees_the_first_round_s_result(self) -> None:
        model = ScriptedModel(json.dumps({"answer": "Got it."}))
        history = (
            ToolCallRecord(
                tool="get_dish",
                args={"name": "Margherita"},
                result={"found": True, "menu_item_id": "abc-123"},
            ),
        )
        plan_step("add it", history=history, generate=model)
        self.assertEqual(len(model.prompts), 1)
        self.assertIn("abc-123", model.prompts[0])
        self.assertIn("add it", model.prompts[0])

    def test_each_call_only_decides_the_one_next_step(self) -> None:
        # Even with two prior calls in history, a single `plan_step` call
        # only ever invokes the generator once — the loop, not this
        # function, is what turns rounds into a conversation.
        model = ScriptedModel(json.dumps({"tool": "view_cart", "args": {"lines": []}}))
        history = (
            ToolCallRecord(tool="search_menu", args={"query": "pizza"}, result={"results": []}),
            ToolCallRecord(tool="get_dish", args={"name": "Margherita"}, result={"found": False}),
        )
        step = plan_step("what's in my cart?", history=history, generate=model)
        self.assertEqual(len(model.prompts), 1)
        self.assertTrue(step.ok)
        self.assertEqual(step.tool, "view_cart")


if __name__ == "__main__":
    unittest.main()


class NeedsChoiceRuleTests(unittest.TestCase):
    def test_the_prompt_tells_the_model_to_ask_rather_than_retry(self) -> None:
        # Seen live: a correct `needs_choice` result was answered with the
        # same call again. The rule is prompt text, so this pins the text.
        prompt = build_planner_prompt("a pizza", history=[], tool_names=None)
        self.assertIn('"needs_choice"', prompt)
        self.assertIn("do not call the tool again", prompt)
        self.assertIn("never repeat a call you already made", prompt)


class PreviousReplyTests(unittest.TestCase):
    def test_the_previous_line_and_the_checkout_rule_are_in_the_prompt(self) -> None:
        prompt = build_planner_prompt("yes", history=[], tool_names=None, previous_reply="Added a pizza. Add more, or check out?")
        self.assertIn("Added a pizza. Add more, or check out?", prompt)
        self.assertIn("call go_to_checkout", prompt)
        # `lines` is injected by the caller, so it is no longer advertised.
        self.assertIn("go_to_checkout(no arguments)", prompt)


class ThreadAndDietTests(unittest.TestCase):
    def test_the_thread_and_the_diet_are_in_the_prompt(self) -> None:
        prompt = build_planner_prompt(
            "make it two", history=[], tool_names=None,
            recent_history=[{"role": "customer", "text": "add a green curry"}, {"role": "assistant", "text": "Added Green Curry x1. Add more, or check out?"}],
            diet="veg",
        )
        self.assertIn("Customer: add a green curry", prompt)
        self.assertIn("You: Added Green Curry x1.", prompt)
        self.assertIn("The customer is vegetarian", prompt)
        self.assertIn('"not_for_diet"', prompt)

    def test_a_meat_eater_gets_no_diet_line(self) -> None:
        self.assertNotIn("The customer is vegetarian", build_planner_prompt("hi", history=[], tool_names=None, diet=None))


class PromptSizeTests(unittest.TestCase):
    """The prompt has to stay inside the model's context window.

    Measured on the live failure: one un-compacted `get_dish` result was
    17,163 characters, so six rounds pushed the rules and the customer's
    message out of a qwen3:8b prompt and the agent wandered instead of
    adding the dish it had already found.
    """

    def _fat_dish_result(self) -> dict:
        option = {
            "option_id": "11111111-1111-1111-1111-111111111111",
            "name": "Extra cheese",
            "extra_price": "1.50",
            "description": "x" * 400,
            "image_url": "https://example.test/" + "y" * 200,
            "sort_order": 3,
            "is_active": True,
        }
        group = {
            "group_id": "22222222-2222-2222-2222-222222222222",
            "title": "Toppings",
            "needs_selection": True,
            "options": [dict(option, name=f"Option {i}") for i in range(30)],
        }
        return {
            "found": True,
            "menu_item_id": "33333333-3333-3333-3333-333333333333",
            "name": "Cheese Burst Pizza",
            "price": "349.00",
            "description": "z" * 2000,
            "customization_groups": [group] * 4,
        }

    def test_a_six_round_history_stays_small_enough_to_reason_over(self) -> None:
        record = ToolCallRecord(tool="get_dish", args={"name": "Cheese Burst Pizza"}, result=self._fat_dish_result())
        prompt = build_planner_prompt("add it", history=[record] * 6, tool_names=None)
        # Comfortably inside an 8k-token window at ~4 chars per token, with
        # room for the rules, the thread and the reply.
        self.assertLess(len(prompt), 16_000, "a six-round prompt must not crowd out the rules")

    def test_the_ids_the_model_must_reproduce_survive_whole(self) -> None:
        record = ToolCallRecord(tool="get_dish", args={"name": "x"}, result=self._fat_dish_result())
        prompt = build_planner_prompt("add it", history=[record], tool_names=None)
        self.assertIn("33333333-3333-3333-3333-333333333333", prompt)
        self.assertIn("22222222-2222-2222-2222-222222222222", prompt)
        self.assertIn("Cheese Burst Pizza", prompt)
        self.assertIn("349.00", prompt)

    def test_a_long_option_list_says_it_was_cut(self) -> None:
        record = ToolCallRecord(tool="get_dish", args={"name": "x"}, result=self._fat_dish_result())
        prompt = build_planner_prompt("add it", history=[record], tool_names=None)
        self.assertIn("more", prompt)
        self.assertNotIn("z" * 200, prompt, "prose the customer reads is not a planning fact")


class CartInThePromptTests(unittest.TestCase):
    def test_the_cart_is_stated_so_the_model_need_not_look_it_up(self) -> None:
        prompt = build_planner_prompt(
            "what have I got?", history=[], tool_names=None,
            cart_summary="In the cart right now: You have 2 x Corn Fritters - $16.98. Subtotal $16.98.",
        )
        self.assertIn("In the cart right now: You have 2 x Corn Fritters", prompt)

    def test_an_empty_cart_adds_no_line(self) -> None:
        self.assertNotIn("In the cart right now", build_planner_prompt("hi", history=[], tool_names=None))


class AnswerSubjectTests(unittest.TestCase):
    """The model names what its answer is about, so the caller can route it.

    Live: "whats in my basket" was answered by the reply pipeline with
    sticky rice, because "basket" matches a bamboo basket in a dish
    description. No indirect signal caught it — the direct one does.
    """

    def test_the_subject_is_read_off_the_answer(self) -> None:
        step = plan_step("what have I got?", history=[], generate=lambda *a: '{"answer": "Two fritters.", "about": "cart"}')
        self.assertEqual(step.answer, "Two fritters.")
        self.assertEqual(step.answer_about, "cart")

    def test_a_missing_or_odd_subject_is_other(self) -> None:
        for payload in ('{"answer": "hi"}', '{"answer": "hi", "about": 7}', '{"answer": "hi", "about": null}'):
            self.assertEqual(plan_step("x", history=[], generate=lambda *a, p=payload: p).answer_about, "other")

    def test_the_subject_is_case_insensitive(self) -> None:
        step = plan_step("x", history=[], generate=lambda *a: '{"answer": "hi", "about": "  CART "}')
        self.assertEqual(step.answer_about, "cart")

    def test_the_prompt_asks_for_the_subject(self) -> None:
        prompt = build_planner_prompt("x", history=[], tool_names=None)
        self.assertIn('"about"', prompt)



class NothingIsNoneTests(unittest.TestCase):
    def test_an_empty_string_in_an_optional_id_is_none(self) -> None:
        # Live, three times in an afternoon: `"menu_item_size_id": ""`.
        from app.services.ordering_agent.tools import GetDishArgs

        self.assertIsNone(GetDishArgs(name="Corn Fritters", menu_item_size_id="").menu_item_size_id)
        self.assertIsNone(GetDishArgs(name="Corn Fritters", menu_item_size_id="null").menu_item_size_id)

    def test_a_real_value_is_untouched(self) -> None:
        from app.services.ordering_agent.tools import GetDishArgs

        self.assertEqual(GetDishArgs(name="Corn Fritters").name, "Corn Fritters")


class ReadOrderDetailsTests(unittest.TestCase):
    def test_reads_only_what_is_asked_for_and_present(self) -> None:
        from app.services.ordering_agent.planner import extract_order_details

        seen = {}
        def generate(prompt, *a, **k):
            seen["prompt"] = prompt
            return '{"contact_name": "Hitesh", "contact_email": null, "delivery_address": "42 Example Road"}'
        found = extract_order_details(
            "I'm Hitesh, deliver to 42 Example Road",
            missing=["contact_name", "contact_email", "delivery_address"],
            generate=generate,
        )
        self.assertEqual(found, {"contact_name": "Hitesh", "delivery_address": "42 Example Road"})
        self.assertIn("42 Example Road", seen["prompt"])

    def test_nonsense_reads_as_nothing(self) -> None:
        from app.services.ordering_agent.planner import extract_order_details

        self.assertEqual(extract_order_details("hi", missing=["contact_name"], generate=lambda *a, **k: "???"), {})

    def test_nothing_asked_means_no_model_call(self) -> None:
        from app.services.ordering_agent.planner import extract_order_details

        def boom(*a, **k):
            raise AssertionError("should not be called")
        self.assertEqual(extract_order_details("hi", missing=[], generate=boom), {})


class SubjectOnlyTests(unittest.TestCase):
    def test_a_subject_with_nothing_to_add_is_an_empty_answer_about_it(self) -> None:
        # Live: {"about": "cart"} was an error and a wasted round; the cart
        # read-back for that subject is the answer.
        from app.services.ordering_agent.planner import plan_step

        step = plan_step("what is in my cart", history=(), generate=lambda prompt, *a, **k: '{"about": "cart"}', tool_names=("view_cart",))
        self.assertTrue(step.ok)
        self.assertEqual(step.answer, "")
        self.assertEqual(step.answer_about, "cart")

    def test_an_empty_object_is_still_unusable(self) -> None:
        from app.services.ordering_agent.planner import plan_step

        step = plan_step("hi", history=(), generate=lambda prompt, *a, **k: "{}", tool_names=("view_cart",))
        self.assertEqual(step.error, "planner_unusable")


class ReadCartRequestTests(unittest.TestCase):
    """Asking for food, in the ways customers actually ask."""

    def read(self, payload, message="x"):
        from app.services.ordering_agent.planner import extract_cart_request

        return extract_cart_request(message, generate=lambda *a, **k: payload)

    def test_a_request_is_read_with_its_quantity(self) -> None:
        self.assertEqual(
            self.read('{"wants": true, "dish": "Margherita Pizza", "quantity": 2}'),
            ("Margherita Pizza", 2),
        )

    def test_a_request_without_a_number_is_one(self) -> None:
        self.assertEqual(
            self.read('{"wants": true, "dish": "Corn Fritters"}'), ("Corn Fritters", 1)
        )

    def test_a_question_is_not_a_request(self) -> None:
        self.assertIsNone(self.read('{"wants": false, "dish": "Margherita Pizza"}'))

    def test_a_request_naming_nothing_is_not_actionable(self) -> None:
        self.assertIsNone(self.read('{"wants": true, "dish": null}'))

    def test_nonsense_reads_as_nothing(self) -> None:
        self.assertIsNone(self.read("no json here"))

    def test_a_silly_quantity_is_brought_back_into_range(self) -> None:
        self.assertEqual(self.read('{"wants": true, "dish": "Pizza", "quantity": 900}')[1], 20)


class ReadOrderIntentTests(unittest.TestCase):
    """The three things a message can want, from the model's own reading.

    These assert the PARSING, not the model: a live model is not a test
    dependency. What the model actually does with real phrasings was
    measured separately — 9 of 9 adds including Hinglish, 11 of 11 ways of
    asking to check out, 7 of 7 questions correctly wanting neither — and
    the prompt was widened where it fell short (see `read_order_intent`).
    """

    def read(self, payload, message="x", missing=()):
        from app.services.ordering_agent.planner import read_order_intent

        return read_order_intent(message, missing=missing, generate=lambda *a, **k: payload)

    def test_all_three_can_arrive_together(self) -> None:
        got = self.read(
            '{"add": {"dish": "Pad Thai", "quantity": 2},'
            ' "details": {"contact_name": "Ravi", "contact_email": "r@example.com"},'
            ' "checkout": true}'
        )
        self.assertEqual(got["add"], ("Pad Thai", 2))
        self.assertEqual(got["details"], {"contact_name": "Ravi", "contact_email": "r@example.com"})
        self.assertTrue(got["checkout"])

    def test_a_message_wanting_nothing_reads_as_nothing(self) -> None:
        got = self.read('{"add": null, "details": {}, "checkout": false}')
        self.assertEqual(got, {"add": None, "details": {}, "checkout": False, "when": None, "chose": None, "confirms": None, "browse": None, "asks_hours": False})

    def test_nulls_and_empties_are_not_details(self) -> None:
        got = self.read(
            '{"add": {"dish": null}, "details": {"contact_name": "null",'
            ' "contact_email": "  ", "delivery_address": "12 Old Street"}, "checkout": false}'
        )
        self.assertIsNone(got["add"])
        self.assertEqual(got["details"], {"delivery_address": "12 Old Street"})

    def test_a_field_this_draft_does_not_hold_is_ignored(self) -> None:
        # Only the draft's own fields are read back out, so a model that
        # invents a key cannot smuggle it into `remember`.
        got = self.read('{"add": null, "details": {"card_number": "4242..."}, "checkout": false}')
        self.assertEqual(got["details"], {})

    def test_nonsense_wants_nothing_rather_than_raising(self) -> None:
        got = self.read("the model said something else entirely")
        self.assertEqual(got, {"add": None, "details": {}, "checkout": False, "when": None, "chose": None, "confirms": None, "browse": None, "asks_hours": False})

    def test_a_silly_quantity_is_brought_back_into_range(self) -> None:
        got = self.read('{"add": {"dish": "Pizza", "quantity": 900}, "details": {}, "checkout": false}')
        self.assertEqual(got["add"][1], 20)

    def test_what_is_still_missing_is_named_in_the_prompt(self) -> None:
        seen = {}

        def generate(prompt, *a, **k):
            seen["prompt"] = prompt
            return '{"add": null, "details": {}, "checkout": false}'

        from app.services.ordering_agent.planner import read_order_intent

        read_order_intent("x", missing=["contact_email"], generate=generate)
        self.assertIn("contact_email", seen["prompt"])


class QuickReadTests(unittest.TestCase):
    """Sentences plain enough to read without a model."""

    def read(self, message):
        from app.services.ordering_agent.planner import quick_read

        return quick_read(message)

    def test_the_plain_ways_of_asking_are_read_at_once(self) -> None:
        for message, expected in [
            ("cart", "cart"),
            ("What's in my cart?", "cart"),
            ("show me the cart", "cart"),
            ("menu", "menu"),
            ("Show me menu", "menu"),
            ("what do you have on the menu", "menu"),
            ("checkout", "checkout"),
            ("Yeah let's do check out", "checkout"),
            ("checkout please", "checkout"),
            ("order kar do bhai", "checkout"),
            ("chalo order kar do", "checkout"),
            ("done", "checkout"),
            ("give me payment link", "checkout"),
        ]:
            self.assertEqual(self.read(message), expected, message)

    def test_a_sentence_carrying_anything_else_is_left_to_the_model(self) -> None:
        # The dish, the name and the address are the content a word match
        # cannot see, and losing them is how a customer has to say it twice.
        for message in [
            "I want roti canai",
            "add one more pizza",
            "I'll take the pad thai and check out",
            "I will pickup, name is vishal, email is test@gmail.com",
            "how much is the pizza",
            "do you have pizza",
            "is there a minimum order",
        ]:
            self.assertIsNone(self.read(message), message)

    def test_turning_something_down_is_not_asking_for_it(self) -> None:
        # The failure a word match cannot avoid on its own.
        for message in ["no checkout", "don't checkout yet", "not the menu", "cancel my order"]:
            self.assertIsNone(self.read(message), message)

    def test_a_long_sentence_is_never_plain(self) -> None:
        self.assertIsNone(
            self.read("so what I was thinking is maybe we could look at the menu together")
        )

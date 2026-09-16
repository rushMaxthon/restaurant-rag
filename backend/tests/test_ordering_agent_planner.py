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
        step, _ = plan_with(json.dumps({"tool": "search_menu", "args": {}}))
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
        self.assertIn("go_to_checkout(lines)", prompt)


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


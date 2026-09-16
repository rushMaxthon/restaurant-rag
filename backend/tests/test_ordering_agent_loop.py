"""Tests for the ordering agent's bounded loop and its guards (Task 5).

No Ollama, no database, per the brief: `run_turn` takes its `generate` and
`clock` as arguments, so every round is scripted and no wall clock is ever
actually slept on. The tool registry is patched via `unittest.mock.patch.dict`
on `tools.TOOLS` itself (in place, not a rebind) rather than adding a
`registry` parameter to `run_turn`/`guards.prepare_tool_call`: both
`loop.py` and `planner.py` already hold their own `from ... import TOOLS`
name bound to that one dict object, and `patch.dict` mutates the object's
contents rather than replacing the module attribute, so a stub registry
reaches the planner's own tool-name validation for free — a `registry`
parameter would have to be threaded through `plan_step` too, which is not
this task's file to change.

What has to be right here, in the order the brief asks for it:

* the loop stops at the round cap
* exceeding the budget yields the fallback, never a partial answer
* a failing tool does not abort the turn
* results are fed back in order
* the flag being off short-circuits everything else
* an id the model never saw this turn is refused, and the refusal is fed back
* the request cart overrides whatever cart-shaped lines the model typed
* an applied `clear`/ambiguous-`remove` from a (deliberately wrong) stub
  handler is downgraded before it reaches the caller
* actions collected from mutation results stay in call order
"""

from __future__ import annotations

import json
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.schemas.suggestions import CartLinePayload
from app.services.ordering_agent import guards, loop
from app.services.ordering_agent.planner import ToolCallRecord
from app.services.ordering_agent.tools import (
    CartLineArgs,
    NoArgs,
    OrderingScope,
    ToolArgs,
    ToolSpec,
    TOOLS,
)

settings = get_settings()

SCOPE = OrderingScope(
    restaurant_id=uuid.uuid4(),
    restaurant_location_id=uuid.uuid4(),
    customer=None,
)

MENU_ITEM_ID = uuid.uuid4()
SIZE_ID = uuid.uuid4()


class DishLookupArgs(ToolArgs):
    name: str = "anything"


class AddArgs(ToolArgs):
    menu_item_id: uuid.UUID


class BoomArgs(NoArgs):
    pass


class ScriptedGenerate:
    """Replays fixed model replies; anything past the end repeats the last."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt: str, timeout_seconds: float, max_tokens: int) -> str:
        self.prompts.append(prompt)
        index = min(len(self.prompts) - 1, len(self.replies) - 1)
        return self.replies[index]


class ScriptedClock:
    """Replays fixed timestamps; anything past the end repeats the last."""

    def __init__(self, *ticks: float) -> None:
        self.ticks = list(ticks)
        self.calls = 0

    def __call__(self) -> float:
        index = min(self.calls, len(self.ticks) - 1)
        self.calls += 1
        return self.ticks[index]


def _recording_handler(calls: list, result: dict):
    def handler(db, scope, args):
        calls.append(args)
        return result

    return handler


def _tool_call(tool: str, args: dict) -> str:
    return json.dumps({"tool": tool, "args": args})


def _answer(text: str) -> str:
    return json.dumps({"answer": text})


class OrderingAgentLoopTestCase(unittest.TestCase):
    """Enables the flag for the duration of each test and patches `TOOLS`
    to a small stub registry, mirroring how `test_chat_tools.py` toggles
    `settings.enable_ai_manager_chat_tools` directly rather than mocking
    `get_settings`.
    """

    def setUp(self) -> None:
        self._flag = settings.enable_ordering_agent
        settings.enable_ordering_agent = True
        self._registry: dict[str, ToolSpec] = {}
        self._patcher = mock.patch.dict(
            "app.services.ordering_agent.tools.TOOLS", self._registry, clear=True
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        settings.enable_ordering_agent = self._flag

    def register(self, name: str, args_model, handler) -> None:
        TOOLS[name] = ToolSpec(name, "stub", args_model, handler)


class FlagOffTests(OrderingAgentLoopTestCase):
    def test_flag_off_short_circuits_before_anything_runs(self) -> None:
        settings.enable_ordering_agent = False
        generate = ScriptedGenerate(_answer("should never be reached"))
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="hi",
            cart=[],
            generate=generate,
            clock=ScriptedClock(0.0),
        )
        self.assertIsNone(outcome.answer)
        self.assertEqual(outcome.fallback_reason, "flag_off")
        self.assertEqual(outcome.actions, [])
        self.assertEqual(outcome.records, [])
        self.assertEqual(generate.prompts, [])


class RoundCapTests(OrderingAgentLoopTestCase):
    def test_the_loop_stops_at_the_round_cap(self) -> None:
        # Never answers; each round is a fresh, harmless read-only call, so
        # nothing else can stop the loop first.
        self.register("dish_lookup", DishLookupArgs, _recording_handler([], {"found": True}))
        generate = ScriptedGenerate(_tool_call("dish_lookup", {"name": "pizza"}))
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="anything",
            cart=[],
            generate=generate,
            clock=ScriptedClock(0.0),
            max_rounds=3,
            budget_seconds=1000.0,
        )
        self.assertIsNone(outcome.answer)
        self.assertEqual(outcome.fallback_reason, "round_cap")
        self.assertEqual(len(generate.prompts), 3)
        self.assertEqual(len(outcome.records), 3)


class BudgetTests(OrderingAgentLoopTestCase):
    def test_exceeding_the_budget_before_any_round_yields_the_fallback(self) -> None:
        generate = ScriptedGenerate(_answer("too late"))
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="anything",
            cart=[],
            generate=generate,
            clock=ScriptedClock(0.0, 100.0),
            max_rounds=4,
            budget_seconds=30.0,
        )
        self.assertIsNone(outcome.answer)
        self.assertEqual(outcome.fallback_reason, "budget_exceeded")
        self.assertEqual(generate.prompts, [])
        self.assertEqual(outcome.records, [])

    def test_exceeding_the_budget_never_returns_a_partial_answer(self) -> None:
        # Round 1 completes a real tool call; round 2's model check is over
        # budget, so the turn must stop WITHOUT ever asking for round 2's
        # answer, even though the model was scripted to provide one.
        self.register("dish_lookup", DishLookupArgs, _recording_handler([], {"found": True}))
        generate = ScriptedGenerate(
            _tool_call("dish_lookup", {"name": "pizza"}),
            _answer("here you go"),
        )
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="anything",
            cart=[],
            generate=generate,
            # start=0, round1 model-check=5 (ok), round1 tool-check=10 (ok),
            # round2 model-check=50 (exceeds a 30s budget).
            clock=ScriptedClock(0.0, 5.0, 10.0, 50.0),
            max_rounds=4,
            budget_seconds=30.0,
        )
        self.assertIsNone(outcome.answer)
        self.assertEqual(outcome.fallback_reason, "budget_exceeded")
        # Round 1's record survives the later timeout.
        self.assertEqual(len(outcome.records), 1)
        self.assertEqual(len(generate.prompts), 1)


class FailingToolTests(OrderingAgentLoopTestCase):
    def test_a_raising_tool_does_not_abort_the_turn(self) -> None:
        def boom(db, scope, args):
            raise RuntimeError("kaboom")

        self.register("boom", BoomArgs, boom)
        generate = ScriptedGenerate(
            _tool_call("boom", {}),
            _answer("recovered anyway"),
        )
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="anything",
            cart=[],
            generate=generate,
            clock=ScriptedClock(0.0),
            max_rounds=4,
            budget_seconds=1000.0,
        )
        self.assertEqual(outcome.answer, "recovered anyway")
        self.assertIsNone(outcome.fallback_reason)
        self.assertEqual(len(outcome.records), 1)
        self.assertIn("tool_error", outcome.records[0].error or "")


class ResultsFedBackTests(OrderingAgentLoopTestCase):
    def test_results_are_fed_back_to_the_next_round_in_order(self) -> None:
        self.register(
            "dish_lookup",
            DishLookupArgs,
            _recording_handler([], {"found": True, "menu_item_id": str(MENU_ITEM_ID)}),
        )
        generate = ScriptedGenerate(
            _tool_call("dish_lookup", {"name": "pizza"}),
            _answer("added"),
        )
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="anything",
            cart=[],
            generate=generate,
            clock=ScriptedClock(0.0),
            max_rounds=4,
            budget_seconds=1000.0,
        )
        self.assertEqual(outcome.answer, "added")
        self.assertEqual(len(outcome.records), 1)
        self.assertEqual(outcome.records[0].tool, "dish_lookup")
        # Round 2's prompt actually carries round 1's result.
        self.assertEqual(len(generate.prompts), 2)
        self.assertIn(str(MENU_ITEM_ID), generate.prompts[1])

    def test_multiple_tool_results_stay_in_call_order(self) -> None:
        first_id, second_id = uuid.uuid4(), uuid.uuid4()
        self.register(
            "dish_lookup", DishLookupArgs, _recording_handler([], {"menu_item_id": str(first_id)})
        )
        self.register(
            "other_lookup", DishLookupArgs, _recording_handler([], {"menu_item_id": str(second_id)})
        )
        generate = ScriptedGenerate(
            _tool_call("dish_lookup", {"name": "a"}),
            _tool_call("other_lookup", {"name": "b"}),
            _answer("done"),
        )
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="anything",
            cart=[],
            generate=generate,
            clock=ScriptedClock(0.0),
            max_rounds=4,
            budget_seconds=1000.0,
        )
        self.assertEqual([record.tool for record in outcome.records], ["dish_lookup", "other_lookup"])


class ProvenanceTests(OrderingAgentLoopTestCase):
    def test_an_unseen_id_is_refused_and_the_refusal_is_fed_back(self) -> None:
        calls: list = []
        self.register("add_dish", AddArgs, _recording_handler(calls, {"outcome": "action"}))
        unseen_id = uuid.uuid4()
        generate = ScriptedGenerate(
            _tool_call("add_dish", {"menu_item_id": str(unseen_id)}),
            _answer("ok"),
        )
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="anything",
            cart=[],
            generate=generate,
            clock=ScriptedClock(0.0),
            max_rounds=4,
            budget_seconds=1000.0,
        )
        # The handler never actually ran with the unseen id.
        self.assertEqual(calls, [])
        self.assertEqual(len(outcome.records), 1)
        self.assertTrue((outcome.records[0].error or "").startswith("unknown_id"))
        self.assertIn(str(unseen_id), outcome.records[0].error or "")
        # The model got another round and answered.
        self.assertEqual(outcome.answer, "ok")
        self.assertEqual(len(generate.prompts), 2)
        self.assertIn("unknown_id", generate.prompts[1])

    def test_an_id_learned_this_turn_from_a_prior_result_is_accepted(self) -> None:
        learned_id = uuid.uuid4()
        self.register(
            "dish_lookup", DishLookupArgs, _recording_handler([], {"menu_item_id": str(learned_id)})
        )
        calls: list = []
        self.register("add_dish", AddArgs, _recording_handler(calls, {"outcome": "action"}))
        generate = ScriptedGenerate(
            _tool_call("dish_lookup", {"name": "pizza"}),
            _tool_call("add_dish", {"menu_item_id": str(learned_id)}),
            _answer("added"),
        )
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="anything",
            cart=[],
            generate=generate,
            clock=ScriptedClock(0.0),
            max_rounds=4,
            budget_seconds=1000.0,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(outcome.answer, "added")
        self.assertIsNone(outcome.records[1].error)


class CartInjectionTests(OrderingAgentLoopTestCase):
    def test_the_request_cart_overrides_model_typed_lines_for_view_cart(self) -> None:
        class ViewArgs(ToolArgs):
            lines: list[CartLineArgs] = []

        calls: list = []
        self.register("view_cart", ViewArgs, _recording_handler(calls, {"lines": [], "subtotal": "0.00"}))

        real_cart = [
            CartLinePayload(menu_item_id=MENU_ITEM_ID, quantity=2, size_id=SIZE_ID, customization_option_ids=[])
        ]
        # The model invents a completely different, unseen line.
        fabricated_id = str(uuid.uuid4())
        generate = ScriptedGenerate(
            _tool_call("view_cart", {"lines": [{"menu_item_id": fabricated_id, "quantity": 1}]}),
            _answer("here's your cart"),
        )
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="what's in my cart?",
            cart=real_cart,
            generate=generate,
            clock=ScriptedClock(0.0),
            max_rounds=4,
            budget_seconds=1000.0,
        )
        self.assertEqual(outcome.answer, "here's your cart")
        # Twice: once up front, so the prompt can state the cart as a fact,
        # and once for the call the model planned. Both get the real cart —
        # which is the point of the test — so the planned one is the last.
        self.assertEqual(len(calls), 2)
        sent_lines = calls[-1].lines
        self.assertEqual(len(sent_lines), 1)
        self.assertEqual(sent_lines[0].menu_item_id, MENU_ITEM_ID)
        self.assertEqual(sent_lines[0].quantity, 2)


class DestructivePolicyTests(OrderingAgentLoopTestCase):
    def test_an_applied_clear_from_a_stub_handler_is_downgraded(self) -> None:
        # A deliberately wrong handler, to prove the loop's own gate (not
        # the real handler's correctness) is what catches this.
        wrong_result = {"outcome": "action", "action": {"kind": "clear", "status": "applied", "reason": "destructive"}}
        self.register("clear_cart", NoArgs, _recording_handler([], wrong_result))
        generate = ScriptedGenerate(
            _tool_call("clear_cart", {}),
            _answer("cleared"),
        )
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="clear my cart",
            cart=[],
            generate=generate,
            clock=ScriptedClock(0.0),
            max_rounds=4,
            budget_seconds=1000.0,
        )
        self.assertEqual(len(outcome.actions), 1)
        self.assertEqual(outcome.actions[0]["status"], "proposed")
        self.assertEqual(outcome.records[0].result["action"]["status"], "proposed")

    def test_an_applied_remove_with_reason_destructive_is_downgraded(self) -> None:
        # The real shape `_remove_from_cart`'s multi-match branch builds
        # (`tools.py`): `kind="remove"`, `reason="destructive"`, never
        # `"ambiguous"`. A gate that only recognised `reason=="ambiguous"`
        # would miss this one entirely.
        wrong_result = {
            "outcome": "action",
            "action": {"kind": "remove", "status": "applied", "reason": "destructive"},
        }
        self.register("remove_dish", NoArgs, _recording_handler([], wrong_result))
        generate = ScriptedGenerate(
            _tool_call("remove_dish", {}),
            _answer("removed"),
        )
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="remove the pizza",
            cart=[],
            generate=generate,
            clock=ScriptedClock(0.0),
            max_rounds=4,
            budget_seconds=1000.0,
        )
        self.assertEqual(outcome.actions[0]["status"], "proposed")
        self.assertEqual(outcome.records[0].result["action"]["status"], "proposed")

    def test_an_applied_set_quantity_with_reason_ambiguous_is_downgraded(self) -> None:
        # The real shape `_set_quantity`'s multi-match branch builds.
        wrong_result = {
            "outcome": "action",
            "action": {"kind": "set_quantity", "status": "applied", "reason": "ambiguous"},
        }
        self.register("adjust_quantity", NoArgs, _recording_handler([], wrong_result))
        generate = ScriptedGenerate(
            _tool_call("adjust_quantity", {}),
            _answer("updated"),
        )
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="make it two",
            cart=[],
            generate=generate,
            clock=ScriptedClock(0.0),
            max_rounds=4,
            budget_seconds=1000.0,
        )
        self.assertEqual(outcome.actions[0]["status"], "proposed")
        self.assertEqual(outcome.records[0].result["action"]["status"], "proposed")

    def test_an_applied_remove_with_reason_named_is_left_alone(self) -> None:
        # The real shape of a genuinely unambiguous, applied removal
        # (`tools.py:1263`'s single-match branch) must survive this gate
        # unchanged, or a real removal would never reach the customer.
        real_result = {
            "outcome": "action",
            "action": {"kind": "remove", "status": "applied", "reason": "named"},
        }
        self.register("remove_dish", NoArgs, _recording_handler([], real_result))
        generate = ScriptedGenerate(
            _tool_call("remove_dish", {}),
            _answer("removed"),
        )
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="remove the pizza",
            cart=[],
            generate=generate,
            clock=ScriptedClock(0.0),
            max_rounds=4,
            budget_seconds=1000.0,
        )
        self.assertEqual(outcome.actions[0]["status"], "applied")
        self.assertEqual(outcome.records[0].result["action"]["status"], "applied")

    def test_the_first_action_ends_the_turn(self) -> None:
        # Live on 2026-09-16: "add one more" turned into three, because the
        # model went on calling mutation tools after the first applied add.
        # A cart change is the end of the work, whatever the model plans next.
        add_result = {"outcome": "action", "action": {"kind": "add", "status": "applied", "menu_item_id": str(MENU_ITEM_ID)}}
        remove_calls: list = []
        self.register("add_dish", NoArgs, _recording_handler([], add_result))
        self.register("remove_dish", NoArgs, _recording_handler(remove_calls, {"outcome": "action", "action": {"kind": "remove", "status": "proposed", "reason": "destructive"}}))
        generate = ScriptedGenerate(
            _tool_call("add_dish", {}),
            _tool_call("remove_dish", {}),
            _answer("done"),
        )
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="anything",
            cart=[],
            generate=generate,
            clock=ScriptedClock(0.0),
            max_rounds=4,
            budget_seconds=1000.0,
        )
        self.assertEqual([action["kind"] for action in outcome.actions], ["add"])
        self.assertEqual(remove_calls, [], "nothing runs after the first action")
        self.assertIsNone(outcome.fallback_reason)
        # The turn says what it did, from the tool's own rows — no model
        # round spent on it. The web client still renders its own sentence
        # from the action; a chat thread has no client and needs these words.
        self.assertIn("Added", outcome.answer or "")


class GuardsUnitTests(unittest.TestCase):
    """`guards.py`'s own building blocks, exercised directly rather than
    only through the loop.
    """

    def test_scope_for_a_guest_has_no_customer(self) -> None:
        from app.services.chat_principal import guest_principal_for_session

        principal = guest_principal_for_session(uuid.uuid4())
        scope = guards.scope_for(principal, uuid.uuid4(), uuid.uuid4())
        self.assertIsNone(scope.customer)

    def test_seed_seen_ids_walks_every_cart_line_field(self) -> None:
        item_id, size_id, option_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        cart = [
            CartLinePayload(
                menu_item_id=item_id,
                quantity=1,
                size_id=size_id,
                customization_option_ids=[option_id],
            )
        ]
        seen = guards.seed_seen_ids(cart)
        self.assertEqual(seen, {item_id, size_id, option_id})

    def test_grow_seen_ids_walks_nested_results(self) -> None:
        seen: set[uuid.UUID] = set()
        nested_id = uuid.uuid4()
        guards.grow_seen_ids(seen, {"results": [{"menu_item_id": str(nested_id)}]})
        self.assertIn(nested_id, seen)

    def test_enforce_destructive_policy_ignores_actionless_results(self) -> None:
        result = {"found": True}
        self.assertEqual(guards.enforce_destructive_policy(result), result)

    def test_enforce_destructive_policy_leaves_a_proposed_clear_alone(self) -> None:
        result = {"outcome": "action", "action": {"kind": "clear", "status": "proposed"}}
        self.assertEqual(guards.enforce_destructive_policy(result), result)

    def test_enforce_destructive_policy_gates_on_kind_and_reason_not_one_reason_string(self) -> None:
        # The property, not a single reason string: `_remove_from_cart`'s
        # real multi-match branch uses `reason="destructive"`, never
        # `"ambiguous"` (`tools.py:1256`) — a gate that only recognised
        # `"ambiguous"` would miss this shape entirely.
        result = {"outcome": "action", "action": {"kind": "remove", "status": "applied", "reason": "destructive"}}
        downgraded = guards.enforce_destructive_policy(result)
        self.assertEqual(downgraded["action"]["status"], "proposed")

    def test_enforce_destructive_policy_downgrades_an_applied_ambiguous_set_quantity(self) -> None:
        result = {"outcome": "action", "action": {"kind": "set_quantity", "status": "applied", "reason": "ambiguous"}}
        downgraded = guards.enforce_destructive_policy(result)
        self.assertEqual(downgraded["action"]["status"], "proposed")

    def test_enforce_destructive_policy_leaves_an_applied_named_remove_alone(self) -> None:
        # "named" is the only reason the real handlers ever attach to a
        # legitimately applied remove/set_quantity (`tools.py:1263, 1299`).
        result = {"outcome": "action", "action": {"kind": "remove", "status": "applied", "reason": "named"}}
        self.assertEqual(guards.enforce_destructive_policy(result), result)


if __name__ == "__main__":
    unittest.main()


class RepeatedCallTests(OrderingAgentLoopTestCase):
    def test_an_identical_repeat_of_an_answered_call_is_refused_not_run(self) -> None:
        # The live failure this guards: a correct `needs_choice` result,
        # then the same call again and again until the round cap.
        calls: list = []
        self.register("dish_lookup", DishLookupArgs, _recording_handler(calls, {"outcome": "needs_choice"}))
        generate = ScriptedGenerate(
            _tool_call("dish_lookup", {"name": "pizza"}),
            _tool_call("dish_lookup", {"name": "pizza"}),
            _answer("which size?"),
        )
        outcome = loop.run_turn(
            db=None,
            scope=SCOPE,
            message="a pizza",
            cart=[],
            generate=generate,
            clock=ScriptedClock(0.0),
            max_rounds=5,
            budget_seconds=1000.0,
        )
        self.assertEqual(len(calls), 1, "the handler ran once; the repeat was refused")
        self.assertEqual(outcome.answer, "which size?")
        self.assertTrue(outcome.records[1].error and outcome.records[1].error.startswith("repeated_call: identical to call 1"))
        # The refusal reached the model on the next round.
        self.assertIn("repeated_call", generate.prompts[2])

    def test_a_repeat_of_a_refused_call_is_allowed(self) -> None:
        # A call that never ran (refused by a guard) may be retried verbatim
        # once the model has fixed what it can; only answered calls count.
        calls: list = []
        self.register("dish_lookup", DishLookupArgs, _recording_handler(calls, {"found": True}))
        generate = ScriptedGenerate(
            _tool_call("dish_lookup", {"name": "pizza", "restaurant_id": "smuggled"}),
            _tool_call("dish_lookup", {"name": "pizza"}),
            _answer("done"),
        )
        outcome = loop.run_turn(
            db=None, scope=SCOPE, message="a pizza", cart=[], generate=generate,
            clock=ScriptedClock(0.0), max_rounds=5, budget_seconds=1000.0,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(outcome.answer, "done")


class NeedsChoiceTemplateTests(OrderingAgentLoopTestCase):
    def test_a_cap_with_a_needs_choice_result_asks_the_question_from_the_rows(self) -> None:
        # The live failure: the tool said which size/options were needed and
        # the model spent every round not asking. The loop asks instead,
        # from the tool's own rows, and the turn is a success, not a fallback.
        calls: list = []
        result = {
            "outcome": "needs_choice", "name": "Thai Basil Fried Rice", "needs_size": True,
            "available_sizes": [{"size_id": "s1", "name": "Small", "price": "13.99"}],
            "customization_groups": [{
                "title": "Choose your protein", "needs_selection": True,
                "options": [{"option_id": "o1", "name": "Tofu", "extra_price": "0"},
                            {"option_id": "o2", "name": "Chicken", "extra_price": "1.50"}],
            }],
        }
        self.register("dish_lookup", DishLookupArgs, _recording_handler(calls, result))
        generate = ScriptedGenerate(
            _tool_call("dish_lookup", {"name": "rice"}),
            _tool_call("dish_lookup", {"name": "rice"}),
        )
        outcome = loop.run_turn(
            db=None, scope=SCOPE, message="rice please", cart=[], generate=generate,
            clock=ScriptedClock(0.0), max_rounds=2, budget_seconds=1000.0,
        )
        self.assertIsNone(outcome.fallback_reason)
        self.assertIn("Which size for Thai Basil Fried Rice? Small ($13.99).", outcome.answer)
        self.assertIn("Choose your protein for Thai Basil Fried Rice: Tofu, Chicken (+$1.50).", outcome.answer)

    def test_a_cap_without_a_needs_choice_result_is_still_a_fallback(self) -> None:
        self.register("dish_lookup", DishLookupArgs, _recording_handler([], {"found": True}))
        generate = ScriptedGenerate(_tool_call("dish_lookup", {"name": "a"}), _tool_call("dish_lookup", {"name": "b"}))
        outcome = loop.run_turn(
            db=None, scope=SCOPE, message="x", cart=[], generate=generate,
            clock=ScriptedClock(0.0), max_rounds=2, budget_seconds=1000.0,
        )
        self.assertIsNone(outcome.answer)
        self.assertEqual(outcome.fallback_reason, "round_cap")


class CheckoutHandoffTests(OrderingAgentLoopTestCase):
    def test_an_applied_checkout_is_downgraded_to_proposed(self) -> None:
        # The hand-off is never applied: the client navigates on a proposed
        # card the customer taps, and nothing else.
        self.register("checkout", NoArgs, _recording_handler([], {
            "outcome": "action",
            "action": {"kind": "checkout", "status": "applied", "reason": "named"},
        }))
        outcome = loop.run_turn(
            db=None, scope=SCOPE, message="yes", cart=[], generate=ScriptedGenerate(_tool_call("checkout", {})),
            clock=ScriptedClock(0.0), max_rounds=3, budget_seconds=1000.0,
        )
        self.assertEqual(outcome.actions[0]["status"], "proposed")

    def test_the_previous_reply_reaches_the_planner_prompt(self) -> None:
        generate = ScriptedGenerate(_answer("what else?"))
        loop.run_turn(
            db=None, scope=SCOPE, message="no", cart=[], generate=generate,
            clock=ScriptedClock(0.0), max_rounds=3, budget_seconds=1000.0,
            previous_reply="Added a pizza. Add more, or check out?",
        )
        self.assertIn("Added a pizza. Add more, or check out?", generate.prompts[0])


class DietGuardTests(unittest.TestCase):
    def test_a_vegetarian_search_is_forced_veg(self) -> None:
        from app.services.ordering_agent import guards
        prepared, error = guards.prepare_tool_call("search_menu", {"query": "curry", "is_veg": None}, cart=[], seen=set(), diet="veg")
        self.assertIsNone(error)
        self.assertTrue(prepared.is_veg)

    def test_no_diet_leaves_the_search_alone(self) -> None:
        from app.services.ordering_agent import guards
        prepared, error = guards.prepare_tool_call("search_menu", {"query": "curry"}, cart=[], seen=set(), diet=None)
        self.assertIsNone(error)
        self.assertIsNone(prepared.is_veg)


class DishNameInAnIdFieldTests(unittest.TestCase):
    """A name where an id belongs is resolved, not refused forever.

    Live failure: the model called add_to_cart(menu_item_id="Veggie Garden
    Pizza") and the planner rejected it identically on all six rounds, so
    the customer's "just add it" did nothing at all.
    """

    def test_a_confident_name_becomes_the_real_id(self) -> None:
        from app.services.ordering_agent import guards, tools as tools_module

        real = uuid.uuid4()
        original = tools_module._get_dish
        tools_module._get_dish = lambda db, scope, args: {
            "found": True, "confidence": "named", "menu_item_id": real, "name": args.name,
        }
        try:
            args, lookup = guards.resolve_dish_name(None, SCOPE, "add_to_cart", {"menu_item_id": "Veggie Garden Pizza", "quantity": 1})
        finally:
            tools_module._get_dish = original
        self.assertEqual(args["menu_item_id"], str(real))
        self.assertEqual(args["quantity"], 1, "the other arguments are untouched")
        self.assertEqual(lookup["menu_item_id"], real, "the lookup is recorded so the id counts as seen")

    def test_an_unsure_name_is_left_alone_for_the_guards_to_refuse(self) -> None:
        from app.services.ordering_agent import guards, tools as tools_module

        original = tools_module._get_dish
        tools_module._get_dish = lambda db, scope, args: {"found": False, "confidence": "absent"}
        try:
            args, lookup = guards.resolve_dish_name(None, SCOPE, "add_to_cart", {"menu_item_id": "something nobody sells"})
        finally:
            tools_module._get_dish = original
        self.assertEqual(args["menu_item_id"], "something nobody sells")
        self.assertIsNotNone(lookup, "the failed lookup is still fed back, so the model learns")

    def test_a_real_id_is_never_looked_up(self) -> None:
        from app.services.ordering_agent import guards, tools as tools_module

        real = str(uuid.uuid4())
        original = tools_module._get_dish
        tools_module._get_dish = lambda db, scope, args: self.fail("no lookup for an id that is already an id")
        try:
            args, lookup = guards.resolve_dish_name(None, SCOPE, "add_to_cart", {"menu_item_id": real})
        finally:
            tools_module._get_dish = original
        self.assertEqual(args["menu_item_id"], real)
        self.assertIsNone(lookup)

    def test_a_read_only_tool_is_left_alone(self) -> None:
        from app.services.ordering_agent import guards

        args, lookup = guards.resolve_dish_name(None, SCOPE, "search_menu", {"query": "pizza"})
        self.assertIsNone(lookup)
        self.assertEqual(args, {"query": "pizza"})


class OfferedToolsTests(unittest.TestCase):
    """The cart tools appear once there is an id to use, and not before.

    Live failure: with nothing looked up, the model called
    add_to_cart(menu_item_id="123") on all six rounds.
    """

    def test_nothing_seen_hides_the_tools_that_need_an_id(self) -> None:
        offered = loop._offered_tools(set())
        for name in ("add_to_cart", "remove_from_cart", "set_quantity"):
            self.assertNotIn(name, offered)
        for name in ("search_menu", "get_dish", "view_cart", "go_to_checkout"):
            self.assertIn(name, offered, "a tool that needs no id is always offered")

    def test_one_seen_id_opens_the_cart_tools(self) -> None:
        offered = loop._offered_tools({uuid.uuid4()})
        self.assertEqual(set(offered), set(TOOLS))


class CartReadBackTests(OrderingAgentLoopTestCase):
    """The cart is said from its own rows, never from the model's memory.

    Live failure: view_cart returned two lines and a subtotal, the model
    answered with nothing, and the customer was shown the reply pipeline's
    guess — it had searched the menu for a dish called "cart".
    """

    def _result(self, **over):
        base = {
            "lines": [
                {"name": "Corn Fritters", "quantity": 2, "total_price": "16.98", "size_name": None},
                {"name": "Margherita Pizza", "quantity": 1, "total_price": "12.00", "size_name": "Large"},
            ],
            "subtotal": "28.98",
            "needs_choice": [],
        }
        base.update(over)
        return base

    def test_every_line_and_the_subtotal_are_read_back(self) -> None:
        said = loop.describe_cart(self._result())
        self.assertIn("2 x Corn Fritters - $16.98", said)
        self.assertIn("1 x Margherita Pizza (Large) - $12.00", said)
        self.assertIn("Subtotal $28.98", said)
        self.assertIn("Ready to check out?", said)

    def test_an_empty_cart_says_so(self) -> None:
        self.assertEqual(loop.describe_cart(self._result(lines=[], subtotal="0.00")), "Your cart is empty at the moment.")

    def test_a_line_still_needing_a_choice_is_not_called_ready(self) -> None:
        said = loop.describe_cart(self._result(needs_choice=[{"name": "Build Your Own Pizza"}]))
        self.assertNotIn("Ready to check out?", said)
        self.assertIn("needs a choice", said)

    def test_anything_that_is_not_a_cart_is_left_alone(self) -> None:
        for value in (None, {}, {"found": True}, "cart", 7):
            self.assertIsNone(loop.describe_cart(value))

    def test_an_empty_answer_falls_back_to_the_cart_rather_than_nothing(self) -> None:
        self.register("cart", NoArgs, _recording_handler([], self._result()))
        generate = ScriptedGenerate(_tool_call("cart", {}), _answer("   "))
        outcome = loop.run_turn(
            db=None, scope=SCOPE, message="show me my cart", cart=[], generate=generate,
            clock=ScriptedClock(0.0), max_rounds=4, budget_seconds=1000.0,
        )
        self.assertIn("Subtotal $28.98", outcome.answer or "")


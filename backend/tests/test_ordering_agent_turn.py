"""Tests for Task 6: the ordering agent wired into the chat turn, additively.

No Ollama and no database. `rag.run_turn` is patched at the seam (that name
exists in `rag.py` precisely so it can be), and every stage of
`stream_chat_message` that would otherwise reach Postgres, Redis or a model is
patched the way `test_rag_chat_fallback.py` already patches them.

The property under test is one sentence long and the whole point of the task:
**what the customer already gets today does not change.** So the assertions are
about frames, not about the agent:

* with the flag off the SSE frames are byte-identical to the literal bytes this
  endpoint emitted before the agent existed, and `run_turn` is never called
* with the flag on, every existing frame key keeps its existing value — the
  only difference anywhere in the stream is `turn_id` on `meta` and
  `turn_id`/`cart_actions`/`agent_reply` on `done`
* an agent that raises, or a turn with no branch to scope to, costs the
  customer nothing but those three (empty) keys
* the greeting and acknowledgement paths never run the agent at all
"""

from __future__ import annotations

import json
import sys
import unittest
import uuid
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.schemas.suggestions import CartLinePayload
from app.services import rag
from app.services.chat_principal import GuestPrincipal
from app.services.ordering_agent.loop import TurnOutcome
from app.services.rag import (
    ExtractedIntent,
    PreparedChatTurn,
    RagStageTimings,
    SessionConversationState,
)

settings = get_settings()

SESSION_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
RESTAURANT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
LOCATION_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
USER = GuestPrincipal(id=uuid.UUID("44444444-4444-4444-8444-444444444444"))

ITEM_A = uuid.UUID("55555555-5555-4555-8555-555555555555")
SIZE_A = uuid.UUID("66666666-6666-4666-8666-666666666666")
OPTION_A = uuid.UUID("77777777-7777-4777-8777-777777777777")
ITEM_B = uuid.UUID("88888888-8888-4888-8888-888888888888")

MENU_QUESTION = "what pizzas do you have"
MENU_REPLY = "We have Margherita, Farmhouse and Peppy Paneer."
HOURS_QUESTION = "what time do you close"
HOURS_REPLY = "We take delivery orders until 10:30 PM today."

# The three keys this task adds, named once so a test asserting "everything
# else is unchanged" cannot drift from the seam's actual contract.
AGENT_KEYS = (
    "turn_id",
    "cart_actions",
    "agent_reply",
    "agent_asks",
    "placed_order",
    "order_ready",
)


def parse_frame(frame: str) -> tuple[str, dict]:
    lines = frame.split("\n")
    return lines[0][len("event: "):], json.loads(lines[1][len("data: "):])


def prepared_turn(*, message: str, reply: str, intent: str) -> PreparedChatTurn:
    """A turn already resolved to a deterministic answer.

    `should_bypass_llm` is True on purpose: the seam under test lives after the
    reply is streamed, so the reply may as well come from the templated path
    that needs no model at all.
    """

    return PreparedChatTurn(
        active_session_id=SESSION_ID,
        message=message,
        effective_message=message,
        restaurant_id=RESTAURANT_ID,
        retrieval_source="keyword_intent",
        is_greeting=False,
        is_follow_up=False,
        uses_personal_context=False,
        should_bypass_llm=True,
        suggestion_limit=5,
        vector_result_count=0,
        extracted_intent=ExtractedIntent(intent=intent),
        session_state=SessionConversationState(),
        final_candidates=[],
        suggestions=[],
        history_messages=[],
        history_block="",
        context_block="",
        prompt="",
        timings=RagStageTimings(),
        fallback_reply=reply,
    )


class SeamTestCase(unittest.TestCase):
    """Restores the flag after every test, the way `test_ordering_agent_loop.py`
    does — the flag is a field on the shared settings singleton, so leaving it
    set would leak into every test module that runs after this one.
    """

    def setUp(self) -> None:
        self._flag = settings.enable_ordering_agent
        settings.enable_ordering_agent = False

    def tearDown(self) -> None:
        settings.enable_ordering_agent = self._flag

    def stream_main_path(
        self,
        *,
        message: str,
        reply: str,
        intent: str = "dish_recommendation",
        run_turn: Mock | None = None,
        cart: list[CartLinePayload] | None = None,
        restaurant_id: uuid.UUID | None = RESTAURANT_ID,
        restaurant_location_id: uuid.UUID | None = LOCATION_ID,
    ) -> list[str]:
        """The ordinary path: not an acknowledgement, not a greeting, no cache
        hit, a reply the templated tier already knows how to give.
        """

        prepared = prepared_turn(message=message, reply=reply, intent=intent)
        with ExitStack() as stack:
            for target, kwargs in (
                ("_is_acknowledgement_message", {"return_value": False}),
                ("_is_greeting_message", {"return_value": False}),
                ("_message_requests_personal_context", {"return_value": False}),
                ("_is_follow_up_recommendation_message", {"return_value": False}),
                ("preference_diet_for_cache", {"return_value": None}),
                (
                    "_lookup_global_response_cache",
                    {"return_value": ("cache-key", None, False, "not_cacheable")},
                ),
                ("_prepare_chat_turn", {"return_value": prepared}),
                ("_resolve_global_cacheability", {"return_value": (False, "not_cacheable")}),
                (
                    "_attach_suggestion_favorites",
                    {"side_effect": lambda _db, _user, suggestions: suggestions},
                ),
                ("may_cache_globally", {"return_value": False}),
                ("_persist_chat_exchange", {"return_value": None}),
                ("_log_rag_timings", {"return_value": None}),
                ("run_turn", {"new": run_turn or Mock(side_effect=AssertionError("agent ran"))}),
            ):
                stack.enter_context(patch.object(rag, target, **kwargs))
            return list(
                rag.stream_chat_message(
                    Mock(),
                    user=USER,
                    message=message,
                    session_id=SESSION_ID,
                    restaurant_id=restaurant_id,
                    restaurant_location_id=restaurant_location_id,
                    cart=cart,
                )
            )

    def assertAdditiveOnly(self, off_frames: list[str], on_frames: list[str]) -> None:
        """Flag on vs flag off: same frames, same order, same values, plus at
        most the three agent keys. Token frames are compared as raw strings —
        the reply the customer watches arrive must be byte-identical.
        """

        self.assertEqual(len(off_frames), len(on_frames))
        for off_frame, on_frame in zip(off_frames, on_frames):
            off_event, off_data = parse_frame(off_frame)
            on_event, on_data = parse_frame(on_frame)
            self.assertEqual(off_event, on_event)
            if on_event == "token":
                self.assertEqual(off_frame, on_frame)
            self.assertEqual(
                off_data,
                {key: value for key, value in on_data.items() if key not in AGENT_KEYS},
            )


class FlagOffTests(SeamTestCase):
    def test_flag_off_emits_exactly_the_frames_this_endpoint_emitted_before(self) -> None:
        raiser = Mock(side_effect=AssertionError("the agent must not run with the flag off"))
        frames = self.stream_main_path(
            message=MENU_QUESTION, reply=MENU_REPLY, run_turn=raiser
        )

        raiser.assert_not_called()
        self.assertEqual(
            frames,
            [
                'event: meta\ndata: {"session_id": "%s", "suggestions": [], '
                '"combo_suggestions": [], "offer_suggestions": []}\n\n' % SESSION_ID,
                'event: token\ndata: {"text": "%s"}\n\n' % MENU_REPLY,
                'event: done\ndata: {"reply": "%s", "session_id": "%s", "suggestions": [], '
                '"combo_suggestions": [], "offer_suggestions": []}\n\n' % (MENU_REPLY, SESSION_ID),
            ],
        )

    def test_flag_off_frames_carry_none_of_the_agent_keys(self) -> None:
        frames = self.stream_main_path(message=MENU_QUESTION, reply=MENU_REPLY)

        for frame in frames:
            _event, data = parse_frame(frame)
            for key in AGENT_KEYS:
                self.assertNotIn(key, data)


class FlagOnAdditiveTests(SeamTestCase):
    def outcome(self) -> TurnOutcome:
        return TurnOutcome(
            answer="Want me to add one?",
            actions=[],
            records=[],
            fallback_reason=None,
            elapsed_seconds=0.02,
        )

    def test_a_menu_question_still_streams_the_menu_answer(self) -> None:
        off_frames = self.stream_main_path(message=MENU_QUESTION, reply=MENU_REPLY)
        settings.enable_ordering_agent = True
        on_frames = self.stream_main_path(
            message=MENU_QUESTION, reply=MENU_REPLY, run_turn=Mock(return_value=self.outcome())
        )

        self.assertAdditiveOnly(off_frames, on_frames)
        _event, done = parse_frame(on_frames[-1])
        self.assertEqual(done["reply"], MENU_REPLY)
        self.assertEqual(done["agent_reply"], "Want me to add one?")

    def test_an_hours_question_still_streams_the_hours_answer(self) -> None:
        off_frames = self.stream_main_path(
            message=HOURS_QUESTION, reply=HOURS_REPLY, intent="hours"
        )
        settings.enable_ordering_agent = True
        on_frames = self.stream_main_path(
            message=HOURS_QUESTION,
            reply=HOURS_REPLY,
            intent="hours",
            run_turn=Mock(return_value=self.outcome()),
        )

        self.assertAdditiveOnly(off_frames, on_frames)
        _event, done = parse_frame(on_frames[-1])
        self.assertEqual(done["reply"], HOURS_REPLY)

    def test_meta_carries_the_turn_id_and_nothing_else_new(self) -> None:
        settings.enable_ordering_agent = True
        frames = self.stream_main_path(
            message=MENU_QUESTION, reply=MENU_REPLY, run_turn=Mock(return_value=self.outcome())
        )

        _event, meta = parse_frame(frames[0])
        _event, done = parse_frame(frames[-1])
        self.assertIn("turn_id", meta)
        self.assertNotIn("cart_actions", meta)
        self.assertNotIn("agent_reply", meta)
        # One turn, one id: the client correlates the actions on `done` with the
        # turn whose tokens it has been rendering.
        self.assertEqual(meta["turn_id"], done["turn_id"])
        self.assertEqual(str(uuid.UUID(done["turn_id"])), done["turn_id"])


class FlagOnActionsTests(SeamTestCase):
    def test_actions_reach_done_in_order_with_ids_as_strings(self) -> None:
        settings.enable_ordering_agent = True
        outcome = TurnOutcome(
            answer="Added the Margherita. Shall I drop the Coke?",
            actions=[
                {
                    "kind": "add",
                    "status": "applied",
                    "reason": "named",
                    "menu_item_id": ITEM_A,
                    "menu_item_size_id": SIZE_A,
                    "selected_option_ids": [OPTION_A],
                    "quantity": 2,
                },
                {
                    "kind": "remove",
                    "status": "proposed",
                    "reason": "destructive",
                    "menu_item_id": ITEM_B,
                    "menu_item_size_id": None,
                    "selected_option_ids": [],
                    "quantity": None,
                },
            ],
            records=[],
            fallback_reason=None,
            elapsed_seconds=0.31,
        )
        frames = self.stream_main_path(
            message="add a margherita", reply=MENU_REPLY, run_turn=Mock(return_value=outcome)
        )

        _event, done = parse_frame(frames[-1])
        self.assertEqual(
            done["cart_actions"],
            [
                {
                    "kind": "add",
                    "status": "applied",
                    "reason": "named",
                    "menu_item_id": str(ITEM_A),
                    "menu_item_size_id": str(SIZE_A),
                    "selected_option_ids": [str(OPTION_A)],
                    "quantity": 2,
                },
                {
                    "kind": "remove",
                    "status": "proposed",
                    "reason": "destructive",
                    "menu_item_id": str(ITEM_B),
                    "menu_item_size_id": None,
                    "selected_option_ids": [],
                    "quantity": None,
                },
            ],
        )
        self.assertEqual(done["agent_reply"], "Added the Margherita. Shall I drop the Coke?")
        self.assertEqual(done["reply"], MENU_REPLY)

    def test_the_request_cart_and_the_callers_scope_reach_the_agent(self) -> None:
        settings.enable_ordering_agent = True
        cart = [CartLinePayload(menu_item_id=ITEM_A, quantity=2, size_id=SIZE_A)]
        run_turn = Mock(
            return_value=TurnOutcome(
                answer=None, actions=[], records=[], fallback_reason=None, elapsed_seconds=0.0
            )
        )
        self.stream_main_path(
            message="what is in my cart", reply=MENU_REPLY, run_turn=run_turn, cart=cart
        )

        run_turn.assert_called_once()
        kwargs = run_turn.call_args.kwargs
        self.assertEqual(kwargs["cart"], cart)
        self.assertEqual(kwargs["message"], "what is in my cart")
        self.assertEqual(kwargs["scope"].restaurant_id, RESTAURANT_ID)
        self.assertEqual(kwargs["scope"].restaurant_location_id, LOCATION_ID)
        # A guest has no customer row; `scope_for` is what decides that, and the
        # seam must not be inventing a customer of its own.
        self.assertIsNone(kwargs["scope"].customer)


class FlagOnFailureTests(SeamTestCase):
    def test_an_agent_that_raises_leaves_the_reply_intact(self) -> None:
        off_frames = self.stream_main_path(message=MENU_QUESTION, reply=MENU_REPLY)
        settings.enable_ordering_agent = True
        # `assertLogs` both proves the failure is reported with its traceback
        # and keeps it off this suite's own output.
        with self.assertLogs(rag.logger, level="WARNING") as captured:
            on_frames = self.stream_main_path(
                message=MENU_QUESTION,
                reply=MENU_REPLY,
                run_turn=Mock(side_effect=RuntimeError("ollama is down")),
            )
        self.assertIn("Ordering agent turn failed", captured.output[0])
        self.assertIn("RuntimeError: ollama is down", captured.output[0])

        self.assertAdditiveOnly(off_frames, on_frames)
        _event, done = parse_frame(on_frames[-1])
        self.assertEqual(done["reply"], MENU_REPLY)
        self.assertEqual(done["cart_actions"], [])
        self.assertIsNone(done["agent_reply"])
        self.assertIn("turn_id", done)

    def test_a_budget_overrun_yields_no_actions_and_no_agent_reply(self) -> None:
        settings.enable_ordering_agent = True
        frames = self.stream_main_path(
            message=MENU_QUESTION,
            reply=MENU_REPLY,
            run_turn=Mock(
                return_value=TurnOutcome(
                    answer=None,
                    actions=[],
                    records=[],
                    fallback_reason="budget_exceeded",
                    elapsed_seconds=9.9,
                )
            ),
        )

        _event, done = parse_frame(frames[-1])
        self.assertEqual(done["reply"], MENU_REPLY)
        self.assertEqual(done["cart_actions"], [])
        self.assertIsNone(done["agent_reply"])

    def test_a_turn_with_no_branch_skips_the_agent_but_keeps_the_keys(self) -> None:
        settings.enable_ordering_agent = True
        run_turn = Mock(side_effect=AssertionError("no branch to scope to"))
        frames = self.stream_main_path(
            message=MENU_QUESTION,
            reply=MENU_REPLY,
            run_turn=run_turn,
            restaurant_location_id=None,
        )

        run_turn.assert_not_called()
        _event, done = parse_frame(frames[-1])
        self.assertEqual(done["cart_actions"], [])
        self.assertIsNone(done["agent_reply"])
        self.assertIn("turn_id", done)


class CachedReplyPathTests(SeamTestCase):
    """The global cache holds prose, not actions: what to do with THIS cart on
    THIS turn cannot be replayed from a reply someone else's question cached.
    """

    def stream_cache_hit(self, *, run_turn: Mock) -> list[str]:
        with ExitStack() as stack:
            for target, kwargs in (
                ("_is_acknowledgement_message", {"return_value": False}),
                ("_is_greeting_message", {"return_value": False}),
                ("_message_requests_personal_context", {"return_value": False}),
                ("_is_follow_up_recommendation_message", {"return_value": False}),
                ("preference_diet_for_cache", {"return_value": None}),
                (
                    "_lookup_global_response_cache",
                    {
                        "return_value": (
                            "cache-key",
                            (MENU_REPLY, [], [], [], "keyword_intent"),
                            True,
                            "cacheable",
                        )
                    },
                ),
                (
                    "_prepare_cached_response_turn",
                    {
                        "return_value": prepared_turn(
                            message=MENU_QUESTION,
                            reply=MENU_REPLY,
                            intent="dish_recommendation",
                        )
                    },
                ),
                (
                    "_attach_suggestion_favorites",
                    {"side_effect": lambda _db, _user, suggestions: suggestions},
                ),
                ("_persist_chat_exchange", {"return_value": None}),
                ("_log_rag_timings", {"return_value": None}),
                ("run_turn", {"new": run_turn}),
            ):
                stack.enter_context(patch.object(rag, target, **kwargs))
            return list(
                rag.stream_chat_message(
                    Mock(),
                    user=USER,
                    message=MENU_QUESTION,
                    session_id=SESSION_ID,
                    restaurant_id=RESTAURANT_ID,
                    restaurant_location_id=LOCATION_ID,
                    cart=[],
                )
            )

    def test_a_cached_reply_still_runs_the_agent(self) -> None:
        settings.enable_ordering_agent = True
        run_turn = Mock(
            return_value=TurnOutcome(
                answer="Sure.", actions=[], records=[], fallback_reason=None, elapsed_seconds=0.01
            )
        )
        frames = self.stream_cache_hit(run_turn=run_turn)

        run_turn.assert_called_once()
        _event, done = parse_frame(frames[-1])
        self.assertEqual(done["reply"], MENU_REPLY)
        self.assertEqual(done["agent_reply"], "Sure.")
        self.assertIn("turn_id", done)

    def test_a_cached_reply_with_the_flag_off_is_untouched(self) -> None:
        run_turn = Mock(side_effect=AssertionError("the agent must not run with the flag off"))
        frames = self.stream_cache_hit(run_turn=run_turn)

        run_turn.assert_not_called()
        for frame in frames:
            _event, data = parse_frame(frame)
            for key in AGENT_KEYS:
                self.assertNotIn(key, data)


class InstantReplyPathTests(SeamTestCase):
    """Neither path has a question to plan over: "ok" and "hi" are the two
    replies this pipeline gives without retrieving anything at all.
    """

    def stream_instant(self, *, acknowledgement: bool, run_turn: Mock) -> list[str]:
        with ExitStack() as stack:
            for target, kwargs in (
                ("_is_acknowledgement_message", {"return_value": acknowledgement}),
                ("_is_greeting_message", {"return_value": not acknowledgement}),
                ("cache_get_json", {"return_value": None}),
                ("cache_set_json", {"return_value": None}),
                ("_persist_chat_exchange", {"return_value": None}),
                ("_log_rag_timings", {"return_value": None}),
                ("run_turn", {"new": run_turn}),
            ):
                stack.enter_context(patch.object(rag, target, **kwargs))
            return list(
                rag.stream_chat_message(
                    Mock(),
                    user=USER,
                    message="ok" if acknowledgement else "hi",
                    session_id=SESSION_ID,
                    restaurant_id=RESTAURANT_ID,
                    restaurant_location_id=LOCATION_ID,
                    cart=[],
                )
            )

    def test_the_acknowledgement_path_never_runs_the_agent(self) -> None:
        settings.enable_ordering_agent = True
        run_turn = Mock(side_effect=AssertionError("acknowledgements never plan"))
        frames = self.stream_instant(acknowledgement=True, run_turn=run_turn)

        run_turn.assert_not_called()
        for frame in frames:
            _event, data = parse_frame(frame)
            for key in AGENT_KEYS:
                self.assertNotIn(key, data)

    def test_the_greeting_path_never_runs_the_agent(self) -> None:
        settings.enable_ordering_agent = True
        run_turn = Mock(side_effect=AssertionError("greetings never plan"))
        frames = self.stream_instant(acknowledgement=False, run_turn=run_turn)

        run_turn.assert_not_called()
        for frame in frames:
            _event, data = parse_frame(frame)
            for key in AGENT_KEYS:
                self.assertNotIn(key, data)


class RouteTests(unittest.TestCase):
    def test_the_stream_route_forwards_the_request_cart(self) -> None:
        from app.api import chat as chat_api
        from app.schemas.chat import ChatMessageRequest

        cart = [CartLinePayload(menu_item_id=ITEM_A, quantity=3)]
        payload = ChatMessageRequest(
            message=MENU_QUESTION,
            restaurant_id=RESTAURANT_ID,
            restaurant_location_id=LOCATION_ID,
            session_id=SESSION_ID,
            cart=cart,
        )

        with patch.object(chat_api, "stream_chat_message", return_value=iter(())) as streamer:
            chat_api.stream_chat_message_route(
                payload=payload,
                db=Mock(),
                current_user=None,
                app_scope=SimpleNamespace(restaurant_filter_id=None),
            )

        streamer.assert_called_once()
        self.assertEqual(streamer.call_args.kwargs["cart"], cart)


class SchemaTests(unittest.TestCase):
    def test_the_non_streaming_response_defaults_to_no_agent_output(self) -> None:
        from app.schemas.chat import CartActionResponse, ChatMessageResponse

        response = ChatMessageResponse(reply="hi", session_id=SESSION_ID)
        self.assertIsNone(response.turn_id)
        self.assertEqual(response.cart_actions, [])
        self.assertIsNone(response.agent_reply)

        action = CartActionResponse(
            kind="add",
            status="applied",
            reason="named",
            menu_item_id=ITEM_A,
            menu_item_size_id=SIZE_A,
            selected_option_ids=[OPTION_A],
            quantity=1,
        )
        # Identifiers and a quantity, and nothing that names or prices a dish.
        self.assertEqual(
            set(action.model_dump().keys()),
            {
                "kind",
                "status",
                "reason",
                "menu_item_id",
                "menu_item_size_id",
                "selected_option_ids",
                "quantity",
            },
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class DietVocabularyTests(unittest.TestCase):
    """One spelling, whatever the model or the preference table says.

    The live failure: the extractor returned "vegetarian", every retrieval
    check compares against "veg", and the diet quietly stopped filtering.
    """

    def test_every_spelling_lands_on_the_form_retrieval_compares(self) -> None:
        from app.services.rag import _canonical_intent_diet

        for spelling in ("veg", "VEG", "Vegetarian", "vegetarian"):
            self.assertEqual(_canonical_intent_diet(spelling), "veg", spelling)
        for spelling in ("non veg", "NON_VEG", "non vegetarian"):
            self.assertEqual(_canonical_intent_diet(spelling), "non_veg", spelling)

    def test_nothing_useful_stays_nothing(self) -> None:
        from app.services.rag import _canonical_intent_diet

        for value in (None, "", "   ", "pescatarian", 7):
            self.assertIsNone(_canonical_intent_diet(value))


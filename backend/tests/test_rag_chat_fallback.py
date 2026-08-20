from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import rag
from app.services.rag import (
    ChatMessageResponse,
    ExtractedIntent,
    PreparedChatTurn,
    SessionConversationState,
)


def make_candidate(name: str = "Pad Thai Veg") -> SimpleNamespace:
    return SimpleNamespace(
        menu_item=SimpleNamespace(
            id=uuid.uuid4(),
            name=name,
        ),
        restaurant=SimpleNamespace(
            id=uuid.uuid4(),
            name="Bangkok Bowl",
        ),
        distance=0.5,
        source="popular_fallback",
    )


class RagChatFallbackTests(unittest.TestCase):
    def test_resolve_candidates_without_embedding_prefers_keywords_when_available(self) -> None:
        keyword_candidate = make_candidate("Margherita Pizza")

        final_candidates, retrieval_source, vector_result_count = (
            rag._resolve_candidates_without_embedding(
                Mock(),
                message="pizza",
                restaurant_id=None,
                restaurant_location_id=None,
                budget_limit=None,
                strict_budget=False,
                intent=ExtractedIntent(intent="dish_recommendation"),
                filtered_keyword_candidates=[keyword_candidate],
                exclude_item_ids=set(),
                limit=5,
                allow_popular_fallback=True,
                is_follow_up=False,
            )
        )

        self.assertEqual(final_candidates, [keyword_candidate])
        self.assertEqual(retrieval_source, "keyword_intent")
        self.assertEqual(vector_result_count, 0)

    def test_prepare_safe_fallback_turn_uses_follow_up_context(self) -> None:
        session_id = uuid.uuid4()
        user = SimpleNamespace(id=uuid.uuid4())
        session_state = SessionConversationState(
            last_intent="recommendation",
            active_intent="recommendation",
            base_query="sweet items",
            active_topic="sweet items",
            last_successful_user_query="sweet items",
        )

        with patch.object(
            rag,
            "_load_cached_session_state_only",
            return_value=session_state,
        ):
            prepared = rag._prepare_safe_fallback_turn(
                Mock(),
                user=user,
                message="Give me more",
                session_id=session_id,
                restaurant_id=None,
                failure_reason="RuntimeError",
            )

        self.assertIsInstance(prepared, PreparedChatTurn)
        self.assertTrue(prepared.is_follow_up)
        self.assertEqual(prepared.effective_message, "sweet items")
        self.assertEqual(prepared.retrieval_source, "no_more_matches")
        self.assertIn("sweet", prepared.fallback_reply or "")

    def test_handle_chat_message_follow_up_prepare_failure_returns_graceful_response(self) -> None:
        session_id = uuid.uuid4()
        user = SimpleNamespace(id=uuid.uuid4())
        session_state = SessionConversationState(
            last_intent="recommendation",
            active_intent="recommendation",
            base_query="sweet items",
            active_topic="sweet items",
            last_successful_user_query="sweet items",
        )

        with (
            patch.object(rag, "_is_acknowledgement_message", return_value=False),
            patch.object(rag, "_is_greeting_message", return_value=False),
            patch.object(
                rag,
                "_lookup_global_response_cache",
                return_value=("cache-key", None, False, "follow_up"),
            ),
            patch.object(rag, "_message_requests_personal_context", return_value=False),
            patch.object(rag, "_is_follow_up_recommendation_message", return_value=True),
            patch.object(rag, "_prepare_chat_turn", side_effect=RuntimeError("boom")),
            patch.object(rag, "_load_cached_session_state_only", return_value=session_state),
            patch.object(rag, "_persist_chat_exchange", return_value=None),
            patch.object(rag, "_attach_suggestion_favorites", side_effect=lambda _db, _user, suggestions: suggestions),
        ):
            response = rag.handle_chat_message(
                Mock(),
                user=user,
                message="Give me more",
                session_id=session_id,
                restaurant_id=None,
                restaurant_location_id=None,
            )

        self.assertIsInstance(response, ChatMessageResponse)
        self.assertEqual(response.session_id, session_id)
        self.assertEqual(response.suggestions, [])
        self.assertIn("sweet", response.reply.lower())


if __name__ == "__main__":
    unittest.main()

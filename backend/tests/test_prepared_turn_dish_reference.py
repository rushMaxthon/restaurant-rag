"""`PreparedChatTurn.dish_reference_verdict` is the ONE place the resolver in
`cart_actions.py` learns whether the customer's message named a real dish. It
must come from the same call `apply_dish_name_guardrail` already makes for the
reply's own dish-name guardrail — not a second, independent computation, or
the two could disagree about whether a dish was named.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: F401 - imported first to settle import order
from app.services.rag import PreparedChatTurn, RagStageTimings


class PreparedTurnDishReferenceTests(unittest.TestCase):
    def test_the_field_exists_and_defaults_to_unknown(self) -> None:
        """A `PreparedChatTurn` built by an early-return path (greeting, cache
        hit) never calls the guardrail at all, so it must default rather than
        raise `TypeError: missing argument`."""

        turn = PreparedChatTurn(
            active_session_id=__import__("uuid").uuid4(),
            message="hi",
            effective_message="hi",
            restaurant_id=None,
            retrieval_source="none",
            is_greeting=True,
            is_follow_up=False,
            uses_personal_context=False,
            should_bypass_llm=True,
            suggestion_limit=0,
            vector_result_count=0,
            extracted_intent=__import__("app.services.rag", fromlist=["ExtractedIntent"]).ExtractedIntent(intent="greeting"),
            session_state=__import__("app.services.rag", fromlist=["SessionConversationState"]).SessionConversationState(),
            final_candidates=[],
            suggestions=[],
            history_messages=[],
            history_block="",
            context_block="",
            prompt="",
            timings=RagStageTimings(),
        )

        self.assertEqual(turn.dish_reference_verdict, "unknown")


if __name__ == "__main__":
    unittest.main()

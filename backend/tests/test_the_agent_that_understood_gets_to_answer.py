""""I didn't quite catch that" must not beat an agent that did catch it.

    >>> Vagharela Khaman
        Which size for Vagharela Khaman? Per Plate (₹35), 1 Kg (₹240).
    >>> Y
        I didn't quite catch that. Ask me about food, restaurants, menus,
        combos, offers, or something like dinner under a budget.

The obvious reading is that "Y" was not understood. It was. Driven straight at
the ordering agent, with the same pending question, every one of these answers
correctly:

    'Y'    -> Sorry, I did not catch that. Which size for Vagharela Khaman?
              Per Plate (₹35), 1 Kg (₹240). ... Just reply with one of these:
              Per Plate, 1 Kg.
    'N'    -> the same
    '2'    -> the same
    'yes'  -> the same

So the agent knew what it had asked and re-asked it with the options spelled
out, which is the right answer. The reply pipeline then threw that away. Its
order of precedence was:

    if prepared.should_bypass_llm:      # the instant "I didn't quite catch that"
        reply = prepared.fallback_reply
    elif agent_owns:                    # the agent's line — never reached
        reply = agent_output["agent_reply"]

`invalid_input` sets `should_bypass_llm`, so the generic apology won every
time, and with it went the question: the size choice was dropped, so the NEXT
message had nothing to be read against either. One classification, three turns
of damage.

Only `invalid_input` loses to the agent here. The other instant replies are
positive classifications — a greeting IS a greeting, an hours question IS an
hours question — and they stay ahead. `invalid_input` is the one that means
"nobody could read this", and it is a claim the agent is in a position to
contradict, because it is holding the question and the list of answers to it.

This also explains a note left on `_is_invalid_or_spam_message`'s own tests:
"a bare number answering a question is handled by the agent, which knows what
it asked". That was true. The handling just never reached the customer.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.rag import agent_answer_beats_instant_reply


class WhoAnswersTests(unittest.TestCase):
    """The one rule, and both routes read it."""

    def test_an_unreadable_message_the_agent_answered_is_the_agents(self) -> None:
        # The reported turn.
        self.assertTrue(
            agent_answer_beats_instant_reply(
                agent_owns=True, should_bypass_llm=True, intent="invalid_input"
            )
        )

    def test_an_unreadable_message_the_agent_did_not_answer_is_not(self) -> None:
        # Nothing to prefer. "Y" with no question pending really is unreadable,
        # and the apology is the honest reply.
        self.assertFalse(
            agent_answer_beats_instant_reply(
                agent_owns=False, should_bypass_llm=True, intent="invalid_input"
            )
        )

    def test_a_greeting_is_still_a_greeting(self) -> None:
        # The instant replies that are positive classifications keep their
        # precedence. Answering "hi" with a re-ask of a size question would be
        # the same bug pointing the other way.
        for intent in ("greeting", "hours_query", "unsupported_domain", "acknowledgement"):
            with self.subTest(intent=intent):
                self.assertFalse(
                    agent_answer_beats_instant_reply(
                        agent_owns=True, should_bypass_llm=True, intent=intent
                    )
                )

    def test_it_says_nothing_about_turns_with_no_instant_reply(self) -> None:
        # Those already go to the agent through the existing `elif`; this rule
        # is only about the branch that was jumping the queue.
        self.assertFalse(
            agent_answer_beats_instant_reply(
                agent_owns=True, should_bypass_llm=False, intent="invalid_input"
            )
        )


class BothRoutesUseItTests(unittest.TestCase):
    """`/chat/message` and the SSE route each had their own copy of the order.

    The streaming route is the one the web concierge and mobile actually call,
    so a fix applied to one of them is a fix a customer might never see.
    """

    def source(self) -> str:
        return (BACKEND_ROOT / "app" / "services" / "rag.py").read_text(encoding="utf-8")

    def test_the_rule_is_read_twice(self) -> None:
        self.assertGreaterEqual(
            self.source().count("agent_answer_beats_instant_reply("),
            3,  # the definition, plus one call per route
            "one of the two routes still decides this for itself",
        )


if __name__ == "__main__":
    unittest.main()

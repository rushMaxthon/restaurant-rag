"""The way a customer calls `run_turn` is the way no test called it.

Every test of the ordering agent injects a scripted model, because that is the
only way to drive a turn deterministically. A customer injects nothing:
`run_turn(generate=None)` is the ONLY shape the live path ever uses, and each
planner call site resolved that None to the real generator itself.

So when `run_turn` grew a wrapper around `generate` — to cap each model call at
the time the turn had left — it wrapped None, and every live turn raised

    TypeError: 'NoneType' object is not callable

while the whole suite stayed green. It was found by replaying a real
conversation through `scripts/dryrun_whatsapp.py`, and it was invisible for a
second reason: the agent's failures are caught and the reply falls back to
retrieval, so the assistant went on answering. It had simply stopped being an
ordering agent.

The gap was structural rather than an oversight in one test — nothing anywhere
asserted what happens with no model injected — so this is its own file.
"""

from __future__ import annotations

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
from app.services.ordering_agent import loop
from app.services.ordering_agent.tools import OrderingScope

settings = get_settings()

SCOPE = OrderingScope(
    restaurant_id=uuid.uuid4(),
    restaurant_location_id=uuid.uuid4(),
    customer=None,
)


class NoModelInjectedTestCase(unittest.TestCase):
    """A turn with the flag on, an empty tool registry and nothing scripted.

    The empty registry is the point: with no tools to call the turn is short,
    and what is being asked is only whether the model seam is reachable at all.
    """

    def setUp(self) -> None:
        self._flag = settings.enable_ordering_agent
        settings.enable_ordering_agent = True
        self._patcher = mock.patch.dict(
            "app.services.ordering_agent.tools.TOOLS", {}, clear=True
        )
        self._patcher.start()

    def tearDown(self) -> None:
        self._patcher.stop()
        settings.enable_ordering_agent = self._flag


class TheDefaultGeneratorIsReachedTests(NoModelInjectedTestCase):
    """With nothing injected, the real model must still be what gets called."""

    def test_the_cap_calls_the_default_rather_than_none(self) -> None:
        # Driven, not read. `run_turn`'s wrapper is a closure with no way in
        # from outside, so this goes through the one seam there is: patch the
        # default and prove the wrapper reaches it.
        #
        # Patched on `loop`, not on `planner`. `loop` imported the name, so it
        # holds its own binding and patching the planner's would leave the real
        # Ollama to answer — which it duly did, for ten seconds, the first time
        # this was written.
        with mock.patch.object(loop, "default_generate", return_value="") as model:
            loop.run_turn(
                db=None,
                scope=SCOPE,
                message="a plate of dhokla",
                cart=[],
                # `generate` deliberately absent: this is the customer's shape,
                # and before this test, the only untested one.
            )
        # What the turn answered is not the point — the stub says nothing, so
        # it will not have answered much. The point is that nothing raised and
        # that the cap had a real model to wrap.
        self.assertTrue(
            model.called,
            "run_turn never reached the model; every live turn would raise",
        )

    def test_an_injected_model_still_wins(self) -> None:
        # The default must not shadow what a caller hands in, or every scripted
        # conversation in the suite would quietly start hitting Ollama.
        injected = mock.Mock(return_value="")
        with mock.patch.object(loop, "default_generate", return_value="") as fallback:
            loop.run_turn(
                db=None,
                scope=SCOPE,
                message="a plate of dhokla",
                cart=[],
                generate=injected,
            )
        self.assertTrue(injected.called)
        self.assertFalse(fallback.called, "an injected model was bypassed for the default")


class EveryCallIsCappedByTheTurnTests(NoModelInjectedTestCase):
    """Why the wrapper exists at all."""

    def test_a_call_cannot_be_given_longer_than_the_turn_has_left(self) -> None:
        # `ordering_agent_planner_timeout_seconds` is 45s while the turn's
        # budget is 30s, so one call could always outlive the turn containing
        # it — and one did, for 54 seconds, on a live thread. The wrapper hands
        # down whichever is smaller.
        seen: list[float] = []

        def model(_prompt: str, timeout_seconds: float, _max_tokens: int) -> str:
            seen.append(timeout_seconds)
            return ""

        loop.run_turn(
            db=None,
            scope=SCOPE,
            message="a plate of dhokla",
            cart=[],
            generate=model,
            budget_seconds=5.0,
        )
        self.assertTrue(seen, "the model was never called, so nothing was capped")
        for timeout in seen:
            self.assertLessEqual(timeout, 5.0)


if __name__ == "__main__":
    unittest.main()

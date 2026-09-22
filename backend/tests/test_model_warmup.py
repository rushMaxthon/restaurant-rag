"""Nobody should pay to load a model in the middle of their question.

From a live WhatsApp thread on 2026-09-21:

    Ordering agent turn fallback_reason=None records=1 actions=1 elapsed=54.14s

54 seconds against a 30-second budget, effectively all of it one intent read
waiting on a cold qwen3:8b, where the same read takes 4.4s once the weights are
resident. The customer got a wrong answer as well as a slow one, because the
turn finished from its budget-exceeded path.

The API had warmed the *embedding* model at startup since this was first hit
there. Two gaps: the generation model — the expensive one, 5.6GB against 274MB
— was never warmed in any process, and warming once only covers one `keep_alive`
window, so a quiet morning evicts the weights exactly like a restart does.

These tests are mostly about the ways this feature can do nothing at all while
appearing to be on. A warm-up that silently stops happening is invisible: there
is no error, only the occasional slow answer it was built to prevent.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import model_warmup, ollama_client


class KeepAliveIsReadAsADurationTests(unittest.TestCase):
    """`keep_alive` is the only statement of how long the weights live."""

    def parsed(self, raw: str, *, cloud: bool = False) -> float | None:
        with mock.patch.object(ollama_client.settings, "ollama_keep_alive", raw), mock.patch.object(
            type(ollama_client.settings), "ollama_is_cloud", property(lambda _self: cloud)
        ):
            return ollama_client.keep_alive_seconds()

    def test_the_configured_default(self) -> None:
        # The value actually shipped. If this ever stops parsing, the re-warm
        # interval quietly becomes None and the loop runs exactly once.
        self.assertEqual(self.parsed("60m"), 3600.0)

    def test_minutes_hours_and_seconds(self) -> None:
        for raw, seconds in (("30s", 30.0), ("5m", 300.0), ("2h", 7200.0)):
            with self.subTest(raw=raw):
                self.assertEqual(self.parsed(raw), seconds)

    def test_a_compound_duration(self) -> None:
        self.assertEqual(self.parsed("1h30m"), 5400.0)

    def test_a_bare_number_is_seconds(self) -> None:
        # Ollama reads an unsuffixed value as seconds, and so must we.
        self.assertEqual(self.parsed("900"), 900.0)

    def test_forever_has_no_clock(self) -> None:
        # Negative is Ollama's "hold indefinitely". Nothing to re-warm.
        self.assertIsNone(self.parsed("-1"))

    def test_the_cloud_has_no_clock_either(self) -> None:
        # A managed endpoint is never sent keep_alive, so its value says
        # nothing about residency there.
        self.assertIsNone(self.parsed("60m", cloud=True))

    def test_nonsense_is_not_guessed_at(self) -> None:
        # Guessing would be worse than declining: a wrong interval re-warms
        # after the eviction, which is the bug wearing the fix's clothes.
        with self.assertLogs("app.services.ollama_client", level="WARNING"):
            self.assertIsNone(self.parsed("whenever"))


class TheIntervalFollowsTheWindowTests(unittest.TestCase):
    """The re-warm cadence is derived, never configured beside it."""

    def interval(self, window: float | None) -> float | None:
        with mock.patch.object(model_warmup, "keep_alive_seconds", lambda: window):
            return model_warmup.warm_up_interval_seconds()

    def test_it_lands_inside_the_window(self) -> None:
        # The whole point: re-warming must happen BEFORE the weights are
        # evicted, not after, or the next customer pays anyway.
        window = 3600.0
        self.assertLess(self.interval(window), window)

    def test_the_shipped_hour_becomes_half_an_hour(self) -> None:
        self.assertEqual(self.interval(3600.0), 1800.0)

    def test_no_window_means_one_pass(self) -> None:
        self.assertIsNone(self.interval(None))

    def test_a_short_window_is_honoured_rather_than_fought(self) -> None:
        # A deployment asking for eviction after 30 seconds means it; looping
        # every 15 seconds to defeat that would be the tail wagging the dog.
        self.assertIsNone(self.interval(30.0))


class WarmingIsALoadAndNothingElseTests(unittest.TestCase):
    """What actually goes over the wire."""

    def post(self) -> mock.Mock:
        """Run `warm_generation_model` against a stubbed client, return the post."""

        client = mock.MagicMock()
        client.__enter__.return_value = client
        with mock.patch.object(ollama_client, "build_client", return_value=client):
            ollama_client.warm_generation_model("qwen3:8b")
        return client.post

    def test_the_prompt_is_empty(self) -> None:
        # Ollama treats an empty prompt as "load and generate nothing", and
        # answers done_reason="load". Sending real text would cost tokens and,
        # against a metered endpoint, money — for no answer anybody reads.
        payload = self.post().call_args.kwargs["json"]
        self.assertEqual(payload["prompt"], "")

    def test_it_names_the_model_the_agent_will_use(self) -> None:
        # Warming a different model than the one the turn calls is worse than
        # not warming: two models evict each other, so the customer pays twice.
        payload = self.post().call_args.kwargs["json"]
        self.assertEqual(payload["model"], "qwen3:8b")

    def test_it_asks_the_server_to_keep_what_it_just_loaded(self) -> None:
        payload = self.post().call_args.kwargs["json"]
        self.assertEqual(payload.get("keep_alive"), ollama_client.settings.ollama_keep_alive)

    def test_an_unreachable_ollama_is_a_warning_not_a_crash(self) -> None:
        # This runs on a thread inside API startup and inside worker start. An
        # exception here would be a boot failure caused by a speed improvement.
        import httpx

        client = mock.MagicMock()
        client.__enter__.return_value = client
        client.post.side_effect = httpx.ConnectError("no ollama")
        with mock.patch.object(ollama_client, "build_client", return_value=client):
            with self.assertLogs("app.services.ollama_client", level="WARNING"):
                self.assertFalse(ollama_client.warm_generation_model("qwen3:8b"))


class BothModelsGetWarmedTests(unittest.TestCase):
    """The embedding one was already warmed; the expensive one was not."""

    def test_a_pass_covers_generation_and_embeddings(self) -> None:
        with mock.patch.object(model_warmup, "warm_generation_model") as generation, mock.patch.object(
            model_warmup, "warm_embedding_provider"
        ) as embedding:
            model_warmup.warm_once()
        generation.assert_called_once()
        embedding.assert_called_once()

    def test_the_cloud_is_left_alone(self) -> None:
        # Nothing to keep resident, and each pass would be a billed request.
        with mock.patch.object(
            type(model_warmup.settings), "ollama_is_cloud", property(lambda _self: True)
        ), mock.patch.object(model_warmup, "warm_once") as pass_:
            self.assertIsNone(model_warmup.start_model_warm_up(name="test"))
        pass_.assert_not_called()

    def test_it_does_not_block_whoever_started_it(self) -> None:
        # A cold load is tens of seconds. Inline, that is an API refusing
        # connections at startup or a worker that looks hung before its first
        # task — a speed fix presenting as an outage.
        started = mock.MagicMock()
        with mock.patch.object(model_warmup, "warm_once", started), mock.patch.object(
            model_warmup, "warm_up_interval_seconds", lambda: None
        ), mock.patch.object(
            type(model_warmup.settings), "ollama_is_cloud", property(lambda _self: False)
        ):
            thread = model_warmup.start_model_warm_up(name="test")
            self.assertIsNotNone(thread)
            self.assertTrue(thread.daemon, "a slow Ollama must not hold up shutdown")
            thread.join(timeout=5)
        started.assert_called_once()


class ThePathsThatUseTheModelStartItWarmTests(unittest.TestCase):
    """Warming nothing is the failure mode, so assert both processes do it."""

    def test_the_api_warms_on_startup(self) -> None:
        source = (BACKEND_ROOT / "app" / "main.py").read_text(encoding="utf-8")
        self.assertIn("start_model_warm_up(", source)

    def test_the_worker_warms_when_it_is_ready(self) -> None:
        # The worker is where WhatsApp is answered, and WhatsApp is where the
        # 54-second turn was measured. It warmed nothing at all before this.
        source = (BACKEND_ROOT / "app" / "config" / "celery.py").read_text(encoding="utf-8")
        self.assertIn("@worker_ready.connect", source)
        self.assertIn("start_model_warm_up(", source)


if __name__ == "__main__":
    unittest.main()

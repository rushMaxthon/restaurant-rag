"""Big responses leave this server compressed, and streams do not.

Every response was going out uncompressed. One branch's menu is 164 KB of
JSON for 136 dishes, and the storefront's home page and menu page both ask
for it — on a phone, on mobile data, in a market where that is the whole
experience. Gzip takes it to about 18 KB. It is the cheapest change in this
codebase by a wide margin, and it was simply never switched on: the app had
CORS middleware and nothing else.

The interesting half is what must NOT be compressed. Both `text/event-stream`
endpoints exist to deliver tokens as the model produces them, and a
compressor sitting in front of a stream buffers exactly what the stream is
for. They opt out by naming their own `Content-Encoding`, which Starlette's
GZipMiddleware skips — so the test that matters here is that the opt-out is
still in place, because nothing else would fail if somebody removed it. The
chat would just quietly stop feeling live.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from starlette.middleware.gzip import GZipMiddleware

from app.main import app


class TheAppCompressesTests(unittest.TestCase):
    def test_gzip_middleware_is_installed(self) -> None:
        installed = [m.cls for m in app.user_middleware]
        self.assertIn(GZipMiddleware, installed)

    def test_small_responses_are_left_alone(self) -> None:
        # Compressing a 300-byte body costs CPU at both ends and saves
        # nothing. The threshold is above the size of the small JSON this API
        # mostly returns.
        entry = next(m for m in app.user_middleware if m.cls is GZipMiddleware)
        minimum = entry.kwargs.get("minimum_size")
        self.assertIsNotNone(minimum, "a threshold was set deliberately")
        self.assertGreaterEqual(minimum, 500)


class StreamsOptOutTests(unittest.TestCase):
    """Read off the source, because a broken stream still returns 200.

    A compressed SSE response is not an error anywhere — the client receives
    every token, all at once, at the end. Nothing raises, no status changes,
    and the only symptom is that the chat stops feeling live. So the guard is
    that the opt-out is present at each streaming site.
    """

    def streaming_sites(self) -> list[tuple[str, str]]:
        found = []
        for name in ("chat.py", "insights.py"):
            source = (BACKEND_ROOT / "app" / "api" / name).read_text(encoding="utf-8")
            for chunk in source.split("StreamingResponse(")[1:]:
                head = chunk[: chunk.find("\n    )")]
                if "text/event-stream" in head:
                    found.append((name, head))
        return found

    def test_both_streaming_endpoints_are_found(self) -> None:
        # If this drops to one, an endpoint was renamed or removed and the
        # assertion below would pass while covering less than it claims.
        self.assertEqual(len(self.streaming_sites()), 2)

    def test_every_event_stream_names_its_own_encoding(self) -> None:
        for name, head in self.streaming_sites():
            with self.subTest(module=name):
                self.assertIn(
                    '"Content-Encoding": "identity"',
                    head,
                    "an event stream without this is compressed by the app's "
                    "gzip middleware, which buffers the tokens it exists to "
                    "deliver one at a time",
                )


if __name__ == "__main__":
    unittest.main()

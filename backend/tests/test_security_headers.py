"""Every API response tells the browser how to treat it.

Found in the 2026-10-07 security review: the API sent no security headers at
all (only the compose nginx, which production does not use, added them). So
a response could be framed by another site, sniffed into another content
type, leak its URL in a Referer, and a signed-in answer - orders, addresses,
payouts - could be kept by a shared cache.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402
from app.middleware import security_headers  # noqa: E402


def _tiny(local: bool) -> TestClient:
    tiny = FastAPI()

    @tiny.get("/thing")
    def thing():
        return {"ok": True}

    @tiny.get("/cached")
    def cached():
        from fastapi import Response

        return Response("x", headers={"Cache-Control": "public, max-age=60"})

    tiny.add_middleware(security_headers.SecurityHeadersMiddleware, local=local)
    return TestClient(tiny)


class EveryResponse(unittest.TestCase):
    def test_the_real_app_sends_them(self) -> None:
        response = TestClient(app).get("/api/traffic/overview")  # 401, still a response
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")

    def test_the_set(self) -> None:
        headers = _tiny(local=False).get("/thing").headers
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Referrer-Policy"], "no-referrer")
        self.assertIn("max-age=", headers["Strict-Transport-Security"])

    def test_no_https_only_rule_on_a_local_machine(self) -> None:
        # HSTS on localhost pins the browser to https for every local app.
        self.assertNotIn("Strict-Transport-Security", _tiny(local=True).get("/thing").headers)


class SignedInAnswersAreNotCached(unittest.TestCase):
    def test_a_request_with_a_token_is_no_store(self) -> None:
        headers = _tiny(local=False).get("/thing", headers={"Authorization": "Bearer x"}).headers
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_a_public_answer_keeps_its_own_caching(self) -> None:
        self.assertNotIn("no-store", _tiny(local=False).get("/thing").headers.get("Cache-Control", ""))
        self.assertEqual(
            _tiny(local=False).get("/cached").headers["Cache-Control"], "public, max-age=60"
        )


if __name__ == "__main__":
    unittest.main()

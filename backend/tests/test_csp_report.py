"""Browsers report what the strict script policy would have blocked.

The three web apps send a `Content-Security-Policy-Report-Only` header
(2026-10-07 security review): browsers apply nothing, they only report what
WOULD have been blocked, here. A few days of real traffic with no reports
from legitimate pages is the evidence for switching it to enforcing - which
done blind could break checkout, because Stripe and Razorpay load from
several hosts.

The endpoint is public by necessity (browsers send no login with it), so it
is rate limited, refuses large bodies, and only logs.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api import security_reports  # noqa: E402
from app.main import app  # noqa: E402
from app.services import rate_limit  # noqa: E402

LEGACY = {
    "csp-report": {
        "document-uri": "https://bhagwati.example/checkout",
        "violated-directive": "script-src-elem",
        "blocked-uri": "https://evil.example/x.js",
    }
}
MODERN = [
    {
        "type": "csp-violation",
        "body": {
            "documentURL": "https://admin.example/orders",
            "effectiveDirective": "connect-src",
            "blockedURL": "https://tracker.example/beacon",
        },
    }
]


class ReceivingReports(unittest.TestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(rate_limit, "hit")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(app)

    def _post(self, body, content_type="application/csp-report"):
        with self.assertLogs(security_reports.logger, level="WARNING") as logs:
            response = self.client.post(
                "/api/security/csp-report", content=json.dumps(body), headers={"Content-Type": content_type}
            )
        return response, "\n".join(logs.output)

    def test_the_older_format_is_logged(self) -> None:
        response, logged = self._post(LEGACY)
        self.assertEqual(response.status_code, 204)
        self.assertIn("script-src-elem", logged)
        self.assertIn("https://evil.example/x.js", logged)

    def test_the_reporting_api_format_is_logged(self) -> None:
        response, logged = self._post(MODERN, "application/reports+json")
        self.assertEqual(response.status_code, 204)
        self.assertIn("connect-src", logged)
        self.assertIn("https://tracker.example/beacon", logged)

    def test_a_query_string_is_not_logged(self) -> None:
        body = {"csp-report": dict(LEGACY["csp-report"], **{"document-uri": "https://s.example/orders?token=abc"})}
        _, logged = self._post(body)
        self.assertNotIn("token=abc", logged)

    def test_a_huge_body_is_refused(self) -> None:
        response = self.client.post(
            "/api/security/csp-report",
            content="x" * (security_reports.MAX_REPORT_BYTES + 1),
            headers={"Content-Type": "application/csp-report"},
        )
        self.assertEqual(response.status_code, 413)

    def test_garbage_is_answered_and_ignored(self) -> None:
        response = self.client.post(
            "/api/security/csp-report", content="not json", headers={"Content-Type": "application/csp-report"}
        )
        self.assertEqual(response.status_code, 204)


class RateLimited(unittest.TestCase):
    def test_the_route_counts_per_ip(self) -> None:
        with mock.patch.object(rate_limit, "hit") as hit:
            TestClient(app).post(
                "/api/security/csp-report", content=json.dumps(LEGACY), headers={"Content-Type": "application/csp-report"}
            )
        self.assertEqual(hit.call_args.args[0], "csp-report")


if __name__ == "__main__":
    unittest.main()

"""Rate limits: how many tries anyone gets, and from where they are counted.

Found in the 2026-10-07 security review: nothing in this backend limited how
often anything could be called. Passwords could be guessed without end, the
six-digit print-agent pairing code could be swept in minutes (a hit streams
every kitchen ticket, with customers' phones and addresses, to the
attacker), anonymous chat could burn the LLM quota, and address and delivery
lookups ran up the paid Google and Pidge bills.

The rules these tests hold:

- A limit is a count of attempts in a fixed window, kept in Redis so every
  API worker shares it.
- Counts are kept per IP address AND per account, so neither rotating
  accounts from one machine nor one account from many machines gets around it.
- The IP is the one Render's proxy recorded (the LAST X-Forwarded-For entry),
  never the first, which the caller writes themselves.
- A refusal is 429 with Retry-After and a sentence a person can act on.
- If Redis is down the request is let through: losing the whole login page to
  a cache outage is the worse failure.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402
from app.services import rate_limit  # noqa: E402


class FakeRedis:
    """INCR/EXPIRE/TTL, enough for a fixed window."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        return True

    def ttl(self, key):
        return 42


def _request(*, forwarded: str | None = None, client: str = "10.0.0.9", cloudflare: str | None = None):
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    if cloudflare:
        headers["cf-connecting-ip"] = cloudflare
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=client))


class WhoIsCalling(unittest.TestCase):
    def test_the_proxys_entry_not_the_callers(self) -> None:
        # The caller wrote "1.1.1.1"; Render appended the address it saw.
        self.assertEqual(rate_limit.client_ip(_request(forwarded="1.1.1.1, 203.0.113.7")), "203.0.113.7")

    def test_one_entry(self) -> None:
        self.assertEqual(rate_limit.client_ip(_request(forwarded="203.0.113.7")), "203.0.113.7")

    def test_no_proxy(self) -> None:
        self.assertEqual(rate_limit.client_ip(_request()), "10.0.0.9")

    def test_on_render_cloudflares_header_wins(self) -> None:
        # Every request to a Render web service passes through Cloudflare,
        # which appends to X-Forwarded-For - so its last entry can be a proxy
        # shared by many customers, who would then share one login limit.
        # Cloudflare overwrites CF-Connecting-IP with the real visitor, so a
        # caller cannot set it.
        request = _request(forwarded="1.1.1.1, 203.0.113.7, 172.71.0.5", cloudflare="203.0.113.7")
        self.assertEqual(rate_limit.client_ip(request), "203.0.113.7")

    def test_a_blank_cloudflare_header_is_ignored(self) -> None:
        request = _request(forwarded="203.0.113.7", cloudflare="  ")
        self.assertEqual(rate_limit.client_ip(request), "203.0.113.7")


class Counting(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = FakeRedis()
        patcher = mock.patch.object(rate_limit, "get_redis_client", return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_up_to_the_limit_then_refused(self) -> None:
        for _ in range(3):
            rate_limit.hit("login", "ip:1.2.3.4", limit=3, window_seconds=60)
        with self.assertRaises(HTTPException) as raised:
            rate_limit.hit("login", "ip:1.2.3.4", limit=3, window_seconds=60)
        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.headers["Retry-After"], "42")
        self.assertIn("42 seconds", raised.exception.detail)

    def test_each_caller_and_each_action_has_its_own_count(self) -> None:
        for _ in range(3):
            rate_limit.hit("login", "ip:1.2.3.4", limit=3, window_seconds=60)
        rate_limit.hit("login", "ip:5.6.7.8", limit=3, window_seconds=60)
        rate_limit.hit("chat", "ip:1.2.3.4", limit=3, window_seconds=60)

    def test_the_identity_is_not_stored_as_typed(self) -> None:
        # Emails and phone numbers do not belong in Redis key names.
        rate_limit.hit("login", "id:someone@example.com", limit=3, window_seconds=60)
        self.assertFalse(any("someone" in key for key in self.redis.counts))

    def test_redis_down_lets_the_request_through(self) -> None:
        broken = mock.Mock()
        broken.incr.side_effect = RedisError("down")
        with mock.patch.object(rate_limit, "get_redis_client", return_value=broken):
            rate_limit.hit("login", "ip:1.2.3.4", limit=0, window_seconds=60)


class OnTheRoutes(unittest.TestCase):
    """The limits are actually attached where the review found none."""

    def setUp(self) -> None:
        self.redis = FakeRedis()
        patcher = mock.patch.object(rate_limit, "get_redis_client", return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)
        # No database: a fake session and the unscoped app, so these tests
        # reach no server. A handler that falls over on the fake session is a
        # 500, which is fine - what is being counted is the attempts.
        from app.config.database import get_db
        from app.dependencies import get_app_scope
        from app.services.app_clients import AppScope

        def _db():
            yield mock.MagicMock()

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_app_scope] = lambda: AppScope()
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app, raise_server_exceptions=False)

    def _exhaust(self, method: str, path: str, json: dict, attempts: int) -> int:
        status_code = 0
        for _ in range(attempts):
            status_code = self.client.request(method, path, json=json).status_code
            if status_code == 429:
                return status_code
        return status_code

    def test_password_guessing_on_one_account_is_stopped(self) -> None:
        body = {"email": f"victim-{uuid.uuid4().hex[:6]}@example.com", "password": "wrong-password"}
        with mock.patch("app.api.auth.authenticate_user", return_value=None):
            self.assertEqual(self._exhaust("POST", "/api/auth/login", body, 40), 429)

    def test_sweeping_pairing_codes_is_stopped(self) -> None:
        status_code = 0
        for code in range(40):
            status_code = self.client.post(
                "/api/print-agents/pair", json={"code": f"{code:06d}", "hostname": "x"}
            ).status_code
            if status_code == 429:
                break
        self.assertEqual(status_code, 429)

    def test_anonymous_chat_is_limited(self) -> None:
        status_code = self._exhaust("POST", "/api/chat/message", {"message": "hi"}, 60)
        self.assertEqual(status_code, 429)


if __name__ == "__main__":
    unittest.main()

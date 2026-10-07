"""Print-agent pairing codes live in Redis, are used once, and expire.

They lived in one API process's memory. With more than one gunicorn worker a
code issued by one could not be redeemed at another, so pairing failed at
random (2026-10-07 security review). Redis is shared by every worker, and a
GET and DELETE in one transaction make redeeming atomic, so a code works
exactly once even if two agents race for it. If Redis is unreachable the process's own memory is used, as before.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from unittest import mock

from redis.exceptions import RedisError

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api import print_agents  # noqa: E402


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttl: dict[str, int] = {}

    def set(self, key, value, ex=None, nx=False):
        if nx and key in self.data:
            return None
        self.data[key] = value
        self.ttl[key] = ex
        return True

    def pipeline(self, transaction=True):
        redis = self

        class Pipe:
            def __init__(self):
                self.ops = []

            def get(self, key):
                self.ops.append(("get", key))

            def delete(self, key):
                self.ops.append(("delete", key))

            def execute(self):
                results = []
                for op, key in self.ops:
                    if op == "get":
                        results.append(redis.data.get(key))
                    else:
                        results.append(1 if redis.data.pop(key, None) is not None else 0)
                return results

        return Pipe()


def _issue():
    return print_agents.issue_pairing_code(
        restaurant_id=uuid.uuid4(), restaurant_location_id=uuid.uuid4(), name="Kitchen PC"
    )


class SharedAcrossWorkers(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = FakeRedis()
        patcher = mock.patch.object(print_agents, "get_redis_client", return_value=self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)
        print_agents._pending_codes.clear()

    def test_a_code_is_stored_in_redis_with_its_lifetime(self) -> None:
        issued = _issue()
        key = f"printpair:{issued['code']}"
        self.assertIn(key, self.redis.data)
        self.assertEqual(self.redis.ttl[key], int(print_agents.PAIRING_CODE_TTL.total_seconds()))
        self.assertEqual(print_agents._pending_codes, {})

    def test_another_worker_can_redeem_it(self) -> None:
        issued = _issue()
        entry = print_agents.redeem_pairing_code(issued["code"])
        self.assertIsNotNone(entry)
        self.assertEqual(entry["name"], "Kitchen PC")

    def test_a_code_works_once(self) -> None:
        issued = _issue()
        self.assertIsNotNone(print_agents.redeem_pairing_code(issued["code"]))
        self.assertIsNone(print_agents.redeem_pairing_code(issued["code"]))

    def test_an_unknown_code(self) -> None:
        self.assertIsNone(print_agents.redeem_pairing_code("000000"))


class WithoutRedis(unittest.TestCase):
    def setUp(self) -> None:
        broken = mock.Mock()
        broken.set.side_effect = RedisError("down")
        broken.pipeline.side_effect = RedisError("down")
        patcher = mock.patch.object(print_agents, "get_redis_client", return_value=broken)
        patcher.start()
        self.addCleanup(patcher.stop)
        print_agents._pending_codes.clear()

    def test_pairing_still_works_in_one_process(self) -> None:
        issued = _issue()
        self.assertIsNotNone(print_agents.redeem_pairing_code(issued["code"]))
        self.assertIsNone(print_agents.redeem_pairing_code(issued["code"]))


if __name__ == "__main__":
    unittest.main()

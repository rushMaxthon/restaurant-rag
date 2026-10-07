"""An owner can only read the result of an AI offer run their restaurant started.

Found in the 2026-10-07 security review: `GET /owner/offers/generate-ai/
{task_id}` returned any Celery task's result to any owner - only "is this an
owner" was checked, never "is this their task". Task ids are random UUIDs,
so this was hard to exploit, but a result is another restaurant's offer
summary. The trigger now records which restaurant a task id belongs to, and
the status route answers 404 for any other - including one it never saw.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

from fastapi import HTTPException

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api import personalized_offers as api  # noqa: E402


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def set(self, key, value, ex=None):
        self.data[key] = value
        return True

    def get(self, key):
        return self.data.get(key)


class WhoseTask(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = FakeRedis()
        for target in (
            mock.patch.object(api, "get_redis_client", return_value=self.redis),
            mock.patch.object(
                api.celery_app,
                "AsyncResult",
                return_value=SimpleNamespace(state="SUCCESS", ready=lambda: True, successful=lambda: True, result={"ok": 1}),
            ),
        ):
            target.start()
            self.addCleanup(target.stop)
        self.mine, self.theirs = uuid.uuid4(), uuid.uuid4()

    def _status(self, task_id: str, restaurant_id: uuid.UUID):
        with mock.patch.object(api, "resolve_owner_restaurant_id", return_value=restaurant_id):
            return api.get_owner_ai_offer_generation_status(task_id, mock.MagicMock(), SimpleNamespace(id=uuid.uuid4()))

    def test_my_own_task(self) -> None:
        api.remember_owner_task("task-1", self.mine)
        self.assertEqual(self._status("task-1", self.mine).summary, {"ok": 1})

    def test_another_restaurants_task_is_not_found(self) -> None:
        api.remember_owner_task("task-2", self.theirs)
        with self.assertRaises(HTTPException) as raised:
            self._status("task-2", self.mine)
        self.assertEqual(raised.exception.status_code, 404)

    def test_a_task_nobody_recorded_is_not_found(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self._status(str(uuid.uuid4()), self.mine)
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()

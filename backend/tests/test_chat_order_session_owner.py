"""A conversation's order can only be placed by the customer who had it.

Found in the 2026-10-07 security review: `/chat/place-order` takes the
conversation id from the browser, and the delivery details the agent
collected are stored under that id alone. Another signed-in customer who
learned it could place an order with the first customer's name, number and
address (charged to themselves, but sending a rider to someone else's door
under their name).

The conversation's history says whose it is. If it belongs to somebody else
the answer is 404 - not 403, which would confirm the conversation exists. A
guest who chatted and then signed in to order has no other owner, and still
can.
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

from app.api import chat  # noqa: E402


def _db(owner_ids):
    db = mock.MagicMock()
    db.scalars.return_value.all.return_value = owner_ids
    return db


class WhoseConversation(unittest.TestCase):
    def test_someone_elses_conversation_is_not_found(self) -> None:
        me, them = uuid.uuid4(), uuid.uuid4()
        with self.assertRaises(HTTPException) as raised:
            chat._require_own_conversation(_db([them]), uuid.uuid4(), SimpleNamespace(id=me))
        self.assertEqual(raised.exception.status_code, 404)

    def test_my_own_conversation_is_fine(self) -> None:
        me = uuid.uuid4()
        chat._require_own_conversation(_db([me]), uuid.uuid4(), SimpleNamespace(id=me))

    def test_a_conversation_with_no_saved_owner_is_fine(self) -> None:
        # A guest's chat, then a sign-in to order.
        chat._require_own_conversation(_db([]), uuid.uuid4(), SimpleNamespace(id=uuid.uuid4()))

    def test_no_conversation_id_is_fine(self) -> None:
        chat._require_own_conversation(_db([uuid.uuid4()]), None, SimpleNamespace(id=uuid.uuid4()))


if __name__ == "__main__":
    unittest.main()

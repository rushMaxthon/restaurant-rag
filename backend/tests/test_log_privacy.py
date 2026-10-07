"""What a customer typed, and how to reach them, stays out of production logs.

Found in the 2026-10-07 security review: the chat code logged every message
in full (customers type their address and number into chat), WhatsApp replies
logged the customer's full phone number, and a failed push logged the whole
device token. Logs are kept longer and read by more people than the
database, and none of them needed the values.

- A phone number is logged as its last four digits.
- A device token as its last eight characters.
- What a customer typed as its length and a short fingerprint in production
  (the same message has the same fingerprint, so it can still be traced),
  and as itself on a developer's machine, where reading it is the point.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import log_privacy  # noqa: E402


class Phones(unittest.TestCase):
    def test_only_the_last_four_digits(self) -> None:
        self.assertEqual(log_privacy.phone("+91 98000 01234"), "…1234")

    def test_nothing_to_show(self) -> None:
        self.assertEqual(log_privacy.phone(None), "-")
        self.assertEqual(log_privacy.phone("12"), "…")


class Tokens(unittest.TestCase):
    def test_only_the_last_eight(self) -> None:
        self.assertEqual(log_privacy.token("a" * 140 + "XYZ12345"), "…XYZ12345")


class WhatTheyTyped(unittest.TestCase):
    def test_production_logs_no_text(self) -> None:
        with mock.patch.object(log_privacy, "_local", return_value=False):
            logged = str(log_privacy.said("deliver to 12 MG Road, call 9800001234"))
        self.assertNotIn("MG Road", logged)
        self.assertNotIn("9800001234", logged)
        self.assertIn("38 chars", logged)

    def test_the_same_message_has_the_same_fingerprint(self) -> None:
        with mock.patch.object(log_privacy, "_local", return_value=False):
            self.assertEqual(str(log_privacy.said("paneer roll")), str(log_privacy.said("paneer roll")))
            self.assertNotEqual(str(log_privacy.said("paneer roll")), str(log_privacy.said("veg roll")))

    def test_a_developer_machine_logs_the_text(self) -> None:
        with mock.patch.object(log_privacy, "_local", return_value=True):
            self.assertEqual(str(log_privacy.said("paneer roll")), "paneer roll")

    def test_nothing_typed(self) -> None:
        with mock.patch.object(log_privacy, "_local", return_value=False):
            self.assertEqual(str(log_privacy.said(None)), "-")


class NoFullValuesInTheseLogLines(unittest.TestCase):
    """The lines the review found, read from the source."""

    def _source(self, path: str) -> str:
        from pathlib import Path

        return (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")

    def test_whatsapp_replies_mask_the_number(self) -> None:
        source = self._source("app/tasks/whatsapp.py")
        self.assertIn("log_privacy.phone(from_number)", source)

    def test_whatsapp_send_failures_mask_the_number(self) -> None:
        source = self._source("app/services/whatsapp.py")
        self.assertNotIn('"WhatsApp send failed for %s", to)', source)

    def test_push_failures_mask_the_token(self) -> None:
        self.assertIn("log_privacy.token(token_value)", self._source("app/services/notifications.py"))

    def test_chat_requests_do_not_log_the_message(self) -> None:
        # Both request log lines (message and stream) wrap the text.
        self.assertEqual(self._source("app/api/chat.py").count("log_privacy.said(payload.message)"), 2)


if __name__ == "__main__":
    unittest.main()

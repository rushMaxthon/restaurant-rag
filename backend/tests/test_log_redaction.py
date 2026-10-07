"""No API key reaches a log line, even inside a URL.

Found 2026-10-07: the HTTP client logs every request URL at INFO, and
Google's geocoding key travels in the query string (`?key=...`) - 24 lines
of one day's local log carried it, and Render's logs would too. Ola Maps
takes its key the same way (`api_key=`). A filter on every handler blanks
key-like query parameters and bearer tokens before anything is written.
"""

from __future__ import annotations

import logging
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import log_privacy  # noqa: E402

SECRET = "AIzaSyDUMMYdummyDUMMYdummyDUMMY123iQAA"


def _render(message: str, *args) -> str:
    record = logging.LogRecord("httpx", logging.INFO, __file__, 1, message, args, None)
    log_privacy.RedactSecrets().filter(record)
    return record.getMessage()


class WhatIsBlanked(unittest.TestCase):
    def test_google_key_in_a_url(self) -> None:
        line = _render('HTTP Request: GET https://maps.googleapis.com/maps/api/geocode/json?address=Surat&key=%s "HTTP/1.1 200 OK"', SECRET)
        self.assertNotIn(SECRET, line)
        self.assertIn("key=[redacted]", line)
        self.assertIn("address=Surat", line)

    def test_ola_api_key_in_a_url(self) -> None:
        line = _render("GET https://api.olamaps.io/places/v1/autocomplete?input=adajan&api_key=%s&location=21,72" % SECRET)
        self.assertNotIn(SECRET, line)
        self.assertIn("location=21,72", line)

    def test_tokens_and_secrets(self) -> None:
        for text in (
            f"access_token={SECRET}",
            f"Authorization: Bearer {SECRET}",
            f"client_secret={SECRET}&x=1",
        ):
            with self.subTest(text=text):
                self.assertNotIn(SECRET, _render(text))

    def test_ordinary_lines_are_untouched(self) -> None:
        line = "Delivery 123 offered to porter for order keyboard=5"
        self.assertEqual(_render(line), line)

    def test_the_api_installs_it(self) -> None:
        import app.main  # noqa: F401

        filters = [f for handler in logging.getLogger().handlers for f in handler.filters]
        self.assertTrue(any(isinstance(f, log_privacy.RedactSecrets) for f in filters))


if __name__ == "__main__":
    unittest.main()

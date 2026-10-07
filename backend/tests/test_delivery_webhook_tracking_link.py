"""A tracking link from the delivery webhook must be Pidge's own.

Found in the 2026-10-07 security review. The webhook's payload is never
trusted for the delivery's STATE - that is re-fetched from Pidge - but the
tracking link is the one thing taken from it, because Pidge only sends it
there. Anyone who knew a delivery id could post a forged webhook with
`tracking_url: https://evil.example/pay-the-rider` and the customer's "Track
your rider" button would open it.

Now a pushed link is kept only when it points at the host of the configured
Pidge tracking page, and a `track_code` must be a plain short code before it
goes into that address.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.delivery import pidge_provider  # noqa: E402


class WhichLinksAreKept(unittest.TestCase):
    def test_a_track_code_becomes_pidges_page(self) -> None:
        self.assertEqual(
            pidge_provider._tracking_url({"track_code": "iaseov"}, {}),
            "https://tracking.pidge.in/?t=iaseov",
        )

    def test_a_link_to_another_site_is_dropped(self) -> None:
        self.assertEqual(
            pidge_provider._tracking_url({"tracking_url": "https://evil.example/pay-the-rider"}, {}), ""
        )

    def test_a_lookalike_host_is_dropped(self) -> None:
        for url in (
            "https://tracking.pidge.in.evil.example/?t=x",
            "https://evil.example/?u=https://tracking.pidge.in/",
            "http://tracking.pidge.in/?t=x",
            "javascript:alert(1)",
        ):
            with self.subTest(url=url):
                self.assertEqual(pidge_provider._tracking_url({"tracking_url": url}, {}), "")

    def test_a_link_on_pidges_own_tracking_host_is_kept(self) -> None:
        url = "https://tracking.pidge.in/?t=abc123"
        self.assertEqual(pidge_provider._tracking_url({"tracking_url": url}, {}), url)

    def test_a_code_carrying_anything_but_a_code_is_dropped(self) -> None:
        for code in ("abc&next=https://evil.example", "../../x", "a b", "x" * 80):
            with self.subTest(code=code):
                self.assertEqual(pidge_provider._tracking_url({"track_code": code}, {}), "")


if __name__ == "__main__":
    unittest.main()

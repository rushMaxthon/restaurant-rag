"""The transport a page uses when it has nothing to say.

A home page cannot ask the chat endpoint for guidance: that endpoint needs a
message, and there is no message here. Without this route the only way to feel
guided is to start a conversation, which is exactly the chat-screen-everywhere
outcome the design rules out.

These tests pin the contract, not the rules — the rules have their own tests
and do not need a database to exercise.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.suggestions import CartLinePayload, SellSuggestionResponse


class SuggestionContractTests(unittest.TestCase):
    def test_the_response_carries_a_basis(self) -> None:
        """`basis` is what stops a category guess being worded as evidence."""

        payload = SellSuggestionResponse(
            kind="cross_sell",
            basis="category_default",
            menu_item_id=uuid.uuid4(),
        )

        self.assertEqual(payload.basis, "category_default")

    def test_a_cart_line_needs_only_identifiers(self) -> None:
        """No prices and no names cross the wire, so there is one price path."""

        line = CartLinePayload(menu_item_id=uuid.uuid4(), quantity=2)

        self.assertEqual(line.quantity, 2)
        self.assertIsNone(line.size_id)
        self.assertEqual(line.customization_option_ids, [])

    def test_an_empty_cart_is_answered_with_no_suggestion_not_an_error(self) -> None:
        """Arriving on the home page with nothing in the cart is the common case."""

        client = TestClient(app)
        response = client.get(
            "/api/suggestions",
            params={"restaurant_location_id": str(uuid.uuid4()), "session_id": str(uuid.uuid4())},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["suggestion"])

    def test_a_malformed_cart_is_ignored_not_rejected(self) -> None:
        """A page calls this on render; guidance must never break a page load.

        `cart` is a JSON string in a query parameter and therefore untrusted in
        a way a typed body would not be — garbage JSON, the wrong shape, or a
        JSON value that is not even a list must all degrade to "no lines"
        rather than surface as a 422 or an unhandled exception.
        """

        client = TestClient(app)
        for garbage_cart in ("{not json", '"just a string"', "42", "null", "[1, 2, 3]"):
            with self.subTest(cart=garbage_cart):
                response = client.get(
                    "/api/suggestions",
                    params={
                        "restaurant_location_id": str(uuid.uuid4()),
                        "session_id": str(uuid.uuid4()),
                        "cart": garbage_cart,
                    },
                )
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.json()["suggestion"])

    def test_declining_a_suggestion_never_needs_a_signed_in_customer(self) -> None:
        """A guest browsing before login can still dismiss a prompt for good."""

        client = TestClient(app)
        response = client.post(
            "/api/suggestions/decline",
            json={"session_id": str(uuid.uuid4()), "menu_item_id": str(uuid.uuid4())},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["suggestion"])


if __name__ == "__main__":
    unittest.main()

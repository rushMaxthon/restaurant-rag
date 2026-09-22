"""Updating a restaurant's settings does not raise before it validates.

Pressing "Disable restaurant" in the admin answered:

    Settings failed — Unable to update restaurant settings.

which is the client's fallback for an error carrying no detail, because a 500
carries none. Behind it:

    app/api/restaurants.py:389, in update_restaurant_settings
        if payload.currency is not None:
    AttributeError: 'RestaurantSettingsUpdate' object has no attribute 'currency'

The handler grew a currency branch when per-restaurant currency shipped and
the schema never grew the field. `payload.currency` is read on the way past
whatever the caller actually changed, so EVERY call to this endpoint raised —
disabling a restaurant, opening one, renaming one, all of it.

No test called this endpoint at all, which is how a whole route stayed
broken. These drive the handler with the real schema and the real permission
rules; only the session and the restaurant row are supplied.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.api import restaurants as endpoint
from app.models.enums import UserRole
from app.schemas.restaurant import RestaurantSettingsUpdate

RESTAURANT_ID = uuid.uuid4()


class TheSchemaCarriesEveryFieldTheHandlerReadsTests(unittest.TestCase):
    """The shape of the bug, checked without a request at all.

    A handler reading a field the schema does not declare is an AttributeError
    on every call. Reading the handler's own source for `payload.<field>` and
    asking the model whether it has them keeps that from happening again to a
    field added later.
    """

    def test_every_payload_field_the_handler_reads_exists(self) -> None:
        import inspect
        import re

        source = inspect.getsource(endpoint.update_restaurant_settings)
        read = set(re.findall(r"payload\.([a-z_0-9]+)", source))
        declared = set(RestaurantSettingsUpdate.model_fields)
        self.assertEqual(
            read - declared,
            set(),
            "the handler reads fields the schema does not declare, so every "
            "call to it raises AttributeError",
        )

    def test_currency_is_one_of_them(self) -> None:
        self.assertIn("currency", RestaurantSettingsUpdate.model_fields)


class TheHandlerAnswersTests(unittest.TestCase):
    """The handler called directly, with the real schema and the real rules.

    Not through the router: the response model wants a fully hydrated
    restaurant, and building one adds nothing — what broke was the schema and
    what matters is the schema, the permission checks and the mutation.
    """

    def setUp(self) -> None:
        self.restaurant = SimpleNamespace(
            id=RESTAURANT_ID, name="Radhe Dhokla", is_active=True, is_open=True,
            currency="INR",
        )
        self.user = SimpleNamespace(id=uuid.uuid4(), role=UserRole.ADMIN)

        class FakeSession:
            def add(_self, _row): pass
            def commit(_self): pass

        self.db = FakeSession()
        self.stack = [
            patch.object(endpoint, "_get_accessible_restaurant",
                         lambda db, rid, user: self.restaurant),
            patch.object(endpoint, "list_restaurant_locations", lambda *a, **k: []),
            patch.object(endpoint, "invalidate_all_personalized_offer_caches",
                         lambda *a, **k: None),
            patch.object(endpoint, "_detail_response", lambda restaurant, **k: restaurant),
        ]
        for item in self.stack:
            item.start()

    def tearDown(self) -> None:
        for item in self.stack:
            item.stop()

    def settings(self, **body):
        """Through the real schema, which is where the bug lived."""

        return endpoint.update_restaurant_settings(
            RESTAURANT_ID,
            RestaurantSettingsUpdate(**body),
            self.db,
            self.user,
        )

    def test_disabling_a_restaurant_succeeds(self) -> None:
        self.settings(is_active=False)
        self.assertFalse(self.restaurant.is_active)

    def test_disabling_also_closes_it(self) -> None:
        # A disabled restaurant that is still "open" would keep taking orders
        # it cannot fulfil.
        self.settings(is_active=False)
        self.assertFalse(self.restaurant.is_open)

    def test_enabling_does_not_reopen_it(self) -> None:
        # Being listed again and being ready to cook are different decisions.
        self.restaurant.is_active, self.restaurant.is_open = False, False
        self.settings(is_active=True)
        self.assertTrue(self.restaurant.is_active)
        self.assertFalse(self.restaurant.is_open)

    def test_a_settings_call_that_touches_nothing_else_still_works(self) -> None:
        # The AttributeError fired on the way PAST whatever was being changed,
        # so the plainest possible call is the one that proves it is gone.
        self.settings(is_open=False)
        self.assertFalse(self.restaurant.is_open)

    def test_a_currency_outside_the_catalogue_is_refused_with_the_list(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self.settings(currency="XYZ")
        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("INR", str(caught.exception.detail), "told what they may type")
        self.assertEqual(self.restaurant.currency, "INR", "and nothing changed")

    def test_a_known_currency_is_normalised(self) -> None:
        self.settings(currency="usd")
        self.assertEqual(self.restaurant.currency, "USD")

    def test_an_owner_may_not_disable_a_restaurant(self) -> None:
        self.user.role = UserRole.OWNER
        with self.assertRaises(HTTPException) as caught:
            self.settings(is_active=False)
        self.assertEqual(caught.exception.status_code, 403)
        self.assertTrue(self.restaurant.is_active)

    def test_an_owner_may_not_change_the_currency(self) -> None:
        # It relabels every price without converting one, so it is a platform
        # decision, not a setting to flip while looking at something else.
        self.user.role = UserRole.OWNER
        with self.assertRaises(HTTPException) as caught:
            self.settings(currency="USD")
        self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual(self.restaurant.currency, "INR")

    def test_an_owner_may_still_open_and_close(self) -> None:
        self.user.role = UserRole.OWNER
        self.settings(is_open=False)
        self.assertFalse(self.restaurant.is_open)


if __name__ == "__main__":
    unittest.main()

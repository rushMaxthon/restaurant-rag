"""Per-restaurant theming: what may be stored, and who may store it."""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.main import app  # noqa: F401 - imported first to settle import order
from app.config.database import get_db
from app.models.enums import UserRole
from app.models.user import User
from app.services.auth import get_current_user
from app.services.restaurant_theme import (
    CUSTOM_PRESET_ID,
    DEFAULT_PRIMARY_COLOR,
    THEME_PRESETS,
    ThemeValidationError,
    normalize_color,
    read_theme,
    resolve_theme,
)


class ThemeResolutionTests(unittest.TestCase):
    def test_a_named_preset_stores_its_own_colour(self) -> None:
        resolved = resolve_theme(preset_id="ocean", primary_color=None)
        self.assertEqual(resolved["preset"], "ocean")
        self.assertEqual(resolved["primary_color"], "#2D7FF9")

    def test_a_preset_wins_over_a_colour_sent_alongside_it(self) -> None:
        # The form keeps a colour in its custom field while a preset is picked;
        # the preset is the deliberate choice.
        resolved = resolve_theme(preset_id="forest", primary_color="#123456")
        self.assertEqual(resolved["primary_color"], "#2E7D32")

    def test_a_custom_colour_is_stored_and_marked_custom(self) -> None:
        resolved = resolve_theme(preset_id=CUSTOM_PRESET_ID, primary_color="#123456")
        self.assertEqual(resolved["preset"], CUSTOM_PRESET_ID)
        self.assertEqual(resolved["primary_color"], "#123456")

    def test_a_custom_colour_matching_a_preset_is_recorded_as_that_preset(self) -> None:
        # Otherwise the gallery would show nothing selected for a colour that is
        # plainly one of the presets.
        resolved = resolve_theme(preset_id=CUSTOM_PRESET_ID, primary_color="#2d7ff9")
        self.assertEqual(resolved["preset"], "ocean")

    def test_an_unknown_preset_is_refused(self) -> None:
        with self.assertRaises(ThemeValidationError):
            resolve_theme(preset_id="neon", primary_color=None)

    def test_a_malformed_colour_is_refused(self) -> None:
        for bad in ("", "red", "#FFF", "#GGGGGG", "FF5200"):
            with self.assertRaises(ThemeValidationError):
                normalize_color(bad)

    def test_colour_is_normalised_to_upper_case(self) -> None:
        self.assertEqual(normalize_color("  #ff5200 "), "#FF5200")

    def test_every_preset_is_a_valid_storable_colour(self) -> None:
        for preset in THEME_PRESETS:
            self.assertEqual(normalize_color(preset.primary_color), preset.primary_color)


class ThemeReadTests(unittest.TestCase):
    def test_an_unset_restaurant_reads_as_the_platform_default(self) -> None:
        stored = read_theme(Mock(theme={}))
        self.assertEqual(stored["primary_color"], DEFAULT_PRIMARY_COLOR)

    def test_a_corrupt_stored_value_falls_back_rather_than_breaking_the_app(self) -> None:
        # A bad colour reaching the device would render an unthemed or crashed
        # screen; falling back keeps the app usable.
        for bad in ({"primary_color": "chartreuse"}, {"primary_color": 42}, None):
            self.assertEqual(
                read_theme(Mock(theme=bad))["primary_color"], DEFAULT_PRIMARY_COLOR
            )

    def test_a_stored_colour_is_returned_upper_cased(self) -> None:
        self.assertEqual(
            read_theme(Mock(theme={"primary_color": "#2d7ff9"}))["primary_color"],
            "#2D7FF9",
        )


class OwnerThemeApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.restaurant_id = uuid.uuid4()
        self.owner = User(
            id=uuid.uuid4(), full_name="Owner", email="theme-owner@test.local",
            phone_number=None, hashed_password="x", role=UserRole.OWNER,
            is_active=True, is_verified=True, default_address=None,
        )
        self.db = Mock()

        def override_db():
            yield self.db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = lambda: self.owner

    def _restaurant(self) -> Mock:
        restaurant = Mock(id=self.restaurant_id, theme={})
        restaurant.name = "Test Kitchen"
        return restaurant

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        self.client.close()

    @patch("app.api.restaurants._theme_restaurant_for")
    def test_an_owner_can_read_their_theme_and_the_gallery(self, mock_scope: Mock) -> None:
        mock_scope.return_value = self._restaurant()
        response = self.client.get(f"/api/restaurants/{self.restaurant_id}/theme")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["primary_color"], DEFAULT_PRIMARY_COLOR)
        self.assertEqual(len(body["presets"]), len(THEME_PRESETS))
        # Carried so the preview can label itself without a second request.
        self.assertEqual(body["restaurant_name"], "Test Kitchen")

    @patch("app.api.restaurants._theme_restaurant_for")
    def test_an_owner_can_set_a_preset(self, mock_scope: Mock) -> None:
        restaurant = self._restaurant()
        mock_scope.return_value = restaurant
        response = self.client.put(
            f"/api/restaurants/{self.restaurant_id}/theme", json={"preset": "ocean"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["primary_color"], "#2D7FF9")
        self.assertEqual(restaurant.theme["primary_color"], "#2D7FF9")

    @patch("app.api.restaurants._theme_restaurant_for")
    def test_an_unknown_preset_is_a_422_not_a_crash(self, mock_scope: Mock) -> None:
        mock_scope.return_value = self._restaurant()
        response = self.client.put(
            f"/api/restaurants/{self.restaurant_id}/theme", json={"preset": "neon"}
        )
        self.assertEqual(response.status_code, 422)

    @patch("app.api.restaurants._theme_restaurant_for")
    def test_a_malformed_custom_colour_is_rejected(self, mock_scope: Mock) -> None:
        mock_scope.return_value = self._restaurant()
        response = self.client.put(
            f"/api/restaurants/{self.restaurant_id}/theme",
            json={"preset": "custom", "primary_color": "not-a-colour"},
        )
        self.assertEqual(response.status_code, 422)

    @patch("app.api.restaurants._theme_restaurant_for")
    def test_another_owners_restaurant_is_not_found(self, mock_scope: Mock) -> None:
        # A 404 rather than a 403: the endpoint must not confirm the id exists.
        mock_scope.side_effect = HTTPException(status_code=404, detail="Restaurant not found")
        response = self.client.put(
            f"/api/restaurants/{self.restaurant_id}/theme", json={"preset": "ocean"}
        )
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

"""Ola Maps: address suggestions, place details and address lookup for India.

Chosen 2026-10-07 after Google refused the platform's key (billing switched
off): Ola's free tier is 100,000 requests a month per API with no card or
credits needed, its data is built for Indian addresses, and each suggestion
already carries coordinates. Its responses use Google's older JSON shape
(`formatted_address`, `geometry.location`, `geometry.location_type`,
`address_components[].long_name/types`), so Google's own tested readers
(`confidence_for`, `address_parts`) are reused rather than copied.

These tests answer with Ola-shaped JSON; nothing here calls Ola.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

import httpx

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.geocoding import ola  # noqa: E402
from app.services.geocoding.base import AddressQuery, GeocodeConfidence, GeocodingError  # noqa: E402

AUTOCOMPLETE = {
    "status": "ok",
    "predictions": [
        {
            "description": "Rander Road, Adajan, Surat, Gujarat, 395009, India",
            "place_id": "ola-platform:abc123",
            "structured_formatting": {"main_text": "Rander Road", "secondary_text": "Adajan, Surat, Gujarat"},
            "geometry": {"location": {"lat": 21.2049, "lng": 72.7985}},
            "types": ["route"],
        },
        {"description": "no id", "structured_formatting": {"main_text": "x"}},
    ],
}
GEOCODE = {
    "status": "ok",
    "geocodingResults": [
        {
            "formatted_address": "Rander Road, Adajan, Surat, Gujarat 395009, India",
            "types": ["route"],
            "geometry": {"location": {"lat": 21.2049, "lng": 72.7985}, "location_type": "GEOMETRIC_CENTER"},
            "address_components": [],
        }
    ],
}
DETAILS = {
    "status": "ok",
    "result": {
        "name": "Shivam Society",
        "formatted_address": "Shivam Society, Rander Road, Adajan, Surat, Gujarat 395009, India",
        "geometry": {"location": {"lat": 21.2051, "lng": 72.7990}},
        "address_components": [
            {"long_name": "Rander Road", "types": ["route"]},
            {"long_name": "Adajan", "types": ["sublocality_level_1", "sublocality"]},
            {"long_name": "Surat", "types": ["locality"]},
            {"long_name": "Gujarat", "types": ["administrative_area_level_1"]},
            {"long_name": "395009", "types": ["postal_code"]},
            {"long_name": "India", "types": ["country"]},
        ],
    },
}


def _answer(payload, status=200):
    return httpx.Response(status, json=payload, request=httpx.Request("GET", "https://api.olamaps.io/x"))


def _provider():
    return ola.OlaMapsGeocoder(api_key="test-key", timeout_seconds=3, country_codes="in")


class Suggestions(unittest.TestCase):
    def test_each_suggestion_has_an_id_and_two_line_label(self) -> None:
        with mock.patch.object(ola.httpx, "get", return_value=_answer(AUTOCOMPLETE)) as get:
            found = _provider().suggest("rander", session_token="s1", latitude=21.17, longitude=72.83)
        self.assertEqual(
            found,
            [{
                "place_id": "ola-platform:abc123",
                "primary": "Rander Road",
                "secondary": "Adajan, Surat, Gujarat",
                "description": "Rander Road, Adajan, Surat, Gujarat, 395009, India",
            }],
        )
        params = get.call_args.kwargs["params"]
        self.assertEqual(params["input"], "rander")
        self.assertEqual(params["location"], "21.17,72.83")
        self.assertEqual(params["api_key"], "test-key")
        self.assertIn("X-Request-Id", get.call_args.kwargs["headers"])

    def test_nothing_typed_asks_nobody(self) -> None:
        with mock.patch.object(ola.httpx, "get") as get:
            self.assertEqual(_provider().suggest("  ", session_token=""), [])
        get.assert_not_called()


class PickingASuggestion(unittest.TestCase):
    def test_the_chosen_place_is_a_rooftop_with_its_address_parts(self) -> None:
        with mock.patch.object(ola.httpx, "get", return_value=_answer(DETAILS)):
            point, parts = _provider().resolve("ola-platform:abc123", session_token="s1")
        self.assertEqual((point.latitude, point.longitude), (21.2051, 72.7990))
        self.assertEqual(point.confidence, GeocodeConfidence.ROOFTOP)
        self.assertEqual(point.provider, "ola")
        self.assertEqual(parts["line1"], "Rander Road")
        self.assertEqual(parts["line2"], "Adajan")
        self.assertEqual(parts["city"], "Surat")
        self.assertEqual(parts["postal_code"], "395009")


class TypedAddresses(unittest.TestCase):
    def test_a_typed_address_is_placed_and_graded(self) -> None:
        query = AddressQuery(line1="Rander Road", city="Surat", state="Gujarat", postal_code="395009", country="India")
        with mock.patch.object(ola.httpx, "get", return_value=_answer(GEOCODE)) as get:
            point = _provider().geocode(query)
        self.assertEqual((point.latitude, point.longitude), (21.2049, 72.7985))
        self.assertTrue(point.confidence.is_precise)
        self.assertIn("Rander Road", get.call_args.kwargs["params"]["address"])

    def test_nothing_found(self) -> None:
        with mock.patch.object(ola.httpx, "get", return_value=_answer({"status": "ok", "geocodingResults": []})):
            self.assertIsNone(_provider().geocode(AddressQuery(freeform="zzzz qqqq")))


class WhenOlaRefuses(unittest.TestCase):
    def test_a_bad_key_is_not_worth_retrying(self) -> None:
        with mock.patch.object(ola.httpx, "get", return_value=_answer({"message": "Invalid API key"}, status=401)):
            with self.assertRaises(GeocodingError) as raised:
                _provider().suggest("rander", session_token="")
        self.assertFalse(raised.exception.retryable)

    def test_their_outage_is(self) -> None:
        with mock.patch.object(ola.httpx, "get", return_value=_answer({}, status=503)):
            with self.assertRaises(GeocodingError) as raised:
                _provider().suggest("rander", session_token="")
        self.assertTrue(raised.exception.retryable)

    def test_unreachable(self) -> None:
        with mock.patch.object(ola.httpx, "get", side_effect=httpx.ConnectTimeout("slow")):
            with self.assertRaises(GeocodingError):
                _provider().suggest("rander", session_token="")


class ChosenOverGoogle(unittest.TestCase):
    def test_with_an_ola_key_ola_answers_both(self) -> None:
        from app.services.geocoding import registry

        with mock.patch.dict(os.environ, {"OLA_MAPS_API_KEY": "k"}):
            from app.config import get_settings

            get_settings.cache_clear()
            registry._geocoder = None
            try:
                self.assertIsInstance(registry.geocoder(), ola.OlaMapsGeocoder)
                self.assertIsInstance(registry.places_geocoder(), ola.OlaMapsGeocoder)
            finally:
                registry._geocoder = None
                get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()

"""When Google refuses the key, addresses are still located - and someone is told.

Found 2026-10-07: every Google call was answered REQUEST_DENIED ("You must
enable Billing on the Google Cloud Project") and Places with 403. With a key
configured the code used Google only, so nothing could be located: the
address dropdown came back empty, checkout said "we could not find that
address on a map", and a branch with no flat fee could not take a delivery
order at all. Nobody saw it until a customer did.

Two changes:

- A refusal that will not go away by retrying (a key or billing problem) is
  answered by OpenStreetMap's Nominatim instead, so addresses are located,
  priced by distance and accepted. Suggestions-as-you-type still need Google:
  Nominatim's terms forbid autocomplete.
- The refusal is recorded, and Platform watch shows "Google Maps" as DOWN with
  what to do, until Google answers again.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import platform_watch  # noqa: E402
from app.services.geocoding import health, service  # noqa: E402
from app.services.geocoding.base import AddressQuery, GeocodedPoint, GeocodeConfidence, GeocodingError  # noqa: E402


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value, ex=None):
        self.data[key] = value
        return True

    def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)
        return 1


POINT = GeocodedPoint(
    latitude=21.17, longitude=72.83, confidence=GeocodeConfidence.ROOFTOP, matched="Adajan, Surat", provider="nominatim"
)
QUERY = AddressQuery(line1="12 Craft Road", city="Surat", state="Gujarat", postal_code="395009", country="India")


class _WithRedis(unittest.TestCase):
    def setUp(self) -> None:
        self.redis = FakeRedis()
        for target in (
            mock.patch.object(health, "get_redis_client", return_value=self.redis),
            mock.patch.object(service, "cache_get_json", return_value=None),
            mock.patch.object(service, "_store"),
        ):
            target.start()
            self.addCleanup(target.stop)


class LocatingWhenGoogleRefuses(_WithRedis):
    def _locate(self, google_error=None, google_point=None):
        google = mock.Mock(name="google")
        google.name = "google"
        if google_error is not None:
            google.geocode.side_effect = google_error
        else:
            google.geocode.return_value = google_point
        fallback = mock.Mock(name="nominatim")
        fallback.name = "nominatim"
        fallback.geocode.return_value = POINT
        db = mock.MagicMock()
        db.scalar.return_value = None
        with mock.patch.object(service, "geocoder", return_value=google), mock.patch.object(
            service, "fallback_geocoder", return_value=fallback
        ), mock.patch.object(service, "_is_google", return_value=True):
            return service.locate(db, QUERY), fallback

    def test_a_billing_refusal_is_answered_by_openstreetmap(self) -> None:
        point, fallback = self._locate(GeocodingError("Google answered REQUEST_DENIED: enable Billing", retryable=False))
        self.assertEqual(point, POINT)
        fallback.geocode.assert_called_once()

    def test_the_refusal_is_recorded_for_platform_watch(self) -> None:
        self._locate(GeocodingError("Google answered REQUEST_DENIED: enable Billing", retryable=False))
        refusal = health.last_refusal()
        self.assertIsNotNone(refusal)
        self.assertIn("Billing", refusal["message"])

    def test_a_passing_blip_is_not_sent_elsewhere(self) -> None:
        # Retryable (a timeout, a 500): the address is fine and Google will be
        # back; answering from a less precise source would price it worse.
        point, fallback = self._locate(GeocodingError("Could not reach Google: timeout", retryable=True))
        self.assertIsNone(point)
        fallback.geocode.assert_not_called()
        self.assertIsNone(health.last_refusal())

    def test_google_answering_again_clears_the_alarm(self) -> None:
        health.record_refusal("geocode", "denied")
        self._locate(google_point=POINT)
        self.assertIsNone(health.last_refusal())


class PlatformWatchSaysSo(_WithRedis):
    def test_a_recent_refusal_is_down_with_what_to_do(self) -> None:
        health.record_refusal("places", "403 The caller does not have permission")
        with mock.patch.object(platform_watch, "_google_configured", return_value=True):
            check = platform_watch._check_maps(datetime.now(UTC))
        self.assertEqual(check.status, platform_watch.DOWN)
        self.assertIn("billing", check.hint.lower())

    def test_an_old_refusal_is_not_todays_problem(self) -> None:
        old = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
        self.redis.data[health.REFUSAL_KEY] = '{"at": "%s", "service": "geocode", "message": "x"}' % old
        with mock.patch.object(platform_watch, "_google_configured", return_value=True):
            check = platform_watch._check_maps(datetime.now(UTC))
        self.assertEqual(check.status, platform_watch.OK)

    def test_no_key_is_a_warning_not_an_outage(self) -> None:
        with mock.patch.object(platform_watch, "_google_configured", return_value=False):
            check = platform_watch._check_maps(datetime.now(UTC))
        self.assertEqual(check.status, platform_watch.WARN)

    def test_it_is_one_of_the_checks(self) -> None:
        self.assertIn("maps", platform_watch._LABELS)


if __name__ == "__main__":
    unittest.main()

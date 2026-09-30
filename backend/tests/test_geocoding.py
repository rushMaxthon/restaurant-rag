"""Turning an address into a point, and refusing to pretend.

The failure this whole module guards against is specific and quiet. A geocoder
ALWAYS answers. Ask it for "12 Fake Street, Nowhere" and it returns the centroid
of the nearest city, or of the country, with a 200 and no complaint. A delivery
priced from a country centroid is a real courier price for a trip nobody is
taking, and it looks exactly like a correct answer.

So most of what is tested here is the grading, not the lookup: which answers are
precise enough to charge somebody for, which are coordinates that happen to be
in the right region, and the fact that the two are never confused.

Two findings from running this against the live services are encoded below:

* Nominatim's STRUCTURED search returns nothing for landmark and society
  addresses, which is how most Indian addresses are written. Freeform finds
  them. `test_nominatim_asks_freeform` is what stops that being undone.
* A remembered MISS is cached, so a broken provider configuration poisons the
  cache. `test_a_transport_failure_is_not_remembered` is the guard: only an
  actual "no match" may be stored.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import get_settings  # noqa: E402
from app.services.geocoding import google as google_module  # noqa: E402
from app.services.geocoding import nominatim as nominatim_module  # noqa: E402
from app.services.geocoding import service as geocode_service  # noqa: E402
from app.services.geocoding.base import (  # noqa: E402
    AddressQuery,
    GeocodeConfidence,
    GeocodedPoint,
    GeocodingError,
)
from app.services.geocoding.registry import geocoder, places_geocoder, reset_geocoder  # noqa: E402


class WhatCountsAsPreciseEnoughToCharge(unittest.TestCase):
    """The one decision this package exists to make."""

    def test_only_a_building_or_a_street_may_price_a_delivery(self) -> None:
        self.assertTrue(GeocodeConfidence.ROOFTOP.is_precise)
        self.assertTrue(GeocodeConfidence.STREET.is_precise)

    def test_a_postcode_is_not_an_address(self) -> None:
        # Measured: an Indian PIN code resolves, and it spans kilometres. A
        # delivery priced from the middle of one is priced from nowhere in
        # particular.
        self.assertFalse(GeocodeConfidence.POSTCODE.is_precise)

    def test_a_locality_or_region_is_never_precise(self) -> None:
        self.assertFalse(GeocodeConfidence.LOCALITY.is_precise)
        self.assertFalse(GeocodeConfidence.REGION.is_precise)


class BuildingTheQuery(unittest.TestCase):
    def test_parts_are_joined_postally(self) -> None:
        query = AddressQuery(
            line1="12 MG Road",
            city="Ahmedabad",
            state="Gujarat",
            postal_code="380009",
            country="India",
        )
        self.assertEqual(query.as_text(), "12 MG Road, Ahmedabad, Gujarat, 380009, India")

    def test_freeform_is_used_when_there_are_no_parts(self) -> None:
        # Every address stored before the structured form existed.
        self.assertEqual(
            AddressQuery(freeform="102 Demo Street, Ahmedabad").as_text(),
            "102 Demo Street, Ahmedabad",
        )

    def test_the_cache_key_ignores_case_and_spacing(self) -> None:
        # Otherwise "12 MG Road" and "12  mg  road" are two lookups and, with
        # a paid provider, two charges for one answer.
        a = AddressQuery(line1="12 MG  Road", city="Ahmedabad")
        b = AddressQuery(line1="12 mg road", city="ahmedabad")
        self.assertEqual(a.cache_key(), b.cache_key())

    def test_an_empty_query_is_recognised(self) -> None:
        self.assertTrue(AddressQuery().is_empty)
        self.assertTrue(AddressQuery(country="India").is_empty)
        self.assertFalse(AddressQuery(line1="12 MG Road").is_empty)


class ReadingNominatim(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = nominatim_module.NominatimGeocoder(user_agent="tests/1.0")

    def test_nominatim_asks_freeform(self) -> None:
        # MEASURED, not assumed. Their structured search treats `street` as a
        # field that must match an OSM street and will not fall back:
        # "Kankaria Lake, Ahmedabad, Gujarat, India" returns the lake as
        # freeform and NOTHING as structured. Indian addresses are written from
        # landmarks and society names far more often than numbered streets, so
        # structured search fails on most real input here — with a 200 and an
        # empty list, which reads exactly like "no such address".
        seen: dict[str, object] = {}

        class Reply:
            status_code = 200

            @staticmethod
            def json():
                return []

        def fake_get(url, params=None, headers=None, timeout=None):
            seen.update(params or {})
            return Reply()

        with mock.patch.object(nominatim_module.httpx, "get", side_effect=fake_get):
            self.provider.geocode(AddressQuery(line1="Kankaria Lake", city="Ahmedabad"))

        self.assertIn("q", seen)
        self.assertNotIn("street", seen)

    def test_the_user_agent_is_always_sent(self) -> None:
        # Their usage policy treats a default library agent as abuse and blocks
        # by it. An omitted header is a banned IP for everybody.
        seen: dict[str, object] = {}

        class Reply:
            status_code = 200

            @staticmethod
            def json():
                return []

        def fake_get(url, params=None, headers=None, timeout=None):
            seen.update(headers or {})
            return Reply()

        with mock.patch.object(nominatim_module.httpx, "get", side_effect=fake_get):
            self.provider.geocode(AddressQuery(line1="anywhere"))
        self.assertEqual(seen.get("User-Agent"), "tests/1.0")

    def test_a_building_is_a_rooftop_and_a_lake_is_not(self) -> None:
        # A lake, a park or a river is a landmark people navigate by, not a
        # door a rider can hand food to.
        self.assertEqual(
            nominatim_module.confidence_for({"addresstype": "building"}),
            GeocodeConfidence.ROOFTOP,
        )
        self.assertEqual(
            nominatim_module.confidence_for({"addresstype": "lake"}),
            GeocodeConfidence.LOCALITY,
        )

    def test_an_unknown_type_is_never_mistaken_for_a_rooftop(self) -> None:
        self.assertEqual(
            nominatim_module.confidence_for({"addresstype": "something_new"}),
            GeocodeConfidence.LOCALITY,
        )

    def test_rate_limiting_is_reported_as_retryable(self) -> None:
        class Reply:
            status_code = 429
            text = "slow down"

        with mock.patch.object(nominatim_module.httpx, "get", return_value=Reply()):
            with self.assertRaises(GeocodingError) as caught:
                self.provider.geocode(AddressQuery(line1="anywhere"))
        self.assertTrue(caught.exception.retryable)

    def test_a_result_with_no_coordinates_is_a_miss_not_an_error(self) -> None:
        class Reply:
            status_code = 200

            @staticmethod
            def json():
                return [{"display_name": "somewhere"}]

        with mock.patch.object(nominatim_module.httpx, "get", return_value=Reply()):
            self.assertIsNone(self.provider.geocode(AddressQuery(line1="anywhere")))


class ReadingGoogle(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = google_module.GoogleGeocoder(api_key="k")

    def test_a_society_entrance_is_precise_despite_an_approximate_location_type(self) -> None:
        # The case that made this read both fields. A society or mall entrance
        # comes back `establishment` with `location_type: APPROXIMATE`, and
        # reading only the latter refuses to price a perfectly deliverable
        # address.
        result = {
            "types": ["establishment", "point_of_interest"],
            "geometry": {"location_type": "APPROXIMATE"},
        }
        self.assertTrue(google_module.confidence_for(result).is_precise)

    def test_a_postcode_result_is_not_precise(self) -> None:
        result = {"types": ["postal_code"], "geometry": {"location_type": "APPROXIMATE"}}
        self.assertFalse(google_module.confidence_for(result).is_precise)

    def test_a_rejected_key_is_not_retryable(self) -> None:
        # REQUEST_DENIED is a key or billing problem and fails identically
        # forever; retrying it is noise in a log and a slower checkout.
        class Reply:
            status_code = 200

            @staticmethod
            def json():
                return {"status": "REQUEST_DENIED", "error_message": "bad key"}

        with mock.patch.object(google_module.httpx, "get", return_value=Reply()):
            with self.assertRaises(GeocodingError) as caught:
                self.provider.geocode(AddressQuery(line1="anywhere"))
        self.assertFalse(caught.exception.retryable)

    def test_zero_results_is_an_answer_not_an_error(self) -> None:
        class Reply:
            status_code = 200

            @staticmethod
            def json():
                return {"status": "ZERO_RESULTS", "results": []}

        with mock.patch.object(google_module.httpx, "get", return_value=Reply()):
            self.assertIsNone(self.provider.geocode(AddressQuery(line1="anywhere")))

    def test_a_house_number_and_street_become_one_line(self) -> None:
        parts = google_module.address_parts(
            {
                "formatted_address": "12 MG Road, Ahmedabad, Gujarat 380009, India",
                "address_components": [
                    {"long_name": "12", "types": ["street_number"]},
                    {"long_name": "MG Road", "types": ["route"]},
                    {"long_name": "Navrangpura", "types": ["sublocality_level_1"]},
                    {"long_name": "Ahmedabad", "types": ["locality"]},
                    {"long_name": "Gujarat", "types": ["administrative_area_level_1"]},
                    {"long_name": "380009", "types": ["postal_code"]},
                    {"long_name": "India", "types": ["country"]},
                ],
            }
        )
        self.assertEqual(parts["line1"], "12 MG Road")
        self.assertEqual(parts["city"], "Ahmedabad")
        self.assertEqual(parts["state"], "Gujarat")
        self.assertEqual(parts["postal_code"], "380009")

    def test_a_named_building_with_no_street_number_uses_its_name(self) -> None:
        # How a great many Indian addresses identify themselves: the society or
        # complex name IS the address, and there is no route component.
        parts = google_module.address_parts(
            {
                "name": "Shivalik Plaza",
                "formatted_address": "Shivalik Plaza, Ahmedabad",
                "address_components": [{"long_name": "Ahmedabad", "types": ["locality"]}],
            }
        )
        self.assertEqual(parts["line1"], "Shivalik Plaza")

    def test_autocomplete_uses_the_new_places_api(self) -> None:
        """The legacy endpoints cannot be enabled at all on a new project.

        Places went legacy on 1 March 2025 and does not appear in the Cloud
        console for any project created after it, so legacy calls fail on every
        new deployment with a 403 that reads exactly like a bad key. Geocoding
        is unaffected and stays on the old host, which is why only this half
        moved.
        """

        seen: dict[str, object] = {}

        class Reply:
            status_code = 200

            @staticmethod
            def json():
                return {"suggestions": []}

        def fake_request(method, url, headers=None, timeout=None, **kwargs):
            seen["method"] = method
            seen["url"] = url
            seen["headers"] = headers or {}
            seen["json"] = kwargs.get("json") or {}
            return Reply()

        with mock.patch.object(google_module.httpx, "request", side_effect=fake_request):
            self.provider.suggest("12 MG", session_token="tok-1")

        self.assertEqual(seen["method"], "POST")
        self.assertIn("places.googleapis.com/v1/places:autocomplete", seen["url"])
        # The key travels in a header now, not a query string — which is better
        # anyway, because query strings end up in access logs and proxies.
        self.assertEqual(seen["headers"].get("X-Goog-Api-Key"), "k")
        # The field mask is mandatory AND is the billing model: you pay for the
        # fields you ask for, so asking for everything is a standing charge.
        self.assertIn("X-Goog-FieldMask", seen["headers"])
        self.assertNotIn("*", seen["headers"]["X-Goog-FieldMask"])

    def test_autocomplete_carries_a_session_token(self) -> None:
        # Billed per SESSION when the keystrokes and the details call share a
        # token, and per REQUEST when they do not. Dropping it turns one charge
        # into one per character typed.
        seen: dict[str, object] = {}

        class Reply:
            status_code = 200

            @staticmethod
            def json():
                return {"suggestions": []}

        def fake_request(method, url, headers=None, timeout=None, **kwargs):
            seen.update(kwargs.get("json") or {})
            return Reply()

        with mock.patch.object(google_module.httpx, "request", side_effect=fake_request):
            self.provider.suggest("12 MG", session_token="tok-1")
        self.assertEqual(seen.get("sessionToken"), "tok-1")

    def test_autocomplete_does_not_filter_out_establishments(self) -> None:
        # The legacy version restricted results to street addresses, and that
        # was wrong for this market: a great many Indian addresses are a
        # society, a complex or a mall, which the API classes as establishments.
        seen: dict[str, object] = {}

        class Reply:
            status_code = 200

            @staticmethod
            def json():
                return {"suggestions": []}

        def fake_request(method, url, headers=None, timeout=None, **kwargs):
            seen.update(kwargs.get("json") or {})
            return Reply()

        with mock.patch.object(google_module.httpx, "request", side_effect=fake_request):
            self.provider.suggest("Shivalik Plaza", session_token="t")
        self.assertNotIn("includedPrimaryTypes", seen)

    def test_a_picked_place_is_read_from_the_new_shape(self) -> None:
        # `location.latitude`, `addressComponents[].longText` and
        # `displayName.text` — a different envelope around the same component
        # types.
        class Reply:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "id": "ChIJ123",
                    "formattedAddress": "Shivalik Plaza, Ahmedabad, Gujarat 380009, India",
                    "location": {"latitude": 23.0261, "longitude": 72.5567},
                    "displayName": {"text": "Shivalik Plaza", "languageCode": "en"},
                    "addressComponents": [
                        {"longText": "Navrangpura", "types": ["sublocality_level_1"]},
                        {"longText": "Ahmedabad", "types": ["locality"]},
                        {"longText": "Gujarat", "types": ["administrative_area_level_1"]},
                        {"longText": "380009", "types": ["postal_code"]},
                    ],
                }

        with mock.patch.object(google_module.httpx, "request", return_value=Reply()):
            resolved = self.provider.resolve("ChIJ123", session_token="t")

        self.assertIsNotNone(resolved)
        point, parts = resolved
        self.assertEqual((point.latitude, point.longitude), (23.0261, 72.5567))
        # The customer chose this building from a list. There is no more precise
        # statement available, and the new API offers no location_type to
        # second-guess it with.
        self.assertTrue(point.is_precise)
        # A named complex with no street number: the name IS the address, which
        # is how a great many Indian addresses identify themselves.
        self.assertEqual(parts["line1"], "Shivalik Plaza")
        self.assertEqual(parts["city"], "Ahmedabad")
        self.assertEqual(parts["postal_code"], "380009")

    def test_a_places_api_not_enabled_error_is_not_retried(self) -> None:
        # The 403 somebody will actually hit: the key is fine and the API was
        # never switched on. Their message says so, and surfacing it is the
        # difference between a five-second fix and an afternoon.
        class Reply:
            status_code = 403
            text = ""

            @staticmethod
            def json():
                return {
                    "error": {
                        "code": 403,
                        "message": "Places API (New) has not been used in project 1 before",
                        "status": "PERMISSION_DENIED",
                    }
                }

        with mock.patch.object(google_module.httpx, "request", return_value=Reply()):
            with self.assertRaises(GeocodingError) as caught:
                self.provider.suggest("anything", session_token="t")
        self.assertFalse(caught.exception.retryable)
        self.assertIn("has not been used in project", str(caught.exception))


class WhichGeocoderAnswers(unittest.TestCase):
    def setUp(self) -> None:
        reset_geocoder()
        get_settings.cache_clear()
        self.addCleanup(reset_geocoder)
        self.addCleanup(get_settings.cache_clear)

    def test_google_wins_when_a_key_exists(self) -> None:
        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "k"}):
            get_settings.cache_clear()
            self.assertEqual(geocoder().name, "google")

    def test_openstreetmap_answers_with_no_key_at_all(self) -> None:
        # The reason the delivery quote is real in every deployment rather than
        # only the ones that have been through a Cloud console.
        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": ""}):
            get_settings.cache_clear()
            self.assertEqual(geocoder().name, "nominatim")

    def test_there_is_no_autocomplete_without_google(self) -> None:
        # A dropdown that cannot rank, cannot batch a session and is limited to
        # one request per second is worse than no dropdown, so the checkout
        # shows plain text boxes instead.
        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": ""}):
            get_settings.cache_clear()
            self.assertIsNone(places_geocoder())
        reset_geocoder()
        with mock.patch.dict(os.environ, {"GOOGLE_MAPS_API_KEY": "k"}):
            get_settings.cache_clear()
            self.assertIsNotNone(places_geocoder())


class WhatIsRemembered(unittest.TestCase):
    """A geocode is looked up once. A failure to ASK is not a lookup."""

    def setUp(self) -> None:
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)

    def _db(self) -> mock.Mock:
        db = mock.MagicMock()
        db.scalar.return_value = None
        return db

    def test_a_transport_failure_is_not_remembered(self) -> None:
        # The guard that matters. A timeout or a rejected key says nothing about
        # the address; caching it as "not found" would blind us to a perfectly
        # good address for as long as the entry lived. Found the hard way: a
        # broken provider configuration cached misses for every address tried
        # during it.
        provider = mock.Mock()
        provider.name = "x"
        provider.geocode.side_effect = GeocodingError("timeout")
        db = self._db()
        with mock.patch.object(geocode_service, "geocoder", return_value=provider):
            with mock.patch.object(geocode_service, "cache_get_json", return_value=None):
                with mock.patch.object(geocode_service, "_store") as store:
                    self.assertIsNone(
                        geocode_service.locate(db, AddressQuery(line1="12 MG Road"))
                    )
        store.assert_not_called()

    def test_a_real_no_match_is_remembered(self) -> None:
        # This one IS worth storing: an address that would not resolve today
        # will not resolve on the next page load either, and re-asking every
        # time is how a quota disappears quietly.
        provider = mock.Mock()
        provider.name = "x"
        provider.geocode.return_value = None
        db = self._db()
        with mock.patch.object(geocode_service, "geocoder", return_value=provider):
            with mock.patch.object(geocode_service, "cache_get_json", return_value=None):
                with mock.patch.object(geocode_service, "_store") as store:
                    self.assertIsNone(
                        geocode_service.locate(db, AddressQuery(line1="12 Fake Street"))
                    )
        store.assert_called_once()

    def test_a_cached_miss_asks_nobody(self) -> None:
        provider = mock.Mock()
        provider.name = "x"
        db = self._db()
        with mock.patch.object(geocode_service, "geocoder", return_value=provider):
            with mock.patch.object(
                geocode_service, "cache_get_json", return_value={"miss": True}
            ):
                self.assertIsNone(geocode_service.locate(db, AddressQuery(line1="anywhere")))
        provider.geocode.assert_not_called()

    def test_a_cached_hit_asks_nobody(self) -> None:
        provider = mock.Mock()
        provider.name = "x"
        db = self._db()
        cached = {
            "lat": 23.0395,
            "lng": 72.5066,
            "confidence": "ROOFTOP",
            "provider": "google",
            "matched": "somewhere",
        }
        with mock.patch.object(geocode_service, "geocoder", return_value=provider):
            with mock.patch.object(geocode_service, "cache_get_json", return_value=cached):
                point = geocode_service.locate(db, AddressQuery(line1="anywhere"))
        provider.geocode.assert_not_called()
        self.assertIsNotNone(point)
        self.assertTrue(point.is_precise)

    def test_an_empty_address_is_never_looked_up(self) -> None:
        provider = mock.Mock()
        db = self._db()
        with mock.patch.object(geocode_service, "geocoder", return_value=provider):
            self.assertIsNone(geocode_service.locate(db, AddressQuery()))
        provider.geocode.assert_not_called()

    def test_a_geocoder_bug_does_not_reach_the_customer(self) -> None:
        provider = mock.Mock()
        provider.name = "x"
        provider.geocode.side_effect = RuntimeError("worse")
        db = self._db()
        with mock.patch.object(geocode_service, "geocoder", return_value=provider):
            with mock.patch.object(geocode_service, "cache_get_json", return_value=None):
                self.assertIsNone(geocode_service.locate(db, AddressQuery(line1="anywhere")))


class LocatingTheEndsOfATrip(unittest.TestCase):
    """The delivery seam: a row, then a geocoder, then a stand-in."""

    def setUp(self) -> None:
        from app.services.delivery import geocoding as delivery_geocoding

        self.seam = delivery_geocoding

    def _branch(self, **over):
        branch = mock.MagicMock()
        branch.id = "b1"
        branch.latitude = None
        branch.longitude = None
        # Explicit, because a MagicMock attribute is truthy and would be read
        # as a confidence string nobody recognises.
        branch.geocode_confidence = ""
        branch.address_line_1 = "Shivalik Plaza"
        branch.address_line_2 = ""
        branch.city = "Ahmedabad"
        branch.state = "Gujarat"
        branch.postal_code = "380009"
        for key, value in over.items():
            setattr(branch, key, value)
        return branch

    def test_a_stored_coordinate_calls_nobody(self) -> None:
        # The layer that matters for cost: a branch located once is free
        # forever, and so is a saved address the customer picked. An empty
        # confidence means a person typed it, which is trusted above any
        # lookup.
        point = self.seam.for_branch(self._branch(latitude=23.05, longitude=72.51), None)
        self.assertEqual((point.latitude, point.longitude), (23.05, 72.51))
        self.assertTrue(point.exact)
        self.assertEqual(point.source, "row")

    def _found(self, point):
        from app.services.geocoding.branches import BranchLocation

        return BranchLocation(point=point, matched_on="address")

    def test_a_precise_lookup_is_written_back_onto_the_branch(self) -> None:
        branch = self._branch()
        located = GeocodedPoint(
            latitude=23.04,
            longitude=72.50,
            confidence=GeocodeConfidence.STREET,
            matched="Shivalik Plaza",
            provider="google",
        )
        with mock.patch(
            "app.services.geocoding.branches.locate_branch", return_value=self._found(located)
        ):
            point = self.seam.for_branch(branch, mock.MagicMock())
        self.assertTrue(point.exact)
        # Written back so the next order reads it for free, WITH how precise it
        # is — the pair alone cannot say whether it is a door or a suburb.
        self.assertEqual(branch.latitude, 23.04)
        self.assertEqual(branch.longitude, 72.50)
        self.assertEqual(branch.geocode_confidence, "STREET")

    def test_a_vague_lookup_is_used_but_never_stored_or_trusted(self) -> None:
        # A city centroid still gives a more honest distance than a hardcoded
        # point, so it is priced from — but it must not be written onto the row
        # as though somebody had located the branch.
        branch = self._branch()
        located = GeocodedPoint(
            latitude=23.02,
            longitude=72.57,
            confidence=GeocodeConfidence.LOCALITY,
            matched="Ahmedabad",
            provider="nominatim",
        )
        with mock.patch(
            "app.services.geocoding.branches.locate_branch", return_value=self._found(located)
        ):
            point = self.seam.for_branch(branch, mock.MagicMock())
        self.assertFalse(point.exact)
        self.assertIsNone(branch.latitude)
        # Still usable: a neighbourhood point prices a delivery to within a
        # kilometre or two, which is a real answer.
        self.assertTrue(point.usable)

    def test_nothing_found_falls_back_to_the_stand_in_and_says_so(self) -> None:
        with mock.patch("app.services.geocoding.branches.locate_branch", return_value=None):
            point = self.seam.for_branch(self._branch(), mock.MagicMock())
        self.assertFalse(point.exact)
        self.assertEqual(point.source, "stand-in")
        # And never priced from: a stand-in is a constant with no relationship
        # to the order.
        self.assertFalse(point.usable)

    def test_a_picked_place_short_circuits_everything(self) -> None:
        # The customer chose a building from a list. Re-geocoding the text
        # underneath would be a second paid call for a worse answer.
        point = self.seam.for_address(
            "anything at all", mock.MagicMock(), known=(23.1, 72.6, "ROOFTOP")
        )
        self.assertTrue(point.exact)
        self.assertEqual(point.source, "row")

    def test_a_stored_point_that_is_only_locality_is_not_trusted(self) -> None:
        point = self.seam.for_address("x", mock.MagicMock(), known=(23.1, 72.6, "LOCALITY"))
        self.assertFalse(point.exact)

    def test_an_unrecognised_stored_confidence_is_not_trusted(self) -> None:
        point = self.seam.for_address("x", mock.MagicMock(), known=(23.1, 72.6, "WHATEVER"))
        self.assertFalse(point.exact)

    def test_a_bare_string_address_is_geocoded_as_freeform(self) -> None:
        # Every address stored before the structured form existed.
        seen: list[AddressQuery] = []

        def fake_locate(db, query):
            seen.append(query)
            return None

        with mock.patch("app.services.geocoding.branches.locate", side_effect=fake_locate):
            self.seam.for_address("102 Demo Street, Ahmedabad", mock.MagicMock())
        self.assertEqual(seen[0].freeform, "102 Demo Street, Ahmedabad")

    def test_a_customer_address_gets_the_same_cascade_a_branch_does(self) -> None:
        # The bug a real customer hit: "A-31, Rangdarshan Soc, Near Dhanmora,
        # Katargam" resolves to nothing as a whole address, so the delivery fee
        # showed as "Free". The neighbourhood and the PIN code beside it both
        # resolve, and asking them turns that into a real ₹54.08 quote.
        asked: list[str] = []

        def fake_locate(db, query):
            asked.append(query.as_text())
            return None

        with mock.patch("app.services.geocoding.branches.locate", side_effect=fake_locate):
            self.seam.for_address(
                AddressQuery(
                    line1="A-31, Rangdarshan Soc, Near Dhanmora, Katargam",
                    city="Surat",
                    state="Gujarat",
                    postal_code="395004",
                ),
                mock.MagicMock(),
            )
        # The whole address, then the neighbourhood, then the postcode.
        self.assertEqual(len(asked), 3)
        self.assertIn("Katargam, Surat", asked[1])
        self.assertIn("395004", asked[2])

    def test_the_cascade_keeps_the_best_answer_not_the_first(self) -> None:
        # Measured: "Katargam, Surat" answers with a TALUKA, too coarse to
        # price from, while the PIN code beside it answers with a far smaller
        # area. Stopping at the first answer took the worse one and left the
        # customer with no quote.
        answers = {
            "locality": GeocodedPoint(
                latitude=21.2, longitude=72.8, confidence=GeocodeConfidence.REGION
            ),
            "postcode": GeocodedPoint(
                latitude=21.3, longitude=72.9, confidence=GeocodeConfidence.POSTCODE
            ),
        }

        def fake_locate(db, query):
            text = query.as_text()
            if "395004" in text:
                return answers["postcode"]
            if text.startswith("Katargam"):
                return answers["locality"]
            return None

        with mock.patch("app.services.geocoding.branches.locate", side_effect=fake_locate):
            point = self.seam.for_address(
                AddressQuery(
                    line1="A-31, Rangdarshan Soc, Katargam",
                    city="Surat",
                    state="Gujarat",
                    postal_code="395004",
                ),
                mock.MagicMock(),
            )
        self.assertEqual(point.confidence, "POSTCODE")
        self.assertTrue(point.usable)

    def test_a_precise_answer_stops_the_cascade(self) -> None:
        # Nothing further down can beat a door, and the lookups cost money.
        calls: list[str] = []

        def fake_locate(db, query):
            calls.append(query.as_text())
            return GeocodedPoint(
                latitude=1.0, longitude=2.0, confidence=GeocodeConfidence.ROOFTOP
            )

        with mock.patch("app.services.geocoding.branches.locate", side_effect=fake_locate):
            self.seam.for_address(
                AddressQuery(line1="12 MG Road, Navrangpura", city="Ahmedabad"),
                mock.MagicMock(),
            )
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()

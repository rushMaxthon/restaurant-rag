"""What delivery costs, and every way that question can go unanswered.

This exists because a delivery fee is the last number a customer reads before
they pay, and the ways it can be wrong are all quiet. A courier priced in the
wrong currency, a courier that did not answer at all, a courier that will not
serve the street - none of them raise. Each one has to land on the branch's
own flat fee, which is what every order was charged before any of this
existed, so switching the feature on cannot change what anybody pays until a
courier actually prices their trip.

Each case below is a way the checkout could have printed a wrong figure.
"""

from __future__ import annotations

import os
import sys
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import get_settings  # noqa: E402
from app.services.delivery import quoting  # noqa: E402
from app.services.delivery.base import DeliveryProviderError, DeliveryQuote  # noqa: E402
from app.services.delivery.pidge_provider import PidgeProvider  # noqa: E402


class _Branch:
    """Just enough of a RestaurantLocation to be quoted for."""

    id = "branch-1"
    latitude = None
    longitude = None
    delivery_fee = Decimal("40.00")


def _quote(**kwargs) -> DeliveryQuote:
    base = {
        "serviceable": True,
        "min_cost": Decimal("67.04"),
        "max_cost": Decimal("87.04"),
        "currency": "INR",
    }
    base.update(kwargs)
    return DeliveryQuote(**base)


class ChoosingTheFigureToPrint(unittest.TestCase):
    """A courier quotes a band; a checkout prints one number."""

    def setUp(self) -> None:
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)

    def test_the_ceiling_is_charged_by_default(self) -> None:
        # The end that cannot leave the platform paying the difference when a
        # rider turns out to cost the top of the band.
        with mock.patch.dict(os.environ, {"DELIVERY_QUOTE_BASIS": "max"}):
            get_settings.cache_clear()
            self.assertEqual(quoting.fee_from(_quote()), Decimal("87.04"))

    def test_an_operator_can_choose_the_floor(self) -> None:
        with mock.patch.dict(os.environ, {"DELIVERY_QUOTE_BASIS": "min"}):
            get_settings.cache_clear()
            self.assertEqual(quoting.fee_from(_quote()), Decimal("67.04"))

    def test_the_middle_is_available_and_rounds_to_two_places(self) -> None:
        with mock.patch.dict(os.environ, {"DELIVERY_QUOTE_BASIS": "mid"}):
            get_settings.cache_clear()
            self.assertEqual(quoting.fee_from(_quote()), Decimal("77.04"))

    def test_an_unserviceable_address_has_no_fee_at_all(self) -> None:
        # Not a fee of zero. Free delivery to an address nobody will drive to
        # is the most expensive bug available here.
        self.assertIsNone(quoting.fee_from(DeliveryQuote(serviceable=False)))

    def test_a_quote_with_no_numbers_produces_none(self) -> None:
        self.assertIsNone(quoting.fee_from(_quote(min_cost=None, max_cost=None)))

    def test_one_end_of_the_band_is_enough(self) -> None:
        self.assertEqual(quoting.fee_from(_quote(max_cost=None)), Decimal("67.04"))


class WhenTheQuoteCannotBeUsed(unittest.TestCase):
    """Every path back to the branch's own fee."""

    def setUp(self) -> None:
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)

    def test_a_quote_in_another_currency_is_refused(self) -> None:
        # Found by running it: an Indian courier quoted rupees for a branch
        # billing in CAD. Adding those is not money in any currency.
        self.assertFalse(quoting.usable_in(_quote(currency="INR"), "CAD"))
        self.assertTrue(quoting.usable_in(_quote(currency="INR"), "INR"))

    def test_a_courier_that_names_no_currency_is_trusted(self) -> None:
        # Refusing here would discard a good quote over a missing field.
        self.assertTrue(quoting.usable_in(_quote(currency=""), "INR"))

    def test_the_wrong_currency_charges_the_branch_fee(self) -> None:
        with mock.patch.object(quoting, "quote_for", return_value=_quote(currency="INR")):
            self.assertIsNone(quoting.delivery_fee_for(_Branch(), "somewhere", currency="CAD"))

    def test_the_right_currency_charges_the_courier(self) -> None:
        with mock.patch.dict(os.environ, {"DELIVERY_QUOTE_BASIS": "max"}):
            get_settings.cache_clear()
            with mock.patch.object(quoting, "quote_for", return_value=_quote()):
                self.assertEqual(
                    quoting.delivery_fee_for(_Branch(), "somewhere", currency="INR"),
                    Decimal("87.04"),
                )

    def test_the_flag_being_off_asks_nobody(self) -> None:
        with mock.patch.dict(os.environ, {"ENABLE_DELIVERY_QUOTES": "false"}):
            get_settings.cache_clear()
            with mock.patch.object(quoting, "delivery_provider") as provider:
                self.assertIsNone(quoting.quote_for(_Branch(), "somewhere"))
                provider.assert_not_called()

    def test_no_courier_configured_quotes_nothing(self) -> None:
        with mock.patch.dict(os.environ, {"ENABLE_DELIVERY_QUOTES": "true"}):
            get_settings.cache_clear()
            with mock.patch.object(quoting, "delivery_provider", return_value=None):
                self.assertIsNone(quoting.quote_for(_Branch(), "somewhere"))

    def test_a_courier_that_cannot_price_is_not_an_error(self) -> None:
        # A second courier added later may only dispatch. That is a missing
        # feature, not a broken checkout.
        class DispatchOnly:
            name = "someone"

        with mock.patch.dict(os.environ, {"ENABLE_DELIVERY_QUOTES": "true"}):
            get_settings.cache_clear()
            with mock.patch.object(quoting, "delivery_provider", return_value=DispatchOnly()):
                self.assertIsNone(quoting.quote_for(_Branch(), "somewhere"))

    def test_a_courier_failure_does_not_reach_the_customer(self) -> None:
        # Somebody holding a card must not be blocked by a courier having a
        # bad minute.
        for boom in (DeliveryProviderError("down"), RuntimeError("worse")):
            with self.subTest(boom=type(boom).__name__):
                provider = mock.Mock(name="provider")
                provider.quote.side_effect = boom
                with mock.patch.dict(os.environ, {"ENABLE_DELIVERY_QUOTES": "true"}):
                    get_settings.cache_clear()
                    with mock.patch.object(quoting, "delivery_provider", return_value=provider):
                        self.assertIsNone(quoting.quote_for(_Branch(), "somewhere"))


class AStandInIsNotATrip(unittest.TestCase):
    """The pickup point is half the price, and it was the half going wrong.

    Caught in a browser, not in a test. A branch with no coordinates fell back
    to the hardcoded Ahmedabad stand-in while the customer was in Surat; the
    courier honestly priced 258 km and the checkout showed ₹2,601.48 delivery on
    a ₹50 loaf of bread. The courier was not wrong — it was asked about a
    journey nobody was making.

    The distinction that matters is vague versus invented. A geocoder that only
    reached a suburb still answered about the real address, so the distance is
    roughly right. A stand-in is a constant with no relationship to the order.
    Pidge's estimate endpoint takes coordinates only, with no address form, so
    there is no way to hand the problem back to them.
    """

    def setUp(self) -> None:
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)

    def _quote_with(self, pickup_source: str, drop_source: str):
        from app.services.delivery.geocoding import Coordinates

        provider = mock.Mock()
        provider.name = "pidge"
        provider.quote.return_value = _quote()
        points = (
            Coordinates(23.0, 72.5, exact=True, source=pickup_source),
            Coordinates(21.1, 72.8, exact=True, source=drop_source),
        )
        with mock.patch.dict(os.environ, {"ENABLE_DELIVERY_QUOTES": "true"}):
            get_settings.cache_clear()
            with mock.patch.object(quoting, "delivery_provider", return_value=provider):
                result = quoting.quote_for(_Branch(), "somewhere", points=points)
        return result, provider

    def test_a_region_level_point_asks_no_courier(self) -> None:
        # Three tiers, not two. A neighbourhood is priced from; a taluka or
        # state centroid is not, because "somewhere in this district" can be
        # ten kilometres from the branch and a fee built on it is wrong by
        # more than the fee itself. Two of the 25 seeded branches resolved
        # this coarsely, which is why the tier exists.
        from app.services.delivery.geocoding import Coordinates

        provider = mock.Mock()
        provider.name = "pidge"
        provider.quote.return_value = _quote()
        points = (
            Coordinates(23.0, 72.5, exact=False, source="geocoder", confidence="REGION"),
            Coordinates(21.1, 72.8, exact=True, source="row"),
        )
        with mock.patch.dict(os.environ, {"ENABLE_DELIVERY_QUOTES": "true"}):
            get_settings.cache_clear()
            with mock.patch.object(quoting, "delivery_provider", return_value=provider):
                self.assertIsNone(quoting.quote_for(_Branch(), "x", points=points))
        provider.quote.assert_not_called()

    def test_a_locality_point_is_priced_from(self) -> None:
        # The middle tier, and the one most branches have. Right to within a
        # kilometre or two, which is a real answer for a delivery fee —
        # refusing it would throw away the only point 14 of 25 branches have.
        from app.services.delivery.geocoding import Coordinates

        provider = mock.Mock()
        provider.name = "pidge"
        provider.quote.return_value = _quote()
        points = (
            Coordinates(23.0, 72.5, exact=False, source="geocoder", confidence="LOCALITY"),
            Coordinates(23.1, 72.6, exact=False, source="geocoder", confidence="LOCALITY"),
        )
        with mock.patch.dict(os.environ, {"ENABLE_DELIVERY_QUOTES": "true"}):
            get_settings.cache_clear()
            with mock.patch.object(quoting, "delivery_provider", return_value=provider):
                self.assertIsNotNone(quoting.quote_for(_Branch(), "x", points=points))

    def test_a_hand_typed_branch_point_is_trusted(self) -> None:
        # An empty confidence with coordinates present means a person put them
        # there, pointing at their own front door. That beats any geocoder and
        # must not be read as "unknown, assume the worst".
        from app.services.delivery.geocoding import Coordinates, for_branch

        branch = _Branch()
        branch.latitude, branch.longitude = 23.05, 72.51
        branch.geocode_confidence = ""
        point = for_branch(branch, None)
        self.assertTrue(point.exact)
        self.assertTrue(Coordinates.usable.fget(point))

    def test_a_stored_locality_branch_point_is_not_called_exact(self) -> None:
        from app.services.delivery.geocoding import for_branch

        branch = _Branch()
        branch.latitude, branch.longitude = 23.05, 72.51
        branch.geocode_confidence = "LOCALITY"
        point = for_branch(branch, None)
        self.assertFalse(point.exact)
        self.assertTrue(point.usable)

    def test_a_stand_in_pickup_asks_no_courier(self) -> None:
        result, provider = self._quote_with("stand-in", "geocoder")
        self.assertIsNone(result)
        # Not merely discarded afterwards: the courier is never called, because
        # a request about the wrong journey is a wasted one.
        provider.quote.assert_not_called()

    def test_a_stand_in_drop_asks_no_courier(self) -> None:
        result, provider = self._quote_with("row", "stand-in")
        self.assertIsNone(result)
        provider.quote.assert_not_called()

    def test_two_real_points_are_quoted(self) -> None:
        result, provider = self._quote_with("row", "geocoder")
        self.assertIsNotNone(result)
        provider.quote.assert_called_once()

    def test_a_vague_point_is_still_quoted(self) -> None:
        # A suburb-level match is imprecise, not invented. It is priced from,
        # and `exact_location` is what tells the caller not to over-trust it.
        from app.services.delivery.geocoding import Coordinates

        provider = mock.Mock()
        provider.name = "pidge"
        provider.quote.return_value = _quote()
        points = (
            Coordinates(23.0, 72.5, exact=False, source="geocoder"),
            Coordinates(23.1, 72.6, exact=False, source="geocoder"),
        )
        with mock.patch.dict(os.environ, {"ENABLE_DELIVERY_QUOTES": "true"}):
            get_settings.cache_clear()
            with mock.patch.object(quoting, "delivery_provider", return_value=provider):
                self.assertIsNotNone(quoting.quote_for(_Branch(), "x", points=points))


class ADeliveryNobodyWouldDrive(unittest.TestCase):
    """The backstop, and the most expensive bug this work turned up.

    A typo'd address geocoded to the centroid of India. The coordinates were
    graded honestly, the cascade then found a same-named place elsewhere, and
    Pidge quoted the journey without complaint: 1,605 km, ₹16,076.02 to deliver
    a ₹50 loaf of bread, shown to the customer as the delivery fee.

    Grading coordinates does not catch every variant of a lookup landing in the
    wrong place. A distance nobody would ever drive does, and the courier
    cannot be expected to apply that judgement — it is our order, not theirs.
    """

    def setUp(self) -> None:
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)

    def test_a_journey_across_the_country_is_refused(self) -> None:
        from app.services.delivery.geocoding import Coordinates

        provider = mock.Mock()
        provider.name = "pidge"
        provider.quote.return_value = _quote(distance_metres=1_605_603.0)
        points = (
            Coordinates(21.2, 72.8, exact=True, source="row"),
            Coordinates(20.6, 78.9, exact=False, source="geocoder", confidence="LOCALITY"),
        )
        with mock.patch.dict(os.environ, {"ENABLE_DELIVERY_QUOTES": "true"}):
            get_settings.cache_clear()
            with mock.patch.object(quoting, "delivery_provider", return_value=provider):
                self.assertIsNone(quoting.quote_for(_Branch(), "x", points=points))

    def test_an_ordinary_trip_is_not(self) -> None:
        from app.services.delivery.geocoding import Coordinates

        provider = mock.Mock()
        provider.name = "pidge"
        provider.quote.return_value = _quote(distance_metres=6_704.0)
        points = (
            Coordinates(21.2, 72.8, exact=True, source="row"),
            Coordinates(21.3, 72.9, exact=True, source="geocoder", confidence="ROOFTOP"),
        )
        with mock.patch.dict(os.environ, {"ENABLE_DELIVERY_QUOTES": "true"}):
            get_settings.cache_clear()
            with mock.patch.object(quoting, "delivery_provider", return_value=provider):
                self.assertIsNotNone(quoting.quote_for(_Branch(), "x", points=points))

    def test_the_branch_radius_wins_over_the_platform_bound(self) -> None:
        # A restaurant that says it delivers 5 km is answering the question
        # better than any default could.
        near = SimpleNamespace(service_radius_km=Decimal("5"))
        self.assertTrue(quoting.within_reach(near, 4_000))
        self.assertFalse(quoting.within_reach(near, 9_000))

    def test_an_unknown_distance_is_allowed_through(self) -> None:
        # A courier that priced the trip without saying how far it is has still
        # answered. Refusing on a missing field throws away good quotes.
        self.assertTrue(quoting.within_reach(_Branch(), None))


class AskingPidgeForAPrice(unittest.TestCase):
    """The two calls, and the fact that they disagree about coordinates."""

    def setUp(self) -> None:
        self.provider = PidgeProvider(base_url="https://store.example", username="u", password="p")

    def test_serviceability_and_estimate_use_different_coordinate_keys(self) -> None:
        # Undocumented, and a 400 if you assume they match: serviceability
        # wants lat/lng, estimate wants latitude/longitude.
        calls: list[tuple[str, dict]] = []

        def fake(method, path, *, timeout=None, **kwargs):
            calls.append((path, kwargs["json"]))
            if path.endswith("serviceability"):
                return {"data": {"serviceable": True}}
            return {
                "data": {
                    "minCost": 67.04,
                    "maxCost": 87.04,
                    "pickupToDropDistance": 6704,
                    "pickupToDropTime": 1609,
                    "timeToAssign": 1080,
                }
            }

        with mock.patch.object(self.provider, "_call", side_effect=fake):
            quote = self.provider.quote(
                pickup_lat=23.0395, pickup_lng=72.5066, drop_lat=23.0395, drop_lng=72.56
            )

        self.assertEqual(set(calls[0][1]["pickup"]), {"lat", "lng"})
        self.assertEqual(set(calls[1][1]["pickup"]), {"latitude", "longitude"})
        self.assertTrue(quote.serviceable)
        self.assertEqual(quote.min_cost, Decimal("67.04"))
        self.assertEqual(quote.max_cost, Decimal("87.04"))
        self.assertEqual(quote.currency, "INR")
        self.assertEqual(quote.distance_metres, 6704.0)
        self.assertEqual(quote.assign_seconds, 1080)

    def test_prices_are_decimal_not_float(self) -> None:
        # Decimal(71.26) is 71.2599999..., and money three places wrong at a
        # checkout is money somebody has to explain.
        with mock.patch.object(
            self.provider,
            "_call",
            side_effect=[{"data": {"serviceable": True}}, {"data": {"minCost": 71.26}}],
        ):
            quote = self.provider.quote(pickup_lat=1.0, pickup_lng=2.0, drop_lat=3.0, drop_lng=4.0)
        self.assertEqual(quote.min_cost, Decimal("71.26"))

    def test_an_unserviceable_pair_is_never_priced(self) -> None:
        # The estimate call must not happen: asking for a price and inferring
        # "unserviceable" from a missing number turns their outage into our
        # silent free delivery.
        with mock.patch.object(
            self.provider, "_call", return_value={"data": {"serviceable": False}}
        ) as call:
            quote = self.provider.quote(pickup_lat=1.0, pickup_lng=2.0, drop_lat=3.0, drop_lng=4.0)
        self.assertFalse(quote.serviceable)
        self.assertIsNone(quote.min_cost)
        self.assertEqual(call.call_count, 1)

    def test_an_unrecognised_reply_does_not_refuse_a_customer(self) -> None:
        # A shape we do not know should not silently decide somebody cannot be
        # served.
        with mock.patch.object(
            self.provider,
            "_call",
            side_effect=[{"data": {}}, {"data": {"minCost": 30, "maxCost": 50}}],
        ):
            quote = self.provider.quote(pickup_lat=1.0, pickup_lng=2.0, drop_lat=3.0, drop_lng=4.0)
        self.assertTrue(quote.serviceable)


class TheCoordinatesAreAStandIn(unittest.TestCase):
    """The one part that is not real yet says so."""

    def test_a_branch_with_coordinates_uses_its_own(self) -> None:
        from app.services.delivery import geocoding

        branch = _Branch()
        branch.latitude, branch.longitude = Decimal("23.05"), Decimal("72.51")
        point = geocoding.for_branch(branch)
        self.assertEqual((point.latitude, point.longitude), (23.05, 72.51))
        self.assertTrue(point.exact)

    def test_a_branch_without_coordinates_is_marked_inexact(self) -> None:
        # The price is real; the trip it prices is a guess, and whoever bills
        # it has to be able to tell.
        from app.services.delivery import geocoding

        self.assertFalse(geocoding.for_branch(_Branch()).exact)
        self.assertFalse(geocoding.for_address("12 Somewhere Road").exact)


if __name__ == "__main__":
    unittest.main()

"""Delivery priced by our own distance slabs, not by the courier's quote.

Decided on 2026-10-07 with the platform owner. Pidge's estimate and the price
of the rider it then assigned disagreed (Rs 285.61 charged against Rs 57
quoted), so the checkout stopped printing the courier's figure. The platform
now sets the price from the distance alone:

    up to 2 km  Rs 68     over 2 km up to 5 km  Rs 78     over 5 km  Rs 100

with 18% GST added on top, and refused past the branch's radius or 10 km.

The distance is the courier's ROAD distance when it answers - a straight line
undercounts every bend - and the straight line times 1.3 when it does not.
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
from app.services import order_charges  # noqa: E402
from app.services.delivery import quoting, slabs  # noqa: E402
from app.services.delivery.base import DeliveryQuote  # noqa: E402
from app.services.delivery.geocoding import Coordinates  # noqa: E402

# Two points in Surat about 1.11 km apart in a straight line (0.01 deg of lat).
_PICKUP = Coordinates(21.1700, 72.8300, True, "row")
_DROP = Coordinates(21.1800, 72.8300, True, "geocoder")


def _branch(**kwargs):
    base = {
        "id": "b1",
        "service_radius_km": None,
        "delivery_fee": Decimal("0.00"),
        "delivery_tax_percent": Decimal("0.00"),
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


class _Settings(unittest.TestCase):
    def setUp(self) -> None:
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)


class TheSlabs(_Settings):
    def test_each_band_and_its_edges(self) -> None:
        cases = {
            0: "68.00",
            1500: "68.00",
            2000: "68.00",
            2001: "78.00",
            4999: "78.00",
            5000: "78.00",
            5001: "100.00",
            9800: "100.00",
        }
        for metres, fee in cases.items():
            with self.subTest(metres=metres):
                self.assertEqual(slabs.fee_for_distance(metres), Decimal(fee))

    def test_the_slabs_are_a_setting(self) -> None:
        with mock.patch.dict(os.environ, {"DELIVERY_FEE_SLABS": "3:50, *:90"}):
            get_settings.cache_clear()
            self.assertEqual(slabs.fee_for_distance(2900), Decimal("50.00"))
            self.assertEqual(slabs.fee_for_distance(3100), Decimal("90.00"))

    def test_a_list_with_no_open_end_charges_its_last_slab_beyond_it(self) -> None:
        # Nobody is left unpriced by a typo in the setting; the distance limit
        # is a separate rule.
        with mock.patch.dict(os.environ, {"DELIVERY_FEE_SLABS": "2:68,5:78"}):
            get_settings.cache_clear()
            self.assertEqual(slabs.fee_for_distance(7000), Decimal("78.00"))

    def test_a_malformed_list_falls_back_to_the_agreed_one(self) -> None:
        with mock.patch.dict(os.environ, {"DELIVERY_FEE_SLABS": "two km: lots"}):
            get_settings.cache_clear()
            self.assertEqual(slabs.fee_for_distance(1000), Decimal("68.00"))
            self.assertEqual(slabs.fee_for_distance(6000), Decimal("100.00"))


class MeasuringTheTrip(_Settings):
    def test_the_couriers_road_distance_is_used_when_it_answers(self) -> None:
        attempt = quoting.QuoteAttempt(DeliveryQuote(serviceable=True, distance_metres=3400.0))
        with mock.patch.object(slabs.quoting, "attempt_quote", return_value=attempt):
            trip = slabs.price_trip(_branch(), "addr", points=(_PICKUP, _DROP))
        self.assertEqual(trip.distance_metres, 3400.0)
        self.assertEqual(trip.measured_by, "road")
        self.assertEqual(trip.fee, Decimal("78.00"))

    def test_without_the_courier_the_straight_line_is_stretched_for_roads(self) -> None:
        attempt = quoting.QuoteAttempt(None, "courier_unavailable")
        with mock.patch.object(slabs.quoting, "attempt_quote", return_value=attempt):
            trip = slabs.price_trip(_branch(), "addr", points=(_PICKUP, _DROP))
        # ~1112 m straight x 1.3
        self.assertAlmostEqual(trip.distance_metres, 1112 * 1.3, delta=15)
        self.assertEqual(trip.measured_by, "straight_line")
        self.assertEqual(trip.fee, Decimal("68.00"))

    def test_a_courier_reply_without_a_distance_still_falls_back(self) -> None:
        attempt = quoting.QuoteAttempt(DeliveryQuote(serviceable=True, distance_metres=None))
        with mock.patch.object(slabs.quoting, "attempt_quote", return_value=attempt):
            trip = slabs.price_trip(_branch(), "addr", points=(_PICKUP, _DROP))
        self.assertEqual(trip.measured_by, "straight_line")

    def test_the_courier_saying_it_will_not_serve_does_not_change_the_price(self) -> None:
        attempt = quoting.QuoteAttempt(DeliveryQuote(serviceable=False, distance_metres=1800.0))
        with mock.patch.object(slabs.quoting, "attempt_quote", return_value=attempt):
            trip = slabs.price_trip(_branch(), "addr", points=(_PICKUP, _DROP))
        self.assertEqual(trip.fee, Decimal("68.00"))
        self.assertFalse(trip.serviceable)

    def test_a_stand_in_point_is_not_priced(self) -> None:
        stand_in = Coordinates(23.02, 72.57, False, "stand-in")
        with mock.patch.object(slabs.quoting, "attempt_quote") as asked:
            trip = slabs.price_trip(_branch(), "addr", points=(stand_in, _DROP))
        asked.assert_not_called()
        self.assertIsNone(trip.fee)
        self.assertEqual(trip.reason, "coarse_point")


class TooFar(_Settings):
    def test_past_ten_km_is_refused(self) -> None:
        attempt = quoting.QuoteAttempt(DeliveryQuote(serviceable=True, distance_metres=10_400.0))
        with mock.patch.object(slabs.quoting, "attempt_quote", return_value=attempt):
            trip = slabs.price_trip(_branch(), "addr", points=(_PICKUP, _DROP))
        self.assertIsNone(trip.fee)
        self.assertEqual(trip.reason, "out_of_range")
        self.assertEqual(trip.distance_metres, 10_400.0)
        self.assertEqual(trip.limit_km, 10.0)

    def test_the_branch_radius_wins_over_the_platform_limit(self) -> None:
        attempt = quoting.QuoteAttempt(DeliveryQuote(serviceable=True, distance_metres=4200.0))
        with mock.patch.object(slabs.quoting, "attempt_quote", return_value=attempt):
            trip = slabs.price_trip(
                _branch(service_radius_km=Decimal("4")), "addr", points=(_PICKUP, _DROP)
            )
        self.assertEqual(trip.reason, "out_of_range")
        self.assertEqual(trip.limit_km, 4.0)

    def test_the_courier_refusing_a_long_trip_keeps_its_distance(self) -> None:
        # attempt_quote throws the quote away past the limit; the distance has
        # to survive it, or the customer is told nothing about why.
        attempt = quoting.QuoteAttempt(None, "out_of_range", distance_metres=14_000.0)
        with mock.patch.object(slabs.quoting, "attempt_quote", return_value=attempt):
            trip = slabs.price_trip(_branch(), "addr", points=(_PICKUP, _DROP))
        self.assertEqual(trip.reason, "out_of_range")
        self.assertEqual(trip.distance_metres, 14_000.0)

    def test_attempt_quote_reports_the_distance_it_refused(self) -> None:
        provider = SimpleNamespace(
            name="fake",
            quote=lambda **_: DeliveryQuote(
                serviceable=True, max_cost=Decimal("90"), distance_metres=60_000.0
            ),
        )
        with mock.patch.dict(os.environ, {"ENABLE_DELIVERY_QUOTES": "true"}):
            get_settings.cache_clear()
            with mock.patch.object(quoting, "delivery_provider", return_value=provider):
                attempt = quoting.attempt_quote(_branch(), "addr", points=(_PICKUP, _DROP))
        self.assertEqual(attempt.reason, "out_of_range")
        self.assertEqual(attempt.distance_metres, 60_000.0)


class GstOnTop(_Settings):
    def test_the_platform_rate_applies_whatever_the_branch_says(self) -> None:
        # Delivery is the platform's money, so its GST is the platform's rate:
        # most branches were left at 0% and would otherwise charge none.
        charges = order_charges.for_location(
            _branch(delivery_tax_percent=Decimal("0.00"), tax_percent=Decimal("5.00")),
            subtotal=Decimal("200.00"),
            delivery_fee=Decimal("68.00"),
            discount_amount=Decimal("0"),
        )
        self.assertEqual(charges.delivery_tax, Decimal("12.24"))

    def test_courier_pricing_keeps_the_branch_rate(self) -> None:
        with mock.patch.dict(os.environ, {"DELIVERY_PRICING": "courier"}):
            get_settings.cache_clear()
            charges = order_charges.for_location(
                _branch(delivery_tax_percent=Decimal("0.00"), tax_percent=Decimal("5.00")),
                subtotal=Decimal("200.00"),
                delivery_fee=Decimal("68.00"),
                discount_amount=Decimal("0"),
            )
        self.assertEqual(charges.delivery_tax, Decimal("0.00"))



class TheCheckoutQuote(_Settings):
    """`POST /orders/delivery-quote` under slab pricing, run for real.

    Only the map lookup and the courier are faked; the endpoint, the slab
    rule and the bill (`order_charges`) are the code the checkout calls.
    """

    def _quote(self, road_metres, **branch):
        import uuid

        from app.api import orders as api_orders
        from app.schemas.order import DeliveryQuoteRequest

        location = _branch(
            tax_percent=Decimal("5.00"),
            restaurant=SimpleNamespace(currency="INR"),
            restaurant_id=uuid.uuid4(),
            **branch,
        )
        import contextlib

        from app.models.restaurant_location import RestaurantLocation

        # The branch for the branch lookup; nothing saved for the platform's
        # delivery pricing, so the agreed defaults apply.
        db = SimpleNamespace(
            get=lambda model, *_: location if model is RestaurantLocation else None,
            is_modified=lambda *_: False,
            begin_nested=contextlib.nullcontext,
        )
        payload = DeliveryQuoteRequest(
            restaurant_location_id=uuid.uuid4(),
            delivery_address="Adajan, Surat",
            latitude=21.18,
            longitude=72.83,
            subtotal=Decimal("200.00"),
        )
        attempt = (
            quoting.QuoteAttempt(None, "out_of_range", distance_metres=road_metres)
            if road_metres > 10_000
            else quoting.QuoteAttempt(DeliveryQuote(serviceable=True, distance_metres=road_metres))
        )
        with mock.patch.object(api_orders, "points_for", return_value=(_PICKUP, _DROP)),                 mock.patch.object(api_orders, "ensure_restaurant_writable"),                 mock.patch.object(slabs.quoting, "attempt_quote", return_value=attempt):
            return api_orders.quote_delivery(payload, db, SimpleNamespace(id=uuid.uuid4()), None)

    def test_a_short_trip_is_68_plus_gst(self) -> None:
        response = self._quote(1800.0)
        self.assertEqual(response.source, "distance")
        self.assertEqual(response.delivery_fee, Decimal("68.00"))
        self.assertEqual(response.distance_metres, 1800.0)
        self.assertTrue(response.serviceable)
        # 200 food + 10 food GST + 68 delivery + 12.24 delivery GST
        self.assertEqual(response.total_amount, Decimal("290.24"))

    def test_a_middle_trip_is_78(self) -> None:
        self.assertEqual(self._quote(3600.0).delivery_fee, Decimal("78.00"))

    def test_a_long_trip_is_100(self) -> None:
        self.assertEqual(self._quote(7200.0).delivery_fee, Decimal("100.00"))

    def test_too_far_is_not_a_price(self) -> None:
        response = self._quote(12_500.0)
        self.assertFalse(response.serviceable)
        self.assertEqual(response.fallback_reason, "out_of_range")
        self.assertEqual(response.delivery_fee, Decimal("0.00"))
        self.assertEqual(response.max_distance_km, 10.0)
        self.assertEqual(response.distance_metres, 12_500.0)


if __name__ == "__main__":
    unittest.main()

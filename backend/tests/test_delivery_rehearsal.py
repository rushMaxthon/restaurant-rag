"""The courier that always says yes, and the two things keeping it off prod.

This provider exists because Pidge's sandbox accepts a booking and then stops:
no rider is ever assigned, so the rider card, the tracking link and the live
status panel cannot be shown working without a live contract. It walks a
delivery along the happy path on a clock instead.

It also invents riders, which makes it the most dangerous module in the
delivery package. Most of what is asserted below is therefore not about the
happy path at all — it is about the flag being off, the environment check
holding, and a rider never appearing before one has been assigned.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config.settings import get_settings  # noqa: E402
from app.services.delivery import registry  # noqa: E402
from app.services.delivery.base import (  # noqa: E402
    DeliveryAddress,
    DeliveryItem,
    DeliveryProvider,
    DeliveryRequest,
    DeliveryState,
)
from app.services.delivery.rehearsal_provider import (  # noqa: E402
    PROVIDER_NAME,
    RehearsalProvider,
)


def a_request() -> DeliveryRequest:
    here = DeliveryAddress(
        address_line_1="Main Branch",
        city="Surat",
        state="Gujarat",
        pincode="395004",
        name="Bhagwati Bakery",
        mobile="+919812000000",
    )
    return DeliveryRequest(
        reference="ORD-TEST-1",
        pickup=here,
        drop=here,
        items=[DeliveryItem(name="Brown Bread", quantity=1, price=Decimal("50.00"))],
        bill_amount=Decimal("134.73"),
    )


def booked_seconds_ago(seconds: int) -> str:
    """A provider order id minted `seconds` ago.

    The id carries its own timestamp precisely so the provider can be
    stateless, which is what lets these tests move time without patching a
    clock.
    """

    when = datetime.now(tz=UTC) - timedelta(seconds=seconds)
    return f"{PROVIDER_NAME}-{int(when.timestamp() * 1000)}"


class ItIsOffUnlessSomebodyAsked(unittest.TestCase):
    """The guards, which matter more than the feature."""

    def setUp(self) -> None:
        registry.reset_delivery_provider()

    def tearDown(self) -> None:
        registry.reset_delivery_provider()
        get_settings.cache_clear()

    def test_the_flag_defaults_off(self) -> None:
        # A courier that invents riders must be asked for, never inherited.
        from app.config.settings import Settings

        self.assertFalse(Settings.model_fields["enable_delivery_rehearsal"].default)

    def test_it_is_refused_outside_a_local_environment(self) -> None:
        """The second guard, and the one that matters.

        A flag is one `.env` line away from being wrong, and being wrong here
        means telling a customer a rider is on the way when nobody is. So the
        environment is checked as well, and a staging box with the flag on
        gets Pidge or nothing — never this.
        """

        os.environ["ENABLE_DELIVERY_REHEARSAL"] = "true"
        os.environ["ENABLE_DELIVERY_DISPATCH"] = "true"
        os.environ["ENVIRONMENT"] = "production"
        get_settings.cache_clear()
        registry.reset_delivery_provider()
        try:
            provider = registry.delivery_provider()
            self.assertNotIsInstance(provider, RehearsalProvider)
        finally:
            for key in (
                "ENABLE_DELIVERY_REHEARSAL",
                "ENABLE_DELIVERY_DISPATCH",
                "ENVIRONMENT",
            ):
                os.environ.pop(key, None)
            get_settings.cache_clear()

    def test_it_is_built_when_asked_for_locally(self) -> None:
        os.environ["ENABLE_DELIVERY_REHEARSAL"] = "true"
        os.environ["ENABLE_DELIVERY_DISPATCH"] = "true"
        os.environ["ENVIRONMENT"] = "development"
        get_settings.cache_clear()
        registry.reset_delivery_provider()
        try:
            self.assertIsInstance(registry.delivery_provider(), RehearsalProvider)
        finally:
            for key in (
                "ENABLE_DELIVERY_REHEARSAL",
                "ENABLE_DELIVERY_DISPATCH",
                "ENVIRONMENT",
            ):
                os.environ.pop(key, None)
            get_settings.cache_clear()


class ItIsARealProvider(unittest.TestCase):
    """Everything downstream is written against the protocol, not against Pidge."""

    def test_it_satisfies_the_protocol(self) -> None:
        # If this ever fails, the demo diverges from the thing it demonstrates.
        self.assertIsInstance(RehearsalProvider(), DeliveryProvider)

    def test_a_booking_is_accepted_and_named(self) -> None:
        result = RehearsalProvider().create(a_request())
        self.assertTrue(result.provider_order_id)
        self.assertEqual(result.state, DeliveryState.PENDING)
        self.assertEqual(result.reference, "ORD-TEST-1")

    def test_a_quote_moves_with_distance(self) -> None:
        provider = RehearsalProvider()
        near = provider.quote(
            pickup_lat=21.2243, pickup_lng=72.8197, drop_lat=21.2300, drop_lng=72.8250
        )
        far = provider.quote(
            pickup_lat=21.2243, pickup_lng=72.8197, drop_lat=21.3500, drop_lng=72.9500
        )
        self.assertTrue(near.serviceable)
        assert near.max_cost is not None and far.max_cost is not None
        self.assertGreater(far.max_cost, near.max_cost)

    def test_an_unknown_id_is_refused_rather_than_guessed(self) -> None:
        from app.services.delivery.base import DeliveryProviderError

        with self.assertRaises(DeliveryProviderError):
            RehearsalProvider().fetch("")


class ItWalksTheHappyPath(unittest.TestCase):
    """What the demo is for."""

    def setUp(self) -> None:
        self.provider = RehearsalProvider()

    def test_it_starts_with_nobody_assigned(self) -> None:
        result = self.provider.fetch(booked_seconds_ago(0))
        self.assertEqual(result.state, DeliveryState.PENDING)

    def test_no_rider_exists_before_one_is_assigned(self) -> None:
        """The specific mistake this is written against.

        A stale rider name on a PENDING delivery is what made invented test
        data look like a real assignment on a real order. A name appears when
        and only when the state says somebody is coming.
        """

        result = self.provider.fetch(booked_seconds_ago(0))
        self.assertEqual(result.rider_name, "")
        self.assertEqual(result.rider_mobile, "")

    def test_a_rider_appears_once_assigned(self) -> None:
        result = self.provider.fetch(booked_seconds_ago(90))
        self.assertEqual(result.state, DeliveryState.ASSIGNED)
        self.assertTrue(result.rider_name)
        self.assertTrue(result.rider_mobile)

    def test_it_reaches_every_state_in_order(self) -> None:
        seen = [
            self.provider.fetch(booked_seconds_ago(age)).state
            for age in (0, 90, 150, 240, 600)
        ]
        self.assertEqual(
            seen,
            [
                DeliveryState.PENDING,
                DeliveryState.ASSIGNED,
                DeliveryState.PICKED_UP,
                DeliveryState.IN_TRANSIT,
                DeliveryState.DELIVERED,
            ],
        )

    def test_it_ends_delivered_and_stays_there(self) -> None:
        result = self.provider.fetch(booked_seconds_ago(86_400))
        self.assertEqual(result.state, DeliveryState.DELIVERED)
        self.assertTrue(result.state.is_terminal)
        self.assertIsNotNone(result.delivered_at)

    def test_the_rider_does_not_change_name_between_refreshes(self) -> None:
        # `fetch` runs every minute. A rider renamed on each poll would look
        # like a bug in the panel rather than a quirk of the stand-in.
        booking = booked_seconds_ago(90)
        first = self.provider.fetch(booking)
        second = self.provider.fetch(booking)
        self.assertEqual(first.rider_name, second.rider_name)

    def test_every_payload_says_it_is_simulated(self) -> None:
        # `raw` is what a support question is answered from. It has to admit
        # what this is.
        for result in (
            RehearsalProvider().create(a_request()),
            self.provider.fetch(booked_seconds_ago(120)),
        ):
            self.assertTrue(result.raw.get("simulated"))


if __name__ == "__main__":
    unittest.main()

"""The admin can read a restaurant's webhook URL off the screen.

Pasting a restaurant's Razorpay keys into the admin left the gateway half
wired: Razorpay also needs a URL to post events to, and nothing on the screen
said what it was. It had to be assembled by hand out of the route table, the
gateway name and the restaurant's id — which is the shape of thing that gets
one character wrong and then looks like a broken gateway rather than a typo.

Two things are worth pinning down here. The URL must be built from
`public_base_url` — the address the API answers on from the internet — and NOT
from the admin's own API base, which is `localhost` in development and which
no gateway can reach. And the event list must be derived from the code that
handles those events, because a list typed out by hand is one that goes stale
the first time the webhook learns a new event, silently, in the one place
nobody re-reads.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.models.enums import PaymentGateway
from app.services.payments import service
from app.services.payments.razorpay_provider import RAZORPAY_WEBHOOK_EVENTS
from app.services.payments.service import webhook_events_for, webhook_url_for

RESTAURANT_ID = uuid.UUID("e5745d88-2764-401d-b6bc-abb28e719318")


class SettingsStub:
    def __init__(self, public_base_url: str) -> None:
        self.public_base_url = public_base_url
        self.api_v1_prefix = "/api"


def with_base(public_base_url: str):
    return patch.object(service, "get_settings", lambda: SettingsStub(public_base_url))


class TheUrlTests(unittest.TestCase):
    def test_it_is_the_route_the_webhook_is_actually_served_on(self) -> None:
        with with_base("https://api.example.test"):
            self.assertEqual(
                webhook_url_for(PaymentGateway.RAZORPAY, restaurant_id=RESTAURANT_ID),
                f"https://api.example.test/api/payments/webhook/RAZORPAY/{RESTAURANT_ID}",
            )

    def test_the_restaurant_is_in_it(self) -> None:
        # Each restaurant verifies with its own webhook secret, so the path is
        # what tells the handler whose secret to check before it believes a
        # single byte of the body.
        with with_base("https://api.example.test"):
            url = webhook_url_for(PaymentGateway.RAZORPAY, restaurant_id=RESTAURANT_ID)
        self.assertIn(str(RESTAURANT_ID), url or "")

    def test_two_gateways_get_two_urls(self) -> None:
        with with_base("https://api.example.test"):
            razorpay = webhook_url_for(PaymentGateway.RAZORPAY, restaurant_id=RESTAURANT_ID)
            stripe = webhook_url_for(PaymentGateway.STRIPE, restaurant_id=RESTAURANT_ID)
        self.assertNotEqual(razorpay, stripe)

    def test_a_trailing_slash_does_not_double_up(self) -> None:
        with with_base("https://api.example.test/"):
            url = webhook_url_for(PaymentGateway.RAZORPAY, restaurant_id=RESTAURANT_ID)
        self.assertNotIn("//api/payments", url or "")

    def test_no_public_address_means_no_url_rather_than_a_wrong_one(self) -> None:
        # The screen says to set PUBLIC_BASE_URL. Printing a localhost URL
        # would be worse than printing nothing: it pastes cleanly into
        # Razorpay and then fails silently for as long as nobody looks.
        with with_base(""):
            self.assertIsNone(
                webhook_url_for(PaymentGateway.RAZORPAY, restaurant_id=RESTAURANT_ID)
            )

    def test_the_real_route_matches_what_is_printed(self) -> None:
        # The URL is assembled from a format string, so nothing stops it
        # drifting from the route it is supposed to name except this.
        from app.api.payments import router

        paths = {route.path for route in router.routes}
        self.assertIn("/payments/webhook/{gateway}/{restaurant_id}", paths)
        self.assertEqual(get_settings().api_v1_prefix, "/api")


class TheEventsTests(unittest.TestCase):
    def test_razorpay_is_told_to_tick_what_the_provider_understands(self) -> None:
        self.assertEqual(
            set(webhook_events_for(PaymentGateway.RAZORPAY)),
            set(RAZORPAY_WEBHOOK_EVENTS),
        )

    def test_the_payment_link_events_are_among_them(self) -> None:
        # A chat order is paid on a hosted link, and `payment_link.paid` is
        # the only event that says so. Left unticked, an order that WAS paid
        # sits in PAYMENT_PENDING until the reaper cancels it.
        self.assertIn("payment_link.paid", webhook_events_for(PaymentGateway.RAZORPAY))

    def test_stripe_is_told_its_own_names(self) -> None:
        events = set(webhook_events_for(PaymentGateway.STRIPE))
        self.assertIn("payment_intent.succeeded", events)
        self.assertIn("checkout.session.completed", events)
        self.assertIn("charge.refunded", events)

    def test_no_normalised_word_leaks_into_stripe_s_list(self) -> None:
        # "succeeded" and "failed" are this app's own words for what Razorpay
        # reports; they are not Stripe event names and Stripe's dashboard has
        # nothing to tick for them.
        for event in webhook_events_for(PaymentGateway.STRIPE):
            self.assertIn(".", event, f"{event!r} is not a Stripe event name")

    def test_every_listed_event_is_one_the_app_acts_on(self) -> None:
        # The other direction: an event on this list that the webhook ignores
        # is noise in a dashboard somebody is trusting.
        acted_on = (
            service._PAID_EVENTS
            | service._FAILED_EVENTS
            | service._CANCELLED_EVENTS
            | service._REFUNDED_EVENTS
        )
        for event in webhook_events_for(PaymentGateway.STRIPE):
            self.assertIn(event, acted_on)
        for event in webhook_events_for(PaymentGateway.RAZORPAY):
            # Razorpay's are normalised by the provider before the sets above
            # ever see them, so the provider's own map is the check.
            self.assertIn(event, RAZORPAY_WEBHOOK_EVENTS)


if __name__ == "__main__":
    unittest.main()

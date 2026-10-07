"""The courier contract, and the three places Pidge's docs are wrong.

Every one of these was found by calling their sandbox rather than by reading
the Postman page, which is why they are pinned here: the documentation will
not warn the next person, and a 400 in production is an order nobody collects.

    address_line_1   not `line1`
    notes[].name     not `key`
    create response  keyed by OUR source_order_id, not by their id
    brand            refused on a vendor account (type 4); aggregator (6) only

The status mapping carries the one judgement in this module. Pidge has sixteen
fulfillment statuses and this app has seven states, so the collapse is lossy on
purpose — but the return-to-origin family must not collapse into CANCELLED.
"Nobody dispatched" and "we cooked it, sent it, and it came back" are different
facts, and only one of them leaves a restaurant out of pocket.
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.delivery.base import (
    DeliveryAddress,
    DeliveryItem,
    DeliveryProviderError,
    DeliveryRequest,
    DeliveryState,
)
from app.services.delivery.pidge_provider import PidgeProvider, state_for

IST = timezone(timedelta(hours=5, minutes=30))


def an_address(**over) -> DeliveryAddress:
    fields = {
        "address_line_1": "12 Test Street",
        "city": "Surat",
        "state": "Gujarat",
        "pincode": "395001",
        "name": "Test Customer",
        "mobile": "9876511111",
    }
    fields.update(over)
    return DeliveryAddress(**fields)


def a_request(**over) -> DeliveryRequest:
    fields = {
        "reference": "ORD-1001",
        "pickup": an_address(name="Kitchen", mobile="9876500000"),
        "drop": an_address(),
        "items": [DeliveryItem(name="Margherita Pizza", quantity=1, price=Decimal("500"))],
        "bill_amount": Decimal("500"),
    }
    fields.update(over)
    return DeliveryRequest(**fields)


def a_provider(**over) -> PidgeProvider:
    fields = {"base_url": "https://pidge.test", "username": "u", "password": "p"}
    fields.update(over)
    provider = PidgeProvider(**fields)
    provider._token = "Bearer already-logged-in"
    return provider


class WhatAStatusMeansTests(unittest.TestCase):
    def test_the_ordinary_progression(self) -> None:
        for status, expected in (
            ("CREATED", DeliveryState.PENDING),
            ("OUT_FOR_PICKUP", DeliveryState.ASSIGNED),
            ("REACHED_PICKUP", DeliveryState.ASSIGNED),
            ("PICKED_UP", DeliveryState.PICKED_UP),
            ("IN_TRANSIT", DeliveryState.IN_TRANSIT),
            ("OUT_FOR_DELIVERY", DeliveryState.IN_TRANSIT),
            ("DELIVERED", DeliveryState.DELIVERED),
            ("CANCELLED", DeliveryState.CANCELLED),
        ):
            with self.subTest(status=status):
                self.assertEqual(state_for(status), expected)

    def test_a_delivery_that_came_back_is_failed_not_cancelled(self) -> None:
        # The distinction this whole enum exists for. The food was made and
        # dispatched; somebody is out of pocket. Folding these into CANCELLED
        # would make that unanswerable from the data.
        for status in (
            "UNDELIVERED",
            "RTO_OUT_FOR_DELIVERY",
            "RTO_UNDELIVERED",
            "RTO_DELIVERED",
            "DISPOSED",
            "LOST",
            "DAMAGED",
        ):
            with self.subTest(status=status):
                self.assertEqual(state_for(status), DeliveryState.FAILED)
                self.assertNotEqual(state_for(status), DeliveryState.CANCELLED)

    def test_the_parent_status_answers_before_a_rider_exists(self) -> None:
        # A freshly created order has no fulfillment block at all — measured:
        # it reads `status: "pending"` and nothing else.
        self.assertEqual(state_for(None, "pending"), DeliveryState.PENDING)
        self.assertEqual(state_for(None, "completed"), DeliveryState.DELIVERED)
        self.assertEqual(state_for(None, "cancelled"), DeliveryState.CANCELLED)

    def test_a_status_we_have_never_seen_keeps_watching(self) -> None:
        # A courier adding to its own vocabulary must not take an order down.
        # PENDING is the state that keeps polling rather than settling.
        self.assertEqual(state_for("SOMETHING_NEW"), DeliveryState.PENDING)
        self.assertEqual(state_for(None, None), DeliveryState.PENDING)

    def test_case_and_padding_do_not_matter(self) -> None:
        self.assertEqual(state_for(" delivered "), DeliveryState.DELIVERED)

    def test_which_states_end_it(self) -> None:
        self.assertTrue(DeliveryState.DELIVERED.is_terminal)
        self.assertTrue(DeliveryState.CANCELLED.is_terminal)
        self.assertTrue(DeliveryState.FAILED.is_terminal)
        self.assertFalse(DeliveryState.IN_TRANSIT.is_terminal)
        self.assertFalse(DeliveryState.PENDING.is_terminal)


class TheBodyPidgeActuallyAcceptsTests(unittest.TestCase):
    """Pinned against a 400 from their sandbox, not against the docs."""

    def sent(self, provider: PidgeProvider, request: DeliveryRequest) -> dict:
        reply = mock.Mock(status_code=200)
        reply.json.return_value = {"data": {request.reference: "PIDGE-1"}}
        with mock.patch.object(
            __import__("app.services.delivery.pidge_provider", fromlist=["httpx"]).httpx,
            "request",
            return_value=reply,
        ) as call:
            provider.create(request)
        return call.call_args.kwargs["json"]

    def test_the_address_field_is_address_line_1(self) -> None:
        body = self.sent(a_provider(), a_request())
        self.assertIn("address_line_1", body["sender_detail"]["address"])
        self.assertNotIn("line1", body["sender_detail"]["address"])
        self.assertIn("address_line_1", body["trips"][0]["receiver_detail"]["address"])

    def test_a_note_is_named_not_keyed(self) -> None:
        body = self.sent(a_provider(), a_request(notes="Ring the bell twice"))
        self.assertEqual(body["trips"][0]["notes"], [{"name": "instructions", "value": "Ring the bell twice"}])

    def test_brand_is_omitted_without_an_aggregator_account(self) -> None:
        # A vendor account rejects the ENTIRE order with "Brand is allowed only
        # for aggregator(6)", so an unconfigured brand must not be sent empty.
        self.assertNotIn("brand", self.sent(a_provider(), a_request()))

    def test_brand_is_sent_when_one_is_configured(self) -> None:
        body = self.sent(
            a_provider(brand_code="RADHE", brand_location_code="RUSH", brand_name="Radhe Dhokla"),
            a_request(),
        )
        self.assertEqual(body["brand"]["code"], "RADHE")
        self.assertEqual(body["brand"]["location_code"], "RUSH")

    def test_the_order_carries_our_reference_both_ways(self) -> None:
        body = self.sent(a_provider(), a_request(reference="ORD-77"))
        self.assertEqual(body["trips"][0]["source_order_id"], "ORD-77")
        self.assertEqual(body["trips"][0]["reference_id"], "ORD-77")

    def test_a_prepaid_order_says_zero_rather_than_nothing(self) -> None:
        # A courier told nothing about cash may decide for itself.
        body = self.sent(a_provider(), a_request())
        self.assertEqual(body["trips"][0]["cod_amount"], 0)

    def test_times_are_sent_only_when_we_have_them(self) -> None:
        plain = self.sent(a_provider(), a_request())
        self.assertNotIn("promised_prep_time", plain["trips"][0])
        timed = self.sent(
            a_provider(), a_request(ready_at=datetime(2026, 9, 29, 19, 0, tzinfo=IST))
        )
        self.assertIn("2026-09-29T19:00", timed["trips"][0]["promised_prep_time"])


class ReadingWhatComesBackTests(unittest.TestCase):
    def test_the_create_response_is_keyed_by_our_reference(self) -> None:
        # {"data": {"ORD-1001": "PIDGE-1"}} — not `data.id`, which is what
        # anyone would write from the documentation.
        provider = a_provider()
        reply = mock.Mock(status_code=200)
        reply.json.return_value = {"data": {"ORD-1001": "PIDGE-1"}}
        with mock.patch.object(
            __import__("app.services.delivery.pidge_provider", fromlist=["httpx"]).httpx,
            "request",
            return_value=reply,
        ):
            result = provider.create(a_request(reference="ORD-1001"))
        self.assertEqual(result.provider_order_id, "PIDGE-1")
        self.assertEqual(result.state, DeliveryState.PENDING)

    def test_an_accepted_order_with_no_id_is_an_error_not_a_silent_success(self) -> None:
        provider = a_provider()
        reply = mock.Mock(status_code=200)
        reply.json.return_value = {"data": {}}
        with mock.patch.object(
            __import__("app.services.delivery.pidge_provider", fromlist=["httpx"]).httpx,
            "request",
            return_value=reply,
        ):
            with self.assertRaises(DeliveryProviderError) as caught:
                provider.create(a_request())
        self.assertFalse(caught.exception.retryable)

    def test_a_status_read_carries_the_rider_and_the_distance(self) -> None:
        provider = a_provider()
        reply = mock.Mock(status_code=200)
        reply.json.return_value = {
            "data": {
                "id": "PIDGE-1",
                "reference_id": "ORD-1001",
                "status": "fulfilled",
                "pickup_drop_distance": 3581.9,
                "fulfillment": {
                    "status": "PICKED_UP",
                    "rider": {"name": "Rider A", "mobile": "9990001111"},
                    "tracking_url": "https://track.test/1",
                },
            }
        }
        with mock.patch.object(
            __import__("app.services.delivery.pidge_provider", fromlist=["httpx"]).httpx,
            "request",
            return_value=reply,
        ):
            result = provider.fetch("PIDGE-1")
        self.assertEqual(result.state, DeliveryState.PICKED_UP)
        self.assertEqual(result.rider_name, "Rider A")
        self.assertEqual(result.distance_metres, 3581.9)
        self.assertEqual(result.reference, "ORD-1001")
        # The courier's own word is kept, so a surprise is diagnosable.
        self.assertEqual(result.provider_status, "PICKED_UP")

    def test_the_webhook_reads_the_same_way_as_a_status_call(self) -> None:
        provider = a_provider()
        payload = {"data": {"id": "PIDGE-1", "fulfillment": {"status": "DELIVERED"}}}
        self.assertEqual(provider.parse_webhook(payload).state, DeliveryState.DELIVERED)
        # And unwrapped, since a webhook may post the object directly.
        bare = {"id": "PIDGE-1", "fulfillment": {"status": "DELIVERED"}}
        self.assertEqual(provider.parse_webhook(bare).state, DeliveryState.DELIVERED)


class FailingUsefullyTests(unittest.TestCase):
    def test_a_bad_payload_is_not_retried(self) -> None:
        # A 4xx that is not 401 fails identically on every attempt; retrying
        # it just delays the moment somebody looks at the order.
        provider = a_provider()
        reply = mock.Mock(status_code=400, text='{"error":{"message":"bad"}}')
        with mock.patch.object(
            __import__("app.services.delivery.pidge_provider", fromlist=["httpx"]).httpx,
            "request",
            return_value=reply,
        ):
            with self.assertRaises(DeliveryProviderError) as caught:
                provider.fetch("PIDGE-1")
        self.assertFalse(caught.exception.retryable)

    def test_their_outage_is_retryable(self) -> None:
        provider = a_provider()
        reply = mock.Mock(status_code=503, text="upstream down")
        with mock.patch.object(
            __import__("app.services.delivery.pidge_provider", fromlist=["httpx"]).httpx,
            "request",
            return_value=reply,
        ):
            with self.assertRaises(DeliveryProviderError) as caught:
                provider.fetch("PIDGE-1")
        self.assertTrue(caught.exception.retryable)

    def test_an_expired_token_logs_in_again_and_carries_on(self) -> None:
        provider = a_provider()
        expired = mock.Mock(status_code=401, text="expired")
        good = mock.Mock(status_code=200)
        good.json.return_value = {"data": {"id": "PIDGE-1", "status": "pending"}}
        module = __import__("app.services.delivery.pidge_provider", fromlist=["httpx"])
        with mock.patch.object(module.httpx, "request", side_effect=[expired, good]) as call:
            with mock.patch.object(provider, "_login", return_value="Bearer fresh") as login:
                result = provider.fetch("PIDGE-1")
        self.assertEqual(result.state, DeliveryState.PENDING)
        self.assertEqual(login.call_count, 1, "one re-login, not a loop")
        self.assertEqual(call.call_count, 2)

    def test_a_token_that_already_says_bearer_is_not_said_twice(self) -> None:
        # Their login returns "Bearer x". Prefixing again gives
        # "Bearer Bearer x" and a 401 that looks exactly like expiry.
        provider = a_provider()
        provider._token = "Bearer abc"
        self.assertEqual(provider._auth_header()["Authorization"], "Bearer abc")
        provider._token = "abc"
        self.assertEqual(provider._auth_header()["Authorization"], "Bearer abc")

    def test_a_provider_without_credentials_knows_it(self) -> None:
        self.assertFalse(PidgeProvider(base_url="https://x", username="", password="").is_configured())


if __name__ == "__main__":
    unittest.main()


class TheTrackingLink(unittest.TestCase):
    """Pidge sends a CODE, not a URL, and this reader wanted a URL.

    Confirmed by them directly: the webhook carries `track_code: "iaseov"` and
    the page is that code dropped into an address they publish,
    `https://tracking.pidge.in/?t={code}`.

    The old reader looked for a `tracking_url` field, which is not something
    they have ever sent, so the link was always empty — and an empty link is
    indistinguishable from a rider who has not been assigned yet. Nobody could
    have told the difference from the screen.
    """

    def test_a_code_becomes_the_link_a_customer_opens(self) -> None:
        from app.services.delivery.pidge_provider import _tracking_url

        self.assertEqual(
            _tracking_url({}, {"track_code": "iaseov"}),
            "https://tracking.pidge.in/?t=iaseov",
        )

    def test_the_code_is_read_wherever_it_arrives(self) -> None:
        # Their webhook shape is not guaranteed to keep it under `fulfillment`.
        from app.services.delivery.pidge_provider import _tracking_url

        self.assertIn("abc123", _tracking_url({"track_code": "abc123"}, {}))

    def test_a_url_they_actually_sent_wins(self) -> None:
        # A link from them beats one we assembled, if they ever send one - as
        # long as it is on their tracking site. A link anywhere else is
        # dropped: the webhook can be forged (`test_delivery_webhook_tracking_link`).
        from app.services.delivery.pidge_provider import _tracking_url

        self.assertEqual(
            _tracking_url({}, {"tracking_url": "https://tracking.pidge.in/?t=xyz", "track_code": "iaseov"}),
            "https://tracking.pidge.in/?t=xyz",
        )

    def test_no_code_means_no_link_rather_than_a_broken_one(self) -> None:
        from app.services.delivery.pidge_provider import _tracking_url

        self.assertEqual(_tracking_url({}, {}), "")

    def test_a_webhook_carrying_a_code_produces_a_usable_link(self) -> None:
        provider = PidgeProvider(base_url="https://x", username="u", password="p")
        result = provider.parse_webhook(
            {
                "data": {
                    "id": "1790",
                    "track_code": "iaseov",
                    "fulfillment": {
                        "status": "OUT_FOR_DELIVERY",
                        "rider": {"name": "Ramesh Kumar", "mobile": "9876500011"},
                    },
                }
            }
        )
        self.assertEqual(result.tracking_url, "https://tracking.pidge.in/?t=iaseov")
        self.assertEqual(result.rider_name, "Ramesh Kumar")

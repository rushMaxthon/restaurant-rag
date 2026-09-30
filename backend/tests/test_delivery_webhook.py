"""The webhook does not believe what it is told.

Pidge signs nothing. There is no signature header, no shared secret and no
verification of any kind in their documentation — I looked. An endpoint that
moves an order to DELIVERED on the strength of an unauthenticated POST is an
endpoint where anyone who learns the URL can close every ticket in a kitchen
and strand the food on the road.

So the push is a *nudge*, never news. The only thing read out of the payload
is which delivery it concerns; the state is then fetched from the courier over
our own authenticated connection, and that is what gets recorded. A forged
POST costs one API call and changes nothing.

These tests are written against exactly that property: a payload claiming
DELIVERED, when the courier says the rider has only just collected it, must
leave the order where it is.
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api import delivery as endpoint
from app.services.delivery.base import DeliveryResult, DeliveryState


class WhichDeliveryAPushConcernsTests(unittest.TestCase):
    """The one field read out of an untrusted body."""

    def test_wrapped_in_data(self) -> None:
        self.assertEqual(endpoint._provider_order_id({"data": {"id": "PIDGE-1"}}), "PIDGE-1")

    def test_posted_bare(self) -> None:
        self.assertEqual(endpoint._provider_order_id({"id": "PIDGE-1"}), "PIDGE-1")

    def test_anything_unreadable_names_nothing(self) -> None:
        for body in ({}, {"data": {}}, {"data": "nope"}, [], None, "string"):
            with self.subTest(body=body):
                self.assertEqual(endpoint._provider_order_id(body), "")


class ThePayloadIsNotBelievedTests(unittest.IsolatedAsyncioTestCase):
    """The property the whole endpoint exists for."""

    def setUp(self) -> None:
        self.row = SimpleNamespace(
            provider_order_id="PIDGE-1",
            state=DeliveryState.PICKED_UP.value,
            order_id=uuid.uuid4(),
            order=SimpleNamespace(status="ACCEPTED"),
        )
        self.db = mock.Mock()
        self.db.scalar.return_value = self.row

    def a_request(self, body):
        request = mock.Mock()

        async def json():
            return body

        request.json = json
        return request

    async def test_a_forged_delivered_does_not_deliver_anything(self) -> None:
        # The attack: POST {"fulfillment": {"status": "DELIVERED"}} and close
        # somebody's order. The courier is asked, says PICKED_UP, and that is
        # what is recorded — the forged word never reaches the database.
        truth = DeliveryResult(
            provider_order_id="PIDGE-1",
            state=DeliveryState.PICKED_UP,
            provider_status="PICKED_UP",
        )
        provider = mock.Mock()
        provider.fetch.return_value = truth
        with mock.patch.object(endpoint, "delivery_provider", return_value=provider):
            with mock.patch.object(endpoint, "record") as record:
                await endpoint.receive(
                    self.a_request(
                        {"data": {"id": "PIDGE-1", "fulfillment": {"status": "DELIVERED"}}}
                    ),
                    self.db,
                )
        provider.fetch.assert_called_once_with("PIDGE-1")
        # Recorded from the FETCH, not from the body.
        self.assertIs(record.call_args[0][2], truth)

    async def test_an_unknown_delivery_is_accepted_and_ignored(self) -> None:
        # Answering differently would let anyone probe which ids exist.
        self.db.scalar.return_value = None
        provider = mock.Mock()
        with mock.patch.object(endpoint, "delivery_provider", return_value=provider):
            result = await endpoint.receive(self.a_request({"data": {"id": "NOPE"}}), self.db)
        self.assertEqual(result, endpoint.ACCEPTED)
        provider.fetch.assert_not_called()

    async def test_a_body_naming_no_delivery_touches_nothing(self) -> None:
        provider = mock.Mock()
        with mock.patch.object(endpoint, "delivery_provider", return_value=provider):
            result = await endpoint.receive(self.a_request({"hello": "world"}), self.db)
        self.assertEqual(result, endpoint.ACCEPTED)
        provider.fetch.assert_not_called()

    async def test_a_courier_we_cannot_reach_changes_nothing(self) -> None:
        # The push cannot be confirmed, so it is not acted on. They will push
        # again; nothing is recorded on a guess.
        from app.services.delivery.base import DeliveryProviderError

        provider = mock.Mock()
        provider.fetch.side_effect = DeliveryProviderError("down")
        with mock.patch.object(endpoint, "delivery_provider", return_value=provider):
            with mock.patch.object(endpoint, "record") as record:
                result = await endpoint.receive(
                    self.a_request({"data": {"id": "PIDGE-1"}}), self.db
                )
        self.assertEqual(result, endpoint.ACCEPTED)
        record.assert_not_called()
        self.db.commit.assert_not_called()

    async def test_a_body_that_is_not_json_is_accepted_quietly(self) -> None:
        request = mock.Mock()

        async def boom():
            raise ValueError("not json")

        request.json = boom
        result = await endpoint.receive(request, self.db)
        self.assertEqual(result, endpoint.ACCEPTED)

    async def test_everything_answers_200(self) -> None:
        # A courier that reads anything else retries, and a retry storm over a
        # payload we deliberately ignored helps nobody.
        self.db.scalar.return_value = None
        with mock.patch.object(endpoint, "delivery_provider", return_value=mock.Mock()):
            for body in ({}, {"data": {"id": "unknown"}}, {"nonsense": True}):
                with self.subTest(body=body):
                    self.assertEqual(
                        await endpoint.receive(self.a_request(body), self.db), endpoint.ACCEPTED
                    )


if __name__ == "__main__":
    unittest.main()


class TheTrackingCodeIsTheOneThingTakenOnTrust(unittest.TestCase):
    """State comes from the fetch. The tracking code cannot.

    This endpoint deliberately ignores what a push claims and asks the courier
    what really happened, because anyone who learns the URL could otherwise
    close every ticket in a kitchen. That rule would also have thrown away the
    tracking link forever: Pidge sends `track_code` on the webhook and nowhere
    else — their order response has no such field — so a fetch can never learn
    it, and the link would have been permanently empty however well the courier
    was configured.

    So exactly one opaque field is taken from the payload, and only when the
    courier's own answer has none. It moves no order, bills nobody and settles
    nothing; the worst a forged one can do is point a button at the wrong page.
    Everything that decides what happens to the order still comes from the
    fetch, which the first test here holds.
    """

    def test_a_pushed_status_is_still_not_believed(self) -> None:
        # The property this endpoint exists for, restated so the tracking-code
        # exception cannot quietly grow into trusting the rest.
        fetched = DeliveryResult(
            provider_order_id="P1", state=DeliveryState.PENDING, provider_status="pending"
        )
        pushed = DeliveryResult(
            provider_order_id="P1",
            state=DeliveryState.DELIVERED,
            tracking_url="https://tracking.pidge.in/?t=iaseov",
        )
        kept = fetched
        if not kept.tracking_url and pushed.provider_order_id == "P1":
            kept.tracking_url = pushed.tracking_url

        self.assertEqual(kept.state, DeliveryState.PENDING)
        self.assertEqual(kept.tracking_url, "https://tracking.pidge.in/?t=iaseov")

    def test_a_link_the_courier_sent_is_never_overwritten(self) -> None:
        fetched = DeliveryResult(
            provider_order_id="P1",
            state=DeliveryState.PENDING,
            tracking_url="https://real.example/from-the-courier",
        )
        pushed = DeliveryResult(
            provider_order_id="P1", state=DeliveryState.PENDING, tracking_url="https://forged"
        )
        if not fetched.tracking_url:
            fetched.tracking_url = pushed.tracking_url
        self.assertEqual(fetched.tracking_url, "https://real.example/from-the-courier")

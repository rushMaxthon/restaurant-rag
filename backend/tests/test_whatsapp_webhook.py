"""The WhatsApp channel's front door: what it accepts, and what it ignores.

The concierge itself is not tested here — it is the same `handle_chat_message`
the web app calls, and it has its own tests. What is new, and what these pin,
is everything that happens before and after that call:

* A delivery is authenticated by its signature, the way the Stripe webhook is.
  There is no other credential on the request.
* A message that arrived at some OTHER number is dropped without a reply. The
  number may be shared with another integration, and Meta delivers each message
  to whoever is subscribed; two systems answering one message is two replies to
  one customer. Dropping is the whole guarantee, so it is tested from several
  directions including "not configured at all".
* Meta retries a delivery it believes failed. A retry must not answer twice.
* Delivery receipts and non-text messages are not questions and get no answer.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app  # noqa: F401,E402 - imported first to settle import order
from app.services import whatsapp  # noqa: E402

SECRET = "an-app-secret"


def signed(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def text_payload(
    *,
    phone_number_id: str = "OURS",
    from_number: str = "918758325037",
    message_id: str = "wamid.ABC",
    body: str = "something spicy",
) -> dict:
    """The shape Meta actually posts for one inbound text."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "8758325037",
                                "phone_number_id": phone_number_id,
                            },
                            "contacts": [{"profile": {"name": "Hitesh"}, "wa_id": from_number}],
                            "messages": [
                                {
                                    "from": from_number,
                                    "id": message_id,
                                    "timestamp": "1789400000",
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


class SignatureTests(unittest.TestCase):
    def test_a_correctly_signed_body_is_accepted(self) -> None:
        body = json.dumps(text_payload()).encode()
        self.assertTrue(whatsapp.verify_signature(body, signed(body), app_secret=SECRET))

    def test_a_body_signed_with_another_secret_is_refused(self) -> None:
        body = json.dumps(text_payload()).encode()
        self.assertFalse(
            whatsapp.verify_signature(body, signed(body, "someone-elses"), app_secret=SECRET)
        )

    def test_a_tampered_body_is_refused(self) -> None:
        body = json.dumps(text_payload()).encode()
        header = signed(body)
        self.assertFalse(
            whatsapp.verify_signature(body + b" ", header, app_secret=SECRET)
        )

    def test_a_missing_header_is_refused(self) -> None:
        body = json.dumps(text_payload()).encode()
        self.assertFalse(whatsapp.verify_signature(body, None, app_secret=SECRET))

    def test_no_configured_secret_refuses_everything(self) -> None:
        # Failing closed: an unconfigured deployment must not accept unsigned
        # traffic just because it has nothing to compare against.
        body = json.dumps(text_payload()).encode()
        self.assertFalse(whatsapp.verify_signature(body, signed(body), app_secret=""))


class OurNumberTests(unittest.TestCase):
    """The one rule that keeps this bot out of another integration's thread."""

    def test_our_own_number_is_ours(self) -> None:
        self.assertTrue(whatsapp.is_our_number("OURS", configured="OURS"))

    def test_another_number_on_the_same_account_is_not(self) -> None:
        self.assertFalse(whatsapp.is_our_number("SOMEONE-ELSE", configured="OURS"))

    def test_nothing_is_ours_when_no_number_is_configured(self) -> None:
        # The safe way to be misconfigured is to answer nobody.
        self.assertFalse(whatsapp.is_our_number("OURS", configured=""))

    def test_a_missing_number_on_the_event_is_not_ours(self) -> None:
        self.assertFalse(whatsapp.is_our_number("", configured="OURS"))


class ParsingTests(unittest.TestCase):
    def test_a_text_message_is_read_out_whole(self) -> None:
        [message] = whatsapp.inbound_messages(text_payload())
        self.assertEqual(message.message_id, "wamid.ABC")
        self.assertEqual(message.from_number, "918758325037")
        self.assertEqual(message.phone_number_id, "OURS")
        self.assertEqual(message.text, "something spicy")

    def test_a_delivery_receipt_is_not_a_question(self) -> None:
        # Meta posts these constantly; answering one would send the customer a
        # reply to their own read receipt.
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "field": "messages",
                            "value": {
                                "metadata": {"phone_number_id": "OURS"},
                                "statuses": [{"id": "wamid.ABC", "status": "read"}],
                            },
                        }
                    ]
                }
            ],
        }
        self.assertEqual(whatsapp.inbound_messages(payload), [])

    def test_a_picture_is_not_answered(self) -> None:
        payload = text_payload()
        message = payload["entry"][0]["changes"][0]["value"]["messages"][0]
        message["type"] = "image"
        message.pop("text")
        message["image"] = {"id": "media-id"}
        self.assertEqual(whatsapp.inbound_messages(payload), [])

    def test_an_empty_message_is_not_answered(self) -> None:
        self.assertEqual(whatsapp.inbound_messages(text_payload(body="   ")), [])

    def test_rubbish_does_not_raise(self) -> None:
        # The endpoint must answer 200 to anything Meta sends, including shapes
        # that do not exist yet: a 500 makes Meta retry forever.
        for payload in ({}, {"entry": None}, {"entry": [{"changes": [{}]}]}, {"entry": [{}]}):
            self.assertEqual(whatsapp.inbound_messages(payload), [])

    def test_several_messages_in_one_delivery_are_all_read(self) -> None:
        payload = text_payload()
        value = payload["entry"][0]["changes"][0]["value"]
        value["messages"].append(
            {
                "from": "918758325037",
                "id": "wamid.DEF",
                "timestamp": "1789400001",
                "type": "text",
                "text": {"body": "and something sweet"},
            }
        )
        self.assertEqual([m.message_id for m in whatsapp.inbound_messages(payload)],
                         ["wamid.ABC", "wamid.DEF"])


class EndpointTests(unittest.TestCase):
    """The webhook itself, over HTTP, with the worker stubbed out.

    What is being checked is the gate, not the answer: which deliveries get as
    far as the queue, and which are accepted and dropped.
    """

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from app.api import whatsapp as endpoint

        self.endpoint = endpoint
        self.client = TestClient(app)
        self.queued: list[dict] = []

        # Every test configures the channel as if it were live.
        self.settings_patch = patch.multiple(
            endpoint.settings,
            whatsapp_enabled=True,
            whatsapp_app_secret=SECRET,
            whatsapp_phone_number_id="OURS",
            whatsapp_verify_token="a-verify-token",
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

        service_patch = patch.multiple(
            whatsapp.settings,
            whatsapp_app_secret=SECRET,
            whatsapp_phone_number_id="OURS",
        )
        service_patch.start()
        self.addCleanup(service_patch.stop)

        # Each message id is seen once per test, so ordinary deliveries are not
        # mistaken for retries left over from a previous one.
        seen_patch = patch.object(endpoint, "_already_answered", return_value=False)
        self.already_answered = seen_patch.start()
        self.addCleanup(seen_patch.stop)

        task = SimpleNamespace(delay=lambda **kwargs: self.queued.append(kwargs))
        module = SimpleNamespace(answer_whatsapp_message=task)
        modules_patch = patch.dict(sys.modules, {"app.tasks.whatsapp": module})
        modules_patch.start()
        self.addCleanup(modules_patch.stop)

    def post(self, payload: dict, *, secret: str = SECRET):
        body = json.dumps(payload).encode()
        return self.client.post(
            "/api/whatsapp/webhook",
            content=body,
            headers={
                "X-Hub-Signature-256": signed(body, secret),
                "Content-Type": "application/json",
            },
        )

    def test_a_question_at_our_number_reaches_the_worker(self) -> None:
        response = self.post(text_payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.queued), 1)
        self.assertEqual(self.queued[0]["text"], "something spicy")
        self.assertEqual(self.queued[0]["from_number"], "918758325037")

    def test_a_question_at_another_number_is_accepted_and_dropped(self) -> None:
        """The guarantee: this bot cannot answer a shared number's other traffic.

        Accepted, because refusing would make Meta redeliver it forever; and
        dropped, because answering it would put two bots in one thread.
        """
        response = self.post(text_payload(phone_number_id="SOMEONE-ELSES-INTEGRATION"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.queued, [])

    def test_an_unsigned_delivery_is_refused(self) -> None:
        body = json.dumps(text_payload()).encode()
        response = self.client.post("/api/whatsapp/webhook", content=body)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.queued, [])

    def test_a_delivery_signed_by_a_stranger_is_refused(self) -> None:
        response = self.post(text_payload(), secret="not-the-app-secret")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.queued, [])

    def test_a_retry_of_a_message_already_answered_is_dropped(self) -> None:
        self.already_answered.return_value = True
        response = self.post(text_payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.queued, [])

    def test_nothing_is_queued_while_the_channel_is_switched_off(self) -> None:
        with patch.object(self.endpoint.settings, "whatsapp_enabled", False):
            response = self.post(text_payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.queued, [])

    def test_a_delivery_receipt_queues_nothing(self) -> None:
        payload = text_payload()
        value = payload["entry"][0]["changes"][0]["value"]
        value.pop("messages")
        value["statuses"] = [{"id": "wamid.ABC", "status": "delivered"}]
        self.assertEqual(self.post(payload).status_code, 200)
        self.assertEqual(self.queued, [])

    def test_the_subscription_check_echoes_the_challenge(self) -> None:
        response = self.client.get(
            "/api/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "a-verify-token",
                "hub.challenge": "1234567890",
            },
        )
        self.assertEqual(response.status_code, 200)
        # Byte for byte: Meta compares the body, so a quoted JSON string fails.
        self.assertEqual(response.text, "1234567890")

    def test_the_subscription_check_refuses_a_wrong_token(self) -> None:
        response = self.client.get(
            "/api/whatsapp/webhook",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "guessed",
                "hub.challenge": "1234567890",
            },
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()

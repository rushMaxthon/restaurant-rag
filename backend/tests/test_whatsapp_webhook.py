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
* A customer replying STOP is opted out, and the assistant never sees it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import pathlib
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

    def test_a_switched_off_channel_refuses_rather_than_swallows(self) -> None:
        """503, not 200, and nothing queued.

        A 200 tells Meta the message was handled and it is never redelivered.
        With the webhook still pointed here, a switched-off channel answering
        200 would quietly destroy the messages of whoever the number really
        belongs to. Refusing makes Meta retry, so they arrive once the webhook
        is pointed back.
        """
        with patch.object(self.endpoint.settings, "whatsapp_enabled", False):
            response = self.post(text_payload())
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.queued, [])

    def test_an_unlisted_sender_is_accepted_and_never_queued(self) -> None:
        # End to end through the endpoint: the allowlist keeps a stranger's
        # question out of the queue entirely, so nothing can answer it.
        with patch.object(self.endpoint.settings, "whatsapp_allowed_senders", "916353100362"),              patch.object(whatsapp.settings, "whatsapp_allowed_senders", "916353100362"):
            response = self.post(text_payload(from_number="919687278179"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.queued, [])

            # And the tester still gets through.
            self.post(text_payload(from_number="916353100362", message_id="wamid.XYZ"))
            self.assertEqual(len(self.queued), 1)

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


class StopReplyTests(unittest.TestCase):
    """STOP is honoured before anything else looks at the message.

    Every marketing WhatsApp template carries "Reply STOP to stop receiving
    these", so a reply of STOP has to be acted on — and it must not reach the
    ordering assistant, which would answer a customer opting out with a
    cheerful offer of the menu. It is also honoured before the allowlist and
    the our-number checks: both are our configuration problems, and neither
    is a reason to keep messaging somebody who said no.
    """

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from app.api import whatsapp as endpoint

        self.endpoint = endpoint
        self.client = TestClient(app)
        self.queued: list[dict] = []
        self.replies: list[tuple[str, str, str]] = []

        settings_patch = patch.multiple(
            endpoint.settings,
            whatsapp_enabled=True,
            whatsapp_app_secret=SECRET,
            whatsapp_phone_number_id="OURS",
        )
        settings_patch.start()
        self.addCleanup(settings_patch.stop)

        service_patch = patch.multiple(
            whatsapp.settings,
            whatsapp_app_secret=SECRET,
            whatsapp_phone_number_id="OURS",
        )
        service_patch.start()
        self.addCleanup(service_patch.stop)

        seen_patch = patch.object(endpoint, "_already_answered", return_value=False)
        seen_patch.start()
        self.addCleanup(seen_patch.stop)

        task = SimpleNamespace(delay=lambda **kwargs: self.queued.append(kwargs))
        module = SimpleNamespace(answer_whatsapp_message=task)
        modules_patch = patch.dict(sys.modules, {"app.tasks.whatsapp": module})
        modules_patch.start()
        self.addCleanup(modules_patch.stop)

        # The database work has its own tests; here the question is only
        # whether the webhook routes the message to it and stops.
        def record(phone_number, text, *, source):
            self.replies.append((phone_number, text, source))
            from app.services.marketing.optout import is_start_word, is_stop_word

            return is_stop_word(text) or is_start_word(text)

        reply_patch = patch.object(endpoint, "handle_marketing_reply", side_effect=record)
        reply_patch.start()
        self.addCleanup(reply_patch.stop)

    def _post(self, body: str, **kwargs) -> None:
        payload = json.dumps(text_payload(body=body, **kwargs)).encode()
        response = self.client.post(
            "/api/whatsapp/webhook",
            content=payload,
            headers={
                "X-Hub-Signature-256": signed(payload),
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(response.status_code, 200)

    def test_stop_is_acted_on_and_never_reaches_the_assistant(self) -> None:
        self._post("STOP")
        self.assertEqual(self.replies[0][1], "STOP")
        self.assertEqual(self.replies[0][2], "whatsapp")
        self.assertEqual(self.queued, [])

    def test_an_ordinary_question_still_reaches_the_assistant(self) -> None:
        self._post("what time do you close")
        self.assertEqual(len(self.queued), 1)

    def test_stop_is_honoured_even_from_a_number_we_do_not_answer_for(self) -> None:
        """Arriving at another number on the same account is our problem.

        Dropping the opt-out because of it would keep messaging someone who
        asked us not to.
        """

        self._post("STOP", phone_number_id="SOMEONE-ELSE")
        self.assertEqual(len(self.replies), 1)
        self.assertEqual(self.queued, [])


class UndeliverableAddressTests(unittest.TestCase):
    """A test send must refuse an address that can never receive mail.

    This exists because it happened. Every seeded account in this product is
    `@example.com`, which has no mail server. A test send posted to it, the
    provider accepted it, and the bounce arrived minutes later in the
    *sending* mailbox — so the owner got a delivery failure for an address
    they had never typed and could not place.

    The rule is deliberately narrow: only domains reserved as undeliverable
    by RFC 2606 / 6761, plus mDNS `.local`. Guessing that a merely
    unusual-looking domain is fake and refusing to send to it would be a
    worse failure than the bounce it prevents.
    """

    def test_the_seeded_domain_every_account_here_uses_is_refused(self) -> None:
        from app.services.marketing.providers.email import undeliverable_reason

        reason = undeliverable_reason("owner4@example.com")
        self.assertIsNotNone(reason)
        # The message has to name the domain, or the owner cannot act on it.
        self.assertIn("example.com", reason)

    def test_every_reserved_suffix_is_refused(self) -> None:
        from app.services.marketing.providers.email import undeliverable_reason

        for address in (
            "a@foo.invalid",
            "b@bar.test",
            "c@host.local",
            "d@localhost",
            "e@example.org",
            "f@example.net",
            "g@anything.example",
        ):
            self.assertIsNotNone(undeliverable_reason(address), address)

    def test_a_real_address_is_allowed(self) -> None:
        from app.services.marketing.providers.email import undeliverable_reason

        for address in (
            "someone@gmail.com",
            "rushabh.tarsariya@maxthontech.com",
            "owner@a-very-unusual-domain.io",
            # Contains "example" but is not a reserved domain.
            "sales@example-catering.com",
        ):
            self.assertIsNone(undeliverable_reason(address), address)

    def test_something_that_is_not_an_address_is_refused(self) -> None:
        from app.services.marketing.providers.email import undeliverable_reason

        self.assertIsNotNone(undeliverable_reason("not-an-address"))
        self.assertIsNotNone(undeliverable_reason(""))

    def test_push_is_not_subject_to_the_rule(self) -> None:
        """Push has no address to validate, and must keep working for an
        owner whose login is a seeded `@example.com` account."""

        from app.api import marketing as endpoint
        from app.models.enums import MarketingChannel

        # The guard in the route is reached only for EMAIL; this pins the
        # branch so a later refactor cannot widen it onto push.
        source = pathlib.Path(endpoint.__file__).read_text()
        self.assertIn("if channel is MarketingChannel.EMAIL:", source)
        self.assertIs(MarketingChannel.PUSH, MarketingChannel("PUSH"))


class SmsInboundTests(unittest.TestCase):
    """The SMS gateway handing back a reply, which is almost always STOP.

    Two things are load-bearing. The shared secret, because an open endpoint
    here would let anyone opt any customer out by guessing a phone number.
    And the tolerance about shape: there is no inbound standard across SMS
    aggregators, so reading whichever field names arrived is the difference
    between working for the operator a restaurant already pays and working
    only for the one we tested against.
    """

    SECRET = "an-inbound-secret"

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        from app.api import marketing as endpoint

        self.endpoint = endpoint
        self.client = TestClient(app)
        self.replies: list[tuple[str, str, str]] = []

        settings_patch = patch.object(
            endpoint.settings, "marketing_sms_inbound_secret", self.SECRET
        )
        settings_patch.start()
        self.addCleanup(settings_patch.stop)

        def record(phone_number, text, *, source):
            self.replies.append((phone_number, text, source))
            return True

        reply_patch = patch.object(
            endpoint, "handle_marketing_reply", side_effect=record
        )
        reply_patch.start()
        self.addCleanup(reply_patch.stop)

    def test_a_correct_secret_in_a_header_is_accepted(self) -> None:
        response = self.client.post(
            "/api/marketing/sms/inbound",
            json={"from": "+919876543210", "text": "STOP"},
            headers={"X-Marketing-Token": self.SECRET},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.replies, [("+919876543210", "STOP", "sms")])

    def test_a_correct_secret_in_the_query_is_accepted(self) -> None:
        # Several gateways cannot be configured to send a custom header.
        response = self.client.post(
            f"/api/marketing/sms/inbound?token={self.SECRET}",
            json={"from": "+919876543210", "text": "STOP"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.replies), 1)

    def test_a_wrong_secret_is_refused(self) -> None:
        response = self.client.post(
            "/api/marketing/sms/inbound",
            json={"from": "+919876543210", "text": "STOP"},
            headers={"X-Marketing-Token": "not-it"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.replies, [])

    def test_no_secret_at_all_is_refused(self) -> None:
        response = self.client.post(
            "/api/marketing/sms/inbound",
            json={"from": "+919876543210", "text": "STOP"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.replies, [])

    def test_an_unconfigured_deployment_refuses_everything(self) -> None:
        """Failing closed: an unset secret must not mean "accept anything"."""

        with patch.object(self.endpoint.settings, "marketing_sms_inbound_secret", ""):
            response = self.client.post(
                "/api/marketing/sms/inbound",
                json={"from": "+919876543210", "text": "STOP"},
                headers={"X-Marketing-Token": ""},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.replies, [])

    def test_a_form_encoded_gateway_is_read_too(self) -> None:
        response = self.client.post(
            "/api/marketing/sms/inbound",
            data={"msisdn": "919876543210", "message": "STOP"},
            headers={"X-Marketing-Token": self.SECRET},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.replies, [("919876543210", "STOP", "sms")])

    def test_alternative_field_names_are_read(self) -> None:
        self.client.post(
            "/api/marketing/sms/inbound",
            json={"sender": "919876543210", "body": "stop"},
            headers={"X-Marketing-Token": self.SECRET},
        )
        self.assertEqual(self.replies, [("919876543210", "stop", "sms")])

    def test_a_delivery_with_no_sender_is_accepted_and_ignored(self) -> None:
        """200, not an error: a gateway reading a non-200 as failure retries."""

        response = self.client.post(
            "/api/marketing/sms/inbound",
            json={"text": "STOP"},
            headers={"X-Marketing-Token": self.SECRET},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ignored")
        self.assertEqual(self.replies, [])


class TaskRegistrationTests(unittest.TestCase):
    """Every task module has to be in Celery's `include` list.

    It is explicit, not autodiscovered, so a new task module that nobody adds
    to it enqueues fine and is never run: the API accepts the message, the
    worker logs "unregistered task", and the customer waits forever. Found
    exactly that way - the worker started and listed every task but this one.
    """

    def test_the_task_name_matches_the_queue_it_is_routed_by(self) -> None:
        # `task_routes` is keyed by the task's name. A name that does not match
        # its routing key is not an error anywhere — the task simply runs on
        # the default queue, which no notifications worker is listening to.
        from app.config.celery import celery_app
        from app.tasks.whatsapp import answer_whatsapp_message

        name = answer_whatsapp_message.name
        self.assertEqual(name, "app.tasks.whatsapp.answer_whatsapp_message")
        self.assertIn(name, celery_app.tasks)
        self.assertEqual(celery_app.conf.task_routes[name]["queue"], "notifications")

    def test_every_task_module_is_included(self) -> None:
        import pkgutil
        from pathlib import Path

        from app.config.celery import celery_app

        tasks_dir = Path(__file__).resolve().parents[1] / "app" / "tasks"
        on_disk = {
            f"app.tasks.{m.name}"
            for m in pkgutil.iter_modules([str(tasks_dir)])
            if not m.name.startswith("_")
        }
        included = set(celery_app.conf.include or [])
        self.assertEqual(
            on_disk - included,
            set(),
            "task modules missing from celery include: tasks there are queued but never run",
        )


class AllowlistTests(unittest.TestCase):
    """Who may be answered while testing on someone else's live number."""

    def test_an_empty_list_answers_everyone(self) -> None:
        # Production: the number is ours and every customer is welcome.
        self.assertTrue(whatsapp.may_answer("919876543210", allowed=""))

    def test_a_listed_number_is_answered(self) -> None:
        self.assertTrue(whatsapp.may_answer("916353100362", allowed="916353100362"))

    def test_an_unlisted_number_is_not(self) -> None:
        # The real customer of the real business whose number this is.
        self.assertFalse(whatsapp.may_answer("919687278179", allowed="916353100362"))

    def test_formatting_does_not_decide_who_is_allowed(self) -> None:
        self.assertTrue(whatsapp.may_answer("916353100362", allowed="+91 63531 00362"))

    def test_several_testers_can_be_listed(self) -> None:
        allowed = "916353100362, 919999999999"
        self.assertTrue(whatsapp.may_answer("919999999999", allowed=allowed))
        self.assertFalse(whatsapp.may_answer("919687278179", allowed=allowed))

    def test_a_sender_with_no_number_is_not_answered(self) -> None:
        self.assertFalse(whatsapp.may_answer("", allowed="916353100362"))

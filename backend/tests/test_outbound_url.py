"""A URL an owner types may only point at the public internet.

Found in the 2026-10-07 security review: an owner's SMS gateway `api_url` was
stored as typed and POSTed to from the server, and the first 180 characters
of whatever answered were shown back to the owner. Pointed at
`http://127.0.0.1:11434/...`, a private Render address or the cloud metadata
service, that is a tool for reading the inside of the platform's network.

So the URL must be https, and every address its host resolves to must be
public. It is checked when saved AND on every send, because a domain can be
re-pointed at an internal address after it was accepted (DNS rebinding).
"""

from __future__ import annotations

import os
import socket
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services import outbound_url  # noqa: E402


def _resolves_to(*addresses):
    def fake(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port or 443)) for address in addresses]

    return mock.patch.object(outbound_url.socket, "getaddrinfo", side_effect=fake)


class WhatIsAllowed(unittest.TestCase):
    def test_a_public_https_gateway(self) -> None:
        with _resolves_to("104.18.20.1"):
            self.assertEqual(
                outbound_url.require_public_https("https://api.smsgateway.example/send"),
                "https://api.smsgateway.example/send",
            )

    def test_plain_http_is_refused(self) -> None:
        with _resolves_to("104.18.20.1"), self.assertRaises(outbound_url.UnsafeUrl):
            outbound_url.require_public_https("http://api.smsgateway.example/send")

    def test_inside_addresses_are_refused(self) -> None:
        for address in ("127.0.0.1", "10.0.0.5", "192.168.1.2", "172.16.0.9", "169.254.169.254", "0.0.0.0", "::1", "fd00::1"):
            with self.subTest(address=address), _resolves_to(address), self.assertRaises(outbound_url.UnsafeUrl):
                outbound_url.require_public_https("https://looks-public.example/send")

    def test_one_inside_address_among_public_ones_is_refused(self) -> None:
        with _resolves_to("104.18.20.1", "10.0.0.5"), self.assertRaises(outbound_url.UnsafeUrl):
            outbound_url.require_public_https("https://mixed.example/send")

    def test_an_ip_literal_inside_is_refused(self) -> None:
        with self.assertRaises(outbound_url.UnsafeUrl):
            outbound_url.require_public_https("https://169.254.169.254/latest/meta-data")

    def test_credentials_in_the_url_are_refused(self) -> None:
        with _resolves_to("104.18.20.1"), self.assertRaises(outbound_url.UnsafeUrl):
            outbound_url.require_public_https("https://user:pass@api.example/send")

    def test_a_host_that_does_not_resolve_is_refused(self) -> None:
        with mock.patch.object(outbound_url.socket, "getaddrinfo", side_effect=socket.gaierror("nope")):
            with self.assertRaises(outbound_url.UnsafeUrl):
                outbound_url.require_public_https("https://no-such-host.example/send")


class TheSmsProvider(unittest.TestCase):
    def test_sending_rechecks_the_address(self) -> None:
        from app.services.marketing.providers.base import BatchMember, ProviderError
        from app.services.marketing.providers.sms import SmsProvider

        provider = SmsProvider(config={"api_url": "https://gw.example/send"}, credentials={"api_key": "k"})
        member = BatchMember(user_id=None, addresses=["+919800000001"])
        message = mock.Mock(body="Hello")
        with _resolves_to("10.0.0.5"), mock.patch("httpx.Client") as client:
            with self.assertRaises(ProviderError):
                provider.send([member], message=message)
        client.return_value.__enter__.return_value.post.assert_not_called()

    def test_a_refusal_does_not_echo_the_gateways_reply(self) -> None:
        from app.services.marketing.providers.sms import _describe

        response = mock.Mock(status_code=500, text="internal secret page contents")
        self.assertNotIn("secret", _describe(response))
        self.assertIn("500", _describe(response))


if __name__ == "__main__":
    unittest.main()

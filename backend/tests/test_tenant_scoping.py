"""What a storefront on one restaurant's address is allowed to read.

`test_tenant_resolution.py` covers the first half: turning an address into a
tenant, so `/app-config` can tell the page which brand to paint. That is not
the same thing as restricting what the page can read, and until this existed
the second half was missing entirely — the customer web app sent a hardcoded
bundle id (`com.quickbite.bangkokbowl`) on every request, so all six tenant
domains served the same restaurant's name, menu and hero copy.

What matters here is the *refusal*. A storefront is free to ask for anything;
the server decides what it may see. These tests pin that the address is what
narrows the query, that the callers who send no address are unaffected, and
that a tenant's own origin is allowed through CORS without a redeploy —
because naming origins exactly stops being possible once onboarding a
restaurant issues it a subdomain.
"""

from __future__ import annotations

import re
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from app.main import app  # noqa: F401 - imported first to settle import order
from app.models.enums import AppClientStatus, AppMode
from app.services import app_clients


def a_tenant(key: str = "dragon_wok", restaurant_id: uuid.UUID | None = None):
    return SimpleNamespace(
        app_mode=AppMode.SINGLE_RESTAURANT,
        restaurant_id=restaurant_id or uuid.uuid4(),
        id=uuid.uuid4(),
        key=key,
        status=AppClientStatus.ACTIVE,
    )


class ScopingDataByTheAddressTests(unittest.TestCase):
    def scope_for(self, *, bundle_id=None, host=None, app_client=None):
        def fake_by_host(_db, *, host):  # noqa: ARG001
            return app_client

        def fake_by_bundle(_db, *, bundle_id, platform):  # noqa: ARG001
            return app_client

        with (
            patch.object(app_clients, "find_app_client_by_host", fake_by_host),
            patch.object(app_clients, "find_app_client_by_bundle_id", fake_by_bundle),
        ):
            return app_clients.resolve_app_scope(object(), bundle_id=bundle_id, host=host)

    def test_an_address_narrows_every_query_to_its_restaurant(self) -> None:
        tenant = a_tenant()
        scope = self.scope_for(host="dragon-wok.example.com", app_client=tenant)

        self.assertEqual(scope.restaurant_filter_id, tenant.restaurant_id)
        self.assertTrue(scope.allows_restaurant(tenant.restaurant_id))
        # The whole point: asking for another restaurant is refused, even
        # though the client is perfectly free to ask.
        self.assertFalse(scope.allows_restaurant(uuid.uuid4()))

    def test_the_address_is_normalised_before_it_is_matched(self) -> None:
        tenant = a_tenant()
        for raw in (
            "Dragon-Wok.Example.com",
            "dragon-wok.example.com:5173",
            "www.dragon-wok.example.com",
            "  dragon-wok.example.com  ",
        ):
            scope = self.scope_for(host=raw, app_client=tenant)
            self.assertEqual(scope.restaurant_filter_id, tenant.restaurant_id, raw)

    def test_an_address_nobody_claims_sees_the_marketplace_not_a_tenant(self) -> None:
        # The admin panel, curl, and any dev machine arrive this way. Falling
        # back to some arbitrary tenant would be far worse than falling back
        # to nothing.
        scope = self.scope_for(host="localhost:5174", app_client=None)
        self.assertIsNone(scope.restaurant_filter_id)
        self.assertTrue(scope.allows_restaurant(uuid.uuid4()))

    def test_no_address_and_no_bundle_id_is_exactly_what_it_was(self) -> None:
        self.assertIs(self.scope_for(), app_clients.UNSCOPED_APP_SCOPE)

    def test_a_bundle_id_beats_an_address(self) -> None:
        """A phone's identity was fixed at release; a host is whatever arrived.

        Both are present when a webview inside a branded app calls the API,
        and the stronger claim has to win — otherwise the page's address could
        widen what the app is allowed to see.
        """

        by_host = a_tenant("dragon_wok")
        by_bundle = a_tenant("bangkok_bowl")

        def fake_by_host(_db, *, host):  # noqa: ARG001
            return by_host

        def fake_by_bundle(_db, *, bundle_id, platform):  # noqa: ARG001
            return by_bundle

        with (
            patch.object(app_clients, "find_app_client_by_host", fake_by_host),
            patch.object(app_clients, "find_app_client_by_bundle_id", fake_by_bundle),
        ):
            scope = app_clients.resolve_app_scope(
                object(),
                bundle_id="com.quickbite.bangkokbowl",
                host="dragon-wok.example.com",
            )

        self.assertEqual(scope.restaurant_filter_id, by_bundle.restaurant_id)
        self.assertEqual(scope.app_key, "bangkok_bowl")

    def test_an_unknown_bundle_id_does_not_fall_through_to_the_address(self) -> None:
        """A misconfigured app is a misconfigured app, not a web request.

        Falling through would mean a build with a typo in its bundle id
        silently adopting whatever tenant its webview happened to be on.
        """

        def fake_by_bundle(_db, *, bundle_id, platform):  # noqa: ARG001
            return None

        def fake_by_host(_db, *, host):  # noqa: ARG001
            raise AssertionError("the host must not be consulted")

        with (
            patch.object(app_clients, "find_app_client_by_bundle_id", fake_by_bundle),
            patch.object(app_clients, "find_app_client_by_host", fake_by_host),
        ):
            scope = app_clients.resolve_app_scope(
                object(), bundle_id="com.example.typo", host="dragon-wok.example.com"
            )

        self.assertIs(scope, app_clients.UNSCOPED_APP_SCOPE)


class TenantOriginsAreAllowedTests(unittest.TestCase):
    """A tenant's storefront reaches the API without a redeploy."""

    def pattern(self, *, platform_domain: str = "example.com", configured: str = "") -> str:
        from app.config.settings import Settings

        return Settings(
            platform_domain=platform_domain,
            backend_cors_origin_regex=configured,
        ).cors_origin_regex

    def test_a_tenant_subdomain_is_allowed(self) -> None:
        pattern = self.pattern()
        for origin in (
            "https://dragon-wok.example.com",
            "http://bangkok-bowl.example.com",
            "http://dragon-wok.example.com:5173",
        ):
            self.assertIsNotNone(re.fullmatch(pattern, origin), origin)

    def test_somebody_elses_domain_is_not(self) -> None:
        pattern = self.pattern()
        for origin in (
            "https://example.com.evil.test",
            "https://evil.test",
            "https://dragon-wok.evil.com",
            # One label deep, matching what `platform_host_for` issues. A `.*`
            # here would have admitted anything ending in the platform domain.
            "https://a.b.example.com",
        ):
            self.assertIsNone(re.fullmatch(pattern, origin), origin)

    def test_a_dot_in_the_domain_is_not_a_wildcard(self) -> None:
        pattern = self.pattern(platform_domain="example.com")
        self.assertIsNone(re.fullmatch(pattern, "https://dragon-wok.exampleXcom"))

    def test_an_explicitly_configured_pattern_still_applies(self) -> None:
        # It exists for what this cannot know about: a LAN address during
        # device testing, or a tenant's own domain.
        pattern = self.pattern(configured=r"http://192\.168\.\d+\.\d+:5173")
        self.assertIsNotNone(re.fullmatch(pattern, "http://192.168.1.14:5173"))
        self.assertIsNotNone(re.fullmatch(pattern, "https://dragon-wok.example.com"))

    def test_no_platform_domain_leaves_the_configured_pattern_alone(self) -> None:
        self.assertEqual(self.pattern(platform_domain="", configured="abc"), "abc")


if __name__ == "__main__":
    unittest.main()

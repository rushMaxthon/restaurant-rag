"""Which restaurant a request belongs to, when one deployment serves many.

A mobile build says who it is with a bundle id the app store fixed at
release time. A web build cannot: one deployment serves every tenant, and
the only thing distinguishing one request from another is the address it
arrived on. So the host is the tenant's identifier.

Two things in here are load-bearing rather than merely tidy. The host is
normalised to exactly one form before it is ever compared, because browsers,
proxies and people all vary it freely and a miss would serve one
restaurant's customers another restaurant's storefront. And the host is read
from `X-Forwarded-Host`, which the proxy writes, never from `Host`, which is
whatever the client typed.
"""

from __future__ import annotations

import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.main import app  # noqa: F401 - imported first to settle import order
from app.models.enums import AppClientStatus, AppMode
from app.services import app_clients


class NormalisingAHostTests(unittest.TestCase):
    """One address, written six ways, is one address."""

    def test_the_forms_a_browser_or_a_person_might_send(self) -> None:
        for raw in (
            "bangkok-bowl.example.com",
            "Bangkok-Bowl.Example.com",
            "bangkok-bowl.example.com:443",
            "  bangkok-bowl.example.com  ",
            "bangkok-bowl.example.com.",
            "www.bangkok-bowl.example.com",
        ):
            self.assertEqual(
                app_clients.normalize_host(raw), "bangkok-bowl.example.com", raw
            )

    def test_nothing_is_nothing(self) -> None:
        for raw in (None, "", "   "):
            self.assertEqual(app_clients.normalize_host(raw), "")

    def test_an_ipv6_literal_keeps_its_brackets_and_loses_its_port(self) -> None:
        # It will never match a real domain either way. What matters is that
        # it does not match the WRONG one by having its address chopped at
        # the first colon.
        self.assertEqual(app_clients.normalize_host("[::1]:8000"), "[::1]")

    def test_a_subdomain_called_www_is_not_stripped_twice(self) -> None:
        self.assertEqual(
            app_clients.normalize_host("www.www.example.com"), "www.example.com"
        )


class TheAddressWeIssueTests(unittest.TestCase):
    """A newly onboarded restaurant gets an address that actually resolves."""

    def host_for(self, app_key: str, domain: str = "example.com") -> str:
        with patch.object(
            app_clients, "get_settings", lambda: SimpleNamespace(platform_domain=domain)
        ):
            return app_clients.platform_host_for(app_key)

    def test_an_app_key_becomes_a_dns_label(self) -> None:
        # App keys carry underscores and hostnames cannot. Hyphens rather
        # than removal, because "bangkok-bowl" is the address a restaurant
        # would expect to be handed and "bangkokbowl" is not.
        self.assertEqual(self.host_for("bangkok_bowl"), "bangkok-bowl.example.com")
        self.assertEqual(self.host_for("Bangkok Bowl"), "bangkok-bowl.example.com")

    def test_a_label_may_not_begin_with_a_digit(self) -> None:
        self.assertTrue(self.host_for("7-Eleven").startswith("app-7-eleven."))

    def test_the_result_is_always_already_normalised(self) -> None:
        issued = self.host_for("Bangkok Bowl", domain="Example.COM")
        self.assertEqual(issued, app_clients.normalize_host(issued))


class _Scalar:
    """A database that answers one query with one row."""

    def __init__(self, row=None):
        self.row = row
        self.statements = []

    def scalar(self, statement):
        self.statements.append(str(statement))
        return self.row


def _client(**over):
    fields = {
        "id": uuid.uuid4(),
        "key": "bangkok_bowl",
        "display_name": "Bangkok Bowl",
        "app_mode": AppMode.SINGLE_RESTAURANT,
        "status": AppClientStatus.ACTIVE,
        "restaurant_id": uuid.uuid4(),
    }
    fields.update(over)
    return SimpleNamespace(**fields)


class ResolvingATenantFromAHostTests(unittest.TestCase):
    """The lookup, and what it refuses."""

    def test_an_empty_host_finds_nothing_without_asking_the_database(self) -> None:
        db = _Scalar()
        self.assertIsNone(app_clients.find_app_client_by_host(db, host=""))
        self.assertEqual(db.statements, [])

    def test_the_query_demands_an_active_verified_domain(self) -> None:
        # Verification is what stops somebody pointing a name they do not own
        # at this platform and being served another brand's storefront.
        db = _Scalar(_client())
        app_clients.find_app_client_by_host(db, host="bangkok-bowl.example.com")
        sql = db.statements[0]
        self.assertIn("app_client_domains", sql)
        self.assertIn("is_active", sql)
        self.assertIn("is_verified", sql)

    def test_an_unclaimed_address_is_a_plain_refusal(self) -> None:
        # Not a silent fall back to the marketplace: a tenant whose domain row
        # was never created should see that, not serve somebody else's brand.
        with self.assertRaises(HTTPException) as raised:
            app_clients.resolve_app_client_by_host(_Scalar(), host="nobody.example.com")
        self.assertEqual(raised.exception.status_code, 404)
        self.assertIn("nobody.example.com", raised.exception.detail)

    def test_no_address_at_all_says_what_to_send(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            app_clients.resolve_app_client_by_host(_Scalar(), host="")
        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("X-Forwarded-Host", raised.exception.detail)

    def test_a_suspended_tenant_is_refused_the_same_way_on_both_paths(self) -> None:
        # A tenant suspended for not paying must not still be serving through
        # whichever lookup happens to be used.
        suspended = _client(status=AppClientStatus.SUSPENDED)
        with self.assertRaises(HTTPException) as by_host:
            app_clients.resolve_app_client_by_host(
                _Scalar(suspended), host="bangkok-bowl.example.com"
            )
        with self.assertRaises(HTTPException) as by_bundle:
            app_clients.resolve_app_client_by_bundle_id(
                _Scalar(suspended), bundle_id="com.quickbite.bangkokbowl"
            )
        self.assertEqual(by_host.exception.status_code, 403)
        self.assertEqual(by_bundle.exception.status_code, 403)
        self.assertEqual(by_host.exception.detail, by_bundle.exception.detail)

    def test_the_host_is_normalised_before_it_is_looked_up(self) -> None:
        found = _client()
        db = _Scalar(found)
        self.assertIs(
            app_clients.find_app_client_by_host(
                db, host="WWW.Bangkok-Bowl.Example.com:443."
            ),
            found,
        )


class TheConfigEndpointTests(unittest.TestCase):
    """`/app-config` answers a bundle id or an address, and says which."""

    def call(self, **kwargs):
        from app.api import app_config

        resolved = {}

        def by_bundle(db, *, bundle_id, platform=None):
            resolved["bundle_id"] = bundle_id
            return _client()

        def by_host(db, *, host):
            resolved["host"] = host
            return _client()

        with patch.object(app_config, "resolve_app_client_by_bundle_id", by_bundle), \
                patch.object(app_config, "resolve_app_client_by_host", by_host), \
                patch.object(
                    app_config,
                    "build_app_config_response",
                    lambda client, **kw: SimpleNamespace(**kw),
                ):
            defaults = {
                "db": None,
                "x_app_bundle_id": None,
                "x_app_platform": None,
                "x_forwarded_host": None,
                "bundle_id": None,
                "platform": None,
                "host": None,
            }
            defaults.update(kwargs)
            return app_config.get_app_config(**defaults), resolved

    def test_a_bundle_id_still_wins(self) -> None:
        # The mobile apps must be untouched by any of this.
        _, resolved = self.call(
            x_app_bundle_id="com.quickbite.bangkokbowl",
            x_forwarded_host="bangkok-bowl.example.com",
        )
        self.assertEqual(resolved.get("bundle_id"), "com.quickbite.bangkokbowl")
        self.assertNotIn("host", resolved)

    def test_a_storefront_resolves_from_the_forwarded_host(self) -> None:
        _, resolved = self.call(x_forwarded_host="bangkok-bowl.example.com")
        self.assertEqual(resolved.get("host"), "bangkok-bowl.example.com")

    def test_a_proxy_chain_names_the_address_the_browser_asked_for_first(self) -> None:
        _, resolved = self.call(
            x_forwarded_host="bangkok-bowl.example.com, internal-lb.example.net"
        )
        self.assertEqual(resolved.get("host"), "bangkok-bowl.example.com")

    def test_the_query_parameter_is_for_testing_and_the_header_beats_it(self) -> None:
        _, resolved = self.call(
            x_forwarded_host="real.example.com", host="claimed.example.com"
        )
        self.assertEqual(resolved.get("host"), "real.example.com")

    def test_neither_one_says_what_to_send(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self.call()
        self.assertEqual(raised.exception.status_code, 400)
        self.assertIn("X-App-Bundle-Id", raised.exception.detail)
        self.assertIn("X-Forwarded-Host", raised.exception.detail)


class HoldingSomebodyElsesCredentialsTests(unittest.TestCase):
    """A tenant's WhatsApp token is theirs, and is not stored in the clear."""

    def cipher(self):
        from cryptography.fernet import Fernet

        from app.services import secrets

        secrets._cipher.cache_clear()
        return patch.object(
            secrets,
            "get_settings",
            lambda: SimpleNamespace(secrets_encryption_key=Fernet.generate_key().decode()),
        )

    def tearDown(self) -> None:
        from app.services import secrets

        secrets._cipher.cache_clear()

    def test_a_credential_survives_the_round_trip(self) -> None:
        from app.services import secrets

        with self.cipher():
            stored = secrets.encrypt_secret("EAAG-a-whatsapp-token")
            self.assertNotIn("whatsapp", stored)
            self.assertEqual(secrets.decrypt_secret(stored), "EAAG-a-whatsapp-token")

    def test_nothing_encrypts_to_nothing(self) -> None:
        # A channel with no app secret of its own is a normal thing; hiding
        # the fact that there is nothing there helps nobody.
        from app.services import secrets

        with self.cipher():
            self.assertEqual(secrets.encrypt_secret(""), "")
            self.assertEqual(secrets.decrypt_secret(""), "")

    def test_a_value_that_will_not_authenticate_raises_rather_than_passing_through(self) -> None:
        # The alternative is sending Meta a bearer token that is really a
        # base64 blob, and reading the 401 as the tenant's number being wrong.
        from app.services import secrets

        with self.cipher():
            with self.assertRaises(secrets.SecretsUnavailable):
                secrets.decrypt_secret("not-a-real-token")

    def test_without_a_key_it_refuses_rather_than_storing_plaintext(self) -> None:
        from app.services import secrets

        secrets._cipher.cache_clear()
        with patch.object(
            secrets, "get_settings", lambda: SimpleNamespace(secrets_encryption_key="")
        ):
            self.assertFalse(secrets.secrets_available())
            with self.assertRaises(secrets.SecretsUnavailable):
                secrets.encrypt_secret("EAAG-a-whatsapp-token")


class WhatAStorefrontLooksLikeTests(unittest.TestCase):
    """Branding an operator sets up once, refused on the way in when unusable.

    The person filling this form is onboarding somebody else's business and
    will never see the result, so anything that would render badly has to be
    caught here rather than discovered by that restaurant's customers.
    """

    def client(self, branding=None, display_name="Bangkok Bowl"):
        return SimpleNamespace(branding=branding or {}, display_name=display_name)

    def test_a_blank_record_still_describes_a_working_storefront(self) -> None:
        from app.services import app_branding

        read = app_branding.read_branding(self.client())
        self.assertEqual(read["primary_color"], "#FF5200")
        self.assertEqual(read["font_family"], "manrope")
        self.assertIn("Manrope", read["font_stack"])
        # The name falls back to the client's own, so a tab is never blank.
        self.assertEqual(read["app_name"], "Bangkok Bowl")

    def test_every_key_a_storefront_reads_is_always_present(self) -> None:
        from app.services import app_branding

        read = app_branding.read_branding(self.client())
        for key in (
            "primary_color", "accent_color", "logo_url", "logo_dark_url",
            "favicon_url", "cover_image_url", "font_family", "font_stack",
            "app_name", "tagline",
        ):
            self.assertIn(key, read)

    def test_a_stored_colour_is_normalised_not_trusted(self) -> None:
        from app.services import app_branding

        read = app_branding.read_branding(self.client({"primary_color": "#0f6a51"}))
        self.assertEqual(read["primary_color"], "#0F6A51")

    def test_rubbish_in_the_record_falls_back_rather_than_rendering(self) -> None:
        from app.services import app_branding

        read = app_branding.read_branding(
            self.client({"primary_color": "chartreuse", "font_family": "comic-sans"})
        )
        self.assertEqual(read["primary_color"], "#FF5200")
        self.assertEqual(read["font_family"], "manrope")

    def test_a_script_url_is_refused(self) -> None:
        # These end up in src and href attributes on a page served under the
        # tenant's own domain.
        from app.services import app_branding

        for bad in ("javascript:alert(1)", "data:text/html;base64,PHN2Zz4=", "/relative.png"):
            with self.assertRaises(app_branding.BrandingValidationError, msg=bad):
                app_branding.resolve_branding({"logo_url": bad})

    def test_an_unknown_font_is_refused_rather_than_written_into_css(self) -> None:
        from app.services import app_branding

        with self.assertRaises(app_branding.BrandingValidationError):
            app_branding.resolve_branding({"font_family": chr(34) + "; background: url(evil)"})

    def test_editing_one_field_leaves_the_rest_alone(self) -> None:
        # A form that edits the logo must not silently clear a tagline it
        # never showed.
        from app.services import app_branding

        existing = {"logo_url": "https://a.test/old.png", "tagline": "Real Thai, fast"}
        updated = app_branding.resolve_branding(
            {"logo_url": "https://a.test/new.png"}, existing=existing
        )
        self.assertEqual(updated["logo_url"], "https://a.test/new.png")
        self.assertEqual(updated["tagline"], "Real Thai, fast")

    def test_clearing_a_field_removes_it(self) -> None:
        from app.services import app_branding

        updated = app_branding.resolve_branding(
            {"tagline": ""}, existing={"tagline": "Real Thai, fast"}
        )
        self.assertNotIn("tagline", updated)

    def test_a_name_cannot_smuggle_a_paragraph_into_a_browser_tab(self) -> None:
        from app.services import app_branding

        with self.assertRaises(app_branding.BrandingValidationError):
            app_branding.resolve_branding({"app_name": "x" * 200})

    def test_control_characters_do_not_survive(self) -> None:
        from app.services import app_branding

        updated = app_branding.resolve_branding(
            {"app_name": "Bangkok" + chr(0) + " Bowl" + chr(10)}
        )
        self.assertEqual(updated["app_name"], "Bangkok Bowl")

    def test_the_owners_own_theme_still_wins_on_the_colour(self) -> None:
        # The precedence `build_app_config_response` already documents: the
        # restaurant is what the owner controls, this record is what an
        # administrator set up.
        from app.services import app_clients

        restaurant = SimpleNamespace(theme={"primary_color": "#0F766E", "preset": "teal"})
        client = SimpleNamespace(
            id=uuid.uuid4(), key="bangkok_bowl", display_name="Bangkok Bowl",
            app_mode=AppMode.SINGLE_RESTAURANT, restaurant_id=uuid.uuid4(),
            status=AppClientStatus.ACTIVE, restaurant=restaurant,
            branding={"primary_color": "#FF5200", "logo_url": "https://a.test/l.png"},
            order_number_prefix="BB", minimum_supported_version="1.0.0",
        )
        built = app_clients.build_app_config_response(client, host="bangkok-bowl.example.com")
        self.assertEqual(built.branding["primary_color"], "#0F766E")
        # And everything the owner does not control survives the override.
        self.assertEqual(built.branding["logo_url"], "https://a.test/l.png")


class OnboardingIssuesAnAddressTests(unittest.TestCase):
    """A restaurant onboarded today has a storefront today.

    `create_app_client` hands a new tenant its iOS bundle id, its Android
    package name and its order sequence. Until host resolution shipped there
    was no web address to hand it, because the one storefront knew which
    restaurant it was from a constant in its own source. The backfill
    migration covered the six restaurants that already existed; nothing
    covered the seventh, so every tenant onboarded afterwards would have had
    a working mobile identity and a storefront that 404s.
    """

    def built(self, app_key="tandoori_nights", domain="example.com"):
        from app.models.enums import AppMode
        from app.services import app_clients

        identity = app_clients.AppClientIdentity(
            app_key=app_key,
            app_mode=AppMode.SINGLE_RESTAURANT,
            ios_bundle_id=f"com.quickbite.{app_key.replace('_', '')}",
            android_package_name=f"com.quickbite.{app_key.replace('_', '')}",
            order_number_prefix="TN",
            brand_primary_color="#FF5200",
            minimum_supported_version="1.0.0",
        )
        with patch.object(
            app_clients, "get_settings", lambda: SimpleNamespace(platform_domain=domain)
        ):
            return app_clients.create_app_client(
                restaurant_id=uuid.uuid4(),
                display_name="Tandoori Nights",
                identity=identity,
            )

    def test_a_new_tenant_is_issued_its_storefront_address(self) -> None:
        client = self.built()
        self.assertEqual([d.host for d in client.domains], ["tandoori-nights.example.com"])

    def test_the_address_needs_no_proving_because_we_issued_it(self) -> None:
        # A domain the restaurant already owns is the case that needs
        # verifying. A subdomain we handed out is not.
        domain = self.built().domains[0]
        self.assertTrue(domain.is_verified)
        self.assertTrue(domain.is_primary)

    def test_it_still_gets_its_mobile_identity(self) -> None:
        client = self.built()
        self.assertEqual(len(client.identifiers), 2)
        self.assertIsNotNone(client.order_sequence)

    def test_a_clashing_address_is_a_conflict_the_form_can_show(self) -> None:
        # Rather than an integrity error from the unique constraint, raised
        # halfway through creating a restaurant.
        from fastapi import HTTPException

        from app.services import app_clients

        # Answers only the domain query, so the app key and bundle id read as
        # free and the host is the one thing clashing.
        class OnlyTheHostIsTaken:
            def scalar(self, statement):
                return uuid.uuid4() if "app_client_domains" in str(statement) else None

        db = OnlyTheHostIsTaken()
        with patch.object(
            app_clients, "get_settings", lambda: SimpleNamespace(platform_domain="example.com")
        ):
            with self.assertRaises(HTTPException) as raised:
                app_clients.validate_app_client_identity_is_available(
                    db,
                    app_key="tandoori_nights",
                    ios_bundle_id="com.quickbite.brandnew",
                    android_package_name="com.quickbite.brandnew",
                )
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("tandoori-nights.example.com", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()

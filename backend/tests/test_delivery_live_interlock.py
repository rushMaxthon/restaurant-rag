"""A laptop must not send a human to a real address.

A development machine dispatches through exactly the same task, the same
provider and the same credentials as production. So the day a live courier
password is pasted into a local `.env` — to try a quote, to check an account,
to see whether the login works — every order the kitchen accepts books a real
rider who turns up at a real door and has to be paid.

`enable_delivery_dispatch` is the wrong thing to be relying on there. It is a
rollout dial: switched on early, left on, and nobody rereads it before pasting
a credential. So the interlock is separate from it and cannot be satisfied by
it.

What it does NOT block is quoting. A quote costs nothing and books nobody,
which is the entire reason those are two flags, and blocking it would make the
interlock something people turn off.
"""

from __future__ import annotations

import os
import sys
import unittest
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config.settings import get_settings  # noqa: E402
from app.models.enums import OrderFulfillmentType, OrderStatus  # noqa: E402
from app.services.delivery.service import (  # noqa: E402
    _is_sandbox_host,
    live_dispatch_blocked_reason,
    should_dispatch,
)


class FakeOrder:
    """Enough of an order for `should_dispatch`, with no database."""

    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.fulfillment_type = OrderFulfillmentType.DELIVERY
        self.status = OrderStatus.ACCEPTED


class Env:
    """Set environment variables and put them back, clearing the cache."""

    def __init__(self, **values: str) -> None:
        self._values = values
        self._previous: dict[str, str | None] = {}

    def __enter__(self) -> None:
        for key, value in self._values.items():
            self._previous[key] = os.environ.get(key)
            os.environ[key] = value
        get_settings.cache_clear()

    def __exit__(self, *_: object) -> None:
        for key, previous in self._previous.items():
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
        get_settings.cache_clear()


class WhichHostsCountAsSandbox(unittest.TestCase):
    def test_pidges_sandbox_is_recognised(self) -> None:
        self.assertTrue(_is_sandbox_host("https://store.dev.pidge.in"))

    def test_pidges_live_host_is_not(self) -> None:
        self.assertFalse(_is_sandbox_host("https://store.pidge.in"))

    def test_a_path_or_port_does_not_defeat_it(self) -> None:
        # Matched on the hostname, so neither of these reads as a sandbox.
        self.assertFalse(_is_sandbox_host("https://store.pidge.in/dev/"))
        self.assertFalse(_is_sandbox_host("https://store.pidge.in:443"))

    def test_other_couriers_name_their_sandboxes_differently(self) -> None:
        for host in (
            "https://sandbox.courier.example",
            "https://api.staging.courier.example",
            "http://localhost:9000",
            "http://127.0.0.1:9000",
        ):
            with self.subTest(host=host):
                self.assertTrue(_is_sandbox_host(host))


class ALaptopCannotBookARealRider(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_a_live_host_from_development_is_refused(self) -> None:
        with Env(
            ENVIRONMENT="development",
            PIDGE_BASE_URL="https://store.pidge.in",
            ENABLE_DELIVERY_DISPATCH="true",
            ALLOW_LIVE_DISPATCH_FROM_LOCAL="false",
        ):
            self.assertTrue(live_dispatch_blocked_reason())
            # And the flag being on does not get past it. That is the point.
            self.assertFalse(should_dispatch(FakeOrder()))

    def test_the_sandbox_from_development_is_allowed(self) -> None:
        with Env(
            ENVIRONMENT="development",
            PIDGE_BASE_URL="https://store.dev.pidge.in",
            ENABLE_DELIVERY_DISPATCH="true",
            ALLOW_LIVE_DISPATCH_FROM_LOCAL="false",
        ):
            self.assertEqual(live_dispatch_blocked_reason(), "")
            self.assertTrue(should_dispatch(FakeOrder()))

    def test_production_against_a_live_host_is_untouched(self) -> None:
        # The interlock is about laptops. A real deployment is supposed to
        # book real riders, and breaking that would be a far worse bug.
        with Env(
            ENVIRONMENT="production",
            PIDGE_BASE_URL="https://store.pidge.in",
            ENABLE_DELIVERY_DISPATCH="true",
            ALLOW_LIVE_DISPATCH_FROM_LOCAL="false",
        ):
            self.assertEqual(live_dispatch_blocked_reason(), "")
            self.assertTrue(should_dispatch(FakeOrder()))

    def test_the_override_exists_and_works(self) -> None:
        # Without a way out, somebody who genuinely needs one real delivery
        # from their desk deletes the check instead, which is worse.
        with Env(
            ENVIRONMENT="development",
            PIDGE_BASE_URL="https://store.pidge.in",
            ENABLE_DELIVERY_DISPATCH="true",
            ALLOW_LIVE_DISPATCH_FROM_LOCAL="true",
        ):
            self.assertEqual(live_dispatch_blocked_reason(), "")
            self.assertTrue(should_dispatch(FakeOrder()))

    def test_the_override_defaults_off(self) -> None:
        from app.config.settings import Settings

        self.assertFalse(Settings.model_fields["allow_live_dispatch_from_local"].default)

    def test_the_reason_names_both_halves(self) -> None:
        # It is logged and read by somebody wondering why nothing dispatched.
        # "Blocked" on its own sends them to the wrong flag.
        with Env(
            ENVIRONMENT="development",
            PIDGE_BASE_URL="https://store.pidge.in",
            ENABLE_DELIVERY_DISPATCH="true",
            ALLOW_LIVE_DISPATCH_FROM_LOCAL="false",
        ):
            reason = live_dispatch_blocked_reason()
            self.assertIn("development", reason)
            self.assertIn("store.pidge.in", reason)


class QuotingIsNotBlocked(unittest.TestCase):
    """The distinction the whole design rests on."""

    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_a_quote_against_a_live_host_from_a_laptop_is_fine(self) -> None:
        # A quote spends nothing and sends nobody. If this were blocked too,
        # the interlock would be in the way of ordinary work and would be
        # switched off — and then it would not be there on the day it matters.
        from app.services.delivery.registry import (
            delivery_provider,
            reset_delivery_provider,
        )

        with Env(
            ENVIRONMENT="development",
            PIDGE_BASE_URL="https://store.pidge.in",
            PIDGE_USERNAME="someone",
            PIDGE_PASSWORD="something",
            ENABLE_DELIVERY_DISPATCH="false",
            ENABLE_DELIVERY_QUOTES="true",
            ENABLE_DELIVERY_REHEARSAL="false",
        ):
            reset_delivery_provider()
            try:
                # A courier object is built — quoting is available — even
                # though nothing may be dispatched.
                self.assertIsNotNone(delivery_provider())
                self.assertFalse(should_dispatch(FakeOrder()))
            finally:
                reset_delivery_provider()


if __name__ == "__main__":
    unittest.main()

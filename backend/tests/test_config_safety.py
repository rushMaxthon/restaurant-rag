"""A deployment that forgets a setting must be safe, not open.

Found in the 2026-10-07 security review. Every dangerous switch here was
guarded by `environment`, and `environment` defaulted to "development": so a
deployment that simply did not set it accepted the fixed phone code 123456
for ANY customer (and returned it in the response), returned tracebacks to
clients, and published the API map at /docs. A missing `JWT_SECRET_KEY` fell
back to a string in this repository, with which anyone could sign an admin
token. Render sets all of these correctly; nothing refused when they were not.

So the defaults are now the safe ones, and a real deployment that is still
unsafe refuses to start, saying what to set.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.config import safety  # noqa: E402
from app.config.settings import Settings  # noqa: E402

STRONG = "k" * 48


def _settings(**over) -> Settings:
    # `_env_file=None`: what the code defaults to, not what this machine's
    # .env happens to say.
    with mock.patch.dict(os.environ, {}, clear=True):
        return Settings(_env_file=None, **over)


class TheDefaultsAreSafe(unittest.TestCase):
    def test_no_environment_means_production(self) -> None:
        self.assertEqual(_settings().environment, "production")

    def test_debug_is_off_unless_asked_for(self) -> None:
        self.assertFalse(_settings().debug)

    def test_the_fixed_phone_code_is_off_by_default(self) -> None:
        from app.services import otp

        with mock.patch.object(otp, "get_settings", return_value=_settings(jwt_secret_key=STRONG)):
            availability = otp.otp_availability()
        self.assertFalse(availability.debug)


class AnUnsafeDeploymentRefusesToStart(unittest.TestCase):
    def test_the_repositorys_jwt_secret(self) -> None:
        with self.assertRaises(safety.UnsafeConfiguration) as raised:
            safety.check(_settings())
        self.assertIn("JWT_SECRET_KEY", str(raised.exception))

    # Only the repository's own secret stops the server: it is a real hole
    # (anyone can sign an admin login). A short secret or DEBUG left on are
    # logged loudly but do not take a live API down on deploy, because this
    # check ships to a Render service whose settings nobody could see first.
    def test_a_short_jwt_secret_is_logged_not_fatal(self) -> None:
        with self.assertLogs(safety.logger, level="ERROR") as logs:
            safety.check(_settings(jwt_secret_key="short-secret"))
        self.assertIn("JWT_SECRET_KEY", " ".join(logs.output))

    def test_debug_in_production_is_logged_and_switched_off(self) -> None:
        settings = _settings(jwt_secret_key=STRONG, debug=True)
        with self.assertLogs(safety.logger, level="ERROR") as logs:
            safety.check(settings)
        self.assertIn("DEBUG", " ".join(logs.output))
        self.assertFalse(safety.effective_debug(settings))

    def test_debug_stays_on_locally_when_asked(self) -> None:
        self.assertTrue(safety.effective_debug(_settings(environment="development", debug=True)))

    def test_a_safe_production_starts(self) -> None:
        safety.check(_settings(jwt_secret_key=STRONG))

    def test_local_development_is_left_alone(self) -> None:
        safety.check(_settings(environment="development", debug=True))
        safety.check(_settings(environment="test"))


class TheApiMapIsLocalOnly(unittest.TestCase):
    def test_docs_are_hidden_in_production(self) -> None:
        self.assertEqual(safety.docs_urls(_settings(jwt_secret_key=STRONG)), (None, None, None))

    def test_docs_are_served_locally(self) -> None:
        self.assertEqual(
            safety.docs_urls(_settings(environment="development")),
            ("/docs", "/redoc", "/openapi.json"),
        )


if __name__ == "__main__":
    unittest.main()

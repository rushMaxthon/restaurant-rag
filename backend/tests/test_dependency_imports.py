"""Guards the import order that used to crash the Celery worker.

`app/services/auth.py` reached `get_app_scope` through `app.api.deps`. Because
`app/api/__init__.py` imports every router, and those routers import
`app.services.auth`, any process importing `app.services` before `app.api` hit a
half-initialised module and died. That is exactly what a Celery worker does, so
no background task could start.

These tests run each import in a fresh interpreter, because once a module is in
`sys.modules` the cycle no longer reproduces and the test would pass for the
wrong reason.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def run_in_fresh_interpreter(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )


class ImportOrderTests(unittest.TestCase):
    def assert_imports_cleanly(self, code: str, label: str) -> None:
        result = run_in_fresh_interpreter(code)
        self.assertEqual(
            result.returncode,
            0,
            f"{label} failed to import:\n{result.stderr[-1500:]}",
        )

    def test_services_package_imports_before_the_api(self) -> None:
        self.assert_imports_cleanly("import app.services", "app.services")

    def test_auth_service_imports_on_its_own(self) -> None:
        self.assert_imports_cleanly("import app.services.auth", "app.services.auth")

    def test_every_task_module_imports_on_its_own(self) -> None:
        # The worker imports these directly; each one must stand alone.
        for module in (
            "app.tasks.ai_offers",
            "app.tasks.ai_recommendations",
            "app.tasks.embed",
            "app.tasks.generated_combos",
            "app.tasks.insights",
            "app.tasks.notifications",
            "app.tasks.payments",
        ):
            with self.subTest(module=module):
                self.assert_imports_cleanly(f"import {module}", module)

    def test_celery_loads_every_task_module_the_way_a_worker_does(self) -> None:
        # Asserted by name rather than count: a missing task should say which
        # one, and a new one should fail loudly enough to be added here.
        expected = {
            "app.tasks.ai_offers.generate_ai_offers_task",
            "app.tasks.ai_recommendations.generate_ai_recommendations_task",
            "app.tasks.embed.backfill_menu_embeddings",
            "app.tasks.embed.embed_menu_item",
            "app.tasks.generated_combos.rebuild_generated_combos_task",
            "app.tasks.insights.generate_owner_briefings_task",
            "app.tasks.insights.measure_action_outcomes_task",
            "app.tasks.insights.run_shadow_analysis_task",
            "app.tasks.notifications.send_order_status_notification",
            "app.tasks.payments.reap_unpaid_orders_task",
        }
        result = run_in_fresh_interpreter(
            "from app.config.celery import celery_app\n"
            "celery_app.loader.import_default_modules()\n"
            "names = sorted(t for t in celery_app.tasks if t.startswith('app.tasks'))\n"
            "print('\\n'.join(names))\n"
        )
        self.assertEqual(result.returncode, 0, result.stderr[-1500:])
        self.assertEqual(set(result.stdout.split()), expected)

    def test_api_still_imports_first_as_well(self) -> None:
        # The web process imports in the opposite order; both must work.
        self.assert_imports_cleanly("import app.main", "app.main")


class DependencyShimTests(unittest.TestCase):
    """`app.api.deps` must keep working for the modules that still import it."""

    def test_shim_re_exports_everything_the_api_uses(self) -> None:
        from app.api import deps

        for name in (
            "APP_BUNDLE_ID_HEADER",
            "APP_PLATFORM_HEADER",
            "AppScope",
            "AppScopeDep",
            "IdentityAppClientDep",
            "ensure_restaurant_readable",
            "ensure_restaurant_writable",
            "get_app_scope",
            "get_identity_app_client_id",
        ):
            with self.subTest(name=name):
                self.assertTrue(hasattr(deps, name))

    def test_shim_exposes_the_same_objects_not_copies(self) -> None:
        # A copy would mean FastAPI's dependency overrides in tests stopped
        # matching the real dependency.
        from app.api import deps
        from app import dependencies

        self.assertIs(deps.get_app_scope, dependencies.get_app_scope)
        self.assertIs(deps.ensure_restaurant_readable, dependencies.ensure_restaurant_readable)
        self.assertIs(deps.ensure_restaurant_writable, dependencies.ensure_restaurant_writable)

    def test_auth_uses_the_relocated_dependency(self) -> None:
        from app.services import auth
        from app import dependencies

        self.assertIs(auth.get_app_scope, dependencies.get_app_scope)


if __name__ == "__main__":
    unittest.main()

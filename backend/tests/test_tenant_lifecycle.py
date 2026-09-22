"""Taking a tenant off the air, and the guards around doing it.

`app_clients.status` has existed since `0032` and until now nothing wrote it
after creation. Adding the endpoint that does made it possible to stop a
paying restaurant's storefront from a browser, so the rules about *when* that
is allowed are the product, not paperwork:

- ADMIN only. An owner reaching this would be reading, and potentially
  changing, every other restaurant's state.
- Off the air requires a note. A storefront that stops answering generates a
  support call within the hour, and the answer should be in the row.
- OFFBOARDED is terminal here. It means the restaurant has left; bringing one
  back should be a deliberate act by somebody who looked at what they still
  have on the platform, not a toggle clicked twice.

The endpoint is tested against its own logic rather than over HTTP, because
what is worth pinning is the decision each guard makes, and the route
signature already enforces the role through `require_admin`.
"""

from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import HTTPException

from app.main import app  # noqa: F401 - imported first to settle import order
from app.api import app_clients as tenants_api
from app.models.enums import AppClientDomainKind, AppClientStatus, AppMode
from app.schemas.app_clients import TenantStatusUpdate


class FakeSession:
    """Just enough Session for the lifecycle endpoint.

    `get` hands back the one tenant under test; `execute` answers the count
    queries with nothing, which is the honest shape for a tenant that has no
    orders rather than a stand-in that would hide a join mistake.
    """

    def __init__(self, tenant: object | None) -> None:
        self.tenant = tenant
        self.committed = False

    def get(self, _model: object, _pk: object) -> object | None:
        return self.tenant

    def execute(self, _statement: object) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: [])

    def scalars(self, _statement: object) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: [])

    def add(self, _instance: object) -> None:
        return None

    def commit(self) -> None:
        self.committed = True

    def refresh(self, _instance: object) -> None:
        return None


def make_tenant(
    *,
    status: AppClientStatus = AppClientStatus.ACTIVE,
    note: str | None = None,
) -> SimpleNamespace:
    now = datetime(2026, 9, 18, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        key="dragon_wok",
        display_name="Dragon Wok",
        app_mode=AppMode.SINGLE_RESTAURANT,
        status=status,
        status_note=note,
        status_changed_at=None,
        status_changed_by_user_id=None,
        restaurant_id=uuid.uuid4(),
        restaurant=SimpleNamespace(
            name="Dragon Wok",
            slug="dragon-wok",
            cuisine_type="Chinese",
            city="Ahmedabad",
            is_approved=True,
            # The console labels each tenant's money with its own symbol, so
            # the summary reads this now.
            currency="CAD",
        ),
        domains=[
            SimpleNamespace(
                host="dragon-wok.localhost",
                kind=AppClientDomainKind.PLATFORM_SUBDOMAIN,
                is_active=True,
            ),
        ],
        brand_primary_color="#FF5200",
        created_at=now,
        updated_at=now,
    )


def make_admin() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        full_name="Admin User",
        email="admin@example.com",
    )


class TakingATenantOffTheAirTests(unittest.TestCase):
    def test_a_suspension_without_a_reason_is_refused(self) -> None:
        tenant = make_tenant()
        db = FakeSession(tenant)

        with self.assertRaises(HTTPException) as caught:
            tenants_api.update_tenant_status(
                tenant.id,
                TenantStatusUpdate(status=AppClientStatus.SUSPENDED),
                db,
                make_admin(),
            )

        self.assertEqual(caught.exception.status_code, 422)
        # And crucially, nothing was written on the way to refusing.
        self.assertEqual(tenant.status, AppClientStatus.ACTIVE)
        self.assertFalse(db.committed)

    def test_whitespace_is_not_a_reason(self) -> None:
        tenant = make_tenant()
        db = FakeSession(tenant)

        with self.assertRaises(HTTPException) as caught:
            tenants_api.update_tenant_status(
                tenant.id,
                TenantStatusUpdate(status=AppClientStatus.SUSPENDED, note="   "),
                db,
                make_admin(),
            )

        self.assertEqual(caught.exception.status_code, 422)

    def test_a_suspension_with_a_reason_records_who_and_when(self) -> None:
        tenant = make_tenant()
        admin = make_admin()
        db = FakeSession(tenant)

        response = tenants_api.update_tenant_status(
            tenant.id,
            TenantStatusUpdate(status=AppClientStatus.SUSPENDED, note="Unpaid invoice"),
            db,
            admin,
        )

        self.assertEqual(tenant.status, AppClientStatus.SUSPENDED)
        self.assertEqual(tenant.status_note, "Unpaid invoice")
        self.assertEqual(tenant.status_changed_by_user_id, admin.id)
        self.assertIsNotNone(tenant.status_changed_at)
        self.assertTrue(db.committed)
        self.assertEqual(response.status, AppClientStatus.SUSPENDED)
        self.assertEqual(response.status_changed_by, "Admin User")

    def test_restoring_needs_no_reason_because_it_explains_itself(self) -> None:
        tenant = make_tenant(status=AppClientStatus.SUSPENDED, note="Unpaid invoice")
        db = FakeSession(tenant)

        response = tenants_api.update_tenant_status(
            tenant.id,
            TenantStatusUpdate(status=AppClientStatus.ACTIVE),
            db,
            make_admin(),
        )

        self.assertEqual(tenant.status, AppClientStatus.ACTIVE)
        # The old reason goes with the old state. Leaving it would have the
        # console showing a working tenant beside "Unpaid invoice".
        self.assertIsNone(tenant.status_note)
        self.assertEqual(response.status, AppClientStatus.ACTIVE)

    def test_offboarded_is_terminal(self) -> None:
        tenant = make_tenant(status=AppClientStatus.OFFBOARDED, note="Left the platform")
        db = FakeSession(tenant)

        with self.assertRaises(HTTPException) as caught:
            tenants_api.update_tenant_status(
                tenant.id,
                TenantStatusUpdate(status=AppClientStatus.ACTIVE),
                db,
                make_admin(),
            )

        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(tenant.status, AppClientStatus.OFFBOARDED)
        self.assertFalse(db.committed)

    def test_setting_the_status_it_already_has_writes_nothing(self) -> None:
        tenant = make_tenant()
        db = FakeSession(tenant)

        response = tenants_api.update_tenant_status(
            tenant.id,
            TenantStatusUpdate(status=AppClientStatus.ACTIVE),
            db,
            make_admin(),
        )

        self.assertFalse(db.committed)
        self.assertIsNone(tenant.status_changed_at)
        self.assertEqual(response.status, AppClientStatus.ACTIVE)

    def test_an_unknown_tenant_is_a_404(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            tenants_api.update_tenant_status(
                uuid.uuid4(),
                TenantStatusUpdate(status=AppClientStatus.ACTIVE),
                FakeSession(None),
                make_admin(),
            )

        self.assertEqual(caught.exception.status_code, 404)


class SummarisingATenantTests(unittest.TestCase):
    """The row the console draws, including the parts that are easy to get wrong."""

    def test_the_platform_address_is_the_one_shown(self) -> None:
        tenant = make_tenant()
        tenant.domains.insert(
            0,
            SimpleNamespace(
                host="order.dragonwok.com",
                kind=AppClientDomainKind.CUSTOM,
                is_active=True,
            ),
        )

        summary = tenants_api._summarize(tenant, counts={}, changed_by=None)

        # The tenant's own domain is counted but not shown: the subdomain we
        # issued is the address that always works and the one support asks
        # somebody to try.
        self.assertEqual(summary.primary_host, "dragon-wok.localhost")
        self.assertEqual(summary.custom_host_count, 1)

    def test_an_inactive_domain_is_neither_shown_nor_counted(self) -> None:
        tenant = make_tenant()
        tenant.domains = [
            SimpleNamespace(
                host="dragon-wok.localhost",
                kind=AppClientDomainKind.PLATFORM_SUBDOMAIN,
                is_active=False,
            ),
            SimpleNamespace(
                host="order.dragonwok.com",
                kind=AppClientDomainKind.CUSTOM,
                is_active=False,
            ),
        ]

        summary = tenants_api._summarize(tenant, counts={}, changed_by=None)

        self.assertIsNone(summary.primary_host)
        self.assertEqual(summary.custom_host_count, 0)

    def test_a_tenant_with_no_restaurant_summarises_cleanly(self) -> None:
        """The marketplace client is a tenant without being a restaurant."""

        tenant = make_tenant()
        tenant.restaurant = None
        tenant.restaurant_id = None
        tenant.app_mode = AppMode.MARKETPLACE

        summary = tenants_api._summarize(tenant, counts={}, changed_by=None)

        self.assertIsNone(summary.restaurant_name)
        self.assertIsNone(summary.is_approved)
        self.assertEqual(summary.location_count, 0)

    def test_missing_counts_read_as_zero_not_as_absent(self) -> None:
        summary = tenants_api._summarize(
            make_tenant(), counts={"order_count": 12}, changed_by=None
        )

        self.assertEqual(summary.order_count, 12)
        self.assertEqual(summary.menu_item_count, 0)
        self.assertEqual(summary.customer_count, 0)


if __name__ == "__main__":
    unittest.main()

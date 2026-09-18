"""Who may see a restaurant owner's name and email.

`GET /restaurants/{id}` serves customers and anonymous visitors as well as
staff, and it used to return the owner block to all of them. That block holds
a real person's email address, so anyone who could reach the endpoint could
collect the email of every owner on the platform by walking restaurant ids.

The fix is a flag on the serialiser rather than a second schema, so there is
exactly one place that decides, and it is named.
"""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import Mock, patch
from datetime import datetime, timezone

from app.main import app  # noqa: F401 - imported first to settle import order
from app.api.restaurants import _detail_response
from app.models.enums import UserRole


class _StubOwner:
    id = uuid.uuid4()
    full_name = "Owner 4"
    email = "owner4@example.com"


class _StubRestaurant:
    """Only the attributes RestaurantDetailResponse reads."""

    id = uuid.uuid4()
    owner_id = _StubOwner.id
    owner = _StubOwner()
    name = "Bangkok Bowl"
    slug = "bangkok-bowl"
    description = "Thai"
    cuisine_type = "Thai"
    phone_number = "9876543210"
    email = "hello@example.com"
    address_line_1 = "1 Test Street"
    address_line_2 = None
    city = "Ahmedabad"
    state = "Gujarat"
    postal_code = "380015"
    country = "India"
    logo_url = None
    banner_url = None
    theme_preset_id = None
    primary_color = None
    is_approved = True
    is_open = True
    is_active = True
    # What this restaurant charges in. On the response since currency stopped
    # being one global setting — the panel shows several restaurants' money on
    # one screen and has to label each figure with the right symbol.
    currency = "CAD"
    created_at = datetime.now(timezone.utc)
    updated_at = datetime.now(timezone.utc)


class RestaurantOwnerPrivacyTests(unittest.TestCase):
    def test_a_customer_response_carries_no_owner_block(self) -> None:
        response = _detail_response(_StubRestaurant(), locations=[], include_owner=False)
        self.assertIsNone(response.owner)

        # And the email is nowhere in the serialised payload either - a nulled
        # attribute is not the same as a field that never ships.
        dumped = response.model_dump_json()
        self.assertNotIn("owner4@example.com", dumped)
        self.assertNotIn("Owner 4", dumped)

    def test_staff_still_get_the_owner(self) -> None:
        response = _detail_response(_StubRestaurant(), locations=[], include_owner=True)
        self.assertIsNotNone(response.owner)
        assert response.owner is not None
        self.assertEqual(response.owner.email, "owner4@example.com")

    def test_including_the_owner_is_the_default_for_internal_callers(self) -> None:
        # The admin settings endpoints call this without the flag, so the
        # default must stay "include" or the dashboard silently loses the owner.
        response = _detail_response(_StubRestaurant(), locations=[])
        self.assertIsNotNone(response.owner)


class RestaurantDetailRouteTests(unittest.TestCase):
    """The helper being right is not the same as the route calling it right."""

    def _call_as(self, current_user):
        from app.api import restaurants as module

        db = Mock()
        db.scalar.return_value = _StubRestaurant()
        with (
            patch.object(module, "ensure_restaurant_readable", return_value=None),
            patch.object(module, "list_restaurant_locations", return_value=[]),
            patch.object(module, "_get_accessible_restaurant", return_value=_StubRestaurant()),
        ):
            return module.get_restaurant_detail(
                restaurant_id=_StubRestaurant.id,
                db=db,
                current_user=current_user,
                app_scope=Mock(),
            )

    def test_an_anonymous_visitor_gets_no_owner(self) -> None:
        self.assertIsNone(self._call_as(None).owner)

    def test_a_signed_in_customer_gets_no_owner(self) -> None:
        customer = Mock()
        customer.role = UserRole.CUSTOMER
        self.assertIsNone(self._call_as(customer).owner)

    def test_an_admin_still_gets_the_owner(self) -> None:
        admin = Mock()
        admin.role = UserRole.ADMIN
        self.assertIsNotNone(self._call_as(admin).owner)


if __name__ == "__main__":
    unittest.main()

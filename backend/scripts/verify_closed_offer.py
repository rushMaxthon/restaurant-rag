"""A closed kitchen should offer a time, never end the conversation.

Places a real order attempt against a branch that is genuinely closed for
delivery right now, once with no time named and once with a time the branch
cannot keep, and prints the sentence the customer would read. Nothing is sent
and no order is created — a refusal is the expected outcome of both.
"""

from __future__ import annotations

import sys
import uuid
from datetime import timedelta

sys.path.insert(0, "F:/restaurant-rag/backend")

from sqlalchemy import select

from app.config.database import SessionLocal
from app.models.enums import OrderFulfillmentType
from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.services import restaurant_locations as branch_hours
from app.services.ordering_agent import order_draft
from app.services.ordering_agent.loop import describe_place_failure
from app.services.ordering_agent.planner import ToolCallRecord
from app.services.ordering_agent.tools import (
    CartLineArgs,
    OrderingScope,
    PlaceOrderArgs,
    TOOLS,
)


def closed_branch(db):
    """Any branch that cannot take a delivery order at this moment."""

    for location in db.scalars(select(RestaurantLocation)):
        open_now, _ = branch_hours.get_location_fulfillment_status(
            location, fulfillment_type=OrderFulfillmentType.DELIVERY
        )
        if not open_now and branch_hours.next_available_slot_start(
            location, fulfillment_type=OrderFulfillmentType.DELIVERY
        ):
            return location
    return None


def attempt(db, scope, line, *, when=None) -> str:
    draft = order_draft.OrderDraft(
        fulfillment_type=OrderFulfillmentType.DELIVERY.value,
        contact_name="Vishal",
        contact_phone="+919876500099",
        contact_email="vishal@example.com",
        delivery_address="42 Example Road, Surat",
        scheduled_at=when.isoformat() if when else None,
    )
    order_draft.save(scope.session_id, draft)
    result = TOOLS["place_order"].handler(db, scope, PlaceOrderArgs(lines=[line]))
    said = describe_place_failure(
        [ToolCallRecord(tool="place_order", args={}, result=result)]
    )
    order_draft.clear(scope.session_id)
    return said or f"(placed — outcome {result.get('outcome')})"


def main() -> int:
    with SessionLocal() as db:
        location = closed_branch(db)
        if location is None:
            print("Every branch can take a delivery right now — nothing to test.")
            return 0
        restaurant = db.get(Restaurant, location.restaurant_id)
        item = db.scalar(
            select(MenuItem).where(
                MenuItem.restaurant_location_id == location.id,
                MenuItem.is_available.is_(True),
            ).limit(1)
        )
        if item is None:
            print(f"{location.branch_name} is closed but has no menu — nothing to order.")
            return 0

        print(f"{restaurant.name} · {location.branch_name} · closed for delivery now\n")
        # A customer is provisioned from the verified phone, and the
        # database refuses a CUSTOMER row with no app client.
        from app.models.app_client import AppClient

        app_client_id = db.scalar(
            select(AppClient.id).where(AppClient.restaurant_id == restaurant.id).limit(1)
        )
        scope = OrderingScope(
            restaurant_id=restaurant.id,
            restaurant_location_id=location.id,
            customer=None,
            session_id=uuid.uuid4(),
            verified_phone="+919876500099",
            app_client_id=app_client_id,
        )
        line = CartLineArgs(menu_item_id=item.id, quantity=1)

        print("no time named:")
        print("  ", attempt(db, scope, line))

        # A time the branch cannot keep: the small hours, two days out.
        awkward = branch_hours._localize_reference_datetime(None).replace(
            hour=3, minute=30, second=0, microsecond=0
        ) + timedelta(days=2)
        print(f"\nasked for {awkward:%a %H:%M}:")
        print("  ", attempt(db, scope, line, when=awkward))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

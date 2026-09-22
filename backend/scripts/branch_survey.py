"""What Radhe Dhokla actually has, per branch. Reads only."""

from __future__ import annotations

import sys

sys.path.insert(0, "F:/restaurant-rag/backend")

from sqlalchemy import func, select

from app.config.database import SessionLocal
from app.models.location_fulfillment_slot import LocationFulfillmentSlot
from app.models.menu_item import MenuItem
from app.models.menu_item_customization_group import MenuItemCustomizationGroup
from app.models.menu_item_customization_option import MenuItemCustomizationOption
from app.models.menu_item_size import MenuItemSize
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation

def main() -> int:
    wanted = sys.argv[1] if len(sys.argv) > 1 else "Radhe Dhokla"
    with SessionLocal() as db:
        restaurant = db.scalar(select(Restaurant).where(Restaurant.name == wanted))
        if restaurant is None:
            print(f"no restaurant called {wanted!r}")
            return 1
        print(f"{restaurant.name}  ({restaurant.currency})\n")
        print(f"{'branch':<16}{'items':>7}{'sizes':>7}{'groups':>8}{'options':>9}"
              f"{'slots':>7}  hours")
        for location in db.scalars(
            select(RestaurantLocation)
            .where(RestaurantLocation.restaurant_id == restaurant.id)
            .order_by(RestaurantLocation.branch_name)
        ):
            items = db.scalar(select(func.count(MenuItem.id)).where(
                MenuItem.restaurant_location_id == location.id))
            sizes = db.scalar(
                select(func.count(MenuItemSize.id))
                .join(MenuItem, MenuItemSize.menu_item_id == MenuItem.id)
                .where(MenuItem.restaurant_location_id == location.id)
            )
            groups = db.scalar(
                select(func.count(MenuItemCustomizationGroup.id))
                .join(MenuItem, MenuItemCustomizationGroup.menu_item_id == MenuItem.id)
                .where(MenuItem.restaurant_location_id == location.id)
            )
            options = db.scalar(
                select(func.count(MenuItemCustomizationOption.id))
                .join(
                    MenuItemCustomizationGroup,
                    MenuItemCustomizationOption.group_id == MenuItemCustomizationGroup.id,
                )
                .join(MenuItem, MenuItemCustomizationGroup.menu_item_id == MenuItem.id)
                .where(MenuItem.restaurant_location_id == location.id)
            )
            slots = db.scalar(select(func.count(LocationFulfillmentSlot.id)).where(
                LocationFulfillmentSlot.location_id == location.id))
            hours = (
                f"{location.opening_time}-{location.closing_time}"
                if location.opening_time and location.closing_time else "(none set)"
            )
            print(f"{location.branch_name:<16}{items:>7}{sizes:>7}{groups:>8}"
                  f"{options:>9}{slots:>7}  {hours}")

        print("\nslot windows, by branch:")
        for location in db.scalars(
            select(RestaurantLocation)
            .where(RestaurantLocation.restaurant_id == restaurant.id)
            .order_by(RestaurantLocation.branch_name)
        ):
            rows = list(db.scalars(
                select(LocationFulfillmentSlot)
                .where(LocationFulfillmentSlot.location_id == location.id)
                .order_by(LocationFulfillmentSlot.day_of_week,
                          LocationFulfillmentSlot.start_time)
            ))
            if not rows:
                print(f"  {location.branch_name:<16} none")
                continue
            shapes = sorted({
                f"{r.fulfillment_type.value} {r.start_time:%H:%M}-{r.end_time:%H:%M}"
                for r in rows
            })
            days = sorted({r.day_of_week.value for r in rows})
            print(f"  {location.branch_name:<16} {len(rows)} rows · {', '.join(shapes)}")
            print(f"  {'':<16} days: {', '.join(days)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

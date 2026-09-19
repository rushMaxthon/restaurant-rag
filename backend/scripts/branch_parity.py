"""Give every branch of a restaurant the same menu and the same hours.

Written for Radhe Dhokla, whose PDF import put all 136 dishes on Rushtampura and nothing on the other
five, while the schedule went the other way — 14 slots on the five, none on
Rushtampura. So the branch that can feed you cannot say when it is open, and
the branches that can say when they are open have nothing to sell. A customer
picking Vesu on the storefront sees an empty menu; the chat, pointed at
Rushtampura, can never quote an opening time.

What this does, per branch that is short of it:

* copies each dish, with its sizes and its customization groups and options,
  keeping ids distinct and remapping the references between them;
* copies the embedding VECTOR rather than recomputing it — the source text is
  the dish's own name and description, which the copy shares exactly, so a
  fresh model call would produce the same numbers 680 times over;
* fills the slot schedule from a branch that has one;
* sets opening and closing times, which nothing had, so a branch can still
  answer "when do you open" if its slots are ever cleared.

Idempotent: a dish already on a branch, by name, is left alone. Safe to run
twice. Reports what it would do and changes nothing unless given --apply.

    python scripts/branch_parity.py "Radhe Dhokla"
    python scripts/branch_parity.py "Radhe Dhokla" --apply
"""

from __future__ import annotations

import argparse
import sys
from datetime import time as clock_time

sys.path.insert(0, "F:/restaurant-rag/backend")

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.config.database import SessionLocal
from app.models.location_fulfillment_slot import LocationFulfillmentSlot
from app.models.menu_embedding import MenuEmbedding
from app.models.menu_item import MenuItem
from app.models.menu_item_customization_group import MenuItemCustomizationGroup
from app.models.menu_item_customization_option import MenuItemCustomizationOption
from app.models.menu_item_size import MenuItemSize
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation

OPENS, CLOSES = clock_time(10, 30), clock_time(22, 0)

#: Columns that describe the DISH rather than where it is sold. Everything
#: else — the id, the branch, the timestamps — belongs to the copy.
DISH_FIELDS = (
    "name", "category", "cuisine_type", "description", "price", "is_veg",
    "is_available", "is_bestseller", "image_url", "popularity_score",
    "rating", "rating_count", "launched_at", "is_new_launch",
    "has_sizes", "has_customizations",
)
SIZE_FIELDS = ("name", "price", "is_active", "sort_order")
GROUP_FIELDS = (
    "title", "selection_type", "is_required", "min_selection", "max_selection",
    "supports_halves",
)


def copy_of(row, fields, **overrides):
    values = {field: getattr(row, field) for field in fields}
    values.update(overrides)
    return values


def option_fields(db) -> tuple[str, ...]:
    """The option's own columns, minus its keys — read off the model so a
    column added later is carried without this script being edited."""

    skip = {"id", "group_id", "created_at", "updated_at"}
    return tuple(
        column.key
        for column in MenuItemCustomizationOption.__table__.columns
        if column.key not in skip
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("restaurant", help="the restaurant to level up")
    parser.add_argument("--apply", action="store_true", help="write the changes")
    args = parser.parse_args()
    dry = not args.apply

    with SessionLocal() as db:
        restaurant = db.scalar(
            select(Restaurant).where(Restaurant.name == args.restaurant)
        )
        if restaurant is None:
            print(f"no restaurant called {args.restaurant!r}")
            return 1
        branches = list(db.scalars(
            select(RestaurantLocation)
            .where(RestaurantLocation.restaurant_id == restaurant.id)
            .order_by(RestaurantLocation.branch_name)
        ))

        counts = {
            b.id: db.scalar(select(func.count(MenuItem.id)).where(
                MenuItem.restaurant_location_id == b.id))
            for b in branches
        }
        source = max(branches, key=lambda b: counts[b.id])
        if not counts[source.id]:
            print("no branch has a menu to copy from")
            return 1
        print(f"{restaurant.name}: menu comes from {source.branch_name} "
              f"({counts[source.id]} dishes)")

        # The schedule comes from whichever branch has one.
        slot_source = next(
            (b for b in branches if db.scalar(select(func.count(LocationFulfillmentSlot.id))
                                              .where(LocationFulfillmentSlot.location_id == b.id))),
            None,
        )
        print(f"{'':>{len(restaurant.name) + 2}}hours come from "
              f"{slot_source.branch_name if slot_source else '(nowhere — none set)'}\n")

        dishes = list(db.scalars(
            select(MenuItem)
            .where(MenuItem.restaurant_location_id == source.id)
            .options(
                selectinload(MenuItem.sizes),
                selectinload(MenuItem.customization_groups)
                .selectinload(MenuItemCustomizationGroup.options),
                selectinload(MenuItem.embedding),
            )
            .order_by(MenuItem.name)
        ))
        template_slots = list(db.scalars(
            select(LocationFulfillmentSlot)
            .where(LocationFulfillmentSlot.location_id == slot_source.id)
        )) if slot_source else []
        opt_fields = option_fields(db)

        added_dishes = added_slots = added_hours = 0
        for branch in branches:
            have = {
                name.casefold()
                for name in db.scalars(select(MenuItem.name).where(
                    MenuItem.restaurant_location_id == branch.id))
            }
            missing = [d for d in dishes if d.name.casefold() not in have]

            slots_here = db.scalar(select(func.count(LocationFulfillmentSlot.id)).where(
                LocationFulfillmentSlot.location_id == branch.id))
            needs_slots = template_slots and not slots_here
            needs_hours = branch.opening_time is None or branch.closing_time is None

            note = []
            if missing:
                note.append(f"+{len(missing)} dishes")
            if needs_slots:
                note.append(f"+{len(template_slots)} slots")
            if needs_hours:
                note.append(f"hours {OPENS:%H:%M}-{CLOSES:%H:%M}")
            print(f"  {branch.branch_name:<14} {', '.join(note) if note else 'already complete'}")

            if dry:
                continue

            for dish in missing:
                copy = MenuItem(
                    restaurant_id=restaurant.id,
                    restaurant_location_id=branch.id,
                    **copy_of(dish, DISH_FIELDS),
                )
                db.add(copy)
                db.flush()
                size_map = {}
                for size in dish.sizes:
                    new_size = MenuItemSize(menu_item_id=copy.id,
                                            **copy_of(size, SIZE_FIELDS))
                    db.add(new_size)
                    db.flush()
                    size_map[size.id] = new_size.id
                for group in dish.customization_groups:
                    new_group = MenuItemCustomizationGroup(
                        menu_item_id=copy.id,
                        # A group can hang off one SIZE, so the reference has
                        # to follow the size's copy, not the original.
                        menu_item_size_id=size_map.get(group.menu_item_size_id),
                        **copy_of(group, GROUP_FIELDS),
                    )
                    db.add(new_group)
                    db.flush()
                    for option in group.options:
                        db.add(MenuItemCustomizationOption(
                            group_id=new_group.id,
                            **copy_of(option, opt_fields),
                        ))
                if dish.embedding is not None:
                    # The vector is a function of the source text, and the
                    # copy's text is identical. Recomputing 680 of these
                    # would spend minutes to arrive at the same numbers.
                    db.add(MenuEmbedding(
                        menu_item_id=copy.id,
                        source_text=dish.embedding.source_text,
                        embedding=dish.embedding.embedding,
                    ))
                added_dishes += 1

            if needs_slots:
                for slot in template_slots:
                    db.add(LocationFulfillmentSlot(
                        location_id=branch.id,
                        day_of_week=slot.day_of_week,
                        fulfillment_type=slot.fulfillment_type,
                        start_time=slot.start_time,
                        end_time=slot.end_time,
                        **({"is_active": slot.is_active}
                           if hasattr(slot, "is_active") else {}),
                    ))
                    added_slots += 1
            if needs_hours:
                branch.opening_time = branch.opening_time or OPENS
                branch.closing_time = branch.closing_time or CLOSES
                added_hours += 1

        if dry:
            print("\nDRY RUN — nothing written. Re-run with --apply.")
            return 0

        db.commit()
        print(f"\nwrote {added_dishes} dishes, {added_slots} slots, "
              f"hours on {added_hours} branches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

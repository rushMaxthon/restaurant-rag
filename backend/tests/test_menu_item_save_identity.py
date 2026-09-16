"""Saving a menu item must not throw away the ids customers are holding.

Reported as "the selected size is unavailable for Build Your Own Pizza" on a
checkout screen, from a cart the customer had built minutes earlier and never
touched since.

Every save rebuilt the item: `menu_item.sizes = []`, then fresh rows with fresh
UUIDs, and the same for every customization group and option. Nothing in the
item looked different afterwards - same names, same prices - but every id had
changed. A cart lives in the browser's storage for days and holds
`menu_item_size_id` and `option_id`, and `resolve_menu_item_selection` refuses
ids it cannot find. So an owner fixing a price broke every cart already holding
that dish, and the customer's only way out was to delete the line; nothing on
the screen said so.

The fix is to match each saved row against the one it is editing and update it
in place. Ids first, because they survive a rename and say exactly which row
the owner had in front of them; then names, which is all the mobile app and the
seed script send.
"""

from __future__ import annotations

import unittest
import uuid

from app.main import app  # noqa: F401 - imported first to settle import order
from app.api.menu_items import _sync_menu_item_customizations
from app.models.enums import MenuItemCustomizationSelectionType
from app.models.menu_item import MenuItem
from app.models.menu_item_customization_group import MenuItemCustomizationGroup
from app.models.menu_item_customization_option import MenuItemCustomizationOption
from app.models.menu_item_size import MenuItemSize
from app.schemas.menu_item import MenuItemUpdate


def saved_item() -> MenuItem:
    """A pizza as it sits in the database: two sizes, toppings on each."""
    item = MenuItem(
        id=uuid.uuid4(),
        name="Build Your Own Pizza",
        price="14.99",
        has_sizes=True,
        has_customizations=True,
    )
    for index, (name, price) in enumerate(
        [("Small (8\")", "14.99"), ("Medium (11\")", "19.49")]
    ):
        size = MenuItemSize(id=uuid.uuid4(), name=name, price=price, is_active=True, sort_order=index)
        item.sizes.append(size)
        # `menu_item=` is what puts the group on the item; appending as well
        # would list it twice, which is the same slip the endpoint had.
        group = MenuItemCustomizationGroup(
            id=uuid.uuid4(),
            menu_item=item,
            menu_item_size=size,
            title="Toppings",
            selection_type=MenuItemCustomizationSelectionType.MULTI,
            is_required=False,
            min_selection=0,
            max_selection=2,
            supports_halves=True,
            is_active=True,
            sort_order=0,
        )
        for order, topping in enumerate(["Pepperoni", "Mushroom"]):
            group.options.append(
                MenuItemCustomizationOption(
                    id=uuid.uuid4(),
                    name=topping,
                    extra_price="1.50",
                    is_active=True,
                    is_countable=False,
                    sort_order=order,
                )
            )
    return item


def payload_from(item: MenuItem, *, send_ids: bool) -> dict:
    """The item as the dashboard sends it back, with or without row ids."""

    def option(row: MenuItemCustomizationOption) -> dict:
        body = {
            "name": row.name,
            "extra_price": str(row.extra_price),
            "is_active": row.is_active,
            "is_countable": row.is_countable,
            "sort_order": row.sort_order,
        }
        if send_ids:
            body["id"] = str(row.id)
        return body

    def group(row: MenuItemCustomizationGroup) -> dict:
        body = {
            "title": row.title,
            "selection_type": row.selection_type,
            "is_required": row.is_required,
            "min_selection": row.min_selection,
            "max_selection": row.max_selection,
            "supports_halves": row.supports_halves,
            "is_active": row.is_active,
            "sort_order": row.sort_order,
            "options": [option(o) for o in row.options],
        }
        if send_ids:
            body["id"] = str(row.id)
        return body

    def size(row: MenuItemSize) -> dict:
        body = {
            "name": row.name,
            "price": str(row.price),
            "is_active": row.is_active,
            "sort_order": row.sort_order,
            "customization_groups": [
                group(g) for g in item.customization_groups if g.menu_item_size is row
            ],
        }
        if send_ids:
            body["id"] = str(row.id)
        return body

    return {
        "name": item.name,
        "category": "Pizza",
        "cuisine_type": "Italian",
        "description": "Yours to build.",
        "price": str(item.price),
        "is_veg": False,
        "is_available": True,
        "image_url": None,
        "is_new_launch": False,
        "has_sizes": True,
        "has_customizations": True,
        "customization_groups": [],
        "sizes": [size(s) for s in item.sizes],
    }


def ids_of(item: MenuItem) -> dict[str, set]:
    return {
        "sizes": {s.id for s in item.sizes},
        "groups": {g.id for g in item.customization_groups},
        "options": {o.id for g in item.customization_groups for o in g.options},
    }


class SaveKeepsIdentity(unittest.TestCase):
    def test_a_price_change_keeps_every_id(self):
        item = saved_item()
        before = ids_of(item)
        body = payload_from(item, send_ids=True)
        body["sizes"][0]["price"] = "15.99"

        _sync_menu_item_customizations(item, MenuItemUpdate(**body))

        self.assertEqual(before, ids_of(item))
        self.assertEqual(str(item.sizes[0].price), "15.99")

    def test_a_save_that_sends_no_ids_still_keeps_them_by_name(self):
        # The mobile app and the seed script do not track row ids, and neither
        # did any client before this. Matching on name covers them.
        item = saved_item()
        before = ids_of(item)
        body = payload_from(item, send_ids=False)
        body["sizes"][1]["customization_groups"][0]["max_selection"] = 3

        _sync_menu_item_customizations(item, MenuItemUpdate(**body))

        self.assertEqual(before, ids_of(item))

    def test_renaming_a_size_keeps_it_when_the_id_comes_back(self):
        item = saved_item()
        kept = item.sizes[0].id
        body = payload_from(item, send_ids=True)
        body["sizes"][0]["name"] = "Personal (8\")"

        _sync_menu_item_customizations(item, MenuItemUpdate(**body))

        self.assertEqual([s.id for s in item.sizes][0], kept)
        self.assertEqual(item.sizes[0].name, "Personal (8\")")

    def test_removing_a_size_removes_it_and_its_groups(self):
        item = saved_item()
        dropped = item.sizes[1].id
        kept = item.sizes[0].id
        body = payload_from(item, send_ids=True)
        del body["sizes"][1]

        _sync_menu_item_customizations(item, MenuItemUpdate(**body))

        self.assertEqual({s.id for s in item.sizes}, {kept})
        # The group that hung off the deleted size goes with it, rather than
        # staying on the item pointing at nothing.
        self.assertEqual(len(item.customization_groups), 1)
        self.assertNotIn(dropped, {g.menu_item_size.id for g in item.customization_groups})

    def test_same_title_on_two_sizes_does_not_swap_rows(self):
        # Both sizes have a group called "Toppings". Reconciling them in one
        # pool would let the Small's row be claimed by the Medium's payload,
        # moving a customer's chosen topping onto the wrong size.
        item = saved_item()
        small, medium = item.sizes
        on_small = next(g.id for g in item.customization_groups if g.menu_item_size is small)
        on_medium = next(g.id for g in item.customization_groups if g.menu_item_size is medium)
        body = payload_from(item, send_ids=False)

        _sync_menu_item_customizations(item, MenuItemUpdate(**body))

        after_small = next(g.id for g in item.customization_groups if g.menu_item_size.name == small.name)
        after_medium = next(g.id for g in item.customization_groups if g.menu_item_size.name == medium.name)
        self.assertEqual(after_small, on_small)
        self.assertEqual(after_medium, on_medium)

    def test_a_new_option_is_added_without_disturbing_the_others(self):
        item = saved_item()
        before = ids_of(item)["options"]
        body = payload_from(item, send_ids=True)
        body["sizes"][0]["customization_groups"][0]["options"].append(
            {"name": "Olives", "extra_price": "1.00", "is_active": True, "is_countable": False, "sort_order": 2}
        )

        _sync_menu_item_customizations(item, MenuItemUpdate(**body))

        after = ids_of(item)["options"]
        self.assertTrue(before.issubset(after))
        self.assertEqual(len(after), len(before) + 1)

    def test_a_removed_option_goes_and_the_rest_stay(self):
        item = saved_item()
        group = next(g for g in item.customization_groups if g.menu_item_size is item.sizes[0])
        dropped = group.options[0].id
        kept = group.options[1].id
        body = payload_from(item, send_ids=True)
        del body["sizes"][0]["customization_groups"][0]["options"][0]

        _sync_menu_item_customizations(item, MenuItemUpdate(**body))

        surviving = {o.id for g in item.customization_groups for o in g.options}
        self.assertNotIn(dropped, surviving)
        self.assertIn(kept, surviving)

    def test_a_brand_new_item_is_built_from_nothing(self):
        # The create path shares this function and has no rows to match.
        item = MenuItem(id=uuid.uuid4(), name="New Pizza", price="9.99")
        template = saved_item()
        body = payload_from(template, send_ids=False)
        body["name"] = "New Pizza"

        _sync_menu_item_customizations(item, MenuItemUpdate(**body))

        self.assertEqual(len(item.sizes), 2)
        self.assertEqual(len(item.customization_groups), 2)
        self.assertEqual(
            [o.name for g in item.customization_groups for o in g.options],
            ["Pepperoni", "Mushroom", "Pepperoni", "Mushroom"],
        )


if __name__ == "__main__":
    unittest.main()

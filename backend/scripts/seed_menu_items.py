"""Fill out Bangkok Bowl's menu, and nothing else in the database.

Why this exists rather than `seed.py`: that script rebuilds users, orders,
offers and every location's fulfillment slots on each run. Wanting more dishes
is not a reason to regenerate a restaurant's opening hours, so this does one
thing.

Three properties it is built around:

1. It only ever INSERTs, and only into the four menu tables. The models for
   users, orders, offers and slots are deliberately not imported, so the script
   cannot touch them even by mistake.
2. Running it twice is a no-op. A dish is "already there" by the same rule the
   product itself uses - `(restaurant, location, lower(trim(name)))`, from the
   bulk-create route - so this script and the admin UI agree on what a duplicate
   is. An existing row is skipped whole and never updated, so a price an owner
   edited later survives a re-run.
3. It refuses to write unless asked. `--apply` is required; without it the run
   prints what it would create and rolls back.

Every item is built as a `MenuItemCreate` and passed through the API's own
`_sync_menu_item_customizations`, so this cannot produce a shape the admin API
would reject - a SINGLE group with two allowed selections, a required group
that permits zero, options attached to an item with customizations switched
off. One definition of a valid menu item, not two.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import func, select

from app.api.menu_items import _sync_menu_item_customizations
from app.config.database import SessionLocal

# Only the menu tables. Importing User/Order/PersonalizedOffer/
# LocationFulfillmentSlot here would make it possible to write them; not
# importing them makes it impossible.
from app.models.menu_item import MenuItem
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.schemas.menu_item import MenuItemCreate

RESTAURANT_NAME = "Bangkok Bowl"


# --- payload helpers -------------------------------------------------------
# Thin wrappers so the catalogue below reads as a menu rather than as nested
# dictionaries. Defaults match the API's own defaults.


def option(name: str, extra: str = "0.00", *, countable: bool = False, active: bool = True, order: int = 0) -> dict:
    return {
        "name": name,
        "extra_price": Decimal(extra),
        "is_countable": countable,
        "is_active": active,
        "sort_order": order,
    }


def group(
    title: str,
    options: list[dict],
    *,
    single: bool = False,
    required: bool = False,
    min_selection: int | None = None,
    max_selection: int | None = None,
    order: int = 0,
) -> dict:
    """One customization group, with the selection rules stated in menu terms.

    `min_selection` defaults to 1 for a required group because the API rejects
    a required group that permits zero - encoding that here means the catalogue
    never has to repeat it.
    """
    resolved_min = min_selection if min_selection is not None else (1 if required else 0)
    if single:
        resolved_max = 1
    else:
        resolved_max = max_selection if max_selection is not None else max(len(options), resolved_min)
    return {
        "title": title,
        "selection_type": "SINGLE" if single else "MULTI",
        "is_required": required,
        "min_selection": resolved_min,
        "max_selection": resolved_max,
        "options": options,
        "sort_order": order,
    }


def size(name: str, price: str, *, active: bool = True, order: int = 0, groups: list[dict] | None = None) -> dict:
    return {
        "name": name,
        "price": Decimal(price),
        "is_active": active,
        "sort_order": order,
        "customization_groups": groups or [],
    }


def dish(
    name: str,
    category: str,
    price: str,
    description: str,
    *,
    veg: bool,
    cuisine: str = "Thai",
    sizes: list[dict] | None = None,
    groups: list[dict] | None = None,
    new_launch: bool = False,
) -> dict:
    """A menu item.

    `has_sizes` / `has_customizations` are derived rather than passed: the API
    validates that they agree with the payload, and a catalogue that states the
    same fact twice is a catalogue that will eventually state it inconsistently.
    """
    sizes = sizes or []
    groups = groups or []
    has_sizes = bool(sizes)
    has_customizations = bool(groups) or any(s["customization_groups"] for s in sizes)
    return {
        "name": name,
        "category": category,
        "cuisine_type": cuisine,
        "description": description,
        # For a sized item the API recomputes `price` as the lowest active size,
        # so this is the floor rather than the truth; it still has to be a valid
        # positive price because the schema requires one.
        "price": Decimal(price),
        "is_veg": veg,
        "is_new_launch": new_launch,
        "has_sizes": has_sizes,
        "has_customizations": has_customizations,
        "sizes": sizes,
        "customization_groups": groups,
    }


# --- groups that recur across the menu -------------------------------------
# A Thai kitchen asks the same few questions about most dishes, so these are
# defined once. Each returns a fresh dict: the payload objects are mutated
# downstream when they are turned into rows, so sharing one instance between
# two dishes would couple them.


def spice_level(required: bool = True) -> dict:
    """Heat, asked as a single choice because a dish has one heat."""
    return group(
        "Spice level",
        [
            option("Mild", order=1),
            option("Medium", order=2),
            option("Thai hot", order=3),
            option("Extra Thai hot", "0.50", order=4),
        ],
        single=True,
        required=required,
        order=1,
    )


def protein_choice() -> dict:
    return group(
        "Choose your protein",
        [
            option("Tofu", order=1),
            option("Chicken", "1.50", order=2),
            option("Prawns", "3.50", order=3),
            # Off the menu until the season returns. Kept rather than deleted so
            # the dish it belongs to still remembers it was ever offered.
            option("Soft shell crab", "5.50", active=False, order=4),
        ],
        single=True,
        required=True,
        order=2,
    )


def thai_addons() -> dict:
    """Extras someone can want more than one of - hence countable."""
    return group(
        "Add extras",
        [
            option("Extra peanuts", "0.75", countable=True, order=1),
            option("Fried egg", "1.75", countable=True, order=2),
            option("Extra tofu", "2.25", countable=True, order=3),
            option("Steamed jasmine rice", "2.95", countable=True, order=4),
            option("Prawn crackers", "2.50", countable=True, order=5),
        ],
        max_selection=5,
        order=3,
    )


def garnishes() -> dict:
    """Free, optional, capped - the shape most 'pick a few' groups take."""
    return group(
        "Garnishes",
        [
            option("Fresh lime", order=1),
            option("Coriander", order=2),
            option("Crispy shallots", order=3),
            option("Spring onion", order=4),
            option("Bird's eye chilli", order=5),
        ],
        max_selection=3,
        order=4,
    )


CATALOGUE: list[dict] = [
    # --- Beverages ---------------------------------------------------------
    dish("Thai Iced Coffee", "Beverages", "4.49",
         "Dark roast over ice, finished with sweet condensed milk.", veg=True),
    dish("Lemongrass Iced Tea", "Beverages", "3.99",
         "Chilled lemongrass infusion with a squeeze of lime.", veg=True),
    dish("Fresh Young Coconut", "Beverages", "5.49",
         "Whole young coconut, served chilled with a straw.", veg=True),
    dish("Singha Soda Lime", "Beverages", "3.49",
         "Sparkling soda with fresh lime and a pinch of sea salt.", veg=True),
    dish("Thai Milk Tea Boba", "Beverages", "4.99",
         "Thai milk tea with chewy tapioca pearls.", veg=True,
         sizes=[
             size("Regular", "4.99", order=1),
             size("Large", "6.49", order=2),
             # Catering size, dormant outside event season.
             size("Party jug (1.5L)", "17.99", active=False, order=3),
         ]),
    dish("Butterfly Pea Lemonade", "Beverages", "5.29",
         "Colour-changing blue pea flower lemonade over crushed ice.", veg=True,
         groups=[
             group("Sweetness",
                   [option("No sugar", order=1), option("Half sweet", order=2),
                    option("Standard", order=3), option("Extra sweet", order=4)],
                   single=True, required=True, order=1),
         ]),
    dish("Iced Matcha Coconut Latte", "Beverages", "5.99",
         "Ceremonial matcha shaken with coconut milk over ice.", veg=True,
         groups=[
             group("Make it stronger",
                   [option("Extra matcha shot", "1.25", countable=True, order=1),
                    option("Espresso shot", "1.50", countable=True, order=2)],
                   max_selection=2, order=1),
         ]),
    dish("Mango Sticky Smoothie", "Beverages", "6.49",
         "Blended alphonso mango with coconut cream and sticky rice pearls.", veg=True,
         sizes=[
             size("Regular", "6.49", order=1,
                  groups=[group("Milk",
                                [option("Coconut milk", order=1), option("Oat milk", "0.75", order=2),
                                 option("Dairy milk", order=3)],
                                single=True, required=True, order=1)]),
             size("Large", "8.29", order=2,
                  groups=[group("Milk",
                                [option("Coconut milk", order=1), option("Oat milk", "0.75", order=2),
                                 option("Dairy milk", order=3), option("Soy milk", "0.75", order=4)],
                                single=True, required=True, order=1)]),
         ]),
    dish("Chrysanthemum Cooler", "Beverages", "4.29",
         "Floral chrysanthemum tea served cold and lightly sweetened.", veg=True,
         groups=[
             group("Add-ins",
                   [option("Honey", "0.50", order=1), option("Lime", order=2),
                    option("Basil seeds", "0.75", order=3), option("Aloe cubes", "1.00", order=4)],
                   max_selection=2, order=1),
         ]),

    # --- Curry -------------------------------------------------------------
    dish("Massaman Beef Curry", "Curry", "17.49",
         "Slow-braised beef with potato, peanuts and warm spices.", veg=False),
    dish("Panang Curry Prawns", "Curry", "18.49",
         "Thick panang curry with prawns, kaffir lime and coconut cream.", veg=False),
    dish("Yellow Curry Vegetables", "Curry", "13.99",
         "Turmeric coconut curry with seasonal vegetables and potato.", veg=True),
    dish("Jungle Curry Chicken", "Curry", "15.49",
         "Broth-based curry with no coconut milk - fiery and herbal.", veg=False,
         groups=[spice_level()]),
    dish("Khao Soi Chicken", "Curry", "16.49",
         "Northern coconut curry noodles topped with crispy egg noodles.", veg=False,
         groups=[spice_level(), garnishes()], new_launch=True),
    dish("Choo Chee Tofu Curry", "Curry", "14.29",
         "Crisp tofu in a fragrant red curry reduction.", veg=True,
         groups=[thai_addons()]),
    dish("Green Curry Family Pot", "Curry", "22.99",
         "Our green curry in a sharing pot, with jasmine rice on the side.", veg=False,
         sizes=[
             size("Serves 2", "22.99", order=1, groups=[spice_level()]),
             size("Serves 4", "39.99", order=2, groups=[spice_level()]),
         ]),
    dish("Build Your Own Curry", "Curry", "14.99",
         "Pick a curry paste and a protein; we cook it to order.", veg=True,
         sizes=[
             size("Regular", "14.99", order=1),
             size("Large", "18.49", order=2),
         ],
         groups=[
             group("Curry paste",
                   [option("Green", order=1), option("Red", order=2),
                    option("Massaman", "1.00", order=3), option("Panang", "1.00", order=4)],
                   single=True, required=True, order=1),
             protein_choice(),
             thai_addons(),
         ]),
    dish("Curry Tasting Trio", "Curry", "21.49",
         "Three small curries chosen by you, with rice and roti.", veg=False,
         groups=[
             # Exactly what it says: a trio needs three, so the minimum is not 1.
             group("Choose three curries",
                   [option("Green chicken", order=1), option("Red tofu", order=2),
                    option("Massaman beef", "2.00", order=3), option("Yellow vegetable", order=4),
                    option("Panang prawn", "2.50", order=5)],
                   required=True, min_selection=3, max_selection=3, order=1),
             spice_level(),
         ]),

    # --- Noodles -----------------------------------------------------------
    dish("Pad See Ew Chicken", "Noodles", "14.99",
         "Wide rice noodles charred with dark soy, egg and Chinese broccoli.", veg=False),
    dish("Drunken Noodles", "Noodles", "15.49",
         "Wide noodles with holy basil, chilli and green peppercorn.", veg=False),
    dish("Glass Noodle Salad", "Noodles", "12.99",
         "Chilled mung bean noodles with lime, chilli and herbs.", veg=True),
    dish("Crispy Noodle Nest", "Noodles", "13.49",
         "Fried egg noodles under a sweet-sour vegetable gravy.", veg=True),
    dish("Pad Thai Prawn", "Noodles", "17.49",
         "The classic, with tiger prawns, tamarind and crushed peanuts.", veg=False,
         groups=[thai_addons()]),
    dish("Boat Noodle Soup", "Noodles", "14.49",
         "Dark, spiced beef broth with rice noodles and morning glory.", veg=False,
         groups=[spice_level(), garnishes()]),
    dish("Tom Yum Noodle Bowl", "Noodles", "15.99",
         "Hot and sour tom yum broth poured over rice noodles.", veg=False,
         sizes=[
             size("Regular", "15.99", order=1),
             size("Large", "19.49", order=2),
         ]),
    dish("Build Your Own Noodle Bowl", "Noodles", "13.99",
         "Choose the noodle, the protein and how hot you want it.", veg=True,
         sizes=[
             size("Regular", "13.99", order=1,
                  groups=[group("Noodle",
                                [option("Thin rice noodle", order=1), option("Wide rice noodle", order=2),
                                 option("Egg noodle", order=3), option("Glass noodle", "0.75", order=4)],
                                single=True, required=True, order=1)]),
             size("Large", "17.29", order=2,
                  groups=[group("Noodle",
                                [option("Thin rice noodle", order=1), option("Wide rice noodle", order=2),
                                 option("Egg noodle", order=3), option("Glass noodle", "0.75", order=4),
                                 option("Brown rice noodle", "1.25", order=5)],
                                single=True, required=True, order=1)]),
         ],
         groups=[protein_choice(), spice_level(), thai_addons()]),
    dish("Pad Woon Sen Veg", "Noodles", "13.29",
         "Glass noodles wok-tossed with egg, cabbage and tomato.", veg=True,
         groups=[garnishes()]),
    dish("Chiang Mai Noodle Box", "Noodles", "16.29",
         "Egg noodles, braised chicken and pickled mustard greens.", veg=False,
         groups=[spice_level(required=False)], new_launch=True),

    # --- Rice --------------------------------------------------------------
    dish("Pineapple Fried Rice", "Rice", "14.49",
         "Fried rice with pineapple, cashews and turmeric, served in the shell.", veg=True),
    dish("Crab Fried Rice", "Rice", "18.99",
         "Jasmine rice wok-tossed with crab meat, egg and spring onion.", veg=False),
    dish("Steamed Jasmine Rice", "Rice", "3.49",
         "A bowl of fragrant steamed jasmine rice.", veg=True),
    dish("Coconut Turmeric Rice", "Rice", "4.99",
         "Jasmine rice steamed with coconut milk and turmeric.", veg=True),
    dish("Thai Basil Fried Rice", "Rice", "13.99",
         "Fried rice with holy basil, chilli and green beans.", veg=True,
         groups=[protein_choice(), spice_level()]),
    dish("Green Curry Fried Rice", "Rice", "15.29",
         "Fried rice cooked in green curry paste with Thai aubergine.", veg=False,
         groups=[thai_addons()]),
    dish("Sticky Rice Basket", "Rice", "4.29",
         "Northern-style glutinous rice, steamed in a bamboo basket.", veg=True,
         sizes=[
             size("Single basket", "4.29", order=1),
             size("Double basket", "7.49", order=2),
         ]),
    dish("Khao Pad Family Platter", "Rice", "24.99",
         "A sharing platter of fried rice with two proteins and prawn crackers.", veg=False,
         sizes=[
             size("Serves 2", "24.99", order=1,
                  groups=[group("Choose two proteins",
                                [option("Chicken", order=1), option("Prawns", "2.00", order=2),
                                 option("Tofu", order=3), option("Beef", "2.50", order=4)],
                                required=True, min_selection=2, max_selection=2, order=1)]),
             size("Serves 4", "44.99", order=2,
                  groups=[group("Choose three proteins",
                                [option("Chicken", order=1), option("Prawns", "3.00", order=2),
                                 option("Tofu", order=3), option("Beef", "3.50", order=4),
                                 option("Soft shell crab", "6.00", active=False, order=5)],
                                required=True, min_selection=3, max_selection=3, order=1)]),
         ],
         groups=[spice_level(), garnishes()]),
    dish("Egg Fried Rice", "Rice", "11.49",
         "Simple wok-fried rice with egg, garlic and white pepper.", veg=True,
         groups=[thai_addons()]),
    dish("Salted Fish Fried Rice", "Rice", "16.49",
         "Fried rice with salted fish, chicken and Chinese kale.", veg=False),

    # --- Main Course -------------------------------------------------------
    dish("Crispy Pork Belly", "Main Course", "18.99",
         "Twice-cooked pork belly with chilli vinegar dipping sauce.", veg=False),
    dish("Whole Steamed Sea Bass", "Main Course", "26.99",
         "Sea bass steamed with lime, garlic and chilli broth.", veg=False),
    dish("Cashew Chicken", "Main Course", "16.49",
         "Wok-fried chicken with roasted cashews and dried chilli.", veg=False),
    dish("Stir-Fried Morning Glory", "Main Course", "10.99",
         "Water spinach flashed with garlic, chilli and yellow bean.", veg=True),
    dish("Tofu Larb", "Main Course", "13.49",
         "Crumbled tofu tossed with toasted rice powder, mint and lime.", veg=True,
         groups=[spice_level()]),
    dish("Garlic Pepper Prawns", "Main Course", "19.49",
         "Tiger prawns seared with white pepper and fried garlic.", veg=False,
         groups=[garnishes(), thai_addons()]),
    dish("Grilled Chicken Satay", "Main Course", "12.99",
         "Turmeric-marinated skewers with peanut sauce and cucumber relish.", veg=False,
         sizes=[
             size("4 skewers", "12.99", order=1),
             size("8 skewers", "22.99", order=2),
             size("Party tray (20)", "52.99", active=False, order=3),
         ]),
    dish("Bangkok Bowl Signature Platter", "Main Course", "27.99",
         "Our house platter: pick the centrepiece and the sides.", veg=False,
         sizes=[
             size("Serves 2", "27.99", order=1,
                  groups=[group("Centrepiece",
                                [option("Crispy pork belly", order=1), option("Grilled chicken", order=2),
                                 option("Whole sea bass", "6.00", order=3)],
                                single=True, required=True, order=1)]),
             size("Serves 4", "49.99", order=2,
                  groups=[group("Centrepiece",
                                [option("Crispy pork belly", order=1), option("Grilled chicken", order=2),
                                 option("Whole sea bass", "10.00", order=3),
                                 option("Whole roast duck", "14.00", order=4)],
                                single=True, required=True, order=1)]),
         ],
         groups=[
             group("Choose two sides",
                   [option("Steamed jasmine rice", order=1), option("Sticky rice", order=2),
                    option("Papaya salad", order=3), option("Morning glory", order=4),
                    option("Prawn crackers", order=5)],
                   required=True, min_selection=2, max_selection=2, order=2),
             spice_level(required=False),
         ]),
    dish("Roast Duck Red Curry", "Main Course", "21.99",
         "Roast duck with lychee, cherry tomato and red curry.", veg=False,
         groups=[spice_level()]),
    dish("Son-in-Law Eggs", "Main Course", "11.49",
         "Crisp-fried eggs with tamarind caramel and fried shallots.", veg=True),

    # --- Dessert -----------------------------------------------------------
    dish("Mango Sticky Rice", "Dessert", "8.49",
         "Sweet coconut sticky rice with ripe mango and sesame.", veg=True),
    dish("Fried Banana Fritters", "Dessert", "6.99",
         "Crisp battered banana with honey and toasted coconut.", veg=True),
    dish("Thai Tea Panna Cotta", "Dessert", "7.49",
         "Set Thai tea cream with condensed milk caramel.", veg=True),
    dish("Coconut Ice Cream", "Dessert", "5.49",
         "Churned coconut ice cream with roasted peanuts.", veg=True,
         groups=[
             group("Toppings",
                   [option("Sticky rice", "1.50", order=1), option("Roasted peanuts", "0.75", countable=True, order=2),
                    option("Palm sugar syrup", "0.75", order=3), option("Fresh mango", "2.25", order=4),
                    option("Toasted coconut", "0.75", countable=True, order=5)],
                   max_selection=4, order=1),
         ]),
    dish("Lod Chong Pandan", "Dessert", "6.49",
         "Green pandan noodles in sweet coconut milk over shaved ice.", veg=True),
    dish("Tub Tim Krob", "Dessert", "6.99",
         "Water chestnut rubies in coconut milk and crushed ice.", veg=True),
    dish("Durian Sticky Rice", "Dessert", "12.99",
         "For the devoted: fresh durian with coconut sticky rice.", veg=True),
    dish("Thai Dessert Platter", "Dessert", "15.99",
         "A sharing plate of our sweets, chosen by you.", veg=True,
         sizes=[
             size("Serves 2", "15.99", order=1),
             size("Serves 4", "27.99", order=2),
         ],
         groups=[
             group("Choose three sweets",
                   [option("Mango sticky rice", order=1), option("Fried banana", order=2),
                    option("Tub tim krob", order=3), option("Lod chong", order=4),
                    option("Coconut ice cream", order=5), option("Durian sticky rice", "4.00", active=False, order=6)],
                   required=True, min_selection=3, max_selection=3, order=1),
         ]),
    dish("Coconut Pandan Waffle", "Dessert", "7.99",
         "Crisp pandan waffle with coconut custard.", veg=True,
         groups=[
             group("Add a scoop",
                   [option("Coconut ice cream", "2.50", countable=True, order=1),
                    option("Thai tea ice cream", "2.50", countable=True, order=2)],
                   max_selection=2, order=1),
         ], new_launch=True),
    dish("Black Sticky Rice Pudding", "Dessert", "6.79",
         "Warm black glutinous rice with salted coconut cream.", veg=True),

    # --- Pizza -------------------------------------------------------------
    # This category predates the Thai menu and its three existing items are
    # Italian. New ones lean Thai-influenced, which is what a Thai kitchen
    # running a pizza oven would actually serve.
    dish("Thai Basil Chicken Pizza", "Pizza", "17.99",
         "Holy basil chicken, chilli and mozzarella on a thin base.", veg=False, cuisine="Thai"),
    dish("Tom Yum Prawn Pizza", "Pizza", "19.49",
         "Tom yum cream base with prawns, mushroom and lemongrass.", veg=False, cuisine="Thai"),
    dish("Paneer Tikka Pizza", "Pizza", "16.49",
         "Spiced paneer, onion and capsicum on a tandoori base.", veg=True, cuisine="Italian"),
    dish("Four Cheese Pizza", "Pizza", "18.49",
         "Mozzarella, cheddar, parmesan and blue cheese.", veg=True, cuisine="Italian",
         sizes=[
             size("Small (8\")", "18.49", order=1),
             size("Medium (11\")", "22.99", order=2),
             size("Large (14\")", "27.49", order=3),
         ]),
    dish("Green Curry Pizza", "Pizza", "18.99",
         "Green curry base, chicken, Thai aubergine and coconut cream.", veg=False, cuisine="Thai",
         groups=[spice_level(required=False)]),
    dish("Veggie Garden Pizza", "Pizza", "15.99",
         "Sweetcorn, olives, peppers, red onion and rocket.", veg=True, cuisine="Italian",
         groups=[
             group("Extra toppings",
                   [option("Extra mozzarella", "2.00", countable=True, order=1),
                    option("Mushroom", "1.50", countable=True, order=2),
                    option("Jalapeno", "1.00", countable=True, order=3),
                    option("Sweetcorn", "1.00", countable=True, order=4),
                    option("Fresh basil", "0.75", order=5),
                    option("Truffle oil", "3.00", active=False, order=6)],
                   max_selection=6, order=2),
         ]),
    dish("Build Your Own Pizza", "Pizza", "14.99",
         "Choose the size, the crust and everything on top of it.", veg=True, cuisine="Italian",
         sizes=[
             # Crust options differ by size because a stuffed crust needs the
             # dough of a bigger base - the reason size-linked groups exist.
             size("Small (8\")", "14.99", order=1,
                  groups=[group("Crust",
                                [option("Thin crust", order=1), option("Classic hand tossed", order=2)],
                                single=True, required=True, order=1)]),
             size("Medium (11\")", "19.49", order=2,
                  groups=[group("Crust",
                                [option("Thin crust", order=1), option("Classic hand tossed", order=2),
                                 option("Cheese burst", "3.00", order=3)],
                                single=True, required=True, order=1)]),
             size("Large (14\")", "24.49", order=3,
                  groups=[group("Crust",
                                [option("Thin crust", order=1), option("Classic hand tossed", order=2),
                                 option("Cheese burst", "4.00", order=3),
                                 option("Stuffed garlic crust", "4.50", order=4)],
                                single=True, required=True, order=1)]),
         ],
         groups=[
             group("Sauce",
                   [option("Tomato", order=1), option("Green curry", "1.00", order=2),
                    option("Tom yum cream", "1.50", order=3), option("Garlic butter", order=4)],
                   single=True, required=True, order=2),
             group("Toppings",
                   [option("Mozzarella", "1.75", countable=True, order=1),
                    option("Chicken", "2.75", countable=True, order=2),
                    option("Prawns", "3.75", countable=True, order=3),
                    option("Tofu", "1.75", countable=True, order=4),
                    option("Mushroom", "1.50", countable=True, order=5),
                    option("Thai basil", "0.75", order=6),
                    option("Bird's eye chilli", "0.50", order=7)],
                   max_selection=7, order=3),
         ]),
    dish("Pepperoni Pizza", "Pizza", "17.49",
         "Cured pepperoni, mozzarella and oregano.", veg=False, cuisine="Italian"),

    # --- Appetizer ---------------------------------------------------------
    dish("Crispy Spring Rolls", "Appetizer", "7.99",
         "Vegetable spring rolls with sweet chilli dipping sauce.", veg=True),
    dish("Prawn Tempura", "Appetizer", "12.49",
         "Lightly battered tiger prawns with tamarind mayo.", veg=False),
    dish("Thai Fish Cakes", "Appetizer", "10.99",
         "Bouncy curried fish cakes with cucumber relish.", veg=False),
    dish("Corn Fritters", "Appetizer", "8.49",
         "Sweetcorn and kaffir lime fritters, fried until golden.", veg=True),
    dish("Chicken Wings", "Appetizer", "11.99",
         "Fried wings tossed in your choice of glaze.", veg=False,
         sizes=[
             size("6 wings", "11.99", order=1),
             size("12 wings", "20.99", order=2),
             size("Bucket (24)", "38.99", active=False, order=3),
         ],
         groups=[
             group("Glaze",
                   [option("Sweet chilli", order=1), option("Tamarind garlic", order=2),
                    option("Thai basil salt", order=3), option("Nam prik pao", "0.75", order=4)],
                   single=True, required=True, order=1),
             group("Dips",
                   [option("Sriracha mayo", "1.00", countable=True, order=1),
                    option("Peanut sauce", "1.25", countable=True, order=2),
                    option("Cucumber relish", "0.75", countable=True, order=3)],
                   max_selection=3, order=2),
         ]),
    dish("Money Bags", "Appetizer", "9.49",
         "Pastry parcels of minced chicken, water chestnut and corn.", veg=False),
    dish("Grilled Pork Skewers", "Appetizer", "11.49",
         "Charcoal-grilled pork with sticky rice and jaew dip.", veg=False,
         groups=[spice_level(required=False)]),
    dish("Tofu Satay", "Appetizer", "9.99",
         "Grilled marinated tofu skewers with peanut sauce.", veg=True,
         groups=[thai_addons()]),
    dish("Appetizer Sampler", "Appetizer", "18.99",
         "A shared board - pick what goes on it.", veg=False,
         sizes=[
             size("Board for 2", "18.99", order=1),
             size("Board for 4", "33.99", order=2),
         ],
         groups=[
             group("Choose four bites",
                   [option("Spring rolls", order=1), option("Corn fritters", order=2),
                    option("Fish cakes", "1.50", order=3), option("Chicken wings", "2.00", order=4),
                    option("Money bags", "1.50", order=5), option("Tofu satay", order=6),
                    option("Prawn tempura", "3.00", active=False, order=7)],
                   required=True, min_selection=4, max_selection=4, order=1),
         ]),
    dish("Roti Canai", "Appetizer", "6.49",
         "Flaky flatbread with a small bowl of curry sauce.", veg=True),

    # --- Salads ------------------------------------------------------------
    dish("Som Tum Papaya Salad", "Salads", "11.49",
         "Shredded green papaya pounded with lime, chilli and peanuts.", veg=True,
         groups=[spice_level()]),
    dish("Larb Gai", "Salads", "13.49",
         "Minced chicken salad with toasted rice powder and mint.", veg=False,
         groups=[spice_level()]),
    dish("Yum Woon Sen", "Salads", "13.99",
         "Glass noodle salad with prawns, minced pork and celery.", veg=False),
    dish("Cucumber Peanut Salad", "Salads", "8.99",
         "Cool cucumber ribbons with crushed peanuts and rice vinegar.", veg=True),
    dish("Pomelo Salad", "Salads", "12.99",
         "Pomelo segments with toasted coconut, shallots and chilli jam.", veg=True),
    dish("Grilled Beef Salad", "Salads", "16.49",
         "Seared beef with tomato, red onion and a lime dressing.", veg=False,
         groups=[spice_level(), garnishes()]),
    dish("Banana Blossom Salad", "Salads", "12.49",
         "Shredded banana blossom with coconut cream and crispy shallots.", veg=True),
    dish("Build Your Own Salad", "Salads", "10.99",
         "Choose the base, the protein and the dressing.", veg=True,
         sizes=[
             size("Regular", "10.99", order=1),
             size("Large", "14.49", order=2),
         ],
         groups=[
             group("Base",
                   [option("Green papaya", order=1), option("Glass noodle", order=2),
                    option("Mixed leaves", order=3), option("Pomelo", "1.50", order=4)],
                   single=True, required=True, order=1),
             protein_choice(),
             group("Dressing",
                   [option("Lime chilli", order=1), option("Peanut", order=2),
                    option("Tamarind", order=3), option("Chilli jam", "0.75", order=4)],
                   single=True, required=True, order=3),
             thai_addons(),
         ]),
    dish("Mango Avocado Salad", "Salads", "12.99",
         "Ripe mango and avocado with lime and toasted sesame.", veg=True, new_launch=True),
    dish("Crispy Duck Salad", "Salads", "17.99",
         "Shredded crispy duck with herbs, chilli and roasted rice.", veg=False),

    # --- Soup --------------------------------------------------------------
    dish("Tom Kha Gai", "Soup", "11.49",
         "Coconut galangal soup with chicken and mushroom.", veg=False),
    dish("Clear Tofu Soup", "Soup", "8.49",
         "Light broth with silken tofu, glass noodle and spring onion.", veg=True),
    dish("Wonton Soup", "Soup", "10.49",
         "Pork and prawn wontons in a clear chicken broth.", veg=False),
    dish("Pumpkin Coconut Soup", "Soup", "9.49",
         "Roast pumpkin blended with coconut milk and Thai basil oil.", veg=True),
    dish("Tom Yum Goong", "Soup", "13.99",
         "The classic hot and sour prawn soup with lemongrass.", veg=False,
         sizes=[
             size("Bowl", "13.99", order=1),
             size("Sharing pot", "24.99", order=2),
         ],
         groups=[spice_level()]),
    dish("Glass Noodle Chicken Soup", "Soup", "11.99",
         "Gaeng jued with glass noodles, chicken and napa cabbage.", veg=False,
         groups=[garnishes()]),
    dish("Spicy Seafood Soup", "Soup", "16.99",
         "Prawns, squid and mussels in a fiery lemongrass broth.", veg=False,
         groups=[spice_level(), thai_addons()]),
    dish("Sweetcorn Egg Drop Soup", "Soup", "8.99",
         "Silky sweetcorn broth with ribbons of egg.", veg=True),
    dish("Build Your Own Soup", "Soup", "10.49",
         "Pick the broth, the protein and the noodle.", veg=True,
         sizes=[
             size("Bowl", "10.49", order=1,
                  groups=[group("Broth",
                                [option("Clear", order=1), option("Tom yum", "1.00", order=2),
                                 option("Coconut galangal", "1.00", order=3)],
                                single=True, required=True, order=1)]),
             size("Sharing pot", "19.99", order=2,
                  groups=[group("Broth",
                                [option("Clear", order=1), option("Tom yum", "1.50", order=2),
                                 option("Coconut galangal", "1.50", order=3),
                                 option("Spicy seafood", "3.50", order=4)],
                                single=True, required=True, order=1)]),
         ],
         groups=[protein_choice(), spice_level(required=False)]),
    dish("Rice Soup with Pork", "Soup", "10.99",
         "Khao tom - comforting rice soup with minced pork and ginger.", veg=False),

    # --- Combo -------------------------------------------------------------
    dish("Pad Thai Lunch Combo", "Combo", "16.99",
         "Pad Thai, spring rolls and a Thai iced tea.", veg=True),
    dish("Curry & Rice Combo", "Combo", "17.49",
         "Any curry with jasmine rice and a soft drink.", veg=False,
         groups=[
             group("Choose your curry",
                   [option("Green chicken", order=1), option("Red tofu", order=2),
                    option("Yellow vegetable", order=3), option("Massaman beef", "2.50", order=4)],
                   single=True, required=True, order=1),
             spice_level(),
         ]),
    dish("Satay Starter Combo", "Combo", "15.49",
         "Chicken satay, papaya salad and a lemongrass iced tea.", veg=False),
    dish("Veg Bento Combo", "Combo", "15.99",
         "Tofu larb, morning glory, jasmine rice and a coconut cooler.", veg=True),
    dish("Date Night Combo", "Combo", "42.99",
         "Two mains, two sides, one dessert and two drinks.", veg=False,
         groups=[
             group("Choose two mains",
                   [option("Thai basil chicken", order=1), option("Cashew chicken", order=2),
                    option("Green curry", order=3), option("Pad see ew", order=4),
                    option("Garlic pepper prawns", "4.00", order=5)],
                   required=True, min_selection=2, max_selection=2, order=1),
             group("Choose one dessert",
                   [option("Mango sticky rice", order=1), option("Coconut ice cream", order=2),
                    option("Fried banana", order=3)],
                   single=True, required=True, order=2),
         ]),
    dish("Family Feast Combo", "Combo", "74.99",
         "Enough for four: three mains, rice, sides and desserts.", veg=False,
         sizes=[
             size("Serves 4", "74.99", order=1),
             size("Serves 6", "108.99", order=2),
             size("Serves 10 (catering)", "179.99", active=False, order=3),
         ],
         groups=[
             group("Choose three mains",
                   [option("Thai basil chicken", order=1), option("Massaman beef", "3.00", order=2),
                    option("Green curry chicken", order=3), option("Red curry tofu", order=4),
                    option("Cashew chicken", order=5), option("Crispy pork belly", "4.00", order=6)],
                   required=True, min_selection=3, max_selection=3, order=1),
             group("Add extras",
                   [option("Extra jasmine rice", "2.95", countable=True, order=1),
                    option("Extra prawn crackers", "2.50", countable=True, order=2),
                    option("Extra roti", "2.25", countable=True, order=3)],
                   max_selection=3, order=2),
             spice_level(),
         ]),
    dish("Student Lunch Combo", "Combo", "12.99",
         "A rice bowl, a spring roll and a soft drink.", veg=True,
         sizes=[
             size("Regular", "12.99", order=1),
             size("Large", "15.49", order=2),
         ]),
    dish("Soup & Salad Combo", "Combo", "14.49",
         "Tom yum soup with a green papaya salad.", veg=False,
         groups=[spice_level(required=False), garnishes()]),
    dish("Noodle Box Combo", "Combo", "16.49",
         "Any noodle box with a drink and prawn crackers.", veg=False,
         groups=[
             group("Choose your noodle box",
                   [option("Pad Thai", order=1), option("Pad see ew", order=2),
                    option("Drunken noodles", order=3), option("Khao soi", "1.50", order=4)],
                   single=True, required=True, order=1),
             protein_choice(),
         ]),
]


# --- the run ---------------------------------------------------------------


def resolve_target(db, *, branch: str | None) -> tuple[Restaurant, list[RestaurantLocation]]:
    """Bangkok Bowl, and every branch of it.

    All three branches already carry the same menu - 13, 12 and 13 items, the
    same dishes - because that is what a restaurant is. Adding a hundred dishes
    to one of them would leave the other two looking abandoned, so the default
    is every branch. `--branch` narrows it when that is genuinely what is wanted.

    Ordered by name rather than by item count: two branches were tied on count,
    and a tie broken by the database is a script that targets a different branch
    on different runs.
    """
    restaurant = db.scalar(select(Restaurant).where(Restaurant.name == RESTAURANT_NAME))
    if restaurant is None:
        raise SystemExit(f"No restaurant named {RESTAURANT_NAME!r}. Nothing was written.")

    query = select(RestaurantLocation).where(RestaurantLocation.restaurant_id == restaurant.id)
    if branch:
        query = query.where(RestaurantLocation.branch_name.ilike(f"%{branch}%"))
    locations = list(db.scalars(query.order_by(RestaurantLocation.branch_name)).all())
    if not locations:
        raise SystemExit(
            f"No matching branch for {RESTAURANT_NAME}"
            + (f" matching {branch!r}" if branch else "")
            + ". Nothing was written."
        )
    return restaurant, locations


def existing_names(db, *, restaurant_id, location_id) -> set[str]:
    """The dish names already on this branch, normalised.

    `lower(trim(...))` mirrors the duplicate rule in the bulk-create route, so
    a name this script considers taken is exactly one the admin API would
    refuse to create.
    """
    rows = db.scalars(
        select(func.lower(func.trim(MenuItem.name))).where(
            MenuItem.restaurant_id == restaurant_id,
            MenuItem.restaurant_location_id == location_id,
        )
    ).all()
    return set(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Seed menu items for {RESTAURANT_NAME} only.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write. Without it the run reports what it would do and rolls back.",
    )
    parser.add_argument(
        "--embed",
        action="store_true",
        help="Queue an embedding job per new item. Needs a Celery worker and an embedding model.",
    )
    parser.add_argument(
        "--branch",
        default=None,
        help="Only seed branches whose name contains this. Default: every branch.",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        restaurant, locations = resolve_target(db, branch=args.branch)
        print(f"Restaurant : {restaurant.name} ({restaurant.id})")
        print(f"Branches   : {len(locations)}\n")

        created: list[MenuItem] = []
        skipped = 0
        per_category: Counter[str] = Counter()

        for location in locations:
            taken = existing_names(db, restaurant_id=restaurant.id, location_id=location.id)
            made_here = 0
            for spec in CATALOGUE:
                if spec["name"].strip().lower() in taken:
                    skipped += 1
                    continue
                # Validation happens here: a bad group shape raises before
                # anything is added to the session, so a mistake in the
                # catalogue cannot leave a half-written menu behind.
                payload = MenuItemCreate(
                    restaurant_id=restaurant.id,
                    restaurant_location_id=location.id,
                    **spec,
                )
                menu_item = MenuItem(
                    restaurant_id=restaurant.id,
                    restaurant_location_id=location.id,
                    name=payload.name,
                    category=payload.category,
                    cuisine_type=payload.cuisine_type,
                    description=payload.description,
                    is_veg=payload.is_veg,
                    is_available=payload.is_available,
                    # Left False deliberately: bestseller is computed from real
                    # order history, not declared by a seed.
                    is_bestseller=False,
                    is_new_launch=payload.is_new_launch,
                )
                _sync_menu_item_customizations(menu_item, payload)
                db.add(menu_item)
                created.append(menu_item)
                per_category[payload.category] += 1
                made_here += 1
            print(f"  {location.branch_name:<32} had {len(taken):>3}, adding {made_here:>3}")

        verb = "Creating" if args.apply else "Would create"
        print(f"\n{verb} {len(created)} items across {len(locations)} branches; "
              f"skipping {skipped} already present.\n")
        for category, count in sorted(per_category.items()):
            print(f"  {category:<14} +{count}  ({count // len(locations)} per branch)")

        if not args.apply:
            db.rollback()
            print("\nDry run - nothing was written. Re-run with --apply to commit.")
            return

        db.commit()
        print(f"\nCommitted {len(created)} new menu items.")

        # The same follow-up work the admin API does after a create. Without it
        # the new dishes exist but the discovery and bestseller caches keep
        # serving the old menu until their TTL expires.
        from app.api.menu_items import (  # noqa: PLC0415 - only needed on the write path
            _invalidate_discovery_caches,
            _queue_embedding_job,
        )
        from app.services.generated_combos import refresh_generated_combo_availability
        from app.services.bestsellers import invalidate_bestseller_cache_for_locations

        _invalidate_discovery_caches()
        invalidate_bestseller_cache_for_locations([loc.id for loc in locations])
        for loc in locations:
            refresh_generated_combo_availability(
                db,
                restaurant_id=restaurant.id,
                restaurant_location_id=loc.id,
            )
        db.commit()
        print("Refreshed discovery, bestseller and combo-availability caches.")

        if args.embed:
            for menu_item in created:
                _queue_embedding_job(menu_item.id)
            print(f"Queued {len(created)} embedding jobs.")
        else:
            print("Embeddings not queued (pass --embed, or run scripts/backfill_embeddings.py).")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()

import os
import random
import sys
import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# Add the backend directory to Python path so 'app' can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from passlib.context import CryptContext

from app.config.database import SessionLocal
from app.services.app_clients import ensure_default_app_client
from app.models.chat_history import ChatHistory
from app.models.enums import (
    ChatMessageRole,
    LocationDayOfWeek,
    OrderStatus,
    OrderFulfillmentType,
    PaymentStatus,
    PersonalizedOfferAudience,
    PersonalizedOfferDiscountType,
    PersonalizedOfferState,
    PersonalizedOfferType,
    UserRole,
)
from app.models.location_fulfillment_slot import LocationFulfillmentSlot
from app.models.menu_item import MenuItem
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.personalized_offer import PersonalizedOffer
from app.models.restaurant import Restaurant
from app.models.restaurant_location import RestaurantLocation
from app.models.user import User
from app.models.user_preferences import UserPreferences
from app.services.personalized_offers import (
    invalidate_all_personalized_offer_caches,
    rebuild_generated_offers,
)
from app.services.recommendations import invalidate_all_recommendation_caches
from app.services.restaurant_locations import DEFAULT_BRANCH_NAME
from app.services.restaurant_locations import ensure_default_location_slots

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
RNG = random.Random(42)
MONEY_QUANT = Decimal("0.01")
ENABLE_PERSONALIZED_OFFERS_DEMO = os.getenv("SEED_PERSONALIZED_OFFERS_DEMO", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
ENABLE_PERSONALIZED_OFFERS_SAMPLE_CAMPAIGNS = os.getenv("SEED_PERSONALIZED_OFFERS_SAMPLE_CAMPAIGNS", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
WEEKDAY_KEYS = (
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
)


def money(value: str | float | int | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def clock(value: str) -> time:
    return time.fromisoformat(value)


def weekly_windows(**days: tuple[str, str]) -> dict[LocationDayOfWeek, tuple[time, time]]:
    return {
        LocationDayOfWeek[day_name]: (clock(start), clock(end))
        for day_name, (start, end) in days.items()
    }


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def generate_random_time(days_back: int = 30) -> datetime:
    now = datetime.now(timezone.utc)
    random_days = RNG.randint(0, days_back)
    return now - timedelta(days=random_days, hours=RNG.randint(0, 23), minutes=RNG.randint(0, 59))


def make_menu_seed(
    name: str,
    category: str,
    is_veg: bool,
    price: str,
    description: str,
    *,
    image_url: str | None = None,
    is_new_launch: bool = False,
) -> dict:
    return {
        "name": name,
        "category": category,
        "is_veg": is_veg,
        "price": money(price),
        "description": description,
        "image_url": image_url,
        "is_new_launch": is_new_launch,
    }


RESTAURANT_SEED_DATA = [
    {
        "name": "Spice Route Indian Kitchen",
        "slug": "spice-route",
        "cuisine_type": "Indian",
        "description": "Authentic North and South Indian cuisine.",
        "address_line_1": "Ground Floor, Shivalik Plaza, Navrangpura",
        "city": "Ahmedabad",
        "state": "Gujarat",
        "postal_code": "380009",
        "minimum_order_amount": money("15.00"),
        "delivery_fee": money("2.49"),
        "locations": [
            {
                "branch_name": "Spice Route Navrangpura",
                "address_line_1": "Shivalik Plaza, Near Xavier's Corner",
                "address_line_2": "Navrangpura",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "380009",
                "phone_number": "+91 79 4001 1101",
                "delivery_fee": money("1.99"),
                "minimum_order_amount": money("14.00"),
                "estimated_delivery_time": 24,
                "is_open": True,
                "is_active": True,
                "price_delta": money("0.00"),
                "unavailable": {"Mutton Rogan Josh"},
                "extras": [
                    make_menu_seed("Kathiyawadi Paneer Bowl", "Main Course", True, "13.79", "Smoky paneer with garlic millet khichdi.", is_new_launch=True),
                    make_menu_seed("Cheese Garlic Naan", "Breads", True, "4.49", "Soft naan topped with garlic butter and cheese."),
                ],
            },
            {
                "branch_name": "Spice Route Maninagar",
                "address_line_1": "First Floor, Radhe Avenue, Maninagar",
                "address_line_2": "Near Kankaria Gate 5",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "380008",
                "phone_number": "+91 79 4001 1102",
                "delivery_fee": money("2.49"),
                "minimum_order_amount": money("15.00"),
                "estimated_delivery_time": 28,
                "is_open": True,
                "is_active": True,
                "price_delta": money("0.50"),
                "unavailable": {"Family Biryani Combo"},
                "extras": [
                    make_menu_seed("Hyderabadi Chicken Biryani", "Rice", False, "15.49", "Layered chicken biryani finished with saffron rice."),
                    make_menu_seed("Anda Ghotala Kathi Roll", "Rolls", False, "9.49", "Spiced egg bhurji roll with onion lachha."),
                ],
            },
            {
                "branch_name": "Spice Route Bopal",
                "address_line_1": "Shop 12, Maple Trade Center, Bopal",
                "address_line_2": "South Bopal",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "380058",
                "phone_number": "+91 79 4001 1103",
                "delivery_fee": money("2.99"),
                "minimum_order_amount": money("16.00"),
                "estimated_delivery_time": 34,
                "is_open": False,
                "is_active": True,
                "price_delta": money("0.75"),
                "unavailable": {"Chicken Tikka"},
                "excluded": {"Mutton Rogan Josh"},
                "extras": [
                    make_menu_seed("Millet Khichdi Bowl", "Healthy Bowls", True, "11.49", "Comforting millet khichdi with roasted peanuts and tadka."),
                    make_menu_seed("Tandoori Broccoli", "Appetizer", True, "9.79", "Charred broccoli florets with hung curd marinade."),
                ],
            },
        ],
        "base_menu": [
            make_menu_seed("Butter Chicken", "Main Course", False, "14.99", "Creamy tomato curry with tender chicken."),
            make_menu_seed("Paneer Tikka Masala", "Main Course", True, "12.99", "Grilled cottage cheese in spiced gravy."),
            make_menu_seed("Garlic Naan", "Breads", True, "3.99", "Soft flatbread with garlic and butter."),
            make_menu_seed("Vegetable Biryani", "Rice", True, "11.99", "Fragrant basmati rice with mixed vegetables."),
            make_menu_seed("Samosa (2 pcs)", "Appetizer", True, "5.99", "Crispy pastry filled with spiced potatoes."),
            make_menu_seed("Chicken Tikka", "Appetizer", False, "11.49", "Char-grilled chicken marinated with yogurt and spices."),
            make_menu_seed("Mutton Rogan Josh", "Main Course", False, "16.99", "Slow-cooked mutton curry with Kashmiri spices."),
            make_menu_seed("Paneer Butter Masala", "Main Course", True, "13.49", "Paneer cubes simmered in a buttery tomato sauce."),
            make_menu_seed("Family Biryani Combo", "Combo", False, "18.99", "Chicken biryani with raita, kebab, and a cold drink."),
            make_menu_seed("Masala Cola", "Beverages", True, "2.49", "Chilled cola with a hint of masala spice."),
            make_menu_seed("Sweet Lassi", "Beverages", True, "3.49", "Traditional yogurt drink served cold."),
        ],
    },
    {
        "name": "Luigi's Italian Trattoria",
        "slug": "luigis-italian",
        "cuisine_type": "Italian",
        "description": "Homemade pasta and wood-fired pizzas.",
        "address_line_1": "8 Riverfront Arcade, Downtown",
        "city": "Ahmedabad",
        "state": "Gujarat",
        "postal_code": "380006",
        "minimum_order_amount": money("15.00"),
        "delivery_fee": money("2.79"),
        "locations": [
            {
                "branch_name": "Luigi's Italian Trattoria Downtown",
                "address_line_1": "Riverfront Arcade, C.G. Road Connector",
                "address_line_2": "Downtown",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "380006",
                "phone_number": "+91 79 4010 2201",
                "delivery_fee": money("2.29"),
                "minimum_order_amount": money("15.00"),
                "estimated_delivery_time": 22,
                "is_open": True,
                "is_active": True,
                "price_delta": money("0.00"),
                "unavailable": {"Lasagna Combo"},
                "extras": [
                    make_menu_seed("Truffle Mushroom Pizza", "Pizza", True, "18.99", "White sauce pizza with mushrooms and truffle oil.", is_new_launch=True),
                    make_menu_seed("Burrata Caprese", "Appetizer", True, "10.79", "Tomato, basil, pesto, and creamy burrata."),
                ],
            },
            {
                "branch_name": "Luigi's Italian Trattoria Riverside",
                "address_line_1": "Riverside Promenade, Sabarmati Riverfront",
                "address_line_2": "Riverside",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "380015",
                "phone_number": "+91 79 4010 2202",
                "delivery_fee": money("2.99"),
                "minimum_order_amount": money("16.00"),
                "estimated_delivery_time": 29,
                "is_open": True,
                "is_active": True,
                "price_delta": money("0.50"),
                "unavailable": {"Pepperoni Pizza"},
                "extras": [
                    make_menu_seed("Pesto Genovese Pasta", "Pasta", True, "15.79", "Basil pesto pasta with toasted pine nuts."),
                    make_menu_seed("Lemon Herb Bruschetta", "Appetizer", True, "7.49", "Tomato bruschetta finished with lemon zest."),
                ],
            },
            {
                "branch_name": "Luigi's Italian Trattoria Airport Road",
                "address_line_1": "Sunrise Business Park, Airport Road",
                "address_line_2": "Hansol",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "382475",
                "phone_number": "+91 79 4010 2203",
                "delivery_fee": money("3.49"),
                "minimum_order_amount": money("17.00"),
                "estimated_delivery_time": 35,
                "is_open": False,
                "is_active": True,
                "price_delta": money("0.75"),
                "excluded": {"Spaghetti Carbonara"},
                "extras": [
                    make_menu_seed("Calzone Classico", "Pizza", False, "17.99", "Folded wood-fired calzone with mozzarella and chicken salami."),
                    make_menu_seed("Espresso Tiramisu Jar", "Dessert", True, "8.49", "Single-serve tiramisu layered in a jar."),
                ],
            },
        ],
        "base_menu": [
            make_menu_seed("Margherita Pizza", "Pizza", True, "16.99", "Classic cheese and tomato pizza with fresh basil."),
            make_menu_seed("Spaghetti Carbonara", "Pasta", False, "15.99", "Pasta with creamy egg sauce, pancetta, and parmesan."),
            make_menu_seed("Tiramisu", "Dessert", True, "7.99", "Coffee-flavored Italian dessert."),
            make_menu_seed("Garlic Bread", "Appetizer", True, "6.99", "Toasted bread with garlic butter and herbs."),
            make_menu_seed("Fettuccine Alfredo", "Pasta", True, "14.99", "Fettuccine pasta tossed with butter and parmesan cheese."),
            make_menu_seed("Pepperoni Pizza", "Pizza", False, "18.49", "Wood-fired pizza topped with pepperoni and mozzarella."),
            make_menu_seed("Farmhouse Veg Pizza", "Pizza", True, "17.49", "Loaded pizza with bell peppers, olives, onion, and mushrooms."),
            make_menu_seed("Penne Arrabbiata", "Pasta", True, "13.99", "Penne pasta in a spicy tomato and garlic sauce."),
            make_menu_seed("Lasagna Combo", "Combo", False, "19.49", "Chicken lasagna served with garlic bread and a drink."),
            make_menu_seed("Iced Lemon Soda", "Beverages", True, "2.99", "Fresh sparkling lemon soda served chilled."),
        ],
    },
    {
        "name": "Dragon Wok",
        "slug": "dragon-wok",
        "cuisine_type": "Chinese",
        "description": "Delicious dim sum and stir-fried noodles.",
        "address_line_1": "12 Commerce Avenue, C.G. Road",
        "city": "Ahmedabad",
        "state": "Gujarat",
        "postal_code": "380006",
        "minimum_order_amount": money("14.00"),
        "delivery_fee": money("2.19"),
        "locations": [
            {
                "branch_name": "Dragon Wok CG Road",
                "address_line_1": "Commerce Avenue, C.G. Road",
                "address_line_2": "Navrangpura",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "380006",
                "phone_number": "+91 79 4022 3301",
                "delivery_fee": money("1.99"),
                "minimum_order_amount": money("14.00"),
                "estimated_delivery_time": 21,
                "is_open": True,
                "is_active": True,
                "price_delta": money("0.00"),
                "unavailable": {"Sweet and Sour Pork"},
                "extras": [
                    make_menu_seed("Crispy Corn Chilli Pepper", "Appetizer", True, "8.99", "Golden fried corn tossed in chilli garlic.", is_new_launch=True),
                    make_menu_seed("Black Pepper Chicken Bao", "Bao", False, "9.49", "Steamed bao buns stuffed with pepper chicken."),
                ],
            },
            {
                "branch_name": "Dragon Wok Satellite",
                "address_line_1": "Shops at Prerna Circle, Satellite",
                "address_line_2": "Jodhpur",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "380015",
                "phone_number": "+91 79 4022 3302",
                "delivery_fee": money("2.49"),
                "minimum_order_amount": money("15.00"),
                "estimated_delivery_time": 26,
                "is_open": True,
                "is_active": True,
                "price_delta": money("0.40"),
                "unavailable": {"Pork Dumplings (6 pcs)"},
                "extras": [
                    make_menu_seed("Burnt Garlic Veg Fried Rice", "Rice", True, "11.79", "Fried rice loaded with burnt garlic and vegetables."),
                    make_menu_seed("Chilli Chicken Dry", "Main Course", False, "14.79", "Spicy chilli chicken with peppers and onions."),
                ],
            },
            {
                "branch_name": "Dragon Wok SG Highway",
                "address_line_1": "Skyline Hub, SG Highway",
                "address_line_2": "Bodakdev",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "380054",
                "phone_number": "+91 79 4022 3303",
                "delivery_fee": money("2.99"),
                "minimum_order_amount": money("16.00"),
                "estimated_delivery_time": 32,
                "is_open": False,
                "is_active": True,
                "price_delta": money("0.70"),
                "excluded": {"Schezwan Veg Momos (6 pcs)"},
                "extras": [
                    make_menu_seed("Shanghai Fish in Chilli Broth", "Main Course", False, "16.29", "Tender fish fillets in a fragrant chilli broth."),
                    make_menu_seed("Sesame Honey Noodles", "Noodles", True, "12.39", "Sweet-savoury noodles topped with sesame crunch."),
                ],
            },
        ],
        "base_menu": [
            make_menu_seed("Kung Pao Chicken", "Main Course", False, "13.99", "Spicy stir-fried chicken with peanuts and vegetables."),
            make_menu_seed("Vegetable Spring Rolls (4 pcs)", "Appetizer", True, "6.99", "Crispy rolls filled with cabbage, carrots, and glass noodles."),
            make_menu_seed("Pork Dumplings (6 pcs)", "Dim Sum", False, "8.99", "Steamed or pan-fried pork dumplings."),
            make_menu_seed("Fried Rice", "Rice", True, "10.99", "Stir-fried rice with egg, peas, and carrots."),
            make_menu_seed("Sweet and Sour Pork", "Main Course", False, "14.99", "Deep-fried pork in sweet and sour sauce."),
            make_menu_seed("Chicken Hakka Noodles", "Noodles", False, "12.99", "Wok-tossed noodles with chicken and crunchy vegetables."),
            make_menu_seed("Schezwan Veg Momos (6 pcs)", "Momos", True, "8.49", "Veg momos tossed in spicy schezwan sauce."),
            make_menu_seed("Wok Meal Combo", "Combo", False, "16.49", "Hakka noodles, chicken gravy, and a canned drink."),
            make_menu_seed("Lychee Iced Tea", "Beverages", True, "3.49", "Refreshing iced tea with lychee flavor."),
        ],
    },
    {
        "name": "Bangkok Bowl",
        "slug": "bangkok-bowl",
        "cuisine_type": "Thai",
        "description": "Bright Thai curries, noodles, rice bowls, and chilled drinks.",
        "address_line_1": "33 Palm Court, Ellisbridge",
        "city": "Ahmedabad",
        "state": "Gujarat",
        "postal_code": "380009",
        "minimum_order_amount": money("15.00"),
        "delivery_fee": money("2.69"),
        "locations": [
            {
                "branch_name": "Bangkok Bowl Ellisbridge",
                "address_line_1": "Palm Court, Ellisbridge",
                "address_line_2": "Opp. Law Garden",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "380009",
                "phone_number": "+91 79 4033 4401",
                "delivery_fee": money("2.19"),
                "minimum_order_amount": money("15.00"),
                "estimated_delivery_time": 23,
                "is_open": True,
                "is_active": True,
                "price_delta": money("0.00"),
                "extras": [
                    make_menu_seed("Thai Mango Salad", "Salads", True, "8.99", "Crunchy raw mango salad with chilli-lime dressing.", is_new_launch=True),
                    make_menu_seed("Lemongrass Chicken Skewers", "Appetizer", False, "10.49", "Grilled chicken skewers glazed with lemongrass."),
                ],
            },
            {
                "branch_name": "Bangkok Bowl Bodakdev",
                "address_line_1": "One42 Street, Bodakdev",
                "address_line_2": "Near SG Highway",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "380054",
                "phone_number": "+91 79 4033 4402",
                "delivery_fee": money("2.79"),
                "minimum_order_amount": money("16.00"),
                "estimated_delivery_time": 29,
                "is_open": True,
                "is_active": True,
                "price_delta": money("0.35"),
                "unavailable": {"Tom Yum Soup"},
                "extras": [
                    make_menu_seed("Thai Chilli Basil Rice", "Rice", False, "13.99", "Minced chicken and basil served over jasmine rice."),
                    make_menu_seed("Coconut Pandan Pudding", "Dessert", True, "5.99", "Chilled coconut pudding infused with pandan."),
                ],
            },
            {
                "branch_name": "Bangkok Bowl Science City",
                "address_line_1": "Galaxy Retail Park, Science City Road",
                "address_line_2": "Sola",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "380060",
                "phone_number": "+91 79 4033 4403",
                "delivery_fee": money("3.19"),
                "minimum_order_amount": money("16.50"),
                "estimated_delivery_time": 33,
                "is_open": False,
                "is_active": True,
                "price_delta": money("0.60"),
                "excluded": {"Green Curry Chicken"},
                "extras": [
                    make_menu_seed("Bangkok Street Satay", "Appetizer", False, "11.49", "Chicken satay with creamy peanut dip."),
                    make_menu_seed("Tofu Cashew Stir Fry", "Main Course", True, "14.19", "Tofu and cashews stir-fried in a savoury glaze."),
                ],
            },
        ],
        "base_menu": [
            make_menu_seed("Pad Thai Veg", "Noodles", True, "13.49", "Rice noodles with tamarind sauce, tofu, peanuts, and bean sprouts."),
            make_menu_seed("Thai Basil Chicken", "Main Course", False, "14.49", "Minced chicken stir-fried with basil, chilli, and garlic."),
            make_menu_seed("Green Curry Chicken", "Curry", False, "15.49", "Thai green curry with chicken, coconut milk, and vegetables."),
            make_menu_seed("Red Curry Tofu", "Curry", True, "14.29", "Tofu simmered in red curry with Thai herbs."),
            make_menu_seed("Tom Yum Soup", "Soup", False, "9.49", "Tangy and spicy Thai soup with mushrooms and chicken."),
            make_menu_seed("Thai Combo Box", "Combo", False, "17.99", "Thai basil chicken, jasmine rice, and Thai iced tea."),
            make_menu_seed("Thai Iced Tea", "Beverages", True, "3.79", "Sweet chilled Thai milk tea."),
            make_menu_seed("Coconut Cooler", "Beverages", True, "3.29", "Light coconut drink served over ice."),
        ],
    },
    {
        "name": "Momo Mountain",
        "slug": "momo-mountain",
        "cuisine_type": "Tibetan",
        "description": "Steamed momos, thukpa bowls, snacks, and combo platters.",
        "address_line_1": "15 Summit Square, Thaltej",
        "city": "Ahmedabad",
        "state": "Gujarat",
        "postal_code": "380059",
        "minimum_order_amount": money("13.00"),
        "delivery_fee": money("2.39"),
        "locations": [
            {
                "branch_name": "Momo Mountain Gota",
                "address_line_1": "Hilltop Corner, Gota",
                "address_line_2": "Near Vandematram Circle",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "382481",
                "phone_number": "+91 79 4044 5501",
                "delivery_fee": money("2.19"),
                "minimum_order_amount": money("13.00"),
                "estimated_delivery_time": 22,
                "is_open": True,
                "is_active": True,
                "price_delta": money("0.00"),
                "unavailable": {"Paneer Chilli Momos (8 pcs)"},
                "extras": [
                    make_menu_seed("Cheese Corn Momos (8 pcs)", "Momos", True, "9.79", "Steamed momos filled with cheese and sweet corn.", is_new_launch=True),
                    make_menu_seed("Smoked Chilli Fries", "Sides", True, "5.79", "Crispy fries dusted with Himalayan chilli."),
                ],
            },
            {
                "branch_name": "Momo Mountain Thaltej",
                "address_line_1": "Summit Square, Thaltej",
                "address_line_2": "Near Zydus Junction",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "380059",
                "phone_number": "+91 79 4044 5502",
                "delivery_fee": money("2.59"),
                "minimum_order_amount": money("13.50"),
                "estimated_delivery_time": 26,
                "is_open": True,
                "is_active": True,
                "price_delta": money("0.35"),
                "extras": [
                    make_menu_seed("Jhol Momos (6 pcs)", "Momos", False, "10.49", "Steamed momos served in spicy Nepali broth."),
                    make_menu_seed("Veg Thenthuk", "Soup", True, "11.19", "Flat noodle soup with mountain herbs and vegetables."),
                ],
            },
            {
                "branch_name": "Momo Mountain Chandkheda",
                "address_line_1": "North Plaza, Chandkheda",
                "address_line_2": "Near IOC Circle",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "382424",
                "phone_number": "+91 79 4044 5503",
                "delivery_fee": money("2.89"),
                "minimum_order_amount": money("14.00"),
                "estimated_delivery_time": 31,
                "is_open": False,
                "is_active": True,
                "price_delta": money("0.55"),
                "excluded": {"Chicken Thukpa"},
                "extras": [
                    make_menu_seed("Buff Chilli Momos (8 pcs)", "Momos", False, "11.29", "Pan-tossed momos coated in smoky chilli sauce."),
                    make_menu_seed("Butter Tea", "Beverages", True, "3.19", "Warm Himalayan butter tea."),
                ],
            },
        ],
        "base_menu": [
            make_menu_seed("Chicken Momos (8 pcs)", "Momos", False, "9.99", "Steamed momos stuffed with juicy minced chicken."),
            make_menu_seed("Veg Momos (8 pcs)", "Momos", True, "8.99", "Steamed dumplings filled with cabbage, carrot, and herbs."),
            make_menu_seed("Fried Chicken Momos (8 pcs)", "Momos", False, "10.99", "Crisp-fried chicken momos served with spicy chutney."),
            make_menu_seed("Paneer Chilli Momos (8 pcs)", "Momos", True, "10.49", "Momos tossed in a spicy paneer chilli sauce."),
            make_menu_seed("Chicken Thukpa", "Soup", False, "11.99", "Warm noodle soup with chicken and Himalayan spices."),
            make_menu_seed("Momo Meal Combo", "Combo", False, "13.99", "Chicken momos, fries, and a cold drink."),
            make_menu_seed("Peach Soda", "Beverages", True, "2.79", "Chilled peach-flavoured sparkling drink."),
        ],
    },
    {
        "name": "Stacked Grill House",
        "slug": "stacked-grill-house",
        "cuisine_type": "American",
        "description": "Loaded burgers, fried sides, combos, wings, and cold drinks.",
        "address_line_1": "17 Yardhouse Lane, Prahlad Nagar",
        "city": "Ahmedabad",
        "state": "Gujarat",
        "postal_code": "380015",
        "minimum_order_amount": money("14.00"),
        "delivery_fee": money("2.59"),
        "locations": [
            {
                "branch_name": "Stacked Grill House Prahlad Nagar",
                "address_line_1": "Yardhouse Lane, Prahlad Nagar",
                "address_line_2": "Near AUDA Garden",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "380015",
                "phone_number": "+91 79 4055 6601",
                "delivery_fee": money("2.19"),
                "minimum_order_amount": money("14.00"),
                "estimated_delivery_time": 24,
                "is_open": True,
                "is_active": True,
                "price_delta": money("0.00"),
                "extras": [
                    make_menu_seed("Cheese Burger", "Burger", False, "12.79", "Juicy beef burger layered with cheddar cheese."),
                    make_menu_seed("Cajun Fries", "Sides", True, "5.49", "Crispy fries tossed in cajun seasoning."),
                ],
            },
            {
                "branch_name": "Stacked Grill House Sindhu Bhavan",
                "address_line_1": "Food Square, Sindhu Bhavan Road",
                "address_line_2": "Bodakdev",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "380054",
                "phone_number": "+91 79 4055 6602",
                "delivery_fee": money("2.79"),
                "minimum_order_amount": money("15.00"),
                "estimated_delivery_time": 27,
                "is_open": True,
                "is_active": True,
                "price_delta": money("0.45"),
                "unavailable": {"Mint Lime Fizz"},
                "extras": [
                    make_menu_seed("Nashville Hot Chicken Burger", "Burger", False, "13.99", "Crispy chicken burger with Nashville hot glaze."),
                    make_menu_seed("Smoked Onion Rings", "Sides", True, "6.29", "Beer-battered onion rings with smoky dip."),
                ],
            },
            {
                "branch_name": "Stacked Grill House Motera",
                "address_line_1": "Victory Mall, Motera",
                "address_line_2": "Near Stadium Road",
                "city": "Ahmedabad",
                "state": "Gujarat",
                "postal_code": "380005",
                "phone_number": "+91 79 4055 6603",
                "delivery_fee": money("3.09"),
                "minimum_order_amount": money("15.50"),
                "estimated_delivery_time": 33,
                "is_open": False,
                "is_active": True,
                "price_delta": money("0.70"),
                "excluded": {"Peri Peri Chicken Wings"},
                "extras": [
                    make_menu_seed("BBQ Double Stack", "Burger", False, "15.49", "Double patty burger with smoky barbecue glaze."),
                    make_menu_seed("Cookie Cream Shake", "Beverages", True, "4.99", "Milkshake blended with chocolate cookies."),
                ],
            },
        ],
        "base_menu": [
            make_menu_seed("Classic Chicken Burger", "Burger", False, "11.99", "Grilled chicken patty burger with lettuce and house sauce."),
            make_menu_seed("Smoky Beef Burger", "Burger", False, "13.99", "Beef burger with smoked cheese, onion, and pickles."),
            make_menu_seed("Crispy Veg Burger", "Burger", True, "10.49", "Crunchy veg patty burger with tomato and mayo."),
            make_menu_seed("Peri Peri Chicken Wings", "Non-Veg", False, "12.49", "Spicy grilled chicken wings with peri peri seasoning."),
            make_menu_seed("Loaded Burger Combo", "Combo", False, "16.99", "Chicken burger, fries, and cola."),
            make_menu_seed("Double Patty Burger Combo", "Combo", False, "18.49", "Double patty burger with wedges and a soft drink."),
            make_menu_seed("Chocolate Shake", "Beverages", True, "4.29", "Cold chocolate milkshake."),
            make_menu_seed("Mint Lime Fizz", "Beverages", True, "2.99", "Refreshing mint and lime cooler."),
        ],
    },
]

LOCATION_SCHEDULE_CONFIG: dict[str, dict] = {
    "Spice Route Navrangpura": {
        "estimated_delivery_time": 24,
        "estimated_pickup_time": 18,
        "preparation_time_minutes": 16,
        "delivery": weekly_windows(
            MONDAY=("10:30", "22:00"),
            TUESDAY=("11:00", "21:30"),
            WEDNESDAY=("10:00", "22:30"),
            THURSDAY=("10:30", "22:00"),
            FRIDAY=("10:30", "23:00"),
            SATURDAY=("09:30", "23:30"),
            SUNDAY=("09:30", "21:30"),
        ),
        "pickup": weekly_windows(
            MONDAY=("10:00", "22:30"),
            TUESDAY=("10:30", "22:00"),
            WEDNESDAY=("09:30", "23:00"),
            THURSDAY=("10:00", "22:30"),
            FRIDAY=("10:00", "23:30"),
            SATURDAY=("09:00", "23:30"),
            SUNDAY=("09:00", "22:00"),
        ),
    },
    "Spice Route Maninagar": {
        "estimated_delivery_time": 28,
        "estimated_pickup_time": 20,
        "preparation_time_minutes": 18,
        "delivery": weekly_windows(
            MONDAY=("10:00", "21:30"),
            TUESDAY=("10:30", "21:00"),
            WEDNESDAY=("10:00", "22:00"),
            THURSDAY=("10:30", "21:30"),
            FRIDAY=("10:30", "22:30"),
            SATURDAY=("09:30", "23:00"),
            SUNDAY=("09:30", "21:00"),
        ),
        "pickup": weekly_windows(
            MONDAY=("09:30", "22:00"),
            TUESDAY=("10:00", "21:30"),
            WEDNESDAY=("09:30", "22:30"),
            THURSDAY=("10:00", "22:00"),
            FRIDAY=("10:00", "23:00"),
            SATURDAY=("09:00", "23:30"),
            SUNDAY=("09:00", "21:30"),
        ),
    },
    "Spice Route Bopal": {
        "estimated_delivery_time": 34,
        "estimated_pickup_time": 22,
        "preparation_time_minutes": 20,
        "delivery": weekly_windows(
            MONDAY=("11:00", "21:30"),
            TUESDAY=("11:30", "21:00"),
            WEDNESDAY=("11:00", "22:00"),
            THURSDAY=("11:00", "21:30"),
            FRIDAY=("11:00", "22:30"),
            SATURDAY=("10:00", "23:00"),
            SUNDAY=("10:00", "21:00"),
        ),
        "pickup": weekly_windows(
            MONDAY=("10:30", "22:00"),
            TUESDAY=("11:00", "21:30"),
            WEDNESDAY=("10:30", "22:30"),
            THURSDAY=("10:30", "22:00"),
            FRIDAY=("10:30", "23:00"),
            SATURDAY=("09:30", "23:30"),
            SUNDAY=("09:30", "21:30"),
        ),
    },
    "Luigi's Italian Trattoria Downtown": {
        "estimated_delivery_time": 22,
        "estimated_pickup_time": 17,
        "preparation_time_minutes": 16,
        "delivery": weekly_windows(
            MONDAY=("10:30", "22:00"),
            TUESDAY=("11:00", "21:30"),
            WEDNESDAY=("10:30", "22:00"),
            THURSDAY=("10:30", "22:30"),
            FRIDAY=("10:30", "23:00"),
            SATURDAY=("10:00", "23:30"),
            SUNDAY=("10:00", "21:30"),
        ),
        "pickup": weekly_windows(
            MONDAY=("10:00", "22:30"),
            TUESDAY=("10:30", "22:00"),
            WEDNESDAY=("10:00", "22:30"),
            THURSDAY=("10:00", "23:00"),
            FRIDAY=("10:00", "23:30"),
            SATURDAY=("09:30", "23:30"),
            SUNDAY=("09:30", "22:00"),
        ),
    },
    "Luigi's Italian Trattoria Riverside": {
        "estimated_delivery_time": 29,
        "estimated_pickup_time": 18,
        "preparation_time_minutes": 17,
        "delivery": weekly_windows(
            MONDAY=("09:00", "21:00"),
            TUESDAY=("09:30", "20:30"),
            WEDNESDAY=("09:00", "21:30"),
            THURSDAY=("09:30", "21:00"),
            FRIDAY=("09:30", "22:00"),
            SATURDAY=("08:30", "22:30"),
            SUNDAY=("08:30", "20:30"),
        ),
        "pickup": weekly_windows(
            MONDAY=("08:30", "21:30"),
            TUESDAY=("09:00", "21:00"),
            WEDNESDAY=("08:30", "22:00"),
            THURSDAY=("09:00", "21:30"),
            FRIDAY=("09:00", "22:30"),
            SATURDAY=("08:00", "23:00"),
            SUNDAY=("08:00", "21:00"),
        ),
    },
    "Luigi's Italian Trattoria Airport Road": {
        "estimated_delivery_time": 35,
        "estimated_pickup_time": 21,
        "preparation_time_minutes": 19,
        "delivery": weekly_windows(
            MONDAY=("11:00", "21:30"),
            TUESDAY=("11:30", "21:00"),
            WEDNESDAY=("11:00", "22:00"),
            THURSDAY=("11:00", "21:30"),
            FRIDAY=("11:00", "22:30"),
            SATURDAY=("10:30", "23:00"),
            SUNDAY=("10:30", "21:00"),
        ),
        "pickup": weekly_windows(
            MONDAY=("10:30", "22:00"),
            TUESDAY=("11:00", "21:30"),
            WEDNESDAY=("10:30", "22:30"),
            THURSDAY=("10:30", "22:00"),
            FRIDAY=("10:30", "23:00"),
            SATURDAY=("10:00", "23:30"),
            SUNDAY=("10:00", "21:30"),
        ),
    },
    "Dragon Wok CG Road": {
        "estimated_delivery_time": 21,
        "estimated_pickup_time": 17,
        "preparation_time_minutes": 15,
        "delivery": weekly_windows(
            MONDAY=("11:00", "23:00"),
            TUESDAY=("11:30", "22:30"),
            WEDNESDAY=("11:00", "23:00"),
            THURSDAY=("11:00", "23:00"),
            FRIDAY=("11:00", "23:30"),
            SATURDAY=("10:30", "23:30"),
            SUNDAY=("10:30", "22:30"),
        ),
        "pickup": weekly_windows(
            MONDAY=("10:30", "23:30"),
            TUESDAY=("11:00", "23:00"),
            WEDNESDAY=("10:30", "23:30"),
            THURSDAY=("10:30", "23:30"),
            FRIDAY=("10:30", "23:30"),
            SATURDAY=("10:00", "23:30"),
            SUNDAY=("10:00", "23:00"),
        ),
    },
    "Dragon Wok Satellite": {
        "estimated_delivery_time": 26,
        "estimated_pickup_time": 18,
        "preparation_time_minutes": 17,
        "delivery": weekly_windows(
            MONDAY=("10:30", "22:30"),
            TUESDAY=("11:00", "22:00"),
            WEDNESDAY=("10:30", "22:30"),
            THURSDAY=("10:30", "22:30"),
            FRIDAY=("10:30", "23:00"),
            SATURDAY=("10:00", "23:30"),
            SUNDAY=("10:00", "22:00"),
        ),
        "pickup": weekly_windows(
            MONDAY=("10:00", "23:00"),
            TUESDAY=("10:30", "22:30"),
            WEDNESDAY=("10:00", "23:00"),
            THURSDAY=("10:00", "23:00"),
            FRIDAY=("10:00", "23:30"),
            SATURDAY=("09:30", "23:30"),
            SUNDAY=("09:30", "22:30"),
        ),
    },
    "Dragon Wok SG Highway": {
        "estimated_delivery_time": 32,
        "estimated_pickup_time": 20,
        "preparation_time_minutes": 18,
        "delivery": weekly_windows(
            MONDAY=("12:00", "22:00"),
            TUESDAY=("12:00", "21:30"),
            WEDNESDAY=("11:30", "22:30"),
            THURSDAY=("12:00", "22:00"),
            FRIDAY=("12:00", "23:00"),
            SATURDAY=("11:30", "23:30"),
            SUNDAY=("11:30", "21:30"),
        ),
        "pickup": weekly_windows(
            MONDAY=("11:30", "22:30"),
            TUESDAY=("11:30", "22:00"),
            WEDNESDAY=("11:00", "23:00"),
            THURSDAY=("11:30", "22:30"),
            FRIDAY=("11:30", "23:30"),
            SATURDAY=("11:00", "23:30"),
            SUNDAY=("11:00", "22:00"),
        ),
    },
    "Bangkok Bowl Ellisbridge": {
        "estimated_delivery_time": 23,
        "estimated_pickup_time": 18,
        "preparation_time_minutes": 16,
        "delivery": weekly_windows(
            MONDAY=("12:00", "22:00"),
            TUESDAY=("12:00", "21:30"),
            WEDNESDAY=("11:30", "22:00"),
            THURSDAY=("12:00", "22:00"),
            FRIDAY=("12:00", "22:30"),
            SATURDAY=("11:00", "23:00"),
            SUNDAY=("11:00", "21:30"),
        ),
        "pickup": weekly_windows(
            MONDAY=("11:30", "22:30"),
            TUESDAY=("11:30", "22:00"),
            WEDNESDAY=("11:00", "22:30"),
            THURSDAY=("11:30", "22:30"),
            FRIDAY=("11:30", "23:00"),
            SATURDAY=("10:30", "23:30"),
            SUNDAY=("10:30", "22:00"),
        ),
    },
    "Bangkok Bowl Bodakdev": {
        "estimated_delivery_time": 29,
        "estimated_pickup_time": 19,
        "preparation_time_minutes": 17,
        "delivery": weekly_windows(
            MONDAY=("11:00", "21:30"),
            TUESDAY=("11:30", "21:00"),
            WEDNESDAY=("11:00", "22:00"),
            THURSDAY=("11:00", "21:30"),
            FRIDAY=("11:00", "22:30"),
            SATURDAY=("10:30", "23:00"),
            SUNDAY=("10:30", "21:00"),
        ),
        "pickup": weekly_windows(
            MONDAY=("10:30", "22:00"),
            TUESDAY=("11:00", "21:30"),
            WEDNESDAY=("10:30", "22:30"),
            THURSDAY=("10:30", "22:00"),
            FRIDAY=("10:30", "23:00"),
            SATURDAY=("10:00", "23:30"),
            SUNDAY=("10:00", "21:30"),
        ),
    },
    "Bangkok Bowl Science City": {
        "estimated_delivery_time": 33,
        "estimated_pickup_time": 21,
        "preparation_time_minutes": 18,
        "delivery": weekly_windows(
            MONDAY=("11:30", "21:30"),
            TUESDAY=("12:00", "21:00"),
            WEDNESDAY=("11:30", "22:00"),
            THURSDAY=("11:30", "21:30"),
            FRIDAY=("11:30", "22:30"),
            SATURDAY=("11:00", "23:00"),
            SUNDAY=("11:00", "21:00"),
        ),
        "pickup": weekly_windows(
            MONDAY=("11:00", "22:00"),
            TUESDAY=("11:30", "21:30"),
            WEDNESDAY=("11:00", "22:30"),
            THURSDAY=("11:00", "22:00"),
            FRIDAY=("11:00", "23:00"),
            SATURDAY=("10:30", "23:30"),
            SUNDAY=("10:30", "21:30"),
        ),
    },
    "Momo Mountain Gota": {
        "estimated_delivery_time": 22,
        "estimated_pickup_time": 16,
        "preparation_time_minutes": 14,
        "delivery": weekly_windows(
            MONDAY=("10:00", "21:30"),
            TUESDAY=("10:30", "21:00"),
            WEDNESDAY=("10:00", "21:30"),
            THURSDAY=("10:00", "21:30"),
            FRIDAY=("10:00", "22:00"),
            SATURDAY=("09:30", "22:30"),
            SUNDAY=("09:30", "21:00"),
        ),
        "pickup": weekly_windows(
            MONDAY=("09:30", "22:00"),
            TUESDAY=("10:00", "21:30"),
            WEDNESDAY=("09:30", "22:00"),
            THURSDAY=("09:30", "22:00"),
            FRIDAY=("09:30", "22:30"),
            SATURDAY=("09:00", "23:00"),
            SUNDAY=("09:00", "21:30"),
        ),
    },
    "Momo Mountain Thaltej": {
        "estimated_delivery_time": 26,
        "estimated_pickup_time": 17,
        "preparation_time_minutes": 15,
        "delivery": weekly_windows(
            MONDAY=("10:30", "22:00"),
            TUESDAY=("11:00", "21:30"),
            WEDNESDAY=("10:30", "22:00"),
            THURSDAY=("10:30", "22:00"),
            FRIDAY=("10:30", "22:30"),
            SATURDAY=("10:00", "23:00"),
            SUNDAY=("10:00", "21:30"),
        ),
        "pickup": weekly_windows(
            MONDAY=("10:00", "22:30"),
            TUESDAY=("10:30", "22:00"),
            WEDNESDAY=("10:00", "22:30"),
            THURSDAY=("10:00", "22:30"),
            FRIDAY=("10:00", "23:00"),
            SATURDAY=("09:30", "23:30"),
            SUNDAY=("09:30", "22:00"),
        ),
    },
    "Momo Mountain Chandkheda": {
        "estimated_delivery_time": 31,
        "estimated_pickup_time": 19,
        "preparation_time_minutes": 16,
        "delivery": weekly_windows(
            MONDAY=("11:00", "21:00"),
            TUESDAY=("11:30", "20:30"),
            WEDNESDAY=("11:00", "21:30"),
            THURSDAY=("11:00", "21:00"),
            FRIDAY=("11:00", "22:00"),
            SATURDAY=("10:30", "22:30"),
            SUNDAY=("10:30", "20:30"),
        ),
        "pickup": weekly_windows(
            MONDAY=("10:30", "21:30"),
            TUESDAY=("11:00", "21:00"),
            WEDNESDAY=("10:30", "22:00"),
            THURSDAY=("10:30", "21:30"),
            FRIDAY=("10:30", "22:30"),
            SATURDAY=("10:00", "23:00"),
            SUNDAY=("10:00", "21:00"),
        ),
    },
    "Stacked Grill House Prahlad Nagar": {
        "estimated_delivery_time": 24,
        "estimated_pickup_time": 17,
        "preparation_time_minutes": 15,
        "delivery": weekly_windows(
            MONDAY=("11:00", "22:30"),
            TUESDAY=("11:30", "22:00"),
            WEDNESDAY=("11:00", "22:30"),
            THURSDAY=("11:00", "22:30"),
            FRIDAY=("11:00", "23:00"),
            SATURDAY=("10:30", "23:30"),
            SUNDAY=("10:30", "22:00"),
        ),
        "pickup": weekly_windows(
            MONDAY=("10:30", "23:00"),
            TUESDAY=("11:00", "22:30"),
            WEDNESDAY=("10:30", "23:00"),
            THURSDAY=("10:30", "23:00"),
            FRIDAY=("10:30", "23:30"),
            SATURDAY=("10:00", "23:30"),
            SUNDAY=("10:00", "22:30"),
        ),
    },
    "Stacked Grill House Sindhu Bhavan": {
        "estimated_delivery_time": 27,
        "estimated_pickup_time": 18,
        "preparation_time_minutes": 16,
        "delivery": weekly_windows(
            MONDAY=("11:30", "22:00"),
            TUESDAY=("12:00", "21:30"),
            WEDNESDAY=("11:30", "22:00"),
            THURSDAY=("11:30", "22:00"),
            FRIDAY=("11:30", "23:00"),
            SATURDAY=("11:00", "23:30"),
            SUNDAY=("11:00", "21:30"),
        ),
        "pickup": weekly_windows(
            MONDAY=("11:00", "22:30"),
            TUESDAY=("11:30", "22:00"),
            WEDNESDAY=("11:00", "22:30"),
            THURSDAY=("11:00", "22:30"),
            FRIDAY=("11:00", "23:30"),
            SATURDAY=("10:30", "23:30"),
            SUNDAY=("10:30", "22:00"),
        ),
    },
    "Stacked Grill House Motera": {
        "estimated_delivery_time": 33,
        "estimated_pickup_time": 20,
        "preparation_time_minutes": 18,
        "delivery": weekly_windows(
            MONDAY=("12:00", "22:00"),
            TUESDAY=("12:00", "21:30"),
            WEDNESDAY=("12:00", "22:00"),
            THURSDAY=("12:00", "22:00"),
            FRIDAY=("12:00", "23:00"),
            SATURDAY=("11:30", "23:30"),
            SUNDAY=("11:30", "21:30"),
        ),
        "pickup": weekly_windows(
            MONDAY=("11:30", "22:30"),
            TUESDAY=("11:30", "22:00"),
            WEDNESDAY=("11:30", "22:30"),
            THURSDAY=("11:30", "22:30"),
            FRIDAY=("11:30", "23:30"),
            SATURDAY=("11:00", "23:30"),
            SUNDAY=("11:00", "22:00"),
        ),
    },
}


def get_or_create_user(db, *, email: str, defaults: dict) -> tuple[User, bool]:
    """Seed a user, scoping customers to the default marketplace app client.

    Identity is per app client, and a CHECK constraint requires customers to
    have one and staff to have none, so the app client is derived from the role
    rather than left unset.
    """

    role = defaults.get("role")
    app_client_id = None
    if role == UserRole.CUSTOMER:
        app_client_id = ensure_default_app_client(db).id

    query = db.query(User).filter(User.email == email)
    query = query.filter(
        User.app_client_id == app_client_id
        if app_client_id is not None
        else User.app_client_id.is_(None)
    )
    user = query.first()
    if user is not None:
        return user, False

    user = User(id=uuid.uuid4(), email=email, app_client_id=app_client_id, **defaults)
    db.add(user)
    return user, True


def get_or_create_preferences(db, *, user_id: uuid.UUID, defaults: dict) -> tuple[UserPreferences, bool]:
    prefs = db.query(UserPreferences).filter(UserPreferences.user_id == user_id).first()
    if prefs is not None:
        return prefs, False
    prefs = UserPreferences(id=uuid.uuid4(), user_id=user_id, **defaults)
    db.add(prefs)
    return prefs, True


def get_or_create_personalized_offer(
    db,
    *,
    restaurant_id: uuid.UUID,
    name: str,
    defaults: dict,
) -> tuple[PersonalizedOffer, bool]:
    offer = (
        db.query(PersonalizedOffer)
        .filter(
            PersonalizedOffer.restaurant_id == restaurant_id,
            PersonalizedOffer.name == name,
        )
        .first()
    )
    if offer is not None:
        return offer, False
    offer = PersonalizedOffer(
        id=uuid.uuid4(),
        restaurant_id=restaurant_id,
        name=name,
        **defaults,
    )
    db.add(offer)
    return offer, True


def get_or_create_restaurant(db, *, owner_id: uuid.UUID, slug: str, defaults: dict) -> tuple[Restaurant, bool]:
    restaurant = db.query(Restaurant).filter(Restaurant.owner_id == owner_id).first()
    if restaurant is None:
        restaurant = db.query(Restaurant).filter(Restaurant.slug == slug).first()
    if restaurant is not None:
        return restaurant, False
    restaurant = Restaurant(id=uuid.uuid4(), owner_id=owner_id, slug=slug, **defaults)
    db.add(restaurant)
    return restaurant, True


def get_or_create_restaurant_location(
    db,
    *,
    restaurant_id: uuid.UUID,
    branch_name: str,
    defaults: dict,
) -> tuple[RestaurantLocation, bool]:
    location = (
        db.query(RestaurantLocation)
        .filter(
            RestaurantLocation.restaurant_id == restaurant_id,
            RestaurantLocation.branch_name == branch_name,
        )
        .first()
    )
    if location is not None:
        return location, False
    location = RestaurantLocation(
        id=uuid.uuid4(),
        restaurant_id=restaurant_id,
        branch_name=branch_name,
        **defaults,
    )
    db.add(location)
    return location, True


def get_or_create_menu_item(
    db,
    *,
    restaurant_id: uuid.UUID,
    restaurant_location_id: uuid.UUID,
    name: str,
    defaults: dict,
) -> tuple[MenuItem, bool]:
    menu_item = (
        db.query(MenuItem)
        .filter(
            MenuItem.restaurant_id == restaurant_id,
            MenuItem.restaurant_location_id == restaurant_location_id,
            MenuItem.name == name,
        )
        .first()
    )
    if menu_item is not None:
        return menu_item, False
    menu_item = MenuItem(
        id=uuid.uuid4(),
        restaurant_id=restaurant_id,
        restaurant_location_id=restaurant_location_id,
        name=name,
        **defaults,
    )
    db.add(menu_item)
    return menu_item, True


def apply_model_fields(model, values: dict, *, overwrite_existing: bool = True) -> None:
    for field, value in values.items():
        current_value = getattr(model, field, None)
        if overwrite_existing or current_value in (None, "", 0):
            setattr(model, field, value)


def ensure_primary_location(
    db,
    *,
    restaurant: Restaurant,
    location_defaults: dict,
) -> tuple[RestaurantLocation, bool]:
    branch_name = location_defaults["branch_name"]
    location = (
        db.query(RestaurantLocation)
        .filter(
            RestaurantLocation.restaurant_id == restaurant.id,
            RestaurantLocation.branch_name == branch_name,
        )
        .first()
    )
    if location is not None:
        apply_model_fields(location, {k: v for k, v in location_defaults.items() if k != "branch_name"})
        return location, False

    locations = (
        db.query(RestaurantLocation)
        .filter(RestaurantLocation.restaurant_id == restaurant.id)
        .order_by(RestaurantLocation.created_at.asc())
        .all()
    )
    if len(locations) == 1 and locations[0].branch_name == DEFAULT_BRANCH_NAME:
        location = locations[0]
        location.branch_name = branch_name
        apply_model_fields(location, {k: v for k, v in location_defaults.items() if k != "branch_name"})
        return location, False

    location, created = get_or_create_restaurant_location(
        db,
        restaurant_id=restaurant.id,
        branch_name=branch_name,
        defaults={k: v for k, v in location_defaults.items() if k != "branch_name"},
    )
    if not created:
        apply_model_fields(location, {k: v for k, v in location_defaults.items() if k != "branch_name"})
    return location, created


def apply_seed_location_schedule(
    db,
    *,
    location: RestaurantLocation,
) -> None:
    schedule_config = LOCATION_SCHEDULE_CONFIG.get(location.branch_name)
    if schedule_config is None:
        ensure_default_location_slots(db, location_id=location.id)
        return

    delivery_windows: dict[LocationDayOfWeek, tuple[time, time]] = schedule_config["delivery"]
    pickup_windows: dict[LocationDayOfWeek, tuple[time, time]] = schedule_config["pickup"]
    all_window_starts = [window[0] for window in delivery_windows.values()] + [
        window[0] for window in pickup_windows.values()
    ]
    all_window_ends = [window[1] for window in delivery_windows.values()] + [
        window[1] for window in pickup_windows.values()
    ]

    location.delivery_enabled = True
    location.pickup_enabled = True
    location.future_order_enabled = True
    location.max_future_days = 7
    location.slot_interval_minutes = 30
    location.estimated_delivery_time = schedule_config["estimated_delivery_time"]
    location.estimated_pickup_time = schedule_config["estimated_pickup_time"]
    location.preparation_time_minutes = schedule_config["preparation_time_minutes"]
    location.opening_time = min(all_window_starts)
    location.closing_time = max(all_window_ends)
    location.temporary_closed_reason = None
    location.is_open = True
    location.is_active = True
    db.add(location)

    existing_slots = (
        db.query(LocationFulfillmentSlot)
        .filter(LocationFulfillmentSlot.location_id == location.id)
        .all()
    )
    for slot in existing_slots:
        db.delete(slot)
    db.flush()

    for fulfillment_type, windows in (
        (OrderFulfillmentType.DELIVERY, delivery_windows),
        (OrderFulfillmentType.PICKUP, pickup_windows),
    ):
        for day_key in WEEKDAY_KEYS:
            day = LocationDayOfWeek[day_key]
            start_time, end_time = windows[day]
            db.add(
                LocationFulfillmentSlot(
                    id=uuid.uuid4(),
                    location_id=location.id,
                    day_of_week=day,
                    fulfillment_type=fulfillment_type,
                    start_time=start_time,
                    end_time=end_time,
                    is_active=True,
                )
            )


def build_existing_image_map(db, *, restaurant_id: uuid.UUID) -> dict[str, str]:
    image_map: dict[str, str] = {}
    existing_items = db.query(MenuItem).filter(MenuItem.restaurant_id == restaurant_id).all()
    for menu_item in existing_items:
        if menu_item.image_url and menu_item.name not in image_map:
            image_map[menu_item.name] = menu_item.image_url
    return image_map


def assign_legacy_items_to_primary_location(
    db,
    *,
    restaurant_id: uuid.UUID,
    primary_location_id: uuid.UUID,
    valid_location_ids: set[uuid.UUID],
) -> None:
    existing_items = db.query(MenuItem).filter(MenuItem.restaurant_id == restaurant_id).all()
    for menu_item in existing_items:
        if menu_item.restaurant_location_id is None or menu_item.restaurant_location_id not in valid_location_ids:
            menu_item.restaurant_location_id = primary_location_id


# --- demo ratings ----------------------------------------------------------
# Seed data, and only seed data. Production ratings come from diners; these
# exist so a freshly seeded database renders a storefront that looks like a
# real one instead of a menu with every star blank.

def seed_rating(popularity_score: float) -> float:
    """A plausible star, loosely tracking popularity.

    Ratings in the wild cluster hard between 3.8 and 4.9 — a food app with a
    2.1 on the menu has delisted it — so the range is narrow on purpose.
    """
    base = 3.9 + (max(0.0, min(100.0, popularity_score)) - 50.0) / 50.0 * 0.8
    return round(min(4.9, max(3.6, base + RNG.uniform(-0.15, 0.15))), 1)


def build_branch_menu_items(
    base_menu: list[dict],
    branch_config: dict,
) -> list[dict]:
    unavailable = set(branch_config.get("unavailable", set()))
    excluded = set(branch_config.get("excluded", set()))
    price_delta = money(branch_config.get("price_delta", Decimal("0.00")))

    items: list[dict] = []
    for base_item in base_menu:
        if base_item["name"] in excluded:
            continue
        next_item = dict(base_item)
        next_item["price"] = (base_item["price"] + price_delta).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
        next_item["is_available"] = base_item["name"] not in unavailable
        items.append(next_item)

    for extra_item in branch_config.get("extras", []):
        next_item = dict(extra_item)
        next_item["is_available"] = next_item.get("is_available", True)
        items.append(next_item)

    return items


def create_seed_order(
    db,
    *,
    customer: User,
    restaurant: Restaurant,
    restaurant_location: RestaurantLocation,
    selected_items: list[MenuItem],
    order_time: datetime,
    special_instructions: str | None = None,
) -> Order:
    subtotal = sum(Decimal(str(item.price)) for item in selected_items)
    delivery_fee = Decimal(str(restaurant_location.delivery_fee))
    tax = (subtotal * Decimal("0.08")).quantize(MONEY_QUANT)
    total = subtotal + delivery_fee + tax

    order = Order(
        id=uuid.uuid4(),
        customer_id=customer.id,
        restaurant_id=restaurant.id,
        restaurant_location_id=restaurant_location.id,
        status=OrderStatus.DELIVERED,
        payment_status=PaymentStatus.PAID,
        payment_provider="mock",
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        tax_amount=tax,
        discount_amount=Decimal("0.00"),
        total_amount=total,
        currency="INR",
        special_instructions=special_instructions,
        delivery_address=customer.default_address,
        placed_at=order_time,
        created_at=order_time,
        updated_at=order_time + timedelta(minutes=30),
    )
    db.add(order)

    for item in selected_items:
        db.add(
            OrderItem(
                id=uuid.uuid4(),
                order_id=order.id,
                menu_item_id=item.id,
                item_name_snapshot=item.name,
                quantity=1,
                unit_price=item.price,
                total_price=item.price,
                created_at=order_time,
                updated_at=order_time,
            )
        )

    return order


def ensure_demo_order(
    db,
    *,
    label: str,
    customer: User,
    restaurant: Restaurant,
    restaurant_location: RestaurantLocation,
    selected_items: list[MenuItem],
    order_time: datetime,
) -> bool:
    existing_order = db.query(Order).filter(Order.special_instructions == label).first()
    if existing_order is not None:
        existing_order.customer_id = customer.id
        existing_order.restaurant_id = restaurant.id
        existing_order.restaurant_location_id = restaurant_location.id
        existing_order.status = OrderStatus.DELIVERED
        existing_order.payment_status = PaymentStatus.PAID
        existing_order.special_instructions = label
        existing_order.delivery_address = customer.default_address
        existing_order.placed_at = order_time
        existing_order.created_at = order_time
        existing_order.updated_at = order_time + timedelta(minutes=30)
        return False

    create_seed_order(
        db,
        customer=customer,
        restaurant=restaurant,
        restaurant_location=restaurant_location,
        selected_items=selected_items,
        order_time=order_time,
        special_instructions=label,
    )
    return True


def configure_personalized_offer_demo_seed(
    db,
    *,
    default_pwd: str,
    created_users: int,
    restaurant_by_slug: dict[str, Restaurant],
    locations_by_restaurant_slug: dict[str, list[RestaurantLocation]],
    menu_item_lookup: dict[tuple[uuid.UUID, uuid.UUID, str], MenuItem],
) -> tuple[int, int, list[tuple[str, str]]]:
    demo_users_created = 0
    demo_orders_created = 0
    demo_expectations: list[tuple[str, str]] = []

    demo_user1, created = get_or_create_user(
        db,
        email="offers-demo-1@example.com",
        defaults={
            "full_name": "Offers Demo User 1",
            "phone_number": "3000000101",
            "hashed_password": default_pwd,
            "role": UserRole.CUSTOMER,
            "is_active": True,
            "is_verified": True,
            "default_address": "101 Demo Street, Ahmedabad, Gujarat, 380015",
        },
    )
    demo_users_created += int(created)
    demo_user2, created = get_or_create_user(
        db,
        email="offers-demo-2@example.com",
        defaults={
            "full_name": "Offers Demo User 2",
            "phone_number": "3000000102",
            "hashed_password": default_pwd,
            "role": UserRole.CUSTOMER,
            "is_active": True,
            "is_verified": True,
            "default_address": "102 Demo Street, Ahmedabad, Gujarat, 380015",
        },
    )
    demo_users_created += int(created)
    demo_user3, created = get_or_create_user(
        db,
        email="offers-demo-3@example.com",
        defaults={
            "full_name": "Offers Demo User 3",
            "phone_number": "3000000103",
            "hashed_password": default_pwd,
            "role": UserRole.CUSTOMER,
            "is_active": True,
            "is_verified": True,
            "default_address": "103 Demo Street, Ahmedabad, Gujarat, 380015",
        },
    )
    demo_users_created += int(created)
    db.flush()

    demo_user1_prefs, _ = get_or_create_preferences(
        db,
        user_id=demo_user1.id,
        defaults={},
    )
    apply_model_fields(
        demo_user1_prefs,
        {
            "favorite_cuisines": ["Thai"],
            "disliked_cuisines": [],
            "dietary_preferences": ["VEG"],
            "preferred_meal_times": ["dinner"],
            "price_sensitivity": Decimal("1.00"),
            "average_budget": Decimal("280.00"),
            "cuisine_affinity_scores": {"Thai": 0.95},
            "spice_level": "MEDIUM",
            "budget_tier": "MID",
            "favorite_items": ["Pad Thai Veg"],
        },
    )

    demo_user2_prefs, _ = get_or_create_preferences(
        db,
        user_id=demo_user2.id,
        defaults={},
    )
    apply_model_fields(
        demo_user2_prefs,
        {
            "favorite_cuisines": ["Chinese"],
            "disliked_cuisines": [],
            "dietary_preferences": [],
            "preferred_meal_times": ["dinner"],
            "price_sensitivity": Decimal("0.90"),
            "average_budget": Decimal("320.00"),
            "cuisine_affinity_scores": {"Chinese": 0.92},
            "spice_level": "HIGH",
            "budget_tier": "MID",
            "favorite_items": ["Chicken Hakka Noodles"],
        },
    )
    demo_user3_prefs, _ = get_or_create_preferences(
        db,
        user_id=demo_user3.id,
        defaults={},
    )
    apply_model_fields(
        demo_user3_prefs,
        {
            "favorite_cuisines": [],
            "disliked_cuisines": [],
            "dietary_preferences": [],
            "preferred_meal_times": [],
            "price_sensitivity": Decimal("1.00"),
            "average_budget": Decimal("0.00"),
            "cuisine_affinity_scores": {},
            "spice_level": None,
            "budget_tier": None,
            "favorite_items": [],
        },
    )
    db.flush()

    bangkok_bowl = restaurant_by_slug["bangkok-bowl"]
    bangkok_location = next(
        location
        for location in locations_by_restaurant_slug["bangkok-bowl"]
        if location.branch_name == "Bangkok Bowl Ellisbridge"
    )
    pad_thai = menu_item_lookup[(bangkok_bowl.id, bangkok_location.id, "Pad Thai Veg")]
    thai_iced_tea = menu_item_lookup[(bangkok_bowl.id, bangkok_location.id, "Thai Iced Tea")]

    dragon_wok = restaurant_by_slug["dragon-wok"]
    dragon_location = next(
        location
        for location in locations_by_restaurant_slug["dragon-wok"]
        if location.branch_name == "Dragon Wok CG Road"
    )
    hakka_noodles = menu_item_lookup[(dragon_wok.id, dragon_location.id, "Chicken Hakka Noodles")]
    spring_rolls = menu_item_lookup[(dragon_wok.id, dragon_location.id, "Vegetable Spring Rolls (4 pcs)")]

    now = datetime.now(timezone.utc)
    demo_order_specs = [
        (
            "offer-demo:user1:1",
            demo_user1,
            bangkok_bowl,
            bangkok_location,
            [pad_thai, thai_iced_tea],
            now - timedelta(days=21),
        ),
        (
            "offer-demo:user1:2",
            demo_user1,
            bangkok_bowl,
            bangkok_location,
            [pad_thai],
            now - timedelta(days=19),
        ),
        (
            "offer-demo:user1:3",
            demo_user1,
            bangkok_bowl,
            bangkok_location,
            [pad_thai, thai_iced_tea],
            now - timedelta(days=17),
        ),
        (
            "offer-demo:user2:1",
            demo_user2,
            dragon_wok,
            dragon_location,
            [hakka_noodles, spring_rolls],
            now - timedelta(days=5),
        ),
        (
            "offer-demo:user2:2",
            demo_user2,
            dragon_wok,
            dragon_location,
            [hakka_noodles],
            now - timedelta(days=3),
        ),
        (
            "offer-demo:user2:3",
            demo_user2,
            dragon_wok,
            dragon_location,
            [hakka_noodles, spring_rolls],
            now - timedelta(days=1),
        ),
    ]

    for label, customer, restaurant, restaurant_location, selected_items, order_time in demo_order_specs:
        demo_orders_created += int(
            ensure_demo_order(
                db,
                label=label,
                customer=customer,
                restaurant=restaurant,
                restaurant_location=restaurant_location,
                selected_items=selected_items,
                order_time=order_time,
            )
        )

    favorite_item_offer, _ = get_or_create_personalized_offer(
        db,
        restaurant_id=bangkok_bowl.id,
        name="Demo Welcome Back Favorite Item",
        defaults={},
    )
    apply_model_fields(
        favorite_item_offer,
        {
            "restaurant_location_id": bangkok_location.id,
            "applicable_item_id": pad_thai.id,
            "offer_type": PersonalizedOfferType.FAVORITE_ITEM,
            "audience_type": PersonalizedOfferAudience.INACTIVE_USERS,
            "state": PersonalizedOfferState.ACTIVE if ENABLE_PERSONALIZED_OFFERS_DEMO else PersonalizedOfferState.DISABLED,
            "discount_type": PersonalizedOfferDiscountType.PERCENTAGE,
            "discount_value": Decimal("10.00"),
            "max_discount_amount": Decimal("80.00"),
            "minimum_order_amount": Decimal("99.00"),
            "inactivity_days": 14,
            "cooldown_hours": 12,
            "valid_for_days": 7,
            "cta_label": "Order Again",
            "business_rules": {
                "seed_tag": "personalized-offers-demo",
                "demo_target_emails": [demo_user1.email],
            },
            "notes": "Temporary demo seed offer for personalized offers QA.",
            "starts_at": now - timedelta(days=1),
            "expires_at": now + timedelta(days=30),
        },
    )

    favorite_restaurant_offer, _ = get_or_create_personalized_offer(
        db,
        restaurant_id=dragon_wok.id,
        name="Demo New Spicy Picks",
        defaults={},
    )
    apply_model_fields(
        favorite_restaurant_offer,
        {
            "restaurant_location_id": dragon_location.id,
            "applicable_item_id": None,
            "offer_type": PersonalizedOfferType.FAVORITE_RESTAURANT,
            "audience_type": PersonalizedOfferAudience.ACTIVE_USERS,
            "state": PersonalizedOfferState.ACTIVE if ENABLE_PERSONALIZED_OFFERS_DEMO else PersonalizedOfferState.DISABLED,
            "discount_type": PersonalizedOfferDiscountType.NONE,
            "discount_value": Decimal("0.00"),
            "max_discount_amount": None,
            "minimum_order_amount": Decimal("0.00"),
            "inactivity_days": 14,
            "cooldown_hours": 12,
            "valid_for_days": 7,
            "cta_label": "Explore Now",
            "business_rules": {
                "seed_tag": "personalized-offers-demo",
                "demo_target_emails": [demo_user2.email],
            },
            "notes": "Temporary demo seed offer for personalized offers QA.",
            "starts_at": now - timedelta(days=1),
            "expires_at": now + timedelta(days=30),
        },
    )

    welcome_offer, _ = get_or_create_personalized_offer(
        db,
        restaurant_id=bangkok_bowl.id,
        name="Demo Welcome First Order",
        defaults={},
    )
    apply_model_fields(
        welcome_offer,
        {
            "restaurant_location_id": bangkok_location.id,
            "applicable_item_id": None,
            "offer_type": PersonalizedOfferType.WELCOME_FIRST_ORDER,
            "audience_type": PersonalizedOfferAudience.ALL_CUSTOMERS,
            "state": PersonalizedOfferState.ACTIVE if ENABLE_PERSONALIZED_OFFERS_DEMO else PersonalizedOfferState.DISABLED,
            "discount_type": PersonalizedOfferDiscountType.PERCENTAGE,
            "discount_value": Decimal("15.00"),
            "max_discount_amount": Decimal("100.00"),
            "minimum_order_amount": Decimal("149.00"),
            "inactivity_days": 14,
            "cooldown_hours": 12,
            "valid_for_days": 7,
            "cta_label": "Start Here",
            "business_rules": {
                "seed_tag": "personalized-offers-demo",
                "demo_target_emails": [demo_user3.email],
            },
            "notes": "Temporary demo seed offer for first-order welcome QA.",
            "starts_at": now - timedelta(days=1),
            "expires_at": now + timedelta(days=30),
        },
    )

    demo_expectations.append((demo_user1.email, "Your favorite Pad Thai Veg is waiting"))
    demo_expectations.append((demo_user2.email, "Recommended from your favorite restaurant"))
    demo_expectations.append((demo_user3.email, "Welcome! Get your first order offer at Bangkok Bowl"))
    return created_users + demo_users_created, demo_orders_created, demo_expectations


def configure_general_personalized_offer_seed(
    db,
    *,
    restaurants: list[Restaurant],
) -> list[tuple[str, str]]:
    now = datetime.now(timezone.utc)
    sample_state = PersonalizedOfferState.ACTIVE if ENABLE_PERSONALIZED_OFFERS_SAMPLE_CAMPAIGNS else PersonalizedOfferState.DISABLED
    expected_campaigns: list[tuple[str, str]] = []
    restaurant_by_slug = {restaurant.slug: restaurant for restaurant in restaurants}

    def seed_offer(
        *,
        restaurant_slug: str,
        name: str,
        offer_type: PersonalizedOfferType,
        audience_type: PersonalizedOfferAudience,
        discount_type: PersonalizedOfferDiscountType,
        discount_value: str,
        minimum_order_amount: str,
        notes: str,
        cta_label: str,
        applicable_category: str | None = None,
        applicable_cuisine: str | None = None,
        max_discount_amount: str | None = None,
    ) -> None:
        restaurant = restaurant_by_slug.get(restaurant_slug)
        if restaurant is None:
            return
        offer, _ = get_or_create_personalized_offer(
            db,
            restaurant_id=restaurant.id,
            name=name,
            defaults={},
        )
        apply_model_fields(
            offer,
            {
                "restaurant_location_id": None,
                "applicable_item_id": None,
                "offer_type": offer_type,
                "audience_type": audience_type,
                "state": sample_state,
                "discount_type": discount_type,
                "discount_value": Decimal(discount_value),
                "max_discount_amount": Decimal(max_discount_amount) if max_discount_amount is not None else None,
                "minimum_order_amount": Decimal(minimum_order_amount),
                "inactivity_days": 14,
                "cooldown_hours": 12,
                "valid_for_days": 7,
                "cta_label": cta_label,
                "applicable_category": applicable_category,
                "applicable_cuisine": applicable_cuisine,
                "business_rules": {
                    "seed_tag": "personalized-offers-general",
                },
                "notes": notes,
                "starts_at": now - timedelta(days=1),
                "expires_at": now + timedelta(days=180),
            },
        )
        expected_campaigns.append((restaurant.name, name))

    seed_offer(
        restaurant_slug="luigis-italian",
        name="Seed Pizza Lovers",
        offer_type=PersonalizedOfferType.FAVORITE_ITEM,
        audience_type=PersonalizedOfferAudience.ACTIVE_USERS,
        discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
        discount_value="20.00",
        max_discount_amount="6.00",
        minimum_order_amount="20.00",
        applicable_category="Pizza",
        notes="Scoped pizza repeat-order template for generated pizza-lover campaigns.",
        cta_label="Grab Pizza",
    )
    seed_offer(
        restaurant_slug="bangkok-bowl",
        name="Seed Thai Lovers",
        offer_type=PersonalizedOfferType.CUISINE_AFFINITY,
        audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
        discount_type=PersonalizedOfferDiscountType.FLAT,
        discount_value="4.00",
        minimum_order_amount="24.00",
        applicable_cuisine="Thai",
        notes="Scoped Thai cuisine template for affinity-based generated campaigns.",
        cta_label="Explore Thai",
    )
    seed_offer(
        restaurant_slug="dragon-wok",
        name="Seed Dragon Wok Loyalists",
        offer_type=PersonalizedOfferType.FAVORITE_RESTAURANT,
        audience_type=PersonalizedOfferAudience.ACTIVE_USERS,
        discount_type=PersonalizedOfferDiscountType.NONE,
        discount_value="0.00",
        minimum_order_amount="0.00",
        notes="Restaurant-specific loyalty template for favorite-restaurant generation.",
        cta_label="Order Favorite",
    )
    seed_offer(
        restaurant_slug="bangkok-bowl",
        name="Seed Welcome First Order",
        offer_type=PersonalizedOfferType.WELCOME_FIRST_ORDER,
        audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
        discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
        discount_value="10.00",
        max_discount_amount="8.00",
        minimum_order_amount="18.00",
        notes="Welcome template for new customers with no paid orders.",
        cta_label="Start Here",
    )
    seed_offer(
        restaurant_slug="bangkok-bowl",
        name="Seed Welcome Back",
        offer_type=PersonalizedOfferType.FAVORITE_RESTAURANT,
        audience_type=PersonalizedOfferAudience.INACTIVE_USERS,
        discount_type=PersonalizedOfferDiscountType.PERCENTAGE,
        discount_value="12.00",
        max_discount_amount="7.00",
        minimum_order_amount="20.00",
        notes="Comeback template for inactive customers who have not ordered in 14 days.",
        cta_label="Come Back",
    )
    seed_offer(
        restaurant_slug="stacked-grill-house",
        name="Seed Burger Combo Boost",
        offer_type=PersonalizedOfferType.COMBO_AFFINITY,
        audience_type=PersonalizedOfferAudience.ACTIVE_USERS,
        discount_type=PersonalizedOfferDiscountType.FLAT,
        discount_value="3.50",
        minimum_order_amount="19.00",
        applicable_category="Combo",
        notes="Combo-affinity template for burger-heavy users and repeated combo buyers.",
        cta_label="Add Combo",
    )
    seed_offer(
        restaurant_slug="spice-route",
        name="Seed Global Discovery",
        offer_type=PersonalizedOfferType.ORDER_HISTORY_MATCH,
        audience_type=PersonalizedOfferAudience.ALL_CUSTOMERS,
        discount_type=PersonalizedOfferDiscountType.NONE,
        discount_value="0.00",
        minimum_order_amount="0.00",
        notes="Generic fallback template when stronger repeat or cuisine matches are unavailable.",
        cta_label="Discover More",
    )

    return expected_campaigns


def run_seed():
    db = SessionLocal()
    try:
        is_fresh_database = db.query(User).first() is None
        if is_fresh_database:
            print("Seeding database...")
        else:
            print("Database already contains data. Running safe append seed for missing users, restaurants, locations, and menu items...")

        print("Creating users...")
        default_pwd = get_password_hash("password123")
        created_users = 0

        _, created = get_or_create_user(
            db,
            email="admin@example.com",
            defaults={
                "full_name": "Admin User",
                "phone_number": "1234567890",
                "hashed_password": default_pwd,
                "role": UserRole.ADMIN,
                "is_active": True,
                "is_verified": True,
            },
        )
        created_users += int(created)

        owners: list[User] = []
        for index in range(1, len(RESTAURANT_SEED_DATA) + 1):
            owner, created = get_or_create_user(
                db,
                email=f"owner{index}@example.com",
                defaults={
                    "full_name": f"Owner {index}",
                    "phone_number": f"200000000{index}",
                    "hashed_password": default_pwd,
                    "role": UserRole.OWNER,
                    "is_active": True,
                    "is_verified": True,
                },
            )
            owners.append(owner)
            created_users += int(created)

        customers: list[User] = []
        for index in range(1, 6):
            customer, created = get_or_create_user(
                db,
                email=f"customer{index}@example.com",
                defaults={
                    "full_name": f"Customer {index}",
                    "phone_number": f"300000000{index}",
                    "hashed_password": default_pwd,
                    "role": UserRole.CUSTOMER,
                    "is_active": True,
                    "is_verified": True,
                    "default_address": f"{index}00 Main St, City, State, 12345",
                },
            )
            customers.append(customer)
            created_users += int(created)

        db.commit()

        print("Creating user preferences...")
        created_preferences = 0
        for customer in customers:
            _, created = get_or_create_preferences(
                db,
                user_id=customer.id,
                defaults={
                    "favorite_cuisines": ["Italian", "Indian", "Chinese"],
                    "disliked_cuisines": [],
                    "dietary_preferences": ["Vegetarian"] if RNG.choice([True, False]) else [],
                    "preferred_meal_times": ["dinner"],
                    "price_sensitivity": RNG.uniform(0.5, 1.5),
                    "average_budget": RNG.uniform(20.0, 50.0),
                    "cuisine_affinity_scores": {"Italian": 0.8, "Indian": 0.9},
                },
            )
            created_preferences += int(created)
        db.commit()

        print("Creating restaurants...")
        restaurants: list[Restaurant] = []
        restaurant_by_slug: dict[str, Restaurant] = {}
        created_restaurants = 0

        for index, restaurant_seed in enumerate(RESTAURANT_SEED_DATA):
            restaurant, created = get_or_create_restaurant(
                db,
                owner_id=owners[index].id,
                slug=restaurant_seed["slug"],
                defaults={
                    "name": restaurant_seed["name"],
                    "description": restaurant_seed["description"],
                    "cuisine_type": restaurant_seed["cuisine_type"],
                    "address_line_1": restaurant_seed["address_line_1"],
                    "city": restaurant_seed["city"],
                    "state": restaurant_seed["state"],
                    "postal_code": restaurant_seed["postal_code"],
                    "minimum_order_amount": restaurant_seed["minimum_order_amount"],
                    "delivery_fee": restaurant_seed["delivery_fee"],
                    "is_approved": True,
                    "is_open": True,
                    "is_active": True,
                },
            )
            apply_model_fields(
                restaurant,
                {
                    "slug": restaurant_seed["slug"],
                    "name": restaurant_seed["name"],
                    "description": restaurant_seed["description"],
                    "cuisine_type": restaurant_seed["cuisine_type"],
                    "address_line_1": restaurant_seed["address_line_1"],
                    "city": restaurant_seed["city"],
                    "state": restaurant_seed["state"],
                    "postal_code": restaurant_seed["postal_code"],
                    "minimum_order_amount": restaurant_seed["minimum_order_amount"],
                    "delivery_fee": restaurant_seed["delivery_fee"],
                    "is_approved": True,
                    "is_open": True,
                    "is_active": True,
                },
            )
            restaurants.append(restaurant)
            restaurant_by_slug[restaurant.slug] = restaurant
            created_restaurants += int(created)
        db.commit()

        print("Creating restaurant locations and branch-wise menu items...")
        created_locations = 0
        created_menu_items = 0
        locations_by_restaurant_slug: dict[str, list[RestaurantLocation]] = {}

        for restaurant_seed in RESTAURANT_SEED_DATA:
            restaurant = restaurant_by_slug[restaurant_seed["slug"]]
            branch_locations: list[RestaurantLocation] = []

            primary_location, primary_created = ensure_primary_location(
                db,
                restaurant=restaurant,
                location_defaults=restaurant_seed["locations"][0],
            )
            branch_locations.append(primary_location)
            created_locations += int(primary_created)

            for branch_seed in restaurant_seed["locations"][1:]:
                location, created = get_or_create_restaurant_location(
                    db,
                    restaurant_id=restaurant.id,
                    branch_name=branch_seed["branch_name"],
                    defaults={k: v for k, v in branch_seed.items() if k not in {"branch_name", "price_delta", "unavailable", "excluded", "extras"}},
                )
                apply_model_fields(
                    location,
                    {k: v for k, v in branch_seed.items() if k not in {"branch_name", "price_delta", "unavailable", "excluded", "extras"}},
                )
                branch_locations.append(location)
                created_locations += int(created)

            db.flush()
            for location in branch_locations:
                apply_seed_location_schedule(db, location=location)
            location_ids = {location.id for location in branch_locations}
            assign_legacy_items_to_primary_location(
                db,
                restaurant_id=restaurant.id,
                primary_location_id=primary_location.id,
                valid_location_ids=location_ids,
            )
            existing_image_map = build_existing_image_map(db, restaurant_id=restaurant.id)

            for branch_seed, location in zip(restaurant_seed["locations"], branch_locations, strict=True):
                for item_seed in build_branch_menu_items(restaurant_seed["base_menu"], branch_seed):
                    popularity_score = round(RNG.uniform(50.0, 100.0), 2)
                    menu_item, created = get_or_create_menu_item(
                        db,
                        restaurant_id=restaurant.id,
                        restaurant_location_id=location.id,
                        name=item_seed["name"],
                        defaults={
                            "category": item_seed["category"],
                            "cuisine_type": restaurant.cuisine_type,
                            "description": item_seed["description"],
                            "price": item_seed["price"],
                            "is_veg": item_seed["is_veg"],
                            "is_available": item_seed.get("is_available", True),
                            "is_bestseller": RNG.choice([True, False]),
                            "image_url": item_seed.get("image_url") or existing_image_map.get(item_seed["name"]),
                            "is_new_launch": item_seed.get("is_new_launch", False),
                            "popularity_score": popularity_score,
                            "rating": seed_rating(popularity_score),
                            "rating_count": RNG.randint(12, 240),
                        },
                    )
                    if created:
                        created_menu_items += 1
                    else:
                        if menu_item.image_url is None:
                            inherited_image = item_seed.get("image_url") or existing_image_map.get(item_seed["name"])
                            if inherited_image:
                                menu_item.image_url = inherited_image
                        # Backfill only. A dish seeded before ratings existed
                        # has none, and re-seeding is how a demo database
                        # catches up; anything already set is left alone so a
                        # re-run cannot rewrite values somebody chose.
                        if menu_item.rating is None:
                            menu_item.rating = seed_rating(float(menu_item.popularity_score or 0))
                            menu_item.rating_count = RNG.randint(12, 240)

            locations_by_restaurant_slug[restaurant_seed["slug"]] = branch_locations

        db.commit()

        all_menu_items = db.query(MenuItem).all()
        menu_item_lookup = {
            (menu_item.restaurant_id, menu_item.restaurant_location_id, menu_item.name): menu_item
            for menu_item in all_menu_items
        }
        demo_offer_orders_created = 0
        demo_offer_expectations: list[tuple[str, str]] = []
        created_users, demo_offer_orders_created, demo_offer_expectations = configure_personalized_offer_demo_seed(
            db,
            default_pwd=default_pwd,
            created_users=created_users,
            restaurant_by_slug=restaurant_by_slug,
            locations_by_restaurant_slug=locations_by_restaurant_slug,
            menu_item_lookup=menu_item_lookup,
        )
        sample_offer_expectations = configure_general_personalized_offer_seed(
            db,
            restaurants=restaurants,
        )
        rebuild_generated_offers(db)
        db.commit()
        invalidate_all_personalized_offer_caches()
        invalidate_all_recommendation_caches()

        if is_fresh_database:
            print("Creating orders...")
            orders: list[Order] = []
            order_status_pool = [
                OrderStatus.PLACED,
                OrderStatus.ACCEPTED,
                OrderStatus.PREPARING,
                OrderStatus.OUT_FOR_DELIVERY,
                OrderStatus.DELIVERED,
            ]
            for customer in customers:
                for _ in range(2):
                    restaurant = RNG.choice(restaurants)
                    restaurant_locations = [
                        location
                        for location in locations_by_restaurant_slug[restaurant.slug]
                        if location.is_active
                    ]
                    if not restaurant_locations:
                        continue
                    restaurant_location = RNG.choice(restaurant_locations)
                    restaurant_items = [
                        item
                        for item in all_menu_items
                        if item.restaurant_id == restaurant.id
                        and item.restaurant_location_id == restaurant_location.id
                        and item.is_available
                    ]
                    if len(restaurant_items) < 2:
                        continue
                    selected_items = RNG.sample(
                        restaurant_items,
                        min(len(restaurant_items), RNG.randint(2, 4)),
                    )
                    order_time = generate_random_time()
                    order = create_seed_order(
                        db,
                        customer=customer,
                        restaurant=restaurant,
                        restaurant_location=restaurant_location,
                        selected_items=selected_items,
                        order_time=order_time,
                    )
                    order.status = RNG.choice(order_status_pool)
                    orders.append(order)

            combo_demo_patterns = [
                (
                    "combo-demo:pizza-and-soda",
                    "luigis-italian",
                    "Luigi's Italian Trattoria Downtown",
                    ["Margherita Pizza", "Iced Lemon Soda"],
                    [customers[0], customers[1], customers[2]],
                ),
                (
                    "combo-demo:burger-and-shake",
                    "stacked-grill-house",
                    "Stacked Grill House Prahlad Nagar",
                    ["Classic Chicken Burger", "Chocolate Shake"],
                    [customers[1], customers[2], customers[3]],
                ),
                (
                    "combo-demo:momos-and-drink",
                    "momo-mountain",
                    "Momo Mountain Thaltej",
                    ["Chicken Momos (8 pcs)", "Peach Soda"],
                    [customers[0], customers[3], customers[4]],
                ),
                (
                    "combo-demo:pizza-side-drink",
                    "luigis-italian",
                    "Luigi's Italian Trattoria Riverside",
                    ["Margherita Pizza", "Garlic Bread", "Iced Lemon Soda"],
                    [customers[0], customers[2], customers[4]],
                ),
            ]

            for offset, (label, restaurant_slug, branch_name, item_names, pattern_customers) in enumerate(combo_demo_patterns):
                restaurant = restaurant_by_slug.get(restaurant_slug)
                branch_locations = locations_by_restaurant_slug.get(restaurant_slug, [])
                restaurant_location = next(
                    (location for location in branch_locations if location.branch_name == branch_name),
                    None,
                )
                if restaurant is None or restaurant_location is None:
                    continue

                selected_items = [
                    menu_item_lookup[(restaurant.id, restaurant_location.id, item_name)]
                    for item_name in item_names
                    if (restaurant.id, restaurant_location.id, item_name) in menu_item_lookup
                ]
                if len(selected_items) != len(item_names):
                    continue

                for pattern_index, customer in enumerate(pattern_customers):
                    order_time = datetime.now(timezone.utc) - timedelta(days=offset * 3 + pattern_index + 1)
                    orders.append(
                        create_seed_order(
                            db,
                            customer=customer,
                            restaurant=restaurant,
                            restaurant_location=restaurant_location,
                            selected_items=selected_items,
                            order_time=order_time,
                            special_instructions=label,
                        )
                    )

            db.commit()

            print("Creating chat history...")
            spice_route = restaurant_by_slug["spice-route"]
            spice_route_location = locations_by_restaurant_slug["spice-route"][0]
            for customer in customers:
                session_id = uuid.uuid4()
                chat_time = generate_random_time()
                msg1 = ChatHistory(
                    id=uuid.uuid4(),
                    user_id=customer.id,
                    restaurant_id=spice_route.id,
                    restaurant_location_id=spice_route_location.id,
                    session_id=session_id,
                    role=ChatMessageRole.USER,
                    message="I want some spicy Indian food",
                    created_at=chat_time,
                    updated_at=chat_time,
                )
                msg2 = ChatHistory(
                    id=uuid.uuid4(),
                    user_id=customer.id,
                    restaurant_id=spice_route.id,
                    restaurant_location_id=spice_route_location.id,
                    session_id=session_id,
                    role=ChatMessageRole.ASSISTANT,
                    message="I found some great options for you. How about the Butter Chicken from Spice Route Navrangpura?",
                    created_at=chat_time + timedelta(seconds=5),
                    updated_at=chat_time + timedelta(seconds=5),
                )
                db.add_all([msg1, msg2])
            db.commit()
        else:
            orders = []

        print("✅ Database successfully seeded!")
        print(f"Users created this run: {created_users} (Admin + Owners + Customers)")
        print(f"User preferences created this run: {created_preferences}")
        print(f"Restaurants created this run: {created_restaurants}")
        print(f"Restaurant locations created this run: {created_locations}")
        print(f"Menu items created this run: {created_menu_items}")
        print(f"Personalized-offer demo orders created this run: {demo_offer_orders_created}")
        if is_fresh_database:
            print(f"Created: {len(orders)} Orders")
        else:
            if demo_offer_orders_created > 0:
                print("Append seed preserved existing data and added personalized-offer demo orders where missing.")
            else:
                print("Orders/chat history were left unchanged because this was an append seed run.")
        print("Login with email (e.g. admin@example.com, customer1@example.com) and password: password123")
        if ENABLE_PERSONALIZED_OFFERS_DEMO and demo_offer_expectations:
            print("Personalized Offers demo users:")
            for email, expected_card in demo_offer_expectations:
                print(f" - {email} -> {expected_card}")
        elif demo_offer_expectations:
            print("Personalized Offers demo seed is disabled via SEED_PERSONALIZED_OFFERS_DEMO=0.")
        if ENABLE_PERSONALIZED_OFFERS_SAMPLE_CAMPAIGNS and sample_offer_expectations:
            print("General Personalized Offers campaigns:")
            for restaurant_name, expectation in sample_offer_expectations:
                print(f" - {restaurant_name}: {expectation}")
        elif sample_offer_expectations:
            print("General Personalized Offers sample campaigns are disabled via SEED_PERSONALIZED_OFFERS_SAMPLE_CAMPAIGNS=0.")

    except Exception as error:
        print(f"Error seeding database: {error}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run_seed()

# Bangkok Bowl Delights

Build Bangkok Bowl, a single-restaurant multi-branch Thai food ordering web app (3 branches in Ahmedabad, ₹ currency).

CRITICAL LAYOUT & THEME REQUIREMENTS:
1. FULL-WIDTH: Full-width edge-to-edge layout across the entire browser (400px to 1920px). Header spans edge to edge. No narrow centered column with empty side voids. Every band carries content or deliberate structure.
2. WHITE-LABEL CSS VARIABLES: Every color MUST come from CSS variables defined at :root (--primary: #FF5200, --primary-soft: #FFF0E8, --on-primary: #ffffff, --bg: #FAFAFA, --surface: #FFFFFF, --surface-alt: #F4F4F5, --text: #14171F, --muted: #6B7280, --border: #E5E7EB, --success: #16A34A, --danger: #DC2626). No literal hex or hardcoded tailwind color classes. Support light & dark mode.
3. DELIBERATE PLACEHOLDERS: When image_url is null or 404s, show a branded placeholder with the dish's initials on a tint derived from --primary, varied per dish. Never broken or plain grey.
4. VEG / NON-VEG: Indian market requirement - green square with circle for is_veg: true, red/brown square with triangle/circle for is_veg: false.
5. MOTION & DETAILS: Only animate transform and opacity. Respect prefers-reduced-motion. Min 44px tap targets. Prices are decimal strings formatted with ₹. Null ratings show no star. Dishes with has_sizes show "From ₹X". Fixed aspect ratios with object-fit: cover.

SCREENS & FEATURES:
1. Home: Edge-to-edge hero with food photography, branch & open status chips, search, category rail, menu grid, "Ask AI" promo card, personalized picks, active offers.
2. Menu / Restaurant: Branch switcher (Navrangpura, Bodakdev, Vastrapur), sticky category filter rail, complete dish grid with fast add-to-cart.
3. Dish Detail: Large image, price, rating count, prep time, description, size selector, add-on customization groups (single/multi-select), sticky bottom "Add to cart" bar, "Goes well with this" recommendations.
4. Cart & Checkout: Drawer/page with item thumbnails, size/addon summaries, quantity steppers, bill breakdown (subtotal, delivery fee, tax, discount, total ₹), delivery vs pickup toggle, sticky "Place order" bar.
5. AI Chat: Interactive AI food concierge recommending dishes with clickable suggestion cards that can be added directly to cart.
6. Auth: Clean login and register screens.
7. Orders: Order list and order detail with a live visual status timeline (Placed -> Accepted -> Preparing -> Out for Delivery -> Delivered).

DATA SHAPES (Match exact fields):
- MenuItem: { id, restaurant_id, restaurant_location_id, name, category, cuisine_type, description, price, is_veg, is_available, is_bestseller, image_url, rating, rating_count, is_new, is_favorite, has_sizes, has_customizations, sizes: [{ id, name, price, is_active }], customization_groups: [{ id, title, selection_type: 'SINGLE'|'MULTI', is_required, min_selection, max_selection, options: [{ id, name, extra_price, is_countable }] }] }
- Restaurant: { id, name, slug, description, cuisine_type, city, minimum_order_amount, delivery_fee, logo_image_url, cover_image_url, is_open, locations?: RestaurantLocation[] }
- RestaurantLocation: { id, branch_name, address_line_1, city, delivery_fee, minimum_order_amount, estimated_delivery_time, estimated_pickup_time, delivery_enabled, pickup_enabled, is_open, is_active }
- Order: { id, order_number, status, payment_status, fulfillment_type, subtotal, delivery_fee, tax_amount, discount_amount, total_amount, placed_at, delivery_address, items: [{ id, item_name_snapshot, quantity, unit_price, total_price }] }

Include realistic Thai mock dishes (Pad Thai, Tom Yum Goong, Green Curry, Som Tum, Mango Sticky Rice, Massaman Curry, Thai Iced Tea, etc.) priced ₹60-₹600.

This project was built with [Lovable](https://lovable.dev).

**Live app**: https://bangkok-bowl-ai.lovable.app

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/2a4150f5-9c8c-47bb-bb80-d5ee43babc9e).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```

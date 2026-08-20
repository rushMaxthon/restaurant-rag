# Frontend Customer

`frontend-customer/` is the customer-facing web app for the Restaurant RAG platform. It is a React + TypeScript + Vite app with a custom pathname router, local session/cart persistence, public restaurant browsing, AI chat, and order flows.

Access boundary:

- only `CUSTOMER` accounts may sign in here
- `ADMIN` and `OWNER` accounts must be rejected with: `Admin/Owner accounts cannot access the customer app.`

## What This App Does

Customers can:

- browse restaurants without logging in
- open restaurant detail pages and browse menus
- open menu item detail pages that refetch the latest item data by ID
- get redirected to login when trying to add to cart, open cart, or place an order as a guest
- return to the same screen after login or registration and continue smoothly
- get authenticated personalized recommendations
- see compact backend-driven recommendation badges like `Matches Your Taste` and `Based on Your Orders`
- chat with the AI assistant
- add items to a single-restaurant cart
- place and track orders
- manage profile, order history, and settings from the profile area

Role rule:

- customer login is valid only for `CUSTOMER`
- admin/owner login attempts fail gracefully and do not create a stored session

Generated combo cart behavior follows the same source-of-truth rule as mobile:

- `MenuItem.is_veg` is the only source of truth for veg/non-veg status
- combo items keep their original `menu_item_id`
- combo add and combo upsell flows must preserve each item's own `is_veg`

## Tech Stack

- React 19
- TypeScript
- Vite
- native browser `fetch`
- localStorage for auth, cart, and chat session persistence

This app expects the backend Redis layer to be available in local development for the best AI chat and recommendation latency, but normal browsing still works if Redis is temporarily unavailable because the backend fails open.

## Current Structure

```text
frontend-customer/
├── src/
│   ├── components/
│   │   ├── AppShell.tsx
│   │   ├── ChatMessageCard.tsx
│   │   ├── MenuItemCard.tsx
│   │   ├── OrderStepper.tsx
│   │   ├── RestaurantCard.tsx
│   │   ├── Skeleton.tsx
│   │   └── ToastViewport.tsx
│   ├── hooks/
│   │   └── useAppStore.ts
│   ├── pages/
│   │   ├── CartPage.tsx
│   │   ├── Chat.tsx
│   │   ├── ChatPage.tsx
│   │   ├── HomePage.tsx
│   │   ├── LoginPage.tsx
│   │   ├── MenuItemDetail.tsx
│   │   ├── OrdersPage.tsx
│   │   ├── ProfileDetailsPage.tsx
│   │   ├── ProfileHelpPage.tsx
│   │   ├── ProfileOrdersPage.tsx
│   │   ├── ProfilePage.tsx
│   │   ├── ProfileSettingsPage.tsx
│   │   ├── RegisterPage.tsx
│   │   └── RestaurantPage.tsx
│   ├── services/
│   │   ├── api.ts
│   │   └── storage.ts
│   ├── store/
│   │   ├── AppStore.tsx
│   │   └── AppStoreContext.ts
│   ├── types/
│   │   └── app.ts
│   ├── utils/
│   │   ├── authRedirect.ts
│   │   └── generatedComboCart.ts
│   ├── App.tsx
│   ├── index.css
│   └── main.tsx
├── package.json
└── README.md
```

## Important Files

- [src/App.tsx](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/App.tsx)
  - custom pathname router
  - invalid stored-role eviction on startup
  - connects page components to store actions and navigation

- [src/components/AppShell.tsx](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/components/AppShell.tsx)
  - shared shell
  - desktop header and mobile navigation

- [src/store/AppStore.tsx](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/store/AppStore.tsx)
  - auth state
  - cart state
  - chat session state
  - pending cart replacement state for cross-restaurant adds
  - pending auth redirect state
  - rejects non-customer roles before session persistence
  - toast state
  - expired-session handling

- [src/utils/authRedirect.ts](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/utils/authRedirect.ts)
  - reusable auth guard for protected cart actions
  - stores redirect targets and sends guests to login

- [src/services/api.ts](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/services/api.ts)
  - fetch wrapper
  - timeout handling
  - auth invalid event dispatch
  - public fallback behavior for some restaurant/menu requests

- [src/pages/OrderDetailPage.tsx](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/pages/OrderDetailPage.tsx)
  - dedicated order tracking/detail route for customer web
  - shows item breakdown, delivery address, totals, and status stepper

## Current Routes

This app uses a custom history-based router.

Routes:

- `/`
- `/restaurant/:id`
- `/menu-item/:id`
- `/chat`
- `/cart`
- `/orders`
- `/orders/:id`
- `/profile`
- `/profile/details`
- `/profile/orders`
- `/profile/settings`
- `/profile/help`
- `/auth/login`
- `/auth/register`

## Current User Flow

### Home

[src/pages/HomePage.tsx](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/pages/HomePage.tsx)

- loads public restaurant list
- loads generated combos for the `Frequently Ordered Together` section
- loads `Offers` for authenticated users when generated or reusable live campaigns are available
- optionally loads personalized recommendations when authenticated
- recommendation cards can include backend-driven new-item labels and reasons
- allows local search and cuisine filtering
- opens restaurant detail pages

Current home-feed intent:

- `Offers` is additive and does not replace `Personalized Picks`
- offer cards are backend-driven and tied to reusable templates plus generated campaign matching
- item offer cards open menu item detail
- restaurant, cuisine, and combo offers open the matching restaurant flow
- normal item adds can also trigger a contextual offer prompt when an eligible live offer exists

### Restaurant Detail

[src/pages/RestaurantPage.tsx](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/pages/RestaurantPage.tsx)

- loads restaurant detail by `restaurantId`
- loads menu items on page load
- loads generated combos for that restaurant
- shows loading skeletons
- shows retry UI on fetch failure
- category filtering happens client-side after data loads
- uses compact horizontal-style menu cards
- menu cards can show one compact backend-provided badge such as `Just Launched` or `Best Seller`
- branch hero now exposes only the fulfillment modes enabled for that location
- restaurant detail keeps the shared cart `DELIVERY` / `PICKUP` mode aligned with branch rules
- if the selected fulfillment mode is outside the branch slot window, the page shows an unavailable state and blocks add-to-cart
- opens item detail screens by navigating with `itemId` only

### Menu Item Detail

[src/pages/MenuItemDetail.tsx](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/pages/MenuItemDetail.tsx)

- fetches the latest item detail by `itemId`
- fetches restaurant context separately for cart and header copy
- shows loading, retry, and not-found states
- supports size selection and customization groups when the item is configured for them
- keeps simple items on the existing fast add-to-cart flow
- keeps quantity controls synced with the shared cart store
- guards add-to-cart and cart access when the user is logged out
- uses a sticky action bar on smaller screens for fast add/update flows
- can show a new-item badge and backend explanation when the item is a recent personalized launch

### AI Chat

[src/pages/Chat.tsx](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/pages/Chat.tsx)

- sends chat messages to the backend
- renders optimistic user messages
- shows typing/loading UI
- supports streamed replies through `POST /api/chat/message/stream`
- can add backend suggestion items directly to the cart
- can clear the active chat session/history
- suggestion cards can open the suggested menu item detail as well as add it to cart
- relies on backend topic-aware continuation logic, so `show me more` continues the latest topic but a new explicit query like `burger` replaces an older topic like `pizza`
- benefits from backend Redis fast paths for repeated generic queries and greeting/thanks turns
- supports grounded combo questions such as `suggest combos`, `pizza combo`, and `combo under 500`
- also supports grounded new-item queries such as `what's new?`, `new spicy food`, and `new items for me`

### Cart and Orders

- [src/pages/CartPage.tsx](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/pages/CartPage.tsx)
- [src/pages/OrdersPage.tsx](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/pages/OrdersPage.tsx)

Behavior:

- cart is single-restaurant only
- if the user tries to add an item from another restaurant, the app now opens a confirmation modal with cancel vs clear-and-add
- normal item-add flows can call `POST /api/offers/personalized/context` and show an apply-or-skip offer modal before the item is added
- declining a prompted offer suppresses the same offer prompt for the current cart session
- generated combo cards add their underlying items into the normal cart safely
- if a personalized offer is active for the current restaurant/location, cart shows an offer banner and projected discount preview
- if the cart is replaced with another restaurant through `Clear & Add`, the newly selected matching offer is preserved and the old offer is cleared
- cart can show same-restaurant combo upsell suggestions for missing related items
- combo item veg/non-veg display must continue to come from each cart item's own `menuItem.is_veg`
- generated combo mapping uses `src/utils/generatedComboCart.ts` to preserve item-level `is_veg`
- restaurant and item-detail pages both reflect live cart quantity state
- the checkout fulfillment toggle now respects branch settings:
  - delivery is hidden/switched away when `delivery_enabled=false`
  - pickup is hidden/switched away when `pickup_enabled=false`
  - checkout is blocked when the selected fulfillment mode is outside the branch slot window
- add-to-cart, cart access, and order placement are auth-guarded
- guest users are redirected to `/auth/login` and then sent back to the saved screen
- order placement happens through backend validation
- eligible checkouts send `generated_offer_id` when present, plus `personalized_offer_id` for backward compatibility, so backend can validate and apply the correct offer source safely
- after checkout, the app routes directly into order detail/tracking for the new order
- orders page and profile order history both open the dedicated `/orders/:id` detail view

### Profile

The profile area now owns customer-specific subflows:

- account details
- order history
- settings
- help/support
- logout

Profile routes:

- `/profile`
- `/profile/details`
- `/profile/orders`
- `/profile/settings`
- `/profile/help`

## Session, Cart, and Local Storage

Local storage keys:

- `restaurant-rag-customer-auth`
- `restaurant-rag-customer-cart`
- `restaurant-rag-chat-session`
- `restaurant-rag-pending-auth-redirect`

Behavior:

- session restores on refresh
- stored auth restores only when `user.role === CUSTOMER`
- cart restores on refresh
- chat session restores on refresh
- pending login redirect restores if the user was sent to auth from a protected cart action
- invalid/stale JWTs are cleared automatically when the backend returns `401`
- if a saved session belongs to `ADMIN` or `OWNER`, the app clears it and redirects back to `/auth/login`

## Backend APIs Used

Auth:

- `POST /api/auth/register`
- `POST /api/auth/login`

Notes:

- customer web still uses the existing `email + password` login flow
- backend login now also accepts `phone_number + password` so mobile can use phone auth without breaking web

Backend login response requirements used by this app:

- response includes `role`
- customer app accepts the session only when the returned/stored user role is `CUSTOMER`

Public browsing:

- `GET /api/restaurants`
- `GET /api/restaurants/{restaurant_id}`
- `GET /api/menu-items?restaurant_id=...`
- `GET /api/menu-items/{menu_item_id}`
- `GET /api/generated-combos`
- `GET /api/restaurants/{restaurant_id}/generated-combos`

Authenticated customer features:

- `GET /api/recommendations`
- `GET /api/generated-combos/cart-upsell`
- `POST /api/chat/message`
- `POST /api/chat/message/stream`
- `GET /api/chat/history`
- `DELETE /api/chat/history`
- `POST /api/orders`
- `GET /api/orders`

## Environment Variable

Expected in `.env`:

```dotenv
VITE_API_BASE_URL=http://localhost:8000/api
```

Fallback base URL:

```text
http://localhost:8000/api
```

## Install

From `frontend-customer/`:

```bash
npm install
```

## Run Locally

```bash
npm run dev
```

## Build

```bash
npm run build
```

Preview:

```bash
npm run preview
```

## Common Commands

```bash
npm run dev
npm run build
npm run lint
npm run preview
```

## Notes for New Developers

- there is no React Router; all route handling is in `App.tsx`
- restaurant and menu browsing are public by design
- menu item detail routes fetch fresh backend data instead of receiving full menu objects through navigation
- protected cart behavior is implemented with store-backed redirect intent rather than React Router state
- recommendation and chat features expect a valid customer session
- keep cart logic inside `AppStore.tsx`; it currently enforces one restaurant at a time
- if you add new profile pages, update both `App.tsx` and the profile navigation UI

## New Item Recommendation UX

Customer web now renders backend-provided new-item recommendation metadata across the main discovery surfaces.

Behavior:

- `Personalized Picks` can show:
  - `Recommended for You`
  - `Matches Your Taste`
  - `Based on Your Orders`
- restaurant and recommendation cards show one compact backend-provided badge only
- generic launch and demand states can appear as `Just Launched`, `Trending Now`, or `Best Seller`
- menu item detail can show the same backend label when present
- chat suggestion cards can surface real newly launched dishes without inventing them client-side

Source of truth:

- badge text comes from backend payloads
- frontend does not guess which items are new or remap labels client-side

## Multi-location customer flow

Customer web now uses branch-aware ordering:

- restaurant detail auto-selects an active branch
- users can switch branches inside the restaurant detail hero
- menu items and generated combos reload for the selected branch
- each branch now carries its own fulfillment controls:
  - `delivery_enabled`
  - `pickup_enabled`
  - delivery / pickup ETA
  - delivery fee / minimum order
  - weekly availability slots
- cart scope is `restaurant + branch`, so adding from another branch opens the existing replacement flow
- checkout sends `restaurant_location_id` to the backend and uses branch delivery fee / minimum order rules
- checkout also sends `fulfillment_type`, and the backend revalidates branch slot availability before placing the order

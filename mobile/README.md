# Mobile App

React Native CLI customer app for the Restaurant RAG platform.

The mobile client covers restaurant discovery, search, menu browsing, generated combos, cart and checkout, order history, AI chat, profile management, and location selection.

## Stack

- React Native `0.85.2`
- TypeScript
- React Navigation
- Axios
- AsyncStorage
- `react-native-safe-area-context`
- `react-native-gesture-handler`
- `react-native-reanimated`
- `react-native-vector-icons`
- `react-native-geolocation-service`

The app relies on the backend Redis cache layer for faster chat and recommendation responses in local development, but the backend is designed to keep working even if Redis is briefly unavailable.

## Features

- public restaurant browsing
- Home-driven search and discovery
- restaurant menu browsing
- menu item detail flow
- single-restaurant cart and checkout
- cart replacement confirmation modal when switching restaurants
- order success flow
- order history and order detail flow
- AI chat
- generated combo discovery
- profile and account settings
- modal location selection flow

Generated combo cart behavior follows one strict rule:

- `MenuItem.is_veg` is the only source of truth for veg/non-veg status
- combo items carry their own `menu_item_id` and `is_veg`
- combo add-to-cart and combo upsells must preserve each item's own `is_veg`

## Project Structure

```text
mobile/
├── android/
├── ios/
├── src/
│   ├── components/
│   │   ├── AppHeader.tsx
│   │   ├── AuthScreenLayout.tsx
│   │   ├── CartReplacementModal.tsx
│   │   ├── CategoryChips.tsx
│   │   ├── ChatBubble.tsx
│   │   ├── MenuItemCard.tsx
│   │   ├── OrderStepper.tsx
│   │   ├── RestaurantCard.tsx
│   │   ├── SkeletonBlock.tsx
│   │   ├── ToastHost.tsx
│   │   └── home/
│   ├── data/
│   │   ├── homeCategories.ts
│   │   ├── mockLocations.ts
│   │   └── searchSuggestions.ts
│   ├── hooks/
│   │   └── useAppStore.ts
│   ├── navigation/
│   │   ├── AppNavigator.tsx
│   │   ├── navigationService.ts
│   │   └── navigationTypes.ts
│   ├── screens/
│   │   ├── auth/
│   │   │   ├── login/
│   │   │   └── register/
│   │   ├── cart/
│   │   ├── chat/
│   │   ├── home/
│   │   ├── location/
│   │   │   └── locationSelect/
│   │   ├── menuItem/
│   │   ├── orders/
│   │   │   ├── legacy/
│   │   │   ├── orderDetail/
│   │   │   ├── orderList/
│   │   │   └── orderSuccess/
│   │   ├── profile/
│   │   │   ├── appearance/
│   │   │   ├── components/
│   │   │   ├── details/
│   │   │   ├── helpSupport/
│   │   │   ├── notificationSettings/
│   │   │   ├── privacy/
│   │   │   └── savedAddresses/
│   │   ├── restaurant/
│   │   └── search/
│   ├── services/
│   │   ├── api.ts
│   │   ├── location.ts
│   │   ├── pushNotifications.ts
│   │   └── storage.ts
│   ├── store/
│   │   └── AppStore.tsx
│   ├── types/
│   │   ├── app.ts
│   │   └── react-native-vector-icons.d.ts
│   ├── utils/
│   │   ├── authRedirect.ts
│   │   └── generatedComboCart.ts
│   └── theme.ts
├── App.tsx
├── app.json
├── babel.config.js
├── index.js
├── package.json
└── tsconfig.json
```

## Navigation

### Bottom Tabs

- `Home`
- `Orders`
- `Chat`
- `Profile`

### Stack Screens

- `Restaurant`
- `MenuItemDetail`
- `Search`
- `Cart`
- `OrderSuccess`
- `OrderList`
- `OrderDetail`
- `Login`
- `Register`
- `ProfileDetails`
- `SavedAddresses`
- `LocationSelect`
- `NotificationSettings`
- `Privacy`
- `Appearance`
- `HelpSupport`

### Notes

- `Search` is a dedicated stack screen opened from the Home search prompt
- `LocationSelect` opens as a `modal`
- `Restaurant` uses its own in-screen header
- `OrderSuccess` opens only after a successful checkout response

## Core Flows

### Home

- loads restaurants
- loads generated combos for `Frequently Ordered Together`
- loads `Offers` for authenticated users when generated or reusable live campaigns are eligible
- loads `Personalized Picks` for both guests and logged-in users
- guest picks come from preference-context or public fallback recommendations
- logged-in picks prefer authenticated recommendations first, then degrade gracefully to fallback data
- logged-in personalization is preference-first, but also learns from paid order history over time
- recommendation cards can show backend-driven labels such as `Matches Your Taste` or `Trending Now`
- offer cards are backend-driven and additive to the recommendation feed
- Home should never go empty if personalization fails; fallback recommendations still render
- recommendation cards open `MenuItemDetail` directly
- offer cards open either `MenuItemDetail` or `Restaurant`, depending on the backend target
- `+ Add` from recommendation cards updates only cart state without refetching the Home feed
- normal item-add flows can also trigger a contextual offer bottom sheet when an eligible live offer exists
- Home uses a sticky top header with profile, location, cart, and notification actions
- recent orders load when authenticated
- opens the location picker modal from the address chip
- opens the dedicated `Search` screen from the search prompt

### Restaurant

- fetches restaurant detail by `restaurantId`
- fetches menu items on load
- fetches generated combos for that restaurant
- restaurant header uses the same compact cart icon pattern as Home
- branch hero now exposes only the fulfillment modes enabled for that location
- restaurant screen keeps the cart's `DELIVERY` / `PICKUP` mode aligned with branch rules
- ASAP availability now also respects the remaining live service window:
  - if `now + prep_buffer` would run past the active slot or branch closing time, ASAP is unavailable
  - the UI surfaces a concise closing-soon message instead of allowing a broken ASAP state
- if the selected fulfillment mode is outside the branch slot window, the screen shows an unavailable message and blocks add-to-cart
- scheduled selections are revalidated against the live backend slot list when the branch changes or the screen refreshes
- add-to-cart updates only the affected row/cart quantity without reloading the menu list
- menu rows can show a lighter new-item badge for recent launches
- supports category filtering, loading, retry, and empty states

### Menu Item

- fetches the latest item detail by `itemId`
- supports size and customization selection when the menu item is configured for it
- keeps simple items on the original one-tap add flow
- supports add-to-cart with auth guard
- uses a compact sticky bottom action area for add/update cart actions
- can display new-item badge/reason metadata for recently launched dishes

### Cart and Checkout

- single-restaurant cart
- generated combo cards add their underlying items into the existing cart flow
- restaurant offers are now surfaced inline on the restaurant screen instead of blocking add-to-cart with an offer sheet
- cart can show an active personalized-offer banner and projected discount preview when the current cart matches the selected offer
- cart can suggest missing same-restaurant combo items as upsells
- combo item veg/non-veg display comes from each cart item's own `menuItem.is_veg`
- generated combo mapping uses `src/utils/generatedComboCart.ts` to preserve item-level `is_veg`
- trying to add an item from a different restaurant opens a confirmation modal instead of a toast
- if `Clear & Add` replaces the cart with another restaurant, the new matching offer is preserved and the old offer is cleared
- guarded for guests through the shared auth redirect helper
- cart fulfillment toggle now respects the selected branch:
  - delivery is hidden/switched away when `delivery_enabled=false`
  - pickup is hidden/switched away when `pickup_enabled=false`
  - checkout is blocked when the branch is outside the active slot for the selected fulfillment type
- cart now revalidates scheduled selections when the screen opens, when the app returns to foreground, and again right before checkout
- if a scheduled slot expires or becomes invalid, cart shows a clear message and reopens fulfillment selection so the user can pick another time
- if the user tries to switch into `DELIVERY` without an address, the app sends them to address selection first instead of silently landing in an incomplete delivery state
- stale restored fulfillment state now heals safely:
  - invalid scheduled timestamps are downgraded away from broken persisted state during restore
  - invalid branch/mode combinations auto-switch only when one safe fallback mode exists
  - outdated scheduled slots are rejected by live revalidation before checkout
- cart no longer places the order directly
- cart now routes into a dedicated `Payment` screen after fulfillment/address validation succeeds
- payment screen is intentionally compact and shows only:
  - selected restaurant + branch
  - fulfillment summary
  - final payable amount
  - applied offer, if any
  - branch-enabled payment methods
- enabled payment methods come from the selected `restaurant_location_id`
- mobile only renders methods returned by backend for that branch:
  - `Google Pay`
  - `Razorpay`
  - `Pay by Card`
  - `Cash on Delivery`
- payment behavior:
  - `COD` places the order directly
  - online methods complete a payment step first, then place the order
- final order placement still happens through the backend
- eligible checkouts send `generated_offer_id` when present, plus `personalized_offer_id` for backward compatibility, so backend can validate and apply the correct offer source
- redirects successful payment/order placement to `OrderSuccess`

### Orders

- `Orders` tab uses `OrderListScreen`
- `OrderList` fetches `GET /api/orders`
- `OrderDetail` fetches `GET /api/orders/{id}`
- `OrderList` uses compact hero and tighter order cards
- `OrderDetail` includes hero status summary, accordion tracking, restaurant info, delivery details, ordered items, bill summary, and post-order actions

### Push Notifications Phase 1

Phase 1 mobile push support currently includes only:

- payment success plus order placed notifications

Behavior by state:

- foreground:
  - Firebase Messaging receives the remote push
  - Notifee displays a local notification
- background:
  - the OS shows the remote notification
  - tapping it routes through `messaging().onNotificationOpenedApp(...)`
- killed:
  - the OS shows the remote notification
  - tapping it routes through `messaging().getInitialNotification()`

Deep link handling:

- `notification_type = order_placed`
  - opens `OrderDetail`
  - passes the exact `orderId`

Key files:

- [src/services/pushNotifications.ts](/Users/imac/Desktop/restaurant-rag/mobile/src/services/pushNotifications.ts)
- [src/navigation/navigationService.ts](/Users/imac/Desktop/restaurant-rag/mobile/src/navigation/navigationService.ts)
- [index.js](/Users/imac/Desktop/restaurant-rag/mobile/index.js)
- [App.tsx](/Users/imac/Desktop/restaurant-rag/mobile/App.tsx)

### Profile

- compact profile hero with left-aligned avatar, inline identity, and edit action
- order history entry
- saved addresses
- notification settings
- privacy
- appearance
- help and support

### Location Selection

- debounced location search
- current location flow via `react-native-geolocation-service`
- reverse geocoding fallback
- global selected-location persistence

## State and Persistence

Main app state lives in:

- [src/store/AppStore.tsx](/Users/imac/Desktop/restaurant-rag/mobile/src/store/AppStore.tsx)

Persisted with AsyncStorage:

- auth session
- cart
- chat session id
- selected location
- local user preferences
- preferences onboarding completion

Fulfillment persistence notes:

- the cart remains the long-term source of truth for:
  - `restaurantId`
  - `restaurantLocationId`
  - `fulfillmentType`
  - `scheduleType`
  - `scheduledAt`
- restored carts are normalized before use so obviously broken scheduled timestamps do not survive app restart
- branch-specific drafts on the restaurant screen still exist for smoother switching, but live backend validation now wins whenever the app refreshes, foregrounds, or prepares checkout

Storage keys:

- `restaurant-rag-mobile-auth`
- `restaurant-rag-mobile-cart`
- `restaurant-rag-mobile-chat-session`
- `restaurant-rag-mobile-location`

## API Layer

Main API client:

- [src/services/api.ts](/Users/imac/Desktop/restaurant-rag/mobile/src/services/api.ts)

Used endpoints:

- `POST /api/auth/login`
- `POST /api/auth/register`
- `GET /api/restaurants`
- `GET /api/restaurants/{restaurant_id}`
- `GET /api/menu-items?restaurant_id=...`
- `GET /api/menu-items/{menu_item_id}`
- `GET /api/generated-combos`
- `GET /api/restaurants/{restaurant_id}/generated-combos`
- `GET /api/recommendations`
- `GET /api/generated-combos/cart-upsell`
- `POST /api/recommendations/query`
- `GET /api/preferences/me`
- `PUT /api/preferences/me`
- `GET /api/chat/history`
- `POST /api/chat/message`
- `POST /api/chat/message/stream` for streamed responses when supported by the client/runtime
- `DELETE /api/chat/history`
- `POST /api/orders`
- `GET /api/orders`
- `GET /api/orders/{order_id}`
- `POST /api/notifications/device-tokens`

Auth flow:

- mobile customer login uses `country code + phone number + password` in the UI and sends the combined international `phone_number` to `POST /api/auth/login`
- mobile register collects `full_name + country code + phone number + email + password`
- mobile registration sends OTP with Firebase Phone Auth using the full international number, then only calls `POST /api/auth/register` after OTP verification succeeds
- OTP verification happens in a dedicated screen that shows the selected country code and local phone number together
- the country picker is visible on login and register, defaults to India (`+91`), and uses a searchable country list
- backend still returns the same JWT/session response shape used by the app store
- normal login does not require OTP; it stays backend JWT based with `phone_number + password`
- logout and session restore remain AsyncStorage-based; Firebase is only used during registration-time phone verification
- push token registration happens after auth/session restore so mobile can sync the current FCM token to backend

Chat notes:

- the chat screen stores the active `session_id` locally and restores it on relaunch
- the mobile clear-chat action uses `DELETE /api/chat/history`
- follow-up turns like `show me more` continue the latest backend topic, while a new explicit dish query like `pizza` or `burger` replaces the old topic
- repeated generic queries and greeting/thanks turns benefit from backend Redis fast paths

Base URL selection:

- Android emulator: `http://10.0.2.2:8000/api`
- iOS simulator: `http://127.0.0.1:8000/api`
- fallback: `http://localhost:8000/api`

## Import Aliases

Configured in:

- [babel.config.js](/Users/imac/Desktop/restaurant-rag/mobile/babel.config.js)
- [tsconfig.json](/Users/imac/Desktop/restaurant-rag/mobile/tsconfig.json)

Available aliases:

- `@` → `src`
- `@screens` → `src/screens`
- `@components` → `src/components`
- `@services` → `src/services`
- `@hooks` → `src/hooks`
- `@store` → `src/store`
- `@types` → `src/types`
- `@utils` → `src/utils`

Note:

- project code uses `@/types/...` for type imports because TypeScript treats bare `@types/...` specially

## Setup

Install dependencies:

```bash
cd mobile
npm install
```

Install iOS pods:

```bash
cd mobile
npm run install
```

Start Metro:

```bash
cd mobile
npm run start
```

Run iOS:

```bash
cd mobile
npm run ios
```

Run Android:

```bash
cd mobile
npm run android
```

## Scripts

- `npm run start`
- `npm run ios`
- `npm run android`
- `npm run lint`
- `npm run test`
- `npm run install`

## Notes

- The app uses `SafeAreaProvider` and safe-area-aware layouts.
- Bottom tab spacing is customized for iOS and Android.
- Location search currently uses a mobile-first modal flow with local suggestions and GPS lookup integration.
- Order success and order history flows are fully connected to the existing backend APIs.
- Toasts are globally safe-area aware, animated, and color-coded for success, error, and info states.
- `Personalized Picks` should never disappear just because authenticated personalization fails; the home feed must fall back to non-auth recommendation data when needed.
- Guest users personalize from AsyncStorage-backed preferences and public recommendation queries only.
- Logged-in users sync preferences to the backend, then combine backend preferences with paid order-history signals.
- Repeated paid orders can influence recommendations before final delivery, so items from `PLACED`, `ACCEPTED`, `PREPARING`, `OUT_FOR_DELIVERY`, and `DELIVERED` orders can all help reorder `Personalized Picks`.
- Restaurant menu ordering uses the same recommendation scores, so Home ranking and restaurant item ranking stay aligned.
- Recommendation-driven item surfaces now open the shared `MenuItemDetail` screen directly, while keeping `+ Add` isolated to cart updates.
- Chat uses immediate optimistic user messages, assistant placeholders, and backend-safe fallbacks so the UI never sits blank during slow model responses.
- Chat can ask grounded new-item questions such as `what's new?` and `new spicy food`, with suggestion cards sourced only from backend menu data.

## Recommended New Items

The mobile client now renders the backend's new-item recommendation metadata instead of trying to infer launch state locally.

Surfaces:

- Home `Personalized Picks`
- restaurant menu cards
- menu item detail
- chat suggestion cards when the backend returns new-item suggestions

Labels currently supported:

- `Based on Your Orders`
- `Matches Your Taste`
- `Trending Now`
- `Just Launched`
- `Recommended for You`

Rules:

- the client only renders backend payload fields such as `is_new`, `is_new_launch`, `recommendation_label`, and `recommendation_reason`
- mobile shows one compact backend-provided badge and does not invent or remap labels
- the existing add-to-cart, favorites, cart validation, and generated-combo flows are unchanged

## Multi-location customer flow

Mobile ordering now mirrors the web branch model:

- restaurant detail selects an active branch by default
- users can switch branches from the restaurant summary area
- menu items, combos, and cart validation all follow the selected branch
- each branch now carries branch-level fulfillment settings:
  - `delivery_enabled`
  - `pickup_enabled`
  - delivery / pickup ETA
  - delivery fee / minimum order
  - weekly slots per fulfillment type
- ASAP now depends on both branch status and prep cutoff:
  - open + enabled alone is not enough
  - the backend also requires the current slot or closing window to have enough time left for preparation
- the cart no longer allows mixing two branches from the same restaurant brand
- checkout sends the selected `restaurant_location_id`
- checkout also sends the selected `fulfillment_type`, and the backend revalidates:
  - branch open / active state
  - delivery / pickup enablement
  - ASAP closing-soon cutoff
  - scheduled slot validity
  - minimum order and delivery fee rules
- checkout/order placement also sends the selected `payment_method`
- backend rejects the order if that payment method is disabled for the selected branch

## Fulfillment Reliability

The current mobile fulfillment flow now adds production-style runtime safeguards without changing the core architecture.

- ASAP is unavailable when the remaining branch window is shorter than the required preparation buffer.
- Scheduled slots are validated from live backend schedule data, not only persisted local state.
- Foreground refresh keeps branch availability and scheduled-order safety closer to real time without aggressive polling.
- The fulfillment sheet refreshes live schedule options before confirming ASAP or a scheduled slot, so expired slots cannot remain selectable.
- Delivery selection now requires an address before the mode change is finalized.

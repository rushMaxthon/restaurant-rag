# Restaurant RAG

`restaurant-rag` is a monorepo for a multi-restaurant ordering platform with RAG-based food chat and personalized recommendations.

It contains:

- a FastAPI backend
- a customer web app
- an admin/owner web app
- a React Native CLI mobile app

## Repository Structure

```text
restaurant-rag/
├── backend/              FastAPI, PostgreSQL, pgvector, Celery, Redis, Ollama
├── frontend-admin/       Shared admin + owner dashboard
├── frontend-customer/    Customer web application
├── mobile/               React Native CLI customer application
└── README.md
```

## System Overview

### Backend

`backend/` is the source of truth for:

- authentication
- role-based authorization
- restaurant and owner relationships
- menu and order rules
- recommendation scoring
- generated combos from real order patterns
- RAG chat orchestration
- background embedding and notification jobs
- Redis-backed caching for chat sessions, embeddings, responses, and recommendations

### Customer Clients

`frontend-customer/` and `mobile/` share the same customer-facing API behavior:

- public restaurant browsing
- public menu browsing
- menu item detail fetch by item ID
- auth guard for add-to-cart, cart access, and checkout
- personalized picks for both guest and authenticated sessions
- authenticated recommendations
- authenticated favorites with optimistic sync across web and mobile
- authenticated AI chat
- single-restaurant cart
- order placement and order history
- branch-aware payment method selection before final order placement

They also now share the same protected-cart UX rule:

- guests can browse restaurants and menu items freely
- guests are redirected to login when they try to add to cart, open cart, or place an order
- after login or registration, users return to the same screen and keep their context
- only `CUSTOMER` accounts are allowed to keep a customer-app session
- `ADMIN` and `OWNER` accounts are rejected from customer login and cleared on app restore if stored accidentally

The mobile client additionally includes:

- shared-header spacing normalization for stack screens
- sticky menu-item detail actions
- redesigned cart checkout with a bottom action bar
- `Cart -> Payment -> OrderSuccess` flow instead of direct order placement from cart
- Phase 1 customer push notifications for:
  - automatic prepaid order placed confirmations

### Admin App

`frontend-admin/` is one shared web UI for:

- `ADMIN`
- `OWNER`

The UI is shared. Visibility and data are filtered by role.

Reporting rules:

- `ADMIN` can view platform-wide analytics across all restaurants
- `OWNER` can view analytics only for their assigned restaurant
- report filtering is enforced by the backend, not only hidden in the UI

Access rule:

- only `ADMIN` and `OWNER` accounts can access `frontend-admin/`
- `CUSTOMER` accounts are rejected from admin login and cleared on app restore if stored accidentally

## Key Product Rules

- one `OWNER` is linked to exactly one restaurant
- admins create restaurants and the linked owner account
- owners cannot access other restaurants
- customer accounts cannot access the admin panel
- admin/owner accounts cannot access the customer web app
- customers can browse restaurants and menus without logging in
- customers must log in before adding to cart, opening cart, or placing orders
- only `CUSTOMER` accounts can create or remove favorites
- cart is limited to one restaurant at a time
- LLM responses must be constrained by backend-provided menu context

## AI Features

### Recommendations

The backend scores menu items using:

- preference match
- order history
- cuisine and category match
- diet match
- popularity

It also now supports personalized recommendation of newly launched menu items.

Current new-item behavior:

- menu items are treated as new when `launched_at` is within the configurable backend window
- the default source of truth is `MenuItem.launched_at`
- explicit taste and behavior signals decide whether a new item should be boosted
- labels are assigned by backend scoring, not handcrafted in the clients
- old items do not receive new-item badges once they fall outside the launch window

For authenticated users, personalization now learns from paid order history as soon as an order enters the live order lifecycle. That means repeated orders in `PLACED`, `ACCEPTED`, `PREPARING`, `OUT_FOR_DELIVERY`, and `DELIVERED` states can all start influencing `Personalized Picks` and restaurant menu ordering, instead of waiting only for final delivery.

New-item recommendation labels currently include:

- `New for You`
- `New Spicy Pick`
- `Based on Your Orders`
- `New Italian Favorite`

Scoring stays backend-driven:

- explicit preference match remains strongest
- paid order history is the next strongest signal
- cuisine/category and diet refine the ranking
- popularity is only a light fallback
- new-item boosts apply only when the new dish actually matches the user or when fallback discovery is needed

### Favorites

Customers can now favorite available menu items from both the web and mobile apps.

Current behavior:

- favorites are stored in the backend as a user-to-menu-item relationship
- duplicate favorites for the same user and item are prevented at the database level
- only active, approved, available menu items can be favorited
- favorite state is exposed back on menu item, recommendation, chat suggestion, and combo item payloads as `is_favorite`
- the backend remains the source of truth, while clients use optimistic UI and refetch only the favorite-specific data they need

### Generated Combos

The platform now auto-detects items that are frequently ordered together and stores them as generated combos.

Examples:

- pizza + drink
- burger + shake
- momos + cold drink

Current behavior:

- generated from real delivered/paid orders only
- never crosses restaurant boundaries
- excludes unavailable items
- respects restaurant active/approved state
- every combo item keeps its original `menu_item_id`
- every combo item exposes `is_veg` from `MenuItem.is_veg`
- customers add combo items through the normal cart flow, so checkout does not need a separate combo order path
- clients must preserve item-level `is_veg` when mapping combo items into cart rows and must not default missing values to non-veg

### RAG Chat

The backend:

1. loads Redis/history-backed chat session memory
2. uses lightweight backend intent detection first for simple deterministic turns like `pizza`, `burger`, greetings, thanks, and `food under 300`
3. only calls Qwen intent extraction when that lightweight parser is not reliable enough
4. supports follow-up turns like `show me more` by using the most recent active recommendation topic and excluding already suggested items
5. treats a new explicit dish query like `pizza` or `burger` as a fresh topic instead of reusing the old one
6. runs keyword and/or pgvector retrieval from PostgreSQL using that structured intent
7. reuses Redis-cached embeddings and generic normalized chat responses when available
8. filters results using real business rules
9. can skip final Qwen generation when grounded keyword matches already give a safe answer
10. builds strict prompt context from live menu data only when needed
11. streams or returns the grounded response from Ollama
12. falls back to safe DB-backed suggestions if the model is slow or fails
13. returns structured suggestion items for the UI

The chat layer is combo-aware too. Queries like `suggest combos`, `pizza combo`, and `combo under 500` are grounded only in generated-combo rows from the backend.

The chat layer is now new-item aware too. Queries such as `what's new?`, `new spicy food`, `new items for me`, and `new Italian dishes` are resolved against real backend menu rows only. The model is allowed to phrase the answer, but it is not allowed to invent new dishes.

Generic response cache is intentionally limited to non-personalized, non-follow-up queries, so turns like `show me more` still use live session memory instead of shared cache. For cacheable generic item/category requests, the backend now uses topic-based keys so queries like `do you have dessert?`, `dessert?`, and `any dessert available?` can reuse the same Redis response. Simple spacing and punctuation variants such as `Do you have pasta?` and `do you have pasta ?` normalize to the same cache key too.

### Redis Usage

Redis is used for:

- chat session cache
- query embedding cache
- repeated non-personalized chat response cache
- per-user recommendation cache
- Celery broker and result backend

All cache keys expire automatically after 3 days:

- `259200` seconds

## Local Development Setup

### Prerequisites

- Python 3.11+
- Node.js 22+
- PostgreSQL
- Redis
- Ollama
- Android Studio for Android development
- Xcode + CocoaPods for iOS development

## Start Order

### 1. Backend

From `backend/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
alembic upgrade head
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Redis and Celery

From `backend/`:

```bash
redis-server
redis-cli ping
celery -A app.config.celery:celery_app worker --loglevel=info -Q embeddings,notifications,default,analytics
```

### 3. Ollama

```bash
ollama serve
ollama pull qwen3:8b
ollama pull nomic-embed-text
```

### 4. Customer Web

From `frontend-customer/`:

```bash
npm install
npm run dev
```

### 5. Admin Web

From `frontend-admin/`:

```bash
npm install
npm run dev
```

### 6. Mobile

From `mobile/`:

```bash
npm install
npm run install
npm run start
npm run android
npm run ios
```

## Commands by App

### Backend

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
alembic upgrade head
python seed.py
redis-server
redis-cli ping
celery -A app.config.celery:celery_app worker --loglevel=info -Q embeddings,notifications,default
python3 -m compileall app alembic
```

Recent backend migrations include:

- `0003_mobile_pref_fields`
- `0004_chat_perf_indexes`
- `0005_remove_rating_review_flow`
- `0006_generated_combos`
- `0009_menu_item_launch_window`

### Frontend Admin

```bash
npm run dev
npm run build
npm run lint
npm run preview
```

### Frontend Customer

```bash
npm run dev
npm run build
npm run lint
npm run preview
```

### Mobile

```bash
npm run start
npm run android
npm run ios
npm run install
npm run lint
npm run test
./node_modules/.bin/tsc --noEmit
```

## Where to Make Changes

- backend business rules: `backend/app/services/`
- backend routes and contracts: `backend/app/api/` and `backend/app/schemas/`
- DB models and migrations: `backend/app/models/` and `backend/alembic/versions/`
- admin UI: `frontend-admin/src/pages/`, `frontend-admin/src/components/`
- customer web UI: `frontend-customer/src/pages/`, `frontend-customer/src/components/`
- mobile UI: `mobile/src/screens/`, `mobile/src/components/`, `mobile/src/navigation/`

## Verification Commands Used In This Repo

- `python3 -m compileall backend/app backend/alembic`
- `npm run build` in `frontend-admin/`
- `npm run build` in `frontend-customer/`
- `./node_modules/.bin/tsc --noEmit` in `mobile/`

## Push Notifications Phase 1

Phase 1 intentionally supports only one customer push event:

- payment success plus order placed notifications sent automatically after successful prepaid checkout

Deep linking currently supports direct notification open into:

- `OrderDetail`

Details:

- [docs/push-notification-phase1.md](/Users/imac/Desktop/restaurant-rag/docs/push-notification-phase1.md)

## Per-App User Identity

Customer accounts belong to one app: the same phone/email in the Marketplace app
and in a single-restaurant app are two separate accounts, each with their own
orders, favorites and preferences. Tokens are bound to their app, so a Bangkok
Bowl session cannot be used in the Marketplace app.

Details: [docs/per-app-identity.md](/Users/imac/Desktop/restaurant-rag/docs/per-app-identity.md)

## Read Next

- [backend/README.md](/Users/imac/Desktop/restaurant-rag/backend/README.md)
- [frontend-admin/README.md](/Users/imac/Desktop/restaurant-rag/frontend-admin/README.md)
- [frontend-customer/README.md](/Users/imac/Desktop/restaurant-rag/frontend-customer/README.md)
- [mobile/README.md](/Users/imac/Desktop/restaurant-rag/mobile/README.md)
- [docs/location-slot-demo-reference.md](/Users/imac/Desktop/restaurant-rag/docs/location-slot-demo-reference.md)
## Multi-location restaurants

The platform now supports a two-level restaurant model:

- `Restaurant` = brand-level identity used for discovery, ownership, and shared branding
- `RestaurantLocation` = the actual orderable branch/outlet used for menu, orders, delivery rules, and generated combos

Key behavior:

- each restaurant can have many active locations
- menu items are assigned to a specific `restaurant_location_id`
- orders are created against a single location
- each location now owns its own fulfillment controls:
  - `delivery_enabled`
  - `pickup_enabled`
  - delivery fee / minimum order / ETA / pickup ETA
  - temporary closed reason / preparation metadata
- each location also owns its enabled payment methods:
  - `google_pay_enabled`
  - `razorpay_enabled`
  - `card_payment_enabled`
  - `cash_on_delivery_enabled`
- each location can also define weekly fulfillment slots per day and per fulfillment type
- generated combos are rebuilt and served per location only
- customer cart scope is now `restaurant + location`, so different branches of the same brand cannot mix in one cart
- owners manage only locations under their own restaurant; admins can manage all locations
- customer web and mobile restaurant detail screens auto-select an active branch and let the user switch branches before ordering
- ASAP now requires enough remaining branch time for preparation, so “open right now” is not enough on its own near closing time
- checkout now validates location state, fulfillment toggle state, ASAP prep cutoff, weekly slot availability, minimum order, and delivery-fee rules again on the backend before placing the order
- payment method availability is also branch-scoped:
  - mobile shows only the methods returned by the selected location
  - backend rejects any payment method that is disabled for that branch
  - COD creates the order directly
  - online methods complete payment first and then place the order
- mobile additionally revalidates scheduled slots on screen open, app foreground, and before checkout so stale persisted times can recover before the backend has to reject them

## Auth Notes

- backend JWT auth remains the shared source of truth for web and mobile sessions
- customer mobile now signs in with `country code + phone number + password`, which the app submits as one international `phone_number`
- customer mobile registration collects `full_name`, `country code`, `phone_number`, `email`, and `password`
- mobile registration verifies the phone number first with Firebase Phone OTP, then creates the backend customer and stores the normal JWT session
- mobile login stays backend-only and does not require OTP on every sign-in
- admin and owner web login continue to use `email + password`

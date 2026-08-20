# Backend

`backend/` is the FastAPI service for the Restaurant RAG platform. It owns authentication, restaurant and owner management, menu CRUD, recommendations, chat/RAG, order workflows, and background tasks.

This is the API used by:

- `frontend-customer/`
- `frontend-admin/`
- `mobile/`

## What This Backend Does

- exposes the REST API under `/api`
- authenticates users with JWT
- enforces role-based access for `ADMIN`, `OWNER`, and `CUSTOMER`
- stores restaurants, menu items, user preferences, orders, and chat history
- stores user favorites as a protected customer-only relationship to menu items
- exposes role-scoped analytics reports for `ADMIN` and `OWNER`
- generates recommendations from preference, order-history, cuisine/category, diet, and popularity signals
- computes new-item launch metadata, detection signals, and recommendation labels for newly launched dishes
- generates auto-combos from repeated delivered order patterns
- serves a reusable first-order welcome offer and daily AI-powered personalized offers with backend guardrails
- runs retrieval-augmented chat using PostgreSQL + pgvector + Ollama
- dispatches async embedding and notification tasks through Celery

## Tech Stack

- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic
- PostgreSQL
- pgvector
- Celery
- Redis
- Ollama
- `python-jose` for JWT
- `passlib[bcrypt]` for password hashing
- `httpx` for LLM calls

## Redis Setup

Redis is used here for:

- chat session cache
- query embedding cache
- common chat response cache
- per-user recommendation cache
- Celery broker and result backend

PostgreSQL remains the source of truth. Redis is only used for caching, sessions, and background-job plumbing.

### Install Redis

macOS with Homebrew:

```bash
brew install redis
```

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install redis-server
```

Docker:

```bash
docker run --name restaurant-rag-redis -p 6379:6379 -d redis:7
```

### Start Redis

macOS with Homebrew:

```bash
brew services start redis
```

Linux service:

```bash
sudo systemctl start redis
```

Foreground run:

```bash
redis-server
```

### Verify Redis

```bash
redis-cli ping
```

Expected output:

```text
PONG
```

### `.env` settings

```env
REDIS_URL=redis://localhost:6379/0
REDIS_CACHE_TTL_SECONDS=259200
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
```

### Cache TTL

All Redis cache keys are written with a 3-day TTL:

- `259200` seconds

This applies to:

- chat session cache
- embedding cache
- chat response cache
- recommendation cache

Redis handles expiration automatically, so no cleanup job is needed.

## Folder Structure

```text
backend/
├── app/
│   ├── api/              # FastAPI routers
│   ├── config/           # settings, DB, Celery
│   ├── models/           # SQLAlchemy models
│   ├── schemas/          # Pydantic request/response models
│   ├── services/         # auth, orders, recommendations, RAG, Ollama
│   ├── tasks/            # Celery tasks
│   └── main.py           # app entrypoint
├── alembic/
│   ├── env.py
│   └── versions/
├── alembic.ini
├── requirements.txt
└── seed.py
```

## Important Files

- [app/main.py](/Users/imac/Desktop/restaurant-rag/backend/app/main.py)
  - creates the FastAPI app
  - configures CORS
  - mounts all API routers under `settings.api_v1_prefix`
  - exposes `GET /health`

- [app/config/settings.py](/Users/imac/Desktop/restaurant-rag/backend/app/config/settings.py)
  - reads `.env`
  - builds the SQLAlchemy connection string
  - parses CORS and debug values

- [app/config/database.py](/Users/imac/Desktop/restaurant-rag/backend/app/config/database.py)
  - SQLAlchemy engine and session factory
  - `initialize_pg_extensions()` for `CREATE EXTENSION IF NOT EXISTS vector`

- [app/config/celery.py](/Users/imac/Desktop/restaurant-rag/backend/app/config/celery.py)
  - Celery app
  - routes embedding, notification, generated-combo, and AI-offer analytics jobs

- [app/services/cache.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/cache.py)
  - shared Redis client helpers
  - cache get/set/delete wrappers
  - pattern invalidation helpers

- [app/services/auth.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/auth.py)
  - password hashing
  - JWT creation and decoding
  - shared role dependencies
  - owner restaurant resolution

- [app/services/recommendations.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/recommendations.py)
  - recommendation ranking

- [app/services/menu_item_metadata.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/menu_item_metadata.py)
  - `launched_at` / new-item helpers
  - keyword-based signal detection for spicy, cheese, chicken, paneer, cuisines, diet, and dish families
  - recommendation-label helpers shared by recommendations and chat

- [app/services/generated_combos.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/generated_combos.py)
  - generated combo detection, scoring, listing, and cart upsell logic
  - combo item responses preserve `menu_item_id` and `MenuItem.is_veg`

- [app/services/ai_offer_generation.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/ai_offer_generation.py)
  - daily AI-native offer generation
  - Qwen/Ollama prompt assembly, duplicate prevention, validation, fallback, and persistence

- [app/services/rag.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/rag.py)
  - embeddings
  - pgvector retrieval
  - session-aware follow-up recommendation memory
  - prompt construction
  - response generation
  - chat persistence

- [app/services/orders.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/orders.py)
  - order validation
  - totals
  - status transitions

- [app/tasks/embed.py](/Users/imac/Desktop/restaurant-rag/backend/app/tasks/embed.py)
  - background embedding generation for menu items

- [app/tasks/generated_combos.py](/Users/imac/Desktop/restaurant-rag/backend/app/tasks/generated_combos.py)
  - background generated-combo rebuild task

- [app/tasks/ai_offers.py](/Users/imac/Desktop/restaurant-rag/backend/app/tasks/ai_offers.py)
  - daily and manually triggered AI offer generation task

- [app/tasks/notifications.py](/Users/imac/Desktop/restaurant-rag/backend/app/tasks/notifications.py)
  - background order status notification payload generation

## Current API Modules

Routers are registered in [app/api/**init**.py](/Users/imac/Desktop/restaurant-rag/backend/app/api/__init__.py).

- `auth.py`
  - login and registration
- `restaurants.py`
  - public restaurant listing
  - restaurant detail
  - admin restaurant creation with linked owner creation
  - owner/admin restaurant settings updates
- `menu_items.py`
  - public restaurant menu listing
  - public menu item detail fetch by ID
- `favorites.py`
  - `POST /api/favorites/{menu_item_id}`
  - `DELETE /api/favorites/{menu_item_id}`
  - `GET /api/favorites`
  - `GET /api/favorites/ids`
  - admin/owner menu CRUD
- `orders.py`
  - customer order placement
  - customer/admin/owner order listing
  - owner order status updates
- `generated_combos.py`
  - generated combo listing, combo detail, cart upsell suggestions
  - admin combo rebuild and active/inactive management
- `recommendations.py`
  - authenticated customer recommendations
- `chat.py`
  - authenticated customer chat, streaming chat, and history
- `admin.py`
  - admin dashboard, moderation, users, AI logs, menu views
  - admin AI offer generation queue + task-status endpoints
- `reports.py`
  - `GET /api/reports`
  - shared analytics endpoint for `ADMIN` and `OWNER`
  - backend-enforced date, restaurant, cuisine/category, and order-status filtering
  - owner scope is locked to the caller's restaurant even if another `restaurant_id` is requested
- `notifications.py`
  - `POST /api/notifications/device-tokens`
  - `POST /api/admin/notifications/send`
  - `GET /api/admin/notifications/history`
  - Phase 1 customer push support for automatic order-placed notifications

## Database Model Overview

Main models in [app/models/](/Users/imac/Desktop/restaurant-rag/backend/app/models):

- `User`
  - roles: `ADMIN`, `OWNER`, `CUSTOMER`
- `Restaurant`
  - strict `1:1` owner mapping through `owner_id`
- `MenuItem`
  - belongs to one restaurant
- `MenuEmbedding`
  - vector row for a menu item
- `UserPreferences`
  - budget and cuisine preference data
- `Order`
  - belongs to a customer and a restaurant
- `OrderItem`
  - snapshot rows inside an order
- `GeneratedCombo`
  - auto-generated combo aggregate for one restaurant
- `GeneratedComboItem`
  - menu items included in a generated combo
  - uses `menu_item_id` to point back to the source `MenuItem`
  - never owns veg/non-veg truth separately from `MenuItem.is_veg`
- `ChatHistory`
  - stored user/assistant turns and context payloads

Migrations:

## Generated Combo Data Contract

Generated combos are derived data, but each included item still points back to the real menu item row.

Rules:

- `MenuItem.is_veg` is the only source of truth for veg/non-veg status
- generated combo responses must include item-level `is_veg`
- combo/cart clients must preserve that item-level value when mapping combo items into cart state
- combo-level veg labels, if a client derives them, should be `veg` only when all included items are veg

- [alembic/versions/0001_initial_schema.py](/Users/imac/Desktop/restaurant-rag/backend/alembic/versions/0001_initial_schema.py)
- [alembic/versions/0002_enforce_owner_one_to_one.py](/Users/imac/Desktop/restaurant-rag/backend/alembic/versions/0002_enforce_owner_one_to_one.py)
- [alembic/versions/0003_add_mobile_preference_fields.py](/Users/imac/Desktop/restaurant-rag/backend/alembic/versions/0003_add_mobile_preference_fields.py)
- [alembic/versions/0004_chat_performance_indexes.py](/Users/imac/Desktop/restaurant-rag/backend/alembic/versions/0004_chat_performance_indexes.py)
- [alembic/versions/0006_generated_combos.py](/Users/imac/Desktop/restaurant-rag/backend/alembic/versions/0006_generated_combos.py)

Apply schema updates after pulling backend changes:

```bash
cd backend
./.venv/bin/alembic upgrade head
```

`0003` adds the mobile/customer preference fields used by recommendations and profile preference editing:

- `user_preferences.spice_level`
- `user_preferences.budget_tier`
- `user_preferences.favorite_items`

`0004` adds the performance indexes used by the chat/RAG flow:

- `ivfflat` cosine index on `menu_embeddings.embedding`
- restaurant visibility index for active/approved filtering
- menu item availability and popularity index for faster fallback retrieval

## Ownership and Access Model

The current system uses a strict restaurant-owner relationship:

- one `OWNER` manages exactly one restaurant
- one restaurant has exactly one owner
- owners cannot self-register restaurants
- admins create restaurants and the linked owner account together

Backend enforcement is server-side, not just UI-side:

- owners can only see and modify their own restaurant resources
- admins can access all restaurants
- customers can browse public restaurant data and menus

## Authentication Flow

Routes:

- `POST /api/auth/register`
- `POST /api/auth/login`

Auth behavior:

- `POST /api/auth/register` creates users with `full_name`, `email`, `password`, and optional `phone_number`
- `email` stays required for all users
- `phone_number` is optional at the API level but unique when provided
- mobile stores the full international number in `phone_number` (for example `+919876543210`) instead of splitting `country_code` into a separate column
- `POST /api/auth/login` accepts either:
  - `email + password`
  - `phone_number + password`
- this keeps admin/owner web login compatible with email while allowing customer mobile login with phone number
- Firebase Phone Auth is used only by the mobile registration OTP step; backend JWT remains the system of record for sessions, roles, and authorization

### Per-app identity

Customer accounts are scoped by `users.app_client_id`: the same email or phone
can exist once per app client, so a Marketplace customer and a Bangkok Bowl
customer are separate accounts. `ADMIN` and `OWNER` carry no app client.

Access tokens include `app_client_id` and `token_version`, and a token issued
for one app is rejected (401) by another. `POST /api/auth/logout-all` bumps
`token_version` to invalidate every session for the calling account.

Full details, including the migration notes: [docs/per-app-identity.md](../docs/per-app-identity.md)

## Push Notifications Phase 1

Phase 1 currently supports only one customer push event:

- automatic prepaid order placed notifications

Backend push pieces:

- device token registration route:
  - `POST /api/notifications/device-tokens`
- admin notification history route:
  - `GET /api/admin/notifications/history`
- Firebase Admin sender:
  - [app/services/notifications.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/notifications.py)
- automatic order trigger:
  - [app/services/orders.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/orders.py)

Phase 1 payload behavior:

- `notification_type = order_placed`
- includes `order_id`
- mobile uses that payload to open `OrderDetail`

Automatic order notification rule:

- sent only when payment succeeds and order creation succeeds
- not sent for `COD`

Required Firebase backend settings:

- `FCM_PROJECT_ID`
- `FCM_CREDENTIALS_PATH`

The Firebase Admin service account file should live at the configured credentials path and must not be committed to git.

Login response shape:

```json
{
  "access_token": "jwt",
  "token_type": "bearer",
  "role": "OWNER",
  "restaurant_id": "uuid-or-null",
  "user": {
    "id": "uuid",
    "full_name": "Owner Name",
    "email": "owner@example.com",
    "role": "OWNER"
  }
}
```

Shared auth dependencies:

- `get_current_user`
- `get_current_user_optional`
- `require_admin`
- `require_owner`
- `require_customer`
- `resolve_owner_restaurant_id`

## Recommendation Flow

Recommendations are generated in [app/services/recommendations.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/recommendations.py).

Signals used by the scorer include:

- preference match
- exact favorite-item match
- order history
- cuisine and category match
- diet match
- item popularity

Authenticated recommendation ranking is designed to stay preference-first while learning from behavior over time:

- explicit user preferences remain the strongest signal
- repeated paid orders become the second strongest signal
- cuisine and category matching reinforce both preferences and order habits
- popularity is only a light fallback signal

### Recommended New Items

New menu items are now part of the same scoring pipeline.

Data model:

- `MenuItem.launched_at` is the source-of-truth launch timestamp
- `is_new` is computed from `launched_at` and the configurable backend launch window
- the launch window is controlled through backend settings, not hardcoded in clients

Signal detection is automatic:

- item `name`
- `description`
- `category`
- `cuisine_type`
- restaurant cuisine
- `is_veg`
- optional ingredient text when available later

Current keyword families include:

- `spicy`
- `cheesy`
- `chicken`
- `paneer`
- `veg`
- `non_veg`
- `cold_drink`
- `dessert`
- `pizza`
- `burger`
- `indian`
- `italian`
- `chinese`
- `thai`

New-item scoring rules:

- a new item is not boosted just because `launched_at` is recent
- a new item must be manually marked with `is_new_launch`
- boosts apply when the item matches user taste, cuisine, spice, diet, or order-history signals
- users with no useful profile/history can still get generally new/popular fallback items
- unavailable, inactive, or unapproved items are still excluded

Labels are assigned by backend logic and returned to clients:

- `Based on Your Orders`
- `Matches Your Taste`
- `Trending Now`
- `Best Seller`
- `Just Launched`
- `Recommended for You`

Dynamic Best Seller rules:

- scoped by branch / `restaurant_location_id`
- last `30` days by default
- minimum `25` valid orders by default
- counted statuses: `ACCEPTED`, `PREPARING`, `OUT_FOR_DELIVERY`, `DELIVERED`
- only available items at active / approved restaurants can qualify
- thresholds are configurable for future scaling

The personalized payload can also include a machine-readable explanation:

- `recommendation_reason`
- `new_item_reason`

Order-history learning currently uses paid customer orders in these statuses:

- `PLACED`
- `ACCEPTED`
- `PREPARING`
- `OUT_FOR_DELIVERY`
- `DELIVERED`

This is important for local development and QA because customer test orders are created as paid immediately, but may not always be manually advanced all the way to `DELIVERED`. Recommendations can still learn from those repeated orders without waiting for owner-side status progression.

Debug logging in `recommendations.py` now includes:

- loaded order-history status counts
- normalized item, category, and cuisine affinity signals
- per-item order-affinity score breakdown
- final sorted recommendation output

Authenticated recommendation results are cached in Redis under:

- `recommendations:{user_id}`

Recommendation payloads now also carry:

- `launched_at`
- `is_new`
- `recommendation_label`
- `recommendation_reason`
- `new_item_reason`

## Offers / Campaigns

Personalized offers are implemented separately from recommendation ranking in:

- [app/services/personalized_offers.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/personalized_offers.py)
- [app/services/ai_offer_generation.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/ai_offer_generation.py)

Current behavior:

- zero-order customers receive a reusable deterministic `WELCOME_FIRST_ORDER` generated offer immediately
- the welcome offer is stored once in `generated_offers` and matched per user through `generated_offer_user_matches`
- the welcome offer does not use cron or Qwen/Ollama
- when `ENABLE_AI_OFFER_GENERATION=true`, the daily Celery cron generates AI-native offers only for customers with at least one paid order
- admins can manually queue the same AI generation task for local/staging validation
- AI-native offers do not require manual templates to exist
- when AI generation is off, or when fallback inventory is needed, the deterministic template-driven generation path still works
- live offer cards are returned to web and mobile from generated user matches
- cart preview validates discount eligibility before checkout
- checkout validates the same offer again before applying any discount

Current API surface:

- `POST /api/admin/offers/generate-ai`
- `GET /api/admin/offers/generate-ai/{task_id}`
- `GET /api/offers/personalized`
- `POST /api/offers/personalized/context`
- `POST /api/offers/personalized/events`
- `GET /api/restaurants/{restaurant_id}/offers`
- `POST /api/restaurants/{restaurant_id}/offers`
- `PATCH /api/restaurants/{restaurant_id}/offers/{offer_id}`
- `GET /api/restaurants/{restaurant_id}/generated-offers/{generated_offer_id}/matches`
- `PATCH /api/restaurants/{restaurant_id}/generated-offers/{generated_offer_id}`
- `DELETE /api/restaurants/{restaurant_id}/generated-offers/{generated_offer_id}`

Guardrails:

- the LLM can propose title, subtitle, CTA, discount type, discount value, and minimum order
- the reusable welcome offer is backend-authored and never calls the LLM
- backend validates every generated offer server-side before persistence
- fresh active AI offers are skipped to prevent duplicate regeneration
- checkout revalidates every applied offer server-side before discount application
- the system does not bypass scope, availability, or eligibility checks
- unsafe LLM output falls back to a deterministic safe offer or is skipped

Refresh behavior:

- existing AI offers are skipped while still fresh and active
- regeneration happens when the existing offer is expired, converted, near expiry, missing its current match, or force-refreshed by admin
- admin manual generation still reuses the same Celery task and backend generation service
- local/dev admin manual generation can run even when `ENABLE_AI_OFFER_GENERATION` is off, so teams can test without enabling the scheduled cron
- first-order welcome matches are removed automatically after the customer completes the first paid order

Current invalidation triggers for personalized-offer cache include:

- preferences update
- order placement
- order status change
- offer create/update/delete
- generated-offer state change/delete
- restaurant approval or active-state change
- location create/update/deactivate
- menu item create/update/delete
- menu item availability change

View and click tracking is analytics-only:

- opening an offer does not consume it
- clicking an offer does not remove it from Home
- offers remain visible until redemption, expiry, disable/pause, or normal eligibility changes

Current customer-app offer discovery behavior:

- Home offer cards can still be tapped directly and preserve selected-offer context
- normal item-add flows can also query `POST /api/offers/personalized/context`
- if an eligible offer exists for the item / restaurant / branch / user context, web and mobile can show an apply-or-skip prompt before adding the item
- declining a prompted offer suppresses that same prompt for the current cart session
- if the cart is replaced with another restaurant, the old offer is cleared and the new matching offer is preserved through `Clear & Add`

AI offer generation controls:

- `ENABLE_AI_OFFER_GENERATION`
- `AI_OFFER_CRON_ENABLED`
- `AI_OFFER_BATCH_SIZE`
- `AI_OFFER_USER_LIMIT`
- `AI_MAX_FLAT_DISCOUNT`
- `AI_MAX_PERCENTAGE_DISCOUNT`
- `AI_MIN_ORDER_THRESHOLD`
- `AI_OFFER_VALIDITY_DAYS`
- `AI_OFFER_CRON_HOUR`
- `AI_OFFER_CRON_MINUTE`
- `OLLAMA_OFFER_TIMEOUT_SECONDS`
- `QWEN_OFFER_MODEL_NAME`

Default AI-offer schedule:

- `AI_OFFER_CRON_HOUR=17`
- `AI_OFFER_CRON_MINUTE=0`

## Generated Combo Flow

Generated combos are built from real delivered + paid orders.

Current lifecycle:

- `DRAFT`
  - persisted for admin visibility
  - hidden from customers
  - used when a combo has enough repeated orders to exist, but not enough unique users to be socially validated
- `LIVE`
  - visible to customers
  - requires the customer-visibility threshold to be met
- `ARCHIVED`
  - inactive and hidden from customers
  - used for stale live combos and expired drafts

Current rules:

- same restaurant only
- items must still be available
- restaurant must still be active and approved
- repeated patterns must cross the configurable order-count threshold
- draft persistence can start from `GENERATED_COMBO_MIN_UNIQUE_USERS=1`
- customer visibility requires `GENERATED_COMBO_MIN_VISIBLE_UNIQUE_USERS=3` by default
- successful `DELIVERED` orders with `PAID` or `COD` payment state are counted by default
- draft combos archive after `GENERATED_COMBO_DRAFT_EXPIRY_DAYS`
- live combos archive after `GENERATED_COMBO_EXPIRY_DAYS`
- rebuilds upsert by `restaurant_id + restaurant_location_id + sorted item_ids`
- admin combo screens can inspect draft, live, and archived rows without exposing drafts to customers
- combos are scored using:
  - `order_count`
  - `unique_user_count x 2`
  - a recent-activity bonus
- the extra combo discount boost only applies when:
  - confidence clears the boost threshold
  - and unique-user adoption also clears the customer-visibility threshold

Main public endpoints:

- `GET /api/generated-combos`
- `GET /api/generated-combos/{id}`
- `GET /api/restaurants/{restaurant_id}/generated-combos`
- `GET /api/cart/upsell-suggestions`

Admin endpoints:

- `GET /api/admin/generated-combos`
- `POST /api/admin/generated-combos/rebuild`
- `PATCH /api/admin/generated-combos/{id}/status`

Important behavior:

- combos never span multiple restaurants
- combo identity is the canonical signature: `restaurant_id + branch_id + sorted item_ids`
- rebuilds update existing combos by signature instead of creating duplicates
- customer-facing combo APIs only return `LIVE` combos that are customer-visible and active
- admin combo APIs expose `DRAFT`, `LIVE`, and `ARCHIVED`
- combo cards fan out into normal cart items, so order placement stays unchanged
- order delivery transitions can trigger background combo rebuilds on the `analytics` Celery queue
- menu availability updates can deactivate stale generated combos automatically

Fresh seed data now includes repeated delivered orders for patterns like:

- `Margherita Pizza + Iced Lemon Soda`
- `Classic Chicken Burger + Chocolate Shake`
- `Chicken Momos (8 pcs) + Peach Soda`

That makes combo rebuilds testable immediately after `python seed.py`.

They are invalidated when:

- preferences change
- order state changes
- menu content or availability changes

## Chat / RAG Caching

The chat pipeline uses Redis in three main places:

- `chat:session:{user_id}:{session_id}`
  - recent chat history for quick session reloads
  - also used to rebuild short recommendation memory for follow-up turns
- `rag:embedding:{normalized_query}`
  - cached Ollama query embeddings
- `rag:response:{scope}:v6:{intent}:{topic}[:filters...]`
  - cached replies for repeated non-personalized food queries
  - cache keys are topic-based, not raw-message-based
  - query normalization lowercases text, trims whitespace, collapses repeated spaces, and removes spacing before punctuation

New-item chat behavior:

- `what's new?`
- `new spicy food`
- `new items for me`
- `new Italian dishes`

These queries now use a dedicated `new_only` intent path. The backend keeps them grounded to real new menu items from the database and can use a DB-first fast path before embedding/vector work when the query is simple enough.

Generic queries that are cached globally:

- `do you have pasta?`
- `do you have pizza ?`
- `do you have dessert?`
- `any dessert available?`
- `food under 300`
- `suggest spicy veg food`

Queries that are intentionally not cached globally:

- `show me more`
- `something else`
- `recommend based on my preferences`
- restaurant-scoped chat requests

If Redis is unavailable:

- chat still falls back to PostgreSQL + Ollama
- recommendation endpoints still compute normally
- cache reads and writes fail open

## Troubleshooting Redis

1. Verify Redis is running:

```bash
redis-cli ping
```

2. Check backend `.env` values:

- `REDIS_URL`
- `REDIS_CACHE_TTL_SECONDS`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`

3. Check logs for:

- `Redis cache hit`
- `Redis cache miss`
- `Redis cache save`
- `Redis connection failure`

4. Inspect keys manually:

```bash
redis-cli KEYS "rag:*"
redis-cli KEYS "chat:session:*"
redis-cli KEYS "chat:session-state:*"
redis-cli KEYS "recommendations:*"
```

This endpoint is authenticated for customers:

- `GET /api/recommendations`

## RAG Chat Flow

RAG is implemented in [app/services/rag.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/rag.py).

Flow:

1. customer sends `POST /api/chat/message`
2. ultra-fast small-talk paths handle greetings and thanks before retrieval
3. for cacheable generic queries, backend checks Redis response cache before full retrieval
4. backend loads Redis session state first and only pulls full recent history when a follow-up or prompt actually needs it
5. lightweight backend intent detection handles simple deterministic turns like `pizza`, `burger`, `dessert`, and `food under 300`
6. Qwen intent extraction is only used when the lightweight parser is not reliable enough
7. backend merges that intent with session state for continuation turns
8. the most recent active recommendation topic becomes the session anchor for follow-ups like `show me more` or `something else`
9. a new explicit dish query like `pizza` or `burger` replaces the previous active topic instead of reusing it
10. combo-focused turns like `suggest combos` and `pizza combo` are resolved from generated combo rows first
11. backend runs keyword and/or vector retrieval against PostgreSQL/pgvector when the turn is about menu items
12. results are filtered for restaurant state, availability, budget, and already-seen session items
13. when keyword grounding is already strong, backend can skip final Qwen generation and return a deterministic grounded reply
14. otherwise readable grounded context is built from real menu rows or generated combo rows and Ollama/Qwen generates the final conversational reply
15. chat turns and structured session state are persisted in `ChatHistory` and Redis

Important behavior:

- the backend supports `POST /api/chat/message/stream` so clients can render token-by-token output
- the backend still uses Qwen for intent extraction and final conversational wording when needed, but avoids those calls on simple deterministic turns
- the backend tracks structured session memory per active session to avoid duplicate follow-up suggestions
- generic cross-user response cache is only used for non-personalized, non-follow-up queries
- semantically same generic item/category queries reuse the same Redis key, for example `do you have dessert?`, `dessert?`, and `any dessert available?`
- exact/relevant menu matches win before fallback, so `pizza` can match `Margherita Pizza`
- fresh explicit dish queries override the old topic, so `pizza` followed by `burger` switches correctly instead of leaking the old session topic
- combo questions like `combo under 500` are grounded only in generated-combo rows; Qwen does not invent combos
- the backend uses DB-backed fallback suggestions if vector retrieval is weak or LLM generation fails
- generic “I don’t have access” responses are intercepted and replaced
- the API returns structured `suggestions` for UI add-to-cart actions
- auth and RAG stages log detailed timings for latency debugging

Detailed workflow documentation:

- [docs/chat-rag-workflow.md](/Users/imac/Desktop/restaurant-rag/backend/docs/chat-rag-workflow.md)

## Order Flow

Orders are handled in [app/services/orders.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/orders.py).

Supported flow:

- customer places order
- backend validates restaurant and menu item availability
- totals are calculated
- owner updates order status through the allowed transition chain
- menu and restaurant ranking now rely on availability, dynamic bestseller state, popularity, and recency only

Order status progression:

```text
PLACED -> ACCEPTED -> PREPARING -> OUT_FOR_DELIVERY -> DELIVERED
```

## Background Jobs

Celery jobs currently used:

- AI offer generation jobs
  - task: `app.tasks.ai_offers.generate_ai_offers_task`
- embedding jobs
  - task: `app.tasks.embed.embed_menu_item`
- notification jobs
  - task: `app.tasks.notifications.send_order_status_notification`

Queues configured in [app/config/celery.py](/Users/imac/Desktop/restaurant-rag/backend/app/config/celery.py):

- `analytics`
- `default`
- `embeddings`
- `notifications`

## Environment Variables

These values are read from `.env` through `app/config/settings.py`.

Core app:

- `APP_NAME`
- `APP_VERSION`
- `ENVIRONMENT`
- `DEBUG`
- `API_V1_PREFIX`
- `BACKEND_CORS_ORIGINS`

Database:

- `POSTGRES_SERVER`
- `POSTGRES_PORT`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_DB`
- `DATABASE_ECHO`

JWT:

- `JWT_SECRET_KEY`
- `JWT_ALGORITHM`
- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES`

Ollama:

- `OLLAMA_BASE_URL`
- `OLLAMA_CHAT_MODEL`
- `OLLAMA_EMBEDDING_MODEL`
- `OLLAMA_TIMEOUT_SECONDS`
- `OLLAMA_CHAT_TIMEOUT_SECONDS`
- `OLLAMA_EMBEDDING_TIMEOUT_SECONDS`
- `OLLAMA_KEEP_ALIVE`

RAG tuning:

- `RAG_TOP_K_RESULTS`
- `RAG_HISTORY_MESSAGES`
- `RAG_SUGGESTION_LIMIT`
- `RAG_MAX_CONTEXT_CANDIDATES`
- `RAG_MAX_DESCRIPTION_CHARS`
- `RAG_MAX_REPLY_TOKENS`

Redis / Celery:

- `REDIS_URL`
- `CELERY_BROKER_URL`
- `CELERY_RESULT_BACKEND`

Other configured values:

- `STRIPE_SECRET_KEY`
- `STRIPE_PUBLISHABLE_KEY`
- `RAZORPAY_KEY_ID`
- `RAZORPAY_KEY_SECRET`
- `FCM_PROJECT_ID`
- `FCM_CREDENTIALS_PATH`

## Local Setup

From `backend/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Make sure these services are available:

- PostgreSQL
- Redis
- Ollama

Recommended Ollama models for the current config:

```bash
ollama pull qwen3:8b
ollama pull nomic-embed-text
```

## Database Setup

1. Create the database in PostgreSQL.
2. Update `.env` with the correct connection values.
3. Run migrations:

```bash
alembic upgrade head
```

Optional seed:

```bash
python seed.py
```

Legacy demo/sample offer records may still exist in some local databases. The active product path is now:

- AI-native daily generation when `ENABLE_AI_OFFER_GENERATION=true`
- deterministic manual-template generation as backward-compatible fallback

Control it with:

```bash
SEED_PERSONALIZED_OFFERS_DEMO=1 python seed.py
```

Disable the demo offers later with:

```bash
SEED_PERSONALIZED_OFFERS_DEMO=0 python seed.py
```

Disable the general sample campaigns with:

```bash
SEED_PERSONALIZED_OFFERS_SAMPLE_CAMPAIGNS=0 python seed.py
```

## Running the Backend

Start the API:

```bash
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check:

```bash
curl http://localhost:8000/health
```

## Running Celery Workers

Default worker:

```bash
celery -A app.config.celery:celery_app worker --loglevel=info
```

Embeddings queue only:

```bash
celery -A app.config.celery:celery_app worker --loglevel=info -Q embeddings
```

Notifications queue only:

```bash
celery -A app.config.celery:celery_app worker --loglevel=info -Q notifications
```

## Common Commands

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Run migrations:

```bash
alembic upgrade head
```

Compile-check Python files:

```bash
python3 -m compileall app
```

Seed demo data:

```bash
python seed.py
```

## Frontend / Mobile Integration Notes

Customer web and mobile rely on:

- public `GET /api/restaurants`
- public `GET /api/restaurants/{restaurant_id}`
- public `GET /api/menu-items?restaurant_id=...`
- authenticated `GET /api/recommendations`
- authenticated `POST /api/chat/message`
- authenticated `POST /api/chat/message/stream`
- authenticated `GET /api/chat/history`
- authenticated orders

Admin and owner UIs rely on:

- `POST /api/restaurants` for admin-created restaurant + owner setup
- `GET /api/restaurants/{restaurant_id}` for shared restaurant workspace
- `PATCH /api/restaurants/{restaurant_id}/settings`
- admin routes under `/api/admin/*`

## Notes for New Developers

- use `python -m uvicorn`, not bare `uvicorn`, if your virtualenv scripts are inconsistent
- the backend assumes PostgreSQL, not SQLite
- `pgvector` must be available for the RAG pipeline
- owner access is enforced in backend services and route dependencies
- menu item embeddings are not created synchronously in the request path; they are queued through Celery
- recommendation and chat quality depend on seeded menu data and Ollama availability
- if chat feels slow, inspect the `Auth timings ...` and `RAG timings ...` logs first before changing prompts or model choices

## Known Practical Gotchas

- stale client JWTs can cause `401` noise until the client clears them
- if Alembic complains about existing enum types, the database may already contain partial schema objects from a previous failed migration
- if Ollama is down, chat and embedding features will fail even though the rest of the API may still work

## Multi-location architecture

Restaurant data is now split into:

- `restaurants`: brand-level records
- `restaurant_locations`: branch/outlet records with address, fee, minimum order, ETA, open state, active state, and fulfillment controls
- `location_fulfillment_slots`: weekly day/time windows per location and per fulfillment type

Backend rules:

- `menu_items.restaurant_location_id` controls real menu availability
- `orders.restaurant_location_id` scopes checkout and order history
- `orders.fulfillment_type` stores whether the order was placed as `DELIVERY` or `PICKUP`
- `generated_combos.restaurant_location_id` prevents cross-branch combo generation
- existing restaurants are backfilled with a default `Main Branch` during migration
- public menu and combo endpoints accept `location_id`
- admin and owner location CRUD lives under `/api/restaurants/{restaurant_id}/locations`
- admin and owner fulfillment-slot CRUD now lives under:
  - `GET /api/restaurants/{restaurant_id}/locations/{location_id}/slots`
  - `POST /api/restaurants/{restaurant_id}/locations/{location_id}/slots`
  - `PATCH /api/restaurants/{restaurant_id}/locations/{location_id}/slots/{slot_id}`
  - `DELETE /api/restaurants/{restaurant_id}/locations/{location_id}/slots/{slot_id}`
- branch-level fulfillment settings now live under:
  - `GET /api/restaurants/{restaurant_id}/locations/{location_id}/general-settings`
  - `PATCH /api/restaurants/{restaurant_id}/locations/{location_id}/general-settings`
- branch-level payment settings also live on the location model and are edited through the same general-settings surface:
  - `google_pay_enabled`
  - `razorpay_enabled`
  - `card_payment_enabled`
  - `cash_on_delivery_enabled`
  - public and authenticated restaurant detail responses expose these as `enabled_payment_methods`

Branch fulfillment behavior:

- `delivery_enabled` and `pickup_enabled` gate customer-visible fulfillment options
- `is_open` and `is_active` still act as hard branch-level master switches
- if active slots exist for a fulfillment type, those slots become the source of truth for availability
- if no slots exist yet for a fulfillment type, the backend falls back to the legacy opening/closing-hour behavior so existing branches do not break
- ASAP now also enforces a live prep cutoff:
  - `now + prep_buffer` must still fit inside the active slot or fallback operating window
  - if the branch is technically open but closing too soon, ASAP returns unavailable with a closing-soon reason
- schedule-options generation now respects the same branch master switches:
  - inactive branches do not expose future slots
  - closed branches do not expose future slots
  - disabled delivery / pickup modes do not expose future slots for that mode
  - `future_order_enabled=false` prevents scheduled slot generation entirely
- order placement revalidates:
  - branch active/open state
  - fulfillment toggle state
  - ASAP prep cutoff against the current slot / closing window
  - current day/time slot eligibility
  - minimum order
  - delivery fee only for `DELIVERY`
  - zero delivery fee for `PICKUP`
  - selected payment method is enabled for that branch

Scheduled-order validation details:

- `scheduled_at` must be present for `SCHEDULED` orders
- `scheduled_at` must include timezone information
- scheduled time must be at least `prep_buffer_minutes` ahead of now
- scheduled time must fit inside `max_future_days`
- scheduled time must align to the configured slot interval
- scheduled time must fall inside an active fulfillment slot, or inside fallback opening/closing hours when no slot rows exist yet

Payment flow details:

- customer mobile no longer places the order directly from the cart screen
- branch-aware checkout now happens as:
  - `Cart -> Payment -> OrderSuccess`
- the selected location decides which methods the client may show:
  - `GOOGLE_PAY`
  - `RAZORPAY`
  - `CARD`
  - `COD`
- order payload now includes:
  - `payment_method`
  - `payment_provider`
  - optional `payment_reference`
- backend rules:
  - `COD` creates the order directly with `payment_status=COD`
  - online methods require a payment reference before order creation
  - disabled branch payment methods are rejected with `400`

# PROJECT_UNDERSTANDING.md

> Generated 2026-07-31 from a full read of the repo (root readme, `/docs`, backend, both web frontends, mobile app, and the AI/RAG/recommendation code paths). This is a factual snapshot of how the system works **today**, including places where docs and code disagree.

---

## 1. What This Project Is

**Restaurant RAG** is a monorepo for a multi-restaurant food ordering platform with AI-assisted discovery:

- RAG-grounded food chat (PostgreSQL + pgvector + Ollama)
- Personalized recommendations ("Personalized Picks")
- Auto-generated combos mined from real order patterns
- Personalized offers (deterministic welcome offer + LLM-generated offers for existing customers)
- Multi-location (brand → branch) restaurant model with per-branch fulfillment, slots, and payment methods
- Phase-1 push notifications (prepaid order-placed confirmation, deep link to OrderDetail)

Four apps, one backend as source of truth.

---

## 2. Architecture

```
┌─────────────────┐  ┌─────────────────┐  ┌──────────────────┐
│frontend-customer│  │ frontend-admin  │  │ mobile (RN CLI)  │
│ React 19 + Vite │  │ React 19 + Vite │  │ RN 0.85, axios   │
│ fetch wrapper   │  │ ADMIN + OWNER   │  │ Firebase OTP+FCM │
└────────┬────────┘  └────────┬────────┘  └────────┬─────────┘
         └──────────────┬─────┴────────────────────┘
                        ▼  REST /api (JWT bearer)
              ┌──────────────────────┐
              │  FastAPI backend     │  app/api → app/services → app/models
              │  (single /api prefix)│
              └──┬───────┬───────┬───┘
                 ▼       ▼       ▼
         PostgreSQL   Redis    Ollama (local LLM)
         + pgvector   cache +  qwen3:8b (chat/intent/offers/rerank)
         (768-dim)    Celery   nomic-embed-text (768-dim embeddings)
                      broker
                 ▲
          Celery workers (queues: embeddings, notifications, default, analytics)
          Celery beat (only AI-offer cron, off by default)
          Firebase Admin SDK → FCM push
```

Key principles:

- **Backend owns all business rules** (auth, role scoping, menu/order rules, scoring, offer eligibility, checkout validation). Clients are thin and re-validate nothing authoritative.
- **LLM output is always grounded**: menu context comes from live DB rows; the model may phrase answers but never invent items/prices; hallucination guards exist on every LLM path.
- **AI degrades gracefully**: every LLM/embedding failure falls back to deterministic DB-backed behavior; chat never 5xxs because of Ollama.

---

## 3. Repository / Folder Structure

```
restaurant-rag/
├── readme.md                     # canonical setup + product rules
├── LLM_ARCHITECTURE.md           # ⚠ partially stale (see §10)
├── MENU_ITEM_CUSTOMIZATION_FLOW.md
├── docs/
│   ├── PROJECT_OVERVIEW.md       # product/marketing overview
│   ├── LLM_USAGE_OVERVIEW.md
│   ├── recommendation-flow.md
│   ├── personalized-offers.md
│   ├── push-notification-phase1.md
│   └── location-slot-demo-reference.md   # seeded demo branch schedules
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app, CORS, /health; no lifespan hooks
│   │   ├── api/                  # 14 routers, all mounted under /api (no /v1)
│   │   ├── config/               # settings.py (pydantic-settings), database.py, celery.py
│   │   ├── models/               # 25 SQLAlchemy 2.0 models + 20 StrEnums
│   │   ├── schemas/              # Pydantic v2, one module per domain
│   │   ├── services/             # 18 modules — ALL business logic lives here
│   │   └── tasks/                # Celery: embed, ai_offers, ai_recommendations,
│   │                             #         generated_combos, notifications
│   ├── alembic/versions/         # 31 revisions, head = 0031_personalized_recommendation_snapshots
│   ├── seed.py                   # demo data; all users password "password123"
│   ├── firebase-service-account.json   # FCM service account (push only, not auth)
│   └── docs/chat-rag-workflow.md
├── frontend-customer/src/        # pages/, components/, services/(api,storage), store/, hooks/, utils/
├── frontend-admin/src/           # pages/, components/, layouts/, services/, store/
└── mobile/src/                   # screens/, components/, navigation/, services/, store/, utils/
```

---

## 4. Tech Stack

| Layer              | Stack                                                                                                                                                                               |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Backend            | Python 3.11+, FastAPI, SQLAlchemy 2.0 (typed `Mapped[]`), Pydantic v2, Alembic, psycopg                                                                                             |
| Database           | PostgreSQL + pgvector (`Vector(768)`, IVFFlat cosine index)                                                                                                                         |
| Cache / queue      | Redis (db0 = Celery broker, db1 = results; also chat/embedding/response/recommendation caches, 3-day TTL)                                                                           |
| Async work         | Celery (queues: `embeddings`, `notifications`, `default`, `analytics`), Celery beat (TZ Asia/Kolkata)                                                                               |
| LLM                | Ollama local: `qwen3:8b` (chat, intent JSON, offer copy, rec rerank), `nomic-embed-text` (768-dim)                                                                                  |
| Auth               | passlib bcrypt + python-jose HS256 JWT (24 h expiry, no refresh tokens)                                                                                                             |
| Push               | Firebase Admin SDK → FCM multicast; mobile uses @react-native-firebase/messaging + Notifee                                                                                          |
| Customer/Admin web | React 19 + Vite + TypeScript. **No react-router, no axios, no state library** — hand-rolled history-based routing, Context stores (`AppStore`/`AdminStore`), custom `fetch` wrapper |
| Mobile             | React Native 0.85.2 (CLI, not Expo), React Navigation 7 (native stack + bottom tabs), axios, AsyncStorage, Firebase Phone Auth (registration OTP), Reanimated 4                     |
| Payments           | Mock providers (`payment_provider` default "mock"; stripe/razorpay settings are placeholders)                                                                                       |

---

## 5. Backend Detail

### 5.1 API Surface (all under `/api`, flat, no versioning)

| Router              | Prefix             | Highlights                                                                                                   |
| ------------------- | ------------------ | ------------------------------------------------------------------------------------------------------------ |
| auth                | `/auth`            | `register` (⚠ role taken from client payload), `login` (email **or** phone + password)                       |
| admin               | `/admin`           | dashboard stats, restaurant/user management, AI-offer manual trigger + task status, AI logs                  |
| restaurants         | `/restaurants`     | CRUD (admin creates restaurant+owner), locations, per-location slots, schedule-options, general settings     |
| menu_items          | `/menu-items`      | CRUD with sizes + customization groups/options; create/update queues embedding job + clears `rag:response:*` |
| orders              | `/orders`          | place, `validate` (pre-checkout), list (role-scoped), status transitions (owner)                             |
| chat                | `/chat`            | `message`, `message/stream` (SSE), `history` GET/DELETE — auth required                                      |
| recommendations     | `/recommendations` | GET (auth), `personalized-context` (auth), `query` (optional auth — guest personalization)                   |
| personalized_offers | mixed              | customer feed/events/preview/context; owner/admin template + generated-offer management                      |
| generated_combos    | mixed              | public combo lists, `cart/upsell-suggestions`, admin rebuild + lifecycle status PATCH                        |
| notifications       | mixed              | device-token registration; admin send + history                                                              |
| favorites           | `/favorites`       | customer-only CRUD, `/ids` for optimistic sync                                                               |
| profile             | `/profile`         | me + saved addresses (default handling)                                                                      |
| preferences         | `/preferences`     | GET/PUT me                                                                                                   |
| reports             | `/reports`         | role-scoped analytics (ADMIN = platform-wide, OWNER = own restaurant, enforced server-side)                  |

### 5.2 Database Models (25, all UUID PKs + timestamps)

- **Identity**: `User` (role ADMIN/OWNER/CUSTOMER), `UserPreferences` (JSONB cuisine/diet/budget/spice + affinity scores), `UserSavedAddress`, `UserDeviceToken`
- **Restaurant**: `Restaurant` (brand, 1:1 owner), `RestaurantLocation` (branch: fulfillment toggles, payment-method flags, ETAs, slot config, prep time), `LocationFulfillmentSlot` (weekly per-day per-type windows)
- **Menu**: `MenuItem` (per-location, `launched_at`/`is_new_launch`, popularity, bestseller), `MenuItemSize`, `MenuItemCustomizationGroup`, `MenuItemCustomizationOption`, `MenuEmbedding` (`Vector(768)`, unique per item)
- **Orders**: `Order` (location-scoped, fulfillment/schedule/payment fields, INR), `OrderItem` (name/size/options snapshots)
- **Chat**: `ChatHistory` (session_id, role, `context_payload` JSONB)
- **Discovery**: `Favorite` (unique user+item), `GeneratedCombo` (signature, DRAFT/LIVE/ARCHIVED lifecycle, `manual_status_override`, `is_customer_visible`), `GeneratedComboItem`, `PersonalizedRecommendationSnapshot` (1:1 user, AI rerank cache)
- **Offers**: `PersonalizedOffer` (template), `GeneratedOffer` (per-user or global instance, AI or manual source), `GeneratedOfferUserMatch`, `PersonalizedOfferEvent` (VIEWED/CLICKED/CONVERTED)
- **Push**: `PushNotificationCampaign`, `PushNotificationEvent`

### 5.3 Authentication & Authorization

- Bcrypt hashes; HS256 JWT `{sub, role, exp}`, default expiry **24 h**. No refresh tokens, no revocation.
- `OAuth2PasswordBearer` → `get_current_user` / `get_current_user_optional` (optional variant powers public browsing).
- RBAC via `require_admin` / `require_owner` / `require_customer` per endpoint; owner scoping via `get_owner_restaurant_id` (403 if no active restaurant).
- Registration sets `is_active=True, is_verified=True` — no server-side email/phone verification. Mobile does Firebase Phone-OTP **client-side before** calling register.
- Client-side role gating: customer web/mobile only keep `CUSTOMER` sessions; admin web only `ADMIN`/`OWNER` (validated on storage read, cleared otherwise).
- Firebase is used for **two unrelated things**: FCM push (backend, service account) and phone OTP at mobile registration (client-side). It is _not_ part of backend session auth.

### 5.4 Background Processing

- Celery broker/back-end on Redis; queues `embeddings`, `notifications`, `default`, `analytics`; `worker_prefetch_multiplier=1`.
- Tasks: `embed_menu_item` (Ollama embed → upsert, 768-dim asserted), `generate_ai_offers_task`, `generate_ai_recommendations_task`, `rebuild_generated_combos_task`, `send_order_status_notification` (**mock — logs only, does not send FCM**; real FCM send lives in `services/notifications.py` campaign dispatch).
- Celery beat has exactly **one** entry — daily AI-offer generation at 17:00 IST — and it is registered **only when `AI_OFFER_CRON_ENABLED=true`** (default false → beat schedule is empty).

---

## 6. RAG Implementation

### 6.1 Ingestion

- On menu-item create/update, the API queues `embed_menu_item` (Celery, `embeddings` queue).
- Source text: `"{name} | {cuisine} | {category} | {description} | {price} | {Veg|Non-Veg}"` → Ollama `/api/embed` (`nomic-embed-text`) → 768-dim vector upserted into `menu_embeddings` (`ON CONFLICT DO UPDATE`).
- IVFFlat cosine index (`0004_chat_performance_indexes`).

### 6.2 Retrieval (hybrid, keyword-first)

All in [backend/app/services/rag.py](backend/app/services/rag.py) (~5,000 lines — the heart of the system):

1. **Keyword candidates** — ILIKE across item name/category/cuisine/description + restaurant name/cuisine; ranked bestseller → popularity → recency.
2. **Vector candidates** — `cosine_distance` on `menu_embeddings`, business filters pushed into SQL (active/approved restaurant, active location, available item).
3. **Popularity fallback**, then **relaxed-intent retry** (drops topic/cuisine/category constraints), then **emergency DB fallback**.

Routing: for intents like `dish_recommendation`, short queries (≤4 tokens), or follow-ups with a topic, keyword candidates are tried first — if any survive filtering, **the embedding call is skipped entirely**. Special paths bypass menu retrieval altogether: combo queries (generated-combo rows only), offer queries (offer cards only), and `new_only` queries (keyword+popularity with launch-window sorting).

Query embeddings are cached two-tier: Redis (`rag:embedding:<normalized>`) then in-process `lru_cache(256)`.

### 6.3 Prompt Assembly & Generation

- All prompts are inline strings in the service modules (no prompt directory).
- `SYSTEM_PROMPT`: "premium food concierge" with hard grounding rules (never invent items/prices/restaurants; no general knowledge) + style rules (1–3 sentences).
- Final prompt = SYSTEM → TIME CONTEXT → STRUCTURED INTENT (JSON) → SESSION SUMMARY → RECENT HISTORY (last 3 msgs, 120 chars each) → MENU CONTEXT (**max 3 lines**, hard-clamped) → few-shot style examples → USER QUESTION (220 chars).
- Generation: `qwen3:8b`, `temperature=0.35`, `num_predict=120` (`rag_max_reply_tokens`), `keep_alive=10m`; sync and SSE-streaming variants share the logic. Long-lived `httpx.Client`s with connection pooling.

### 6.4 Fallbacks

- `_prepare_chat_turn` is wrapped in a broad try/except → safe fallback turn, so Ollama/DB hiccups never surface as chat 5xx.
- LLM reply failure → deterministic fallback reply built from the grounded candidates.
- `_ensure_useful_reply` replaces model output that claims "menu not available"/contradicts grounded matches.
- Intent-LLM failure silently degrades to the regex/heuristic parser.

---

## 7. Chat Flow (end-to-end)

```
client POST /api/chat/message[/stream]  (JWT required; message, session_id?, restaurant_id?)
  1. Acknowledgement? ("thanks") → instant canned reply, no retrieval, no LLM
  2. Greeting? → Redis greeting cache / deterministic time-of-day reply
  3. Global response cache lookup (topic-normalized key; only non-personal,
     non-follow-up, non-restaurant-scoped queries are cacheable)
  4. _prepare_chat_turn:
     a. lightweight intent parser (default path) — Qwen intent extraction ONLY
        when heuristics are insufficient (rare in practice)
     b. follow-up detection ("show me more") → reuse active topic from
        SessionConversationState, exclude seen_item_ids; a fresh explicit
        dish query resets the topic
     c. retrieval (keyword-first hybrid, §6.2)
  5. should_bypass_llm? → deterministic grounded reply : Qwen generation
     (sync or SSE stream) → _ensure_useful_reply guard
  6. cache save → persist user+assistant ChatHistory rows (context_payload
     stores suggestion IDs, retrieval_source, llm_strategy) → refresh Redis
     session state → attach is_favorite flags
Response: { reply, session_id, suggestions[], combo_suggestions[], offer_suggestions[] }
```

- Session memory: two Redis keys per session (history + structured `SessionConversationState`: active topic, prior filters, seen items, last recommendation context). DB history is loaded lazily only for follow-ups/personal-context turns.
- **No server-side cart actions from chat** — chat returns data; clients handle add-to-cart. Mobile deliberately routes chat suggestions to `MenuItemDetail` (customizations can't be expressed in chat).
- Customer **web** uses `/chat/message/stream` (SSE token streaming); **mobile** uses non-streaming `/chat/message`.

---

## 8. Recommendation & Personalization Flow

### 8.1 Deterministic base scoring (always on)

`services/recommendations.py` scores menu items by (strongest → weakest): explicit preference match → paid order history (counts from any live-lifecycle paid order: PLACED…DELIVERED) → cuisine/category match → diet match → popularity (light fallback). New-launch items (`launched_at` within `NEW_ITEM_WINDOW_DAYS=14`) get conditional boosts + labels (`New for You`, `New Spicy Pick`, `Based on Your Orders`, `New Italian Favorite`). Per-user results cached in Redis (`recommendations:{user_id}`).

Guest personalization: `POST /recommendations/query` accepts client-local preferences without persisting them; on login, the mobile/web client pushes local prefs via `PUT /preferences/me`. Request priority ladder (mobile `getRecommendationsForContext`): authed GET → authed query → public query with local prefs → public query bare.

### 8.2 AI rerank layer (flag-gated, default OFF)

`services/ai_recommendations.py` + `personalized_recommendation_snapshots` table:

- Behind `ENABLE_AI_RECOMMENDATION_RERANKING` (false by default, not set in `.env` → **currently inactive**).
- Deterministic top-50 candidate pool → hash → Qwen rerank (strict JSON, only known `candidate_id`s accepted — hallucination guard) → per-item `ai_reason`/`ai_badge`, collection title + insight → snapshot persisted with status (PENDING/READY/FAILED/SKIPPED_SMALL_SET).
- Refresh enqueued (Celery `analytics` queue) on preference updates, order lifecycle events, favorite add/remove, and cache misses; 15-min retry cooldown after failures.
- Read path applies a READY snapshot only when the candidate hash still matches, and **only on the `dedupe_multi_location=True` path**; diversity caps (≤3 same restaurant, ≤4 same cuisine/category) applied after LLM ordering.
- `GET /recommendations/personalized-context` exposes the AI collection title/insight to clients.

### 8.3 Personalized offers

- **Welcome offer (deterministic, no LLM)**: one global reusable `GeneratedOffer` (15% off, min-order floor); matched to a user at registration and unmatched permanently after their first paid order.
- **AI offers (LLM, flag-gated `ENABLE_AI_OFFER_GENERATION`, default OFF)**: only for customers **with paid-order history**. Candidate ladder: repeated item → favorite restaurant → cuisine affinity → order-history fallback; inactivity (14 days) retargets as INACTIVE_USERS. Qwen generates title/subtitle/CTA/discount as strict JSON; validation clamps discounts (flat ≤ ₹100, ≤30 %, min order ≥ ₹99) and any failure falls back to deterministic copy. Dedup/refresh expires stale offers.
- **Triggers**: daily beat cron (17:00 IST, needs `AI_OFFER_CRON_ENABLED`) or admin `POST /admin/offers/generate-ai` (which passes `allow_disabled=True`, bypassing the master flag — intentional for local testing).
- Event tracking: clients batch VIEWED/CLICKED events; conversions linked at order placement (`generated_offer_id` on the order payload).

### 8.4 Generated combos (no LLM)

`services/generated_combos.py` mines paid DELIVERED orders (90-day lookback) for frequently co-ordered item pairs per **location**. Thresholds: ≥3 orders + ≥1 unique user creates a DRAFT; ≥3 unique users promotes to LIVE (customer-visible); stale combos auto-ARCHIVE (90 d live / 30 d draft). Admin can override lifecycle status manually (`manual_status_override`). Confidence = orders + 2×unique users + recency bonus; discount ≈ 7–9 %. Rebuilds trigger from order events and an admin endpoint — there is **no scheduled rebuild**.

---

## 9. Client Apps

### 9.1 frontend-customer (React 19 + Vite)

- Hand-rolled routing (`usePathname` + `history.pushState` + regex path matchers), Context `AppStore`, custom fetch wrapper (`services/api.ts`, base URL `VITE_API_BASE_URL` → default `http://localhost:8000/api`), `ApiError` normalization, SSE chat streaming.
- localStorage: auth (CUSTOMER-only, validated on read), cart, chat session, pending auth redirect, preferences (+onboarding flag), selected offer.
- Pages: Home, Restaurant, MenuItemDetail, Cart, Chat, Favorites, Orders(+Detail), Preferences onboarding, Profile suite, Login/Register.
- Guest browse → login redirect on protected actions (add-to-cart/cart/checkout) with context restoration; single-restaurant+location cart; combo→cart mapping preserves per-item `is_veg`.

### 9.2 frontend-admin (React 19 + Vite, shared ADMIN+OWNER)

- Same architectural pattern (own `AdminStore`, storage validates ADMIN/OWNER roles).
- Pages: Dashboard (KPIs/charts), Restaurants(+Detail), Locations(+Detail incl. slots/fulfillment/payment settings), MenuItems + MenuItemEditor (sizes/customizations), Orders, Offers (template + generated management), GeneratedCombos (lifecycle admin), Notifications, Reports, AILogs, Users (admin), Settings.
- Role visibility filtered in UI **and** enforced by backend (owner data scoping).

### 9.3 mobile (React Native 0.85 CLI)

- React Navigation: bottom tabs (Home/Orders/Chat/Profile) inside a root native stack; Login/Register are **modals**, not a separate auth stack — the only top-level gate is preferences onboarding.
- Action-site auth guard (`checkAuthAndRedirect`) rather than route guards; post-login stack reset restores the target screen.
- Auth: login = country code + phone + password (backend JWT); registration = Firebase Phone OTP first, then backend register. Token in plaintext AsyncStorage; no refresh flow.
- Checkout: Cart → `POST /orders/validate` + slot revalidation (screen open / foreground / pre-checkout) → Payment (branch-scoped methods; COD places directly, online pays first) → OrderSuccess.
- Push: FCM + Notifee; device token → `POST /notifications/device-tokens` (installation-id keyed); deep link handled only for `order_placed` → OrderDetail, buffered until nav + auth ready.

---

## 10. Important Observations (doc/code divergences & risks)

### AI/RAG

1. **All three AI enhancement flags default OFF** (`ENABLE_AI_OFFER_GENERATION`, `ENABLE_AI_RECOMMENDATION_RERANKING`, `AI_OFFER_CRON_ENABLED`) and are absent from `backend/.env` — in the current checkout, chat RAG is the only live LLM feature; offers/reranking run only via the admin manual trigger.
2. **`LLM_ARCHITECTURE.md` is stale**: it claims recommendations and offer copy use "no LLM call" — contradicted by `ai_recommendations.py` and `ai_offer_generation.py`.
3. **`RAG_MAX_CONTEXT_CANDIDATES=4` is not honored** — `_build_context_block` hard-clamps menu context to 3 lines.
4. **No `<think>` stripping for qwen3:8b** — qwen3 emits reasoning blocks by default; with `num_predict=120` a think block could consume the whole reply budget. Worth verifying/handling.
5. **AI reranking only applies on the `dedupe_multi_location=True` path** — plain `GET /recommendations` never gets AI ordering/badges (undocumented).
6. **`services/ollama_service.py` is dead code with a broken import** (imports names that don't exist in settings); nothing uses it.
7. **`chat-rag-workflow.md` contradicts itself** on whether Qwen intent extraction is the first step (code: lightweight parser is the default; LLM intent is the exception).
8. Offer/rec prompts **include `user.email`** — PII sent to the (local) LLM; fine locally, worth noting if Ollama is ever remote.
9. Welcome offer rows are labeled `source=AI_GENERATED` despite being deterministic (`llm_used=False` in metadata) — AI-offer analytics will over-count.

### Backend

10. **`POST /auth/register` accepts `role` from the client** — anyone can self-register as ADMIN/OWNER. Biggest security gap in the codebase (acceptable for a demo, not production).
11. No refresh tokens/revocation; 24 h JWTs; `is_verified=True` at registration without verification.
12. `tasks/notifications.py::send_order_status_notification` is a **mock** (logs only); real FCM sending happens in `services/notifications.py` (campaigns + order-placed push).
13. Alembic chain is linear but **skips `0026`** (0027 follows 0025) — cosmetic, not a defect.
14. Payments are mocked end-to-end (`payment_provider="mock"`); Stripe/Razorpay settings are placeholders.

### Clients

15. **Mobile API base URL is a hardcoded LAN IP** (`http://192.168.29.236:8000/api` in `mobile/src/services/api.ts`) — no env/platform switching, despite the mobile README claiming emulator/simulator selection logic exists.
16. Mobile has **no axios interceptors**: auth header passed per call; six public GETs silently retry without auth on 401 (auth'd user downgraded to guest data); JWT stored unencrypted.
17. Mobile README's endpoint list is stale (`/chat/message/stream` and `/generated-combos/cart-upsell` don't exist in `api.ts`; real upsell path is `/cart/upsell-suggestions`; mobile chat is non-streaming).
18. Dead/empty artifacts in mobile: `screens/orders/legacy/OrdersScreen.tsx` (unreferenced), empty dirs (`src/context`, `components/cart`, `components/liquidGlass`, `screens/checkout`, `screens/offers`, `scripts/`); registration draft (incl. password) held in a module-level variable.
19. Web apps intentionally use no router/HTTP/state libraries — any new pages must follow the hand-rolled `usePathname` + regex-matcher pattern.
20. `MENU_ITEM_CUSTOMIZATION_FLOW.md` promises chat responses that describe customizations — not implemented; chat suggestion payloads carry no customization fields (mobile works around it by routing suggestions to the detail screen).

### Operational quick reference

- Run order: Postgres → `alembic upgrade head` → uvicorn → Redis → Celery worker (`-Q embeddings,notifications,default,analytics`) → `ollama serve` (+ `qwen3:8b`, `nomic-embed-text`) → web/mobile clients.
- Backend: `python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000` (from `backend/`).
- Seed: `python seed.py` — logins `admin@example.com` / `customer1@example.com` etc., password `password123`.
- Verification used in repo: `python3 -m compileall backend/app backend/alembic`; `npm run build` in both frontends; `tsc --noEmit` in mobile.

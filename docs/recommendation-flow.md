# Recommendation Flow

This is the canonical reference for the current recommendation, launch badge, and dynamic Best Seller system across:

- `backend`
- `frontend-admin`
- `frontend-customer`
- `mobile`

It exists so we can tune recommendation behavior later without breaking payload compatibility, cache behavior, or badge rendering.

Important boundary:

- `Personalized Picks` is recommendation output
- `Offers` is a separate generated-offer system built from reusable business templates
- generated offers do not replace recommendation ranking

## 1. Recommendation Overview

The backend recommendation system ranks and labels menu items using:

- explicit user preferences
- paid order history
- cuisine and category affinity
- diet alignment
- popularity
- dynamic branch-level bestseller signals
- a secondary new-launch boost

Current usage:

- Home `Personalized Picks`
- Home recommendations remain independent from the generated `Offers` feed
- restaurant menu ordering
- `frontend-customer`
- `mobile`
- chatbot/RAG suggestion metadata when recommendation labels are present

Generated combo discovery is a separate backend aggregation layer.

Current generated-combo guardrails:

- combos are derived only from paid `DELIVERED` orders in the current schema
- combos now move through a lifecycle: `DRAFT` -> `LIVE` -> `ARCHIVED`
- draft persistence can begin once a pattern passes the generation floor, even if it is not customer-visible yet
- default draft generation starts at `GENERATED_COMBO_MIN_UNIQUE_USERS=1`
- customer visibility requires `GENERATED_COMBO_MIN_VISIBLE_UNIQUE_USERS=3` by default
- draft combos archive after `GENERATED_COMBO_DRAFT_EXPIRY_DAYS=30` if they never gain enough unique customers
- live combos archive after `GENERATED_COMBO_EXPIRY_DAYS=90` of inactivity by default
- confidence scoring rewards multi-user adoption more heavily than raw repeat count
- admin surfaces can inspect draft combos and see how many more unique customers are needed before publication
- customer APIs return only `LIVE` combos where `is_customer_visible = true`

## Multi-location Home deduplication

Home recommendation surfaces can now opt in to backend multi-location deduplication.

Purpose:

- prevent the same dish from appearing multiple times on Home because a restaurant has multiple branches
- preserve exact location-specific menu pricing on restaurant detail pages
- keep cart and checkout tied to a real branch-backed menu item

Current rule:

- deduplication is opt-in through recommendation request payload or query params
- default recommendation flows remain branch-level and unchanged unless the caller enables deduplication
- Home clients should enable this
- restaurant detail and branch menu flows should continue using location-specific menu items directly

Current recommendation request options:

- `dedupe_multi_location: true`
- optional `location_context`
  - `city`
  - `latitude`
  - `longitude`

Current grouped response metadata:

- `display_price`
- `price_label`
- `available_locations_count`
- `preferred_menu_item_id`
- `preferred_location_id`
- `preferred_location_name`
- `requires_location_selection`
- `location_variants`

Current Home behavior:

- if location context exists, backend prefers the nearest or best-matching branch variant and Home can add/open that branch-backed item directly
- if location context is missing and the item exists at multiple branches, Home shows one grouped card and should route the user to the restaurant/branch flow before direct add

Primary backend modules:

- [backend/app/services/recommendations.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/recommendations.py)
- [backend/app/services/menu_item_metadata.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/menu_item_metadata.py)
- [backend/app/services/bestsellers.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/bestsellers.py)
- [backend/app/services/rag.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/rag.py)

Primary client consumers:

- [frontend-customer/src/pages/HomePage.tsx](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/pages/HomePage.tsx)
- [frontend-customer/src/pages/RestaurantPage.tsx](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/pages/RestaurantPage.tsx)
- [mobile/src/screens/home/HomeScreen.tsx](/Users/imac/Desktop/restaurant-rag/mobile/src/screens/home/HomeScreen.tsx)
- [mobile/src/screens/restaurant/RestaurantScreen.tsx](/Users/imac/Desktop/restaurant-rag/mobile/src/screens/restaurant/RestaurantScreen.tsx)

Admin menu controls live in:

- [frontend-admin/src/components/RestaurantMenuTable.tsx](/Users/imac/Desktop/restaurant-rag/frontend-admin/src/components/RestaurantMenuTable.tsx)
- [frontend-admin/src/pages/MenuItemsPage.tsx](/Users/imac/Desktop/restaurant-rag/frontend-admin/src/pages/MenuItemsPage.tsx)
- [backend/app/api/menu_items.py](/Users/imac/Desktop/restaurant-rag/backend/app/api/menu_items.py)

## 2. Current Recommendation Signals

### User Preferences

Strongest personalization signal.

Current preference inputs include:

- favorite cuisines
- favorite items
- diet
- spice level
- budget tier

### Order History

Order history contributes through repeated affinity across:

- same item
- similar item terms
- category
- cuisine
- restaurant

This is the main source for `Based on Your Orders`.

### Cuisine / Category Match

Cuisine and category affinity reinforce:

- explicit cuisine preferences
- repeated order patterns
- broader taste similarity when there is not an exact repeat

### Diet Match

Diet is a supporting signal and should not dominate ranking.

### Popularity

Popularity is a light ranking signal and also supports non-personalized fallback behavior.

### Dynamic Best Seller

`Best Seller` is now dynamic and branch-specific.

Current logic:

- scoped by `restaurant_location_id`
- last `30` days by default
- valid orders only
- minimum `25` valid orders per item by default
- only available menu items
- only active / approved restaurants
- only active locations

Current valid counted statuses:

- `ACCEPTED`
- `PREPARING`
- `OUT_FOR_DELIVERY`
- `DELIVERED`

Statuses and payment states not intended to count:

- `PLACED`
- `FAILED`
- `REFUNDED`
- any future cancelled state

Current implementation notes:

- customer-facing `is_bestseller` is computed dynamically
- dynamic bestsellers can differ by branch
- no fixed top-item cap is required by default
- the threshold and window are configurable for future growth from `25` to `100` or `200`

### New Launch Boost

New launch treatment remains controlled by:

- `MenuItem.is_new_launch`

Important behavior:

- `launched_at` alone does not produce `Just Launched`
- `is_new_launch` must be enabled by Admin/Owner
- `launched_at` still defines the active launch window and remains useful for analytics and timing

### Fallback Popular Items

Fallback behavior should continue to surface broadly useful items when meaningful personalization is absent.

## 3. Current Scoring Logic

Current recommendation priority should remain:

1. preference match
2. order history influence
3. cuisine/category and diet refinement
4. new-launch boost
5. popularity

Production intent:

- preferences remain the strongest signal
- order history should influence ranking gradually over time
- dynamic bestseller can support popularity and fallback discovery
- new launch is secondary and must not overpower strong preference or order-history matches
- popularity stays a light or fallback signal

Current implementation structure:

- base recommendation score is built from personalization and popularity signals
- new-launch scoring is additive and secondary
- badge metadata is assigned after ranking

Badges should explain ranking, not replace ranking.

## 4. Badge Logic

Current customer-facing badge set:

- `Based on Your Orders`
- `Matches Your Taste`
- `Trending Now`
- `Best Seller`
- `Just Launched`
- `Recommended for You`

Current badge priority:

1. `Based on Your Orders`
2. `Matches Your Taste`
3. `Trending Now`
4. `Best Seller`
5. `Just Launched`
6. `Recommended for You`

Badge rules:

- `Based on Your Orders`: strongest repeated-order signal.
- `Matches Your Taste`: strongest taste or preference match.
- `Trending Now`: `is_new_launch = true` and high popularity / order demand.
- `Best Seller`: dynamic branch-level bestseller based on recent valid orders.
- `Just Launched`: manual launch flag plus active launch window.
- `Recommended for You`: general personalized fallback when no stronger badge applies.

Important rules:

- badges are visual metadata
- backend badge metadata is the source of truth
- frontend and mobile should display only the backend-provided label
- frontend and mobile should not invent, remap, or infer badge labels
- badges must not aggressively control ranking
- the old manual featured flag is retained only as a legacy compatibility field and is no longer used by active app flows

## 5. Best Seller Calculation

Current dynamic Best Seller calculation is implemented in:

- [backend/app/services/bestsellers.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/bestsellers.py)

Current defaults:

- window: `30` days
- threshold: `25` valid orders
- scope: per `restaurant_location_id`
- top item count: unlimited by default unless configured later

How items qualify:

- item is in the current branch
- item is available
- restaurant is active and approved
- location is active
- item has at least the configured number of valid orders in the time window

How ranking is determined inside a branch:

- higher valid-order count first
- higher ordered quantity next
- stable alphabetical tie-break after that

Future scalability:

- `bestseller_min_valid_orders` can be increased later from `25` to `100` or `200`
- `bestseller_window_days` can be widened or narrowed
- `bestseller_top_item_count` can be capped later if needed

## 6. Known Current Issues

These are the main known issues to keep in mind for future tuning.

### Seed And Dev Data Previously Looked Too New

`launched_at` was recent for too many seeded or newly created items, which caused too many `Just Launched` badges.

Current mitigation:

- `Just Launched` requires manual `is_new_launch`
- recent `launched_at` alone is not enough

### Order-History Influence Can Still Saturate Early

Repeated order learning still works, but some history normalization may become strong faster than ideal. This is a scoring-tuning concern, not a badge-source issue.

### Logged-In Empty-Profile Fallback Needs Ongoing Attention

Fallback behavior for logged-in users with weak or empty personalization should keep being verified during future ranking changes.

### Client Badge Drift Must Be Avoided

Clients must not infer or rewrite badges. Backend remains the source of truth.

## 7. Expected Correct Behavior

The expected behavior remains:

- If preferences exist, preference-based picks should appear.
- If repeated orders exist, order-history-based picks should gradually become stronger.
- If no preferences or meaningful history exist, fallback popular items should appear.
- New-launch boost should not overpower strong preference matches.
- Dynamic Best Seller should support discovery but should not overpower personalization.
- Labels should remain clean, accurate, and secondary to ranking.

Practical expectations:

- unchecked recent item does not show `Just Launched`
- checked recent item can show `Just Launched`
- checked recent item with strong demand can show `Trending Now`
- a branch bestseller can show `Best Seller`
- repeated order behavior can surface `Based on Your Orders`
- strong preference or taste alignment can surface `Matches Your Taste`
- generic personalized matches can surface `Recommended for You`

## 8. Safe Change Rules

Future changes must follow these rules.

- Do not remove recommendation API endpoints.
- Do not change response shape without updating `frontend-customer` and `mobile`.
- Keep backward compatibility for recommendation payloads and menu item badge fields.
- Keep `frontend-customer` and `mobile` badge behavior synchronized.
- Keep recommendation cache invalidation working.
- Keep bestseller cache invalidation working.
- Keep fallback behavior stable.
- Keep backend as the source of truth for badge selection.
- Do not let badge text become the primary ranking signal.

If recommendation ranking ever needs rollback, prefer:

- preserving the same API contract
- returning compatible fallback/popular results
- keeping badge fields present even if ranking becomes simpler

## 9. Cache Behavior

### Recommendation Cache

Recommendation responses are cached in Redis.

Recommendation caches should invalidate on:

- preference update
- order placement
- order status change
- menu item create
- menu item update
- `is_new_launch` change
- `launched_at` change
- item availability change
- menu item deletion

### Best Seller Cache

Best Seller data is cached per branch/location in Redis.

Current invalidation triggers:

- order placement
- order status change
- menu item create
- menu item update
- item availability change
- menu item deletion

Current implementation notes:

- recommendation cache is user/discovery oriented
- bestseller cache is branch/location oriented
- RAG response cache is also cleared on menu item create/update/delete and availability changes

## 10. Backend / Frontend / Mobile Handling

### Backend

Backend is responsible for:

- ranking recommendation candidates
- computing dynamic bestseller state
- computing badge metadata
- enforcing badge priority
- preventing `launched_at` alone from producing `Just Launched`

### Frontend Admin

Admin/Owner controls:

- `Mark as Just Launched`
- `Featured Item`

Admin surfaces should:

- show dynamic `Best Seller` status separately
- keep `Featured Item` as manual merchandising
- never let manual featured state masquerade as dynamic Best Seller

### Frontend Customer

Customer web should:

- show only one compact badge on cards
- use backend-provided metadata only
- render `Best Seller` only when backend says the item qualifies

### Mobile

Mobile mirrors customer web behavior:

- one compact badge
- backend-provided label only
- no invented labels

### Chatbot / RAG

If chatbot suggestions include recommendation metadata:

- backend metadata is the source of truth
- Qwen must not invent badge labels
- Qwen must not invent bestseller state

## 11. Testing Checklist

Use this checklist whenever recommendation or badge logic changes.

- preference-based recommendations still surface when preferences exist
- repeated order recommendations still strengthen over time
- no-preference fallback still surfaces popular items
- unchecked recent item does not show `Just Launched`
- checked recent item shows `Just Launched`
- checked item with high popularity shows `Trending Now`
- repeated-order user can see `Based on Your Orders`
- taste/preference match user can see `Matches Your Taste`
- generic personalized match can show `Recommended for You`
- branch-wise bestseller works
- only valid statuses count toward Best Seller
- `PLACED` orders do not count toward Best Seller
- failed or refunded orders do not count toward Best Seller
- minimum bestseller threshold works
- unavailable items are not marked as bestsellers
- inactive or unapproved restaurant items are not marked as bestsellers
- older items no longer show a launch badge after the window expires
- unavailable items are not recommended in customer-facing results
- `frontend-customer` badge rendering matches backend label
- `mobile` badge rendering matches backend label
- restaurant menu ordering still works
- admin/owner featured toggle persists correctly
- recommendation cache invalidates after launch-flag updates
- bestseller cache invalidates after order and availability changes
- chatbot/RAG compatibility remains intact when badge metadata is present

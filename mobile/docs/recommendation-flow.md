See the canonical project-wide recommendation doc at:

- [docs/recommendation-flow.md](/Users/imac/Desktop/restaurant-rag/docs/recommendation-flow.md)

This mobile copy is intentionally kept as a pointer so the recommendation and badge rules stay documented in one place.

## 7. Safe Change Rules

Future recommendation changes should follow these rules.

- Do not remove recommendation API endpoints without adding a compatibility replacement.
- Do not change recommendation response shape without updating `frontend-customer` and `mobile`.
- Keep backward compatibility for `score`, `is_new`, and recommendation metadata fields unless all clients are updated together.
- Keep `frontend-customer` and `mobile` behavior synced.
- Keep recommendation cache invalidation working.
- Keep fallback behavior stable.
- Do not let badge logic become the ranking source of truth.
- Do not let new-item boost become stronger than explicit preference match.

Rollback safety note:

- ranking behavior can be simplified or replaced more safely than the entire recommendation API surface can be removed
- full removal is not considered safe without coordinated backend and client updates

## 8. Cache Behavior

Recommendation cache is currently user-scoped and Redis-backed.

Primary cache key:

- `recommendations:{user_id}`

Current cache-related behavior:

- authenticated recommendation results are cached
- public query-based recommendation paths can still compute fresh results
- cache payloads include recommendation score and new-item metadata

Recommendation cache should invalidate on:

- preference update
- order placement
- order status change
- menu item added
- menu item updated
- menu item availability change

Relevant current paths:

- [backend/app/services/recommendations.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/recommendations.py)
- [backend/app/services/orders.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/orders.py)
- [backend/app/api/menu_items.py](/Users/imac/Desktop/restaurant-rag/backend/app/api/menu_items.py)

Important operational note:

- time-based newness can still appear stale until cache expiry or invalidation, because cached recommendation payloads include computed new-item metadata

## 9. Testing Checklist

Use this checklist before and after recommendation changes.

- Verify preference-based recommendations surface correctly when user preferences exist.
- Verify repeated paid orders increase recommendation influence over time.
- Verify no-preference/no-history users receive fallback popular items.
- Verify new-item badges display correctly for eligible new items.
- Verify old items stop showing new-item badges after the launch window passes.
- Verify unavailable items are not recommended.
- Verify `frontend-customer` displays recommendation badges and reasons correctly.
- Verify `mobile` displays recommendation badges and reasons correctly.
- Verify restaurant menu ordering follows recommendation output without breaking menu browsing.
- Verify chatbot/RAG suggestion cards remain compatible with new-item metadata if applicable.
- Verify preference updates invalidate recommendation cache.
- Verify order placement invalidates recommendation cache.
- Verify order status changes invalidate recommendation cache.
- Verify menu item create/update/availability changes invalidate recommendation-related discovery caches.

## 10. Related Files

Core backend:

- [backend/app/services/recommendations.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/recommendations.py)
- [backend/app/services/menu_item_metadata.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/menu_item_metadata.py)
- [backend/app/api/recommendations.py](/Users/imac/Desktop/restaurant-rag/backend/app/api/recommendations.py)
- [backend/app/api/preferences.py](/Users/imac/Desktop/restaurant-rag/backend/app/api/preferences.py)
- [backend/app/services/orders.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/orders.py)
- [backend/app/api/menu_items.py](/Users/imac/Desktop/restaurant-rag/backend/app/api/menu_items.py)
- [backend/app/services/rag.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/rag.py)
- [backend/app/services/favorites.py](/Users/imac/Desktop/restaurant-rag/backend/app/services/favorites.py)

Client usage:

- [frontend-customer/src/services/api.ts](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/services/api.ts)
- [frontend-customer/src/pages/HomePage.tsx](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/pages/HomePage.tsx)
- [frontend-customer/src/pages/RestaurantPage.tsx](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/pages/RestaurantPage.tsx)
- [frontend-customer/src/utils/menuPersonalization.ts](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/utils/menuPersonalization.ts)
- [frontend-customer/src/utils/newItemBadges.ts](/Users/imac/Desktop/restaurant-rag/frontend-customer/src/utils/newItemBadges.ts)
- [mobile/src/services/api.ts](/Users/imac/Desktop/restaurant-rag/mobile/src/services/api.ts)
- [mobile/src/screens/home/HomeScreen.tsx](/Users/imac/Desktop/restaurant-rag/mobile/src/screens/home/HomeScreen.tsx)
- [mobile/src/screens/restaurant/RestaurantScreen.tsx](/Users/imac/Desktop/restaurant-rag/mobile/src/screens/restaurant/RestaurantScreen.tsx)
- [mobile/src/utils/menuPersonalization.ts](/Users/imac/Desktop/restaurant-rag/mobile/src/utils/menuPersonalization.ts)
- [mobile/src/utils/newItemBadges.ts](/Users/imac/Desktop/restaurant-rag/mobile/src/utils/newItemBadges.ts)

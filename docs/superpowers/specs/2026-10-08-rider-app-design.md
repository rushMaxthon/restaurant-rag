# Own delivery fleet and the Rider app — design

Date: 2026-10-08. Status: approved in conversation, awaiting written review.

## Why

Deliveries go to Pidge today. The platform will also hire its own riders. They
need an Android app to receive orders, go to the restaurant, collect the food,
reach the customer and prove the hand-over, and the platform needs to dispatch
to them, track them, and pay them. Pidge stays, as the backup.

## Decisions (from the user)

| Question | Decision |
|---|---|
| Dispatch | **Auto-offer to the nearest online, free rider; 30 s to accept; then the next.** Admin can reassign by hand. |
| Pidge | **Own riders first, Pidge as backup**, automatically. |
| Rider pay | **Per delivery: base + per km**, set by the super admin. Payout done outside the app (bank), recorded in admin. |
| Cash | **No cash on delivery.** Riders only carry prepaid orders. |
| Fleet ownership | **One platform-wide fleet, super admin only.** Owners see "rider assigned", never manage riders. |
| Login | **Admin creates the rider; phone + password.** No self-signup. |
| Proof of delivery | **4-digit OTP** the customer reads out. |
| Maps | **Google Maps SDK** (react-native-maps) in the app; **turn-by-turn opens the Google Maps app.** |
| Location | **~10 s on a trip**, ~60 s while online and waiting; nothing while offline. |
| Platform | **React Native CLI, Android first**, folder `rider/` in this repo. |
| Feel | Full animated, smooth, attractive; no crash, lag or bug. |

Out of scope for v1: iOS build, cash collection, self-signup and document
upload, batching several orders on one trip, ratings, in-app chat, the
customer **mobile** app's tracking screen (web storefront first).

## Architecture

### The fleet is a courier

`services/delivery/` already has a courier contract (`base.py`:
`DeliveryProvider`, `DeliveryState`, `DeliveryRequest/Result`) and a registry,
written so "a second courier is a module and a registry entry, not a change to
the order flow". The own fleet is that module: `own_fleet_provider.py`,
`PROVIDER_NAME = "own_fleet"`.

Why this and not a parallel dispatch system: `order_deliveries` (one row per
order, `order_id` unique) already carries `state`, `rider_name`,
`rider_mobile`, `rider_latitude/longitude/location_at`, `pickup_eta`,
`drop_eta`, `timeline`, `attempt`, `failure_reason`. The admin Delivery panel,
the storefront order page, `advance_order` (forward-only status moves) and the
slab pricing already read it. A second system would duplicate all of that and
the two would disagree about one order.

Unlike Pidge, `create()` books nobody synchronously: it returns `PENDING` and
the **offer loop** (below) finds the rider. Riders' actions call back into
`service.record()` exactly as a Pidge webhook does, so order status moves by
one rule for both couriers.

### Fallback to Pidge

The same row is re-pointed: `provider` becomes `pidge`, `attempt` += 1, the
timeline gets `{"event": "fallback", "reason": ...}`, and the existing
`dispatch` path books Pidge. Reasons: nobody online in range, every offer
declined/expired, or the offer window (default 4 min) passed. If Pidge is not
configured, the row stays PENDING with `last_error` saying why, and admin is
alerted (Platform watch) — never silently stuck.

### Data model (migration `0089_own_fleet`, RLS on in the migration)

- `UserRole.RIDER`. Platform staff: `app_client_id` NULL, no
  `staff_restaurant_*`. The platform-uniqueness partial indexes name staff roles
  explicitly (lesson of `0071`) and must be widened to include RIDER; the enum
  value is added in an `autocommit_block()` (also `0071`'s lesson).
- `riders` — `user_id` (PK, FK users), `vehicle_type` (BIKE/SCOOTER/CYCLE),
  `vehicle_number`, `city`, `status` (OFFLINE/ONLINE/ON_TRIP), `status_at`,
  `last_latitude`, `last_longitude`, `last_location_at`, `fcm_token`,
  `app_version`, `notes`.
- `rider_offers` — `id`, `order_delivery_id`, `rider_user_id`, `offered_at`,
  `expires_at`, `responded_at`, `outcome` (PENDING/ACCEPTED/DECLINED/EXPIRED/
  WITHDRAWN), `distance_to_pickup_m`. One PENDING offer per delivery at a time
  (partial unique index).
- `rider_trips` — one per accepted delivery: `order_delivery_id` (unique),
  `rider_user_id`, `accepted_at`, `arrived_pickup_at`, `picked_up_at`,
  `arrived_drop_at`, `delivered_at`, `ended_at`, `end_reason`
  (DELIVERED/CANCELLED_BEFORE_PICKUP/CANCELLED_AFTER_PICKUP/CUSTOMER_UNAVAILABLE/
  REASSIGNED), `distance_km`, `earning_amount`, `earning_breakdown` (JSONB),
  `payout_id`.
- `rider_payouts` — `id`, `rider_user_id`, `period_from`, `period_to`,
  `amount`, `reference`, `paid_at`, `created_by_user_id`.
- `order_deliveries.delivery_otp_hash` + `otp_attempts` + `otp_locked`.
  The OTP is stored hashed; the plain code is derived for the customer from a
  server secret (HMAC of order id), so it is never stored in clear.
- Settings in `platform_settings` key `rider_pay`:
  `{"base": 25, "per_km": 6, "min": 30}` and key `own_fleet`:
  `{"offer_seconds": 30, "max_offers": 5, "window_minutes": 4,
  "radius_km": 6, "silent_minutes": 3}`. Edited on the admin page beside
  Delivery pricing; validated like `slabs.validate_update`.

### Dispatch — the offer loop

`services/fleet/dispatch.py`, driven by Celery (`fleet` work on the existing
`notifications` queue plus a beat tick every 10 s as the safety net).

1. Candidates: riders `ONLINE`, location fresher than `silent_minutes`,
   straight-line distance to the branch ≤ `radius_km`, not already offered this
   delivery. Nearest first.
2. Offer to one: insert `rider_offers` PENDING, push FCM high-priority data
   message + Socket.IO `rider:offer` to `rider:{user_id}`.
3. Accept: `SELECT … FOR UPDATE` on the delivery row; only if the offer is still
   PENDING and unexpired and the delivery has no trip → create trip, rider
   `ON_TRIP`, delivery `ASSIGNED` with rider name/mobile. Otherwise the rider
   gets 409 "Taken / expired".
4. Decline / expire → next candidate immediately.
5. Stop and fall back to Pidge when step 1 is empty, `max_offers` reached, or
   `window_minutes` elapsed.
6. Admin reassign: withdraw open offer / end trip `REASSIGNED`, then offer to
   the named rider (same accept rule).

### Trip state

| Rider action | Trip column | DeliveryState | Order status (via `advance_order`) |
|---|---|---|---|
| Accept | `accepted_at` | ASSIGNED | unchanged |
| Arrived at restaurant | `arrived_pickup_at` | ASSIGNED | unchanged |
| Picked up (slide) | `picked_up_at` | PICKED_UP | OUT_FOR_DELIVERY |
| Arrived at customer | `arrived_drop_at` | IN_TRANSIT | unchanged |
| Delivered (OTP) | `delivered_at` | DELIVERED | DELIVERED |
| Customer unavailable | `ended_at` | FAILED | unchanged; admin decides |

Each action is idempotent (same action twice = 200, same result), carries a
client-generated `action_id`, and is refused if out of order. Earnings are
computed at DELIVERED (and at CANCELLED_AFTER_PICKUP / cancelled after
`arrived_pickup_at`): `max(min, base + per_km × trip km)` where trip km is
pickup→drop road distance already stored as `distance_metres`, else
straight-line × `delivery_road_factor`.

OTP: 5 wrong tries locks; admin "Confirm delivered" with a written reason
unlocks and completes (logged in timeline with the admin's id).

Customer unavailable: allowed only after `arrived_drop_at` + 10 min and at
least two call attempts recorded by the app.

Restaurant/system cancellation: rider gets `rider:trip_cancelled`; trip ends;
paid if `arrived_pickup_at` was set.

### Rider liveness

`POST /rider/location` takes a batch of fixes (≤ 20). Server keeps the latest on
`riders` and, on a trip, on `order_deliveries.rider_*`, and emits the existing
`order:updated` hint for that order (throttled to once per 10 s). A beat task
marks riders with no fix for `silent_minutes` OFFLINE (if not on a trip) or
raises a Platform watch alert (if on one).

### API (`/api/rider/*`, `require_rider`; admin under `/api/admin/riders/*`)

Rider: `POST /auth/login` (existing, phone + password), `GET /rider/me`,
`POST /rider/status` (online/offline), `POST /rider/location`,
`POST /rider/device-token`, `GET /rider/offers/current`,
`POST /rider/offers/{id}/accept|decline`, `GET /rider/trip` (active),
`POST /rider/trip/{id}/arrived-pickup|picked-up|arrived-drop|delivered|unavailable|call-logged`,
`GET /rider/earnings?from&to`, `GET /rider/trips?cursor`.

Admin (ADMIN only): riders CRUD + activate/deactivate (bumps `token_version`),
reset password, live map feed (`GET /admin/riders/live`), offers/trip history
per delivery, reassign, confirm-delivered, pay settings, payouts (create =
mark trips paid for a period).

Customer: `GET /orders/{id}` gains `delivery.otp` (only to the order's
customer, only while ASSIGNED…IN_TRANSIT and provider is own_fleet) and the
rider's position/ETA, which it already carries for Pidge.

Realtime: rider sockets join `rider:{user_id}` only. Events
`rider:offer`, `rider:offer_withdrawn`, `rider:trip_updated`,
`rider:trip_cancelled` — hints; the app refetches over REST.

### Flag

`enable_own_fleet` (settings, default **off**). Off: registry never returns the
own-fleet provider; rider endpoints still work for login/profile so riders can
be onboarded and trained before go-live. Optional allowlist of restaurant
location ids in `own_fleet` settings for a city-by-city start (a platform
setting with a visible list on the admin page, not a code constant).

## The Rider app (`rider/`)

Template: `kitchen/` (RN 0.85.2, React 19.2, React Navigation 7, Firebase
messaging, Notifee, Socket.IO, AsyncStorage, same folder layout, Jest against
real store and navigation with `src/services` mocked). No code shared at
runtime; patterns copied.

Additional libraries:

| Library | Why |
|---|---|
| react-native-reanimated 4 + react-native-worklets | UI-thread animation (60 fps under load) |
| react-native-gesture-handler | slide-to-confirm, sheets |
| @gorhom/bottom-sheet | trip sheet with snap points |
| react-native-maps (Google provider) | map, markers, polyline |
| react-native-geolocation-service / foreground service via Notifee | location incl. background on a trip |
| lottie-react-native | delivered / online animations |
| @shopify/flash-list | jank-free lists |
| react-native-haptic-feedback | tactile confirmation |
| @react-native-firebase/crashlytics | crash reports |
| react-native-keychain | token in Android Keystore, not AsyncStorage |
| @react-native-community/netinfo | offline queue |

Screens: Splash → Login → Permissions walkthrough → Home (map, online toggle,
today's earnings/trips, active trip card) → New order (full-screen, sound,
countdown ring, Accept/Decline) → Trip (stepper, Navigate, Call, items,
slide-to-pick-up, slide-to-deliver, OTP 4 boxes, Customer unavailable) →
Delivered (Lottie) → Earnings (today/week, bar per day, trip list, paid/unpaid)
→ History → Profile (vehicle, app version, support call, sign out).

Design: map-first dark theme with one accent; light follows system; high
contrast toggle; Plus Jakarta Sans; touch targets ≥ 48 dp; every disabled
control says why (house rule).

Robustness:
- Offline action queue persisted; retried with the same `action_id`.
- Foreground service with a persistent notification during a trip and while
  online; FCM high-priority data message + Notifee full-screen intent for an
  offer when the app is closed.
- Permissions screen blocks going online until location (always),
  notifications, exact alarm/full-screen intent and battery-optimisation
  exemption are granted, each explained in one sentence.
- Error boundary per screen; Crashlytics; TypeScript strict; Hermes + R8 in
  release; tested on a low-end Android (≈2 GB RAM).
- Session revoked (`session:revoked` / 401) → back to login, foreground service
  stopped, rider set offline server-side.

## Admin panel (`frontend-admin`, no new deps)

`RidersPage` (ADMIN only): list with status pills, add/edit/deactivate, reset
password; live map — **no map library allowed**, so v1 shows a sortable list
with distance and "open in Google Maps" links, plus a static map image if the
Maps Static API is enabled; pay + dispatch settings; payouts (unpaid totals per
rider, "Mark paid" for a period). `DeliveryPanel` shows own-fleet state: offers
tried, current rider, fallback reason, Reassign, Confirm delivered.

## Customer storefront

Order page shows the 4-digit OTP card while own-fleet delivery is on its way,
and the rider's position (existing rider location rendering) with ETA.

## Testing

- Backend `unittest`: offer loop (nearest first, expire → next, max offers →
  Pidge, nobody online → Pidge), accept race (two accepts, one wins), trip order
  enforcement, idempotent actions, OTP lock/admin override, earnings formula,
  cancellation pay rule, liveness sweep, role scoping (rider sees only own
  offers/trips; 404 otherwise), customer sees OTP, nobody else does, flag off =
  nothing changes.
- Rider app Jest: trip stepper rules, offline queue, countdown, slide component,
  permission gate, API client 401 handling.
- Manual end-to-end on a real Android phone against local backend with the
  rehearsal-style local guard: kitchen accepts → offer arrives with app closed →
  accept → pick up → OTP → delivered → earnings show.

## Risks

- **Riders miss offers because Android kills the app.** Mitigated by the
  permission gate, foreground service and high-priority FCM; verified on a
  Xiaomi/Realme-class phone, where this fails most.
- **Google billing.** The Maps SDK for Android needs a valid billing account
  (the current one is flagged). Map display on Android is free, but the key
  must belong to a project with valid billing.
- **Two systems claiming one order.** Prevented by the unique delivery row,
  `FOR UPDATE` on accept, and fallback re-pointing the same row.
- **Background location policy on Google Play** requires a declared use and a
  video; plan for review time before public release (internal testing track is
  fine meanwhile).

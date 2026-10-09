# Rider app: first-time guide and the missing pieces — design

Date: 2026-10-09. Builds on `2026-10-08-rider-app-design.md`. Rider app only;
English only; no in-app map (Google Maps SDK needs billing that is not set up).

## Why

A rider who installs the app is handed Login → Permissions → Home and nothing
tells them that an order *rings* full screen, that each stop is slide-to-confirm,
or that the customer's 4-digit code is what pays them. The app assumed the
manager explained it. Beyond that, a review of every screen found real gaps:
no list of payments received, no detail for a finished delivery, an Appearance
row that cannot be tapped, only the Trip screen knowing about lost network, and
no way to hear what the order alert sounds like before the first real one.

## Decisions (from the user)

- Guide style: intro cards once after first sign-in, PLUS spotlight tips the
  first time each screen opens. Both replayable from Profile.
- English only. All guide copy lives in one module (`guide/tours.ts`) so a
  translation layer later has one place to read.
- No new native dependencies. The spotlight is drawn with `react-native-svg`
  (already installed); the problem sheet uses `@gorhom/bottom-sheet` (already
  installed).

## The guide (`rider/src/guide/`)

### Intro cards (`IntroScreen`)

Route `Intro` on the root stack, shown once: SessionProvider's first-sign-in
path lands on `Intro` when `guide.intro` is unseen, else on Permissions/Main as
today. Four cards in a paged horizontal list, each built from the app's own
components so the rider sees the real thing:

1. **Go online** — the `OnlineToggle`, non-interactive, animating to online.
2. **An order rings** — `CountdownRing` counting from 30, "Accept before the
   ring runs out. Decline costs nothing."
3. **Slide at each stop** — a demo `SlideToConfirm` the rider can actually
   slide (it springs back).
4. **The code pays you** — four `OtpInput` boxes filling in, then
   `AnimatedAmount` landing. "Ask the customer for their 4-digit code."

Skip (top right) and Next; the last card's button is "Let's set up" →
Permissions (or Main when permissions are already granted). Marks `intro` seen
on leaving by either path. Profile → "How the app works" opens it again with a
"Done" that just goes back.

### Spotlight tips (`GuideProvider`, `Spotlight`, `useTour`)

- `GuideProvider` wraps the signed-in tree. It keeps a registry of targets:
  `register(id, ref)` stores a `View` ref; `measure(id)` calls
  `measureInWindow`. Screens and the TabBar register with `useGuideTarget(id)`
  which returns a ref to spread onto the element.
- A tour is `{ id, steps: [{ target, title, body }] }` from `guide/tours.ts`.
  Every `target` named there must be a key of `TARGETS` in the same file; a test
  enforces it so a renamed target cannot silently leave a blank tour step.
- `useTour(tourId, { ready })` — on screen focus, when `ready` (data loaded),
  the tour unseen, no offer on screen and no tour already running, waits
  600 ms for layout to settle and starts. Seen is written when the tour ends by
  Done OR Skip. A tour whose target fails to measure (not rendered) skips that
  step; a tour with no measurable step marks itself seen and shows nothing.
- `Spotlight` renders once, at the root inside `GuideProvider`, above the
  navigator: a full-screen `Svg` with a `Mask` — white rect minus a rounded
  rect around the target padded by 8 dp — filled with `colors.overlay`, and a
  card with title, body, "n of N", Next/Done and Skip. `placeTooltip(target,
  window, cardHeight)` (pure, tested) puts the card below the target when there
  is room for it, else above, and clamps x within 16 dp gutters. Fade in with
  reanimated; the cut-out springs between steps. Tapping the dark area does
  nothing (a rider on a bike should not be able to dismiss by accident); only
  Next/Done/Skip advance.
- Tours cancel at once when `offer` becomes non-null (OfferScreen is a modal
  above everything and the ring must not be covered).
- Seen flags persist in AsyncStorage key `rider.guide.v1` as
  `{ [tourId]: true }`. `guideStore.ts` (pure): `isSeen`, `markSeen`,
  `resetAll`, `decode`/`encode` tolerant of garbage.

Tours and steps (copy in `tours.ts`):

| tour | screen | steps (target → title: body) |
|---|---|---|
| `intro` | IntroScreen | (the cards) |
| `home` | Home | `home.toggle` → "Go online to get orders": "Tap here at the start of your shift. Orders only come while you're online." · `home.today` → "What you've made today": "Updates after every delivery. Tap the Earnings tab for the week." · `tab.orders` → "Orders waiting near you": "Any order nobody has taken yet. Take one from here if you're online and free." |
| `orders` | Orders | `orders.take` (first card's button) → "Take an order": "Looking is free. Taking needs you online with no delivery in hand." |
| `trip` | Trip (to_pickup) | `trip.steps` → "Your four stops": "Restaurant, collect, customer, deliver. The bar fills as you go." · `trip.slide` → "Slide when you're there": "Only slide once you've actually arrived. It tells the customer where their food is." |
| `otp` | Trip (at_drop) | `trip.otp` → "Ask for the code": "The customer has a 4-digit code on their order page. Type it and you're paid." |
| `earnings` | Earnings | `earnings.unpaid` → "To be paid": "Everything you've earned that hasn't reached your bank yet. Payments appear below." |

Profile → "Show tips again" calls `resetAll` and navigates Home, so the Home
tour starts immediately.

## Screens

- **Global connection strip** (`components/ConnectionBanner.tsx`): NetInfo
  `isConnected === false` for more than 1.5 s shows a slim bar under the
  status bar, "No connection — we'll keep trying", slides away when back.
  Mounted once in `SignedIn`. The Trip screen's own "step saved" banner stays:
  it says something more specific.
- **Home**: registers `home.toggle` and `home.today`. Going offline shows a
  "Shift done" card for 8 s — "N deliveries · ₹X today" from `me` — dismissible.
- **TabBar**: registers `tab.orders` on the Orders tab.
- **Orders**: registers `orders.take` on the first card's Take button; the tour
  only runs when the list is non-empty (`ready: openOrders.length > 0`).
- **Trip**: registers `trip.steps`, `trip.slide`, `trip.otp`. "Having a
  problem?" ghost button under the Call/Navigate row opens a bottom sheet
  (`components/trip/ProblemSheet.tsx`): Call restaurant, Call customer, Call
  support, and — at the door only — the existing "Customer unavailable" block
  (calls made, minutes waited, the gated button). The inline "Customer not
  answering?" toggle under the OTP card is removed; the sheet is the one place.
- **Delivered**: primary button "Done" → Home. When `openOrders.length > 0` a
  secondary "N orders waiting" → Orders tab.
- **Earnings**: a segmented control Today / 7 days / 30 days (`days` = 1 / 7 /
  30; backend already accepts it). Hero and chart follow the period; the chart
  hides for Today. New **Payments** section: `GET /rider/payouts`, rows
  "₹amount · N deliveries · paid <date>" with the reference in small text;
  empty state "Nothing paid yet. ₹unpaid is due." Registers `earnings.unpaid`.
- **History**: a row is pressable → `TripDetail` route with the `Trip` as a
  param (no new fetch; the list already has the full row). Screen shows:
  timeline from the five timestamps via `tripTimeline(trip)` (pure, tested;
  missing timestamps render as skipped), pickup and drop with addresses, items,
  distance, earning, how it ended (`END_LABEL` moves to `utils/history.ts`).
- **Profile**: Appearance opens a three-way choice (System / Light / Dark) in
  a bottom sheet; `ThemeProvider` gains `preference` persisted in
  `rider.theme` and `mode` resolves from it. "Test the order alert" posts a
  local Notifee notification on the offer channel with the same sound and
  vibration pattern (`services/push.ts testOfferAlert`), cleared after 6 s.
  Rows "How the app works" and "Show tips again" under a new GUIDE heading.

## Backend

`GET /api/rider/payouts` (`require_rider`) → `list[PayoutOut]` for the caller,
newest `paid_at` first, limit 50. `payouts.rider_payouts(db, rider_user_id)`.
Test: a rider sees their own payouts and not another rider's.

## Testing

Jest (pure, no rendering): `guideStore` (seen/reset/decode garbage),
`placeTooltip` (below when room, above otherwise, x clamped), `tours` (every
target exists, every tour has ≥1 step, no step without copy), `tripTimeline`,
`earningsPeriod` (label and `days`), theme preference resolution, the
Delivered secondary-button rule. Backend unittest for the route. Existing
suites stay green. Then on the emulator: fresh install → intro → permissions →
Home tour → go online → sandbox order → Orders/Trip/OTP tours → Delivered →
Earnings → History → detail → Profile rows.

## Not in this pass

In-app map and ETA; Hindi/Gujarati; new trip actions ("order not ready");
R8/release build.

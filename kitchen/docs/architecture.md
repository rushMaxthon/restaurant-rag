# Kitchen app architecture

The kitchen board as a native app for tablets and phones. Laid out on the same
pattern as `mobile/` so a developer who knows one finds their way around the
other; no code is shared with or copied from `mobile/`. The functional
reference is the web board, `frontend-kitchen/` — same API, same rules,
redesigned for touch rather than ported.

## Root

| File | Role |
|---|---|
| `index.js` | registers the app |
| `App.tsx` | SafeArea → `AppStoreProvider` → `AppThemeProvider` → `RealtimeProvider` → `NavigationContainer` → `StackNavigation` |
| `babel.config.js` / `tsconfig.json` | path aliases — keep the two lists identical |
| `jest.config.js` / `jest.setup.js` | transforms the ESM libraries; stubs AsyncStorage, sound and the socket |
| `.env.example` | documents that there is no env loader, and why |

Aliases: `@` (src), `@screens`, `@navigation`, `@components`, `@services`,
`@hooks`, `@store`, `@types`, `@utils`. Import the domain types as
`@/types/app` — `@types/...` is TypeScript's own namespace and fails (TS6137).

## `src/`

```
theme.ts, themeBase.ts, themePalette.ts   provider / light+dark tokens / status colours, contrast
components/        shared UI — Icon, IconButton, Pill, SearchField, StateView, Skeleton, …
  board/           BoardHeader, MetricsStrip, FilterChips, StageTabs, TicketList, TicketCard
  orders/          OrderItemsList, AdvanceButton, StageProgress, FactList, PaymentPill, …
  realtime/        RealtimeProvider — the one socket, status for every screen
config/            api.ts — backend base URL
data/              boardColumns (stages + empty-state copy), boardFilters
hooks/             useAppStore selectors, usePolling, useBoard, useAdvanceOrder,
                   useOrder, useOrderHistory, useNewOrderAlerts, useRealtime, …
navigation/        stackNavigation/ (root native stack), tabNavigation/ (Home + Settings tabs),
                   hooks/useNavigation.ts, navigationService
screens/           auth/login, board, orders/orderDetail, orders/orderHistory, settings
services/          api (HTTP), auth, orders, restaurants, storage, realtime, sound, orderEvents
store/             AppStore.tsx — session (persisted), preferences
types/             app.ts — mirrors the backend enums and OrderResponse
utils/             pure rules with colocated tests: board, metrics, history, realtime, auth
test/              fixtures and the renderApp harness (tests only)
```

## How data moves

- **REST is the only source of what an order looks like.** Every screen loads
  over REST through `usePolling`, which refetches on an interval, when the
  app returns to the foreground, and on `ordersChanged()`.
- **`ordersChanged()` is the one invalidation signal.** An advance from this
  tablet, a socket push and a reconnect all call it; the board, an open order
  and the completed list all refetch.
- **The socket is a hint.** `order:updated` carries no order data. With it
  live, polling slows from 6s to 30s; with realtime switched off on the server
  (the default, `enable_realtime`), the app polls and says "Polling".
- **The board is four requests**, one per stage, each kept independently: a
  failing stage keeps its last tickets and marks the board "Not updating"
  without blanking the others. All four failing with nothing on screen is the
  full "board isn't updating" fault.
- **Advancing is not optimistic.** The button shows its own spinner; the board
  refetches once the server agrees, and a refusal shows the server's sentence
  on the ticket. One advance per order in flight, across all screens.
- **A 401 on the signed-in token signs out** with an explanation on the login
  screen. A 401 for a token from an earlier login is ignored.
- **Session, sound and branch persist** in AsyncStorage, so a tablet that
  rebooted comes back signed in to the same board.

## Layouts

| Width | Board | Order detail |
|---|---|---|
| ≥ 900pt (landscape tablet, 13" portrait) | four stage columns, metrics strip, search + filters | two panes: dishes left, facts + action right |
| 600–900pt (portrait tablet) | stage tabs, tickets two across | two panes from 768pt |
| < 600pt (phone) | stage tabs, one ticket per row, search behind an icon | one column, action bar fixed at the bottom |

Navigation: signed out, the root stack holds only Login. Signed in, its base
is `MainTabs` — bottom tabs **Home** (the board) and **Settings** — with
Order details and Completed orders pushed full-screen over the tabs. Tabs
keep each other mounted and pushed screens sit above them, so the board
keeps polling and still announces the next ticket from anywhere in the app.
Tab screens navigate with the shared `useNavigationHook()`: a stack route
bubbles up to the root stack, a tab route is handled by the tab navigator.
`ScreenContainer` drops its bottom inset inside a tab, where the tab bar
already owns it.

## Design system

`themeBase.ts` exports one `space`, `radius` and `type` scale alongside the
colours; screens and components use them rather than their own numbers.
Cards are flat — surface, 1px border, `radius.xl` — with no drop shadows:
shadows in long lists are costly on low-end Android, and colour already
carries the meaning (stage colours on counts and buttons, urgency tints on
ticket headers, amber for customer notes, red only when something is late or
failed). `IconTile`, `StateView`, `Pill` and `ScreenHeader` are the shared
pieces every screen is built from.

## Rendering cost

- **Polls reuse unchanged orders** (`utils/reconcile.ts`): an idle poll
  hands the screen the same board object, so nothing below it re-renders;
  a busy one re-renders only tickets that moved. Board, order and history
  all go through it. `hooks/useBoard.test.tsx` pins this.
- **Tickets compare by displayed minute**: the 15-second clock does not
  redraw every card, only those whose wait actually changed.
- **Derived data is memoised** in `BoardScreen` (per-stage lists, counts,
  flags, callbacks) so memoised children get identical props.
- **One skeleton pulse** shared by every placeholder; the arrival highlight
  is a single native-driven fade, not a loop.
- **Lists** render tickets in small batches with a modest window, and
  detach off-screen rows on Android.

## Push notifications

Modelled on `mobile/` (FCM delivers, Notifee draws, a tap opens the order),
with the kitchen's own behaviour. `services/pushNotifications.ts` holds it all;
`components/notifications/PushNotificationBootstrap.tsx` follows the session;
`index.js` registers the background handlers before the app.

- **Registration** after sign-in (and for a session restored at launch):
  permission, FCM token, `POST /notifications/device-tokens` with a stable
  installation id. Re-registered when FCM rotates the token.
- **Foreground**: a `kitchen_new_order` push draws nothing — it calls
  `ordersChanged()` and the board refetches and chimes itself, so one order
  rings once. Anything else is drawn by Notifee.
- **Background / closed**: the OS draws the push on the `kitchen-new-orders`
  Android channel (sound `new_order`, vibration) or with iOS sound
  `new_order.wav`; data-only messages are drawn by the background handler.
- **Taps** from any state open `OrderDetailScreen`; `navigationService` holds
  the request until the navigator is ready AND someone is signed in.
- **Sign-out** calls `DELETE /notifications/device-tokens/{installation_id}`
  with the outgoing token, then deletes the FCM token on the device, so even a
  forced sign-out stops pushes there.
- **Settings** shows whether notifications are on, with a link to the system
  settings when they are off.
- Everything is a no-op on a build without Firebase configured.

Backend: `services/kitchen_push.py`, behind `enable_kitchen_push` (default
off), sent by a Celery task on the `notifications` queue.

## Where the native board differs from the web board

Two board rules exist only here, added with the 2026-10-06 redesign: the
search also matches the guest's name (`matchesFilter` in `utils/metrics.ts`),
and the summary counts live delivery orders (`BoardMetrics.deliveries`). The
web board (`frontend-kitchen/src/lib/metrics.ts`) still searches by order
number only. Port both, or neither, if the two are meant to agree again.

## Menu & stock (the Menu tab)

`screens/menu/MenuScreen.tsx`, `components/menu/` (row, editor sheet),
`hooks/useKitchenMenu.ts`, `services/menu.ts`, rules in `utils/menuStock.ts`.
Reads `GET /kitchen/menu` for the board's scope; changes go to
`PATCH /kitchen/menu/{id}/stock` and `/sizes/{size_id}/stock`. The kitchen
changes stock only — out of stock, the count, the morning refill, per size —
never visibility or price. Not optimistic: a row shows its pending state and
then the server's answer. An empty count box means "not counted", never zero;
only changed boxes are sent, so orders taken while the editor was open are
not undone. "Back in stock" on a dish counted down to zero opens the editor
for a count instead.

## Native setup that is easy to break

- **The chime** is `new_order.wav`, generated (two tones, 0.4s) into
  `android/app/src/main/res/raw/` and `ios/kitchen/`. On iOS it is in the
  target's Copy Bundle Resources with `path = kitchen/new_order.wav` — the
  template's `kitchen` group has no folder path of its own.
- **AVFoundation is linked explicitly** on the iOS target. `react-native-sound`
  0.13 uses it but its podspec does not declare it, so without the link the
  app fails at link time with undefined `_AVAudioSession…` symbols.
- **Ionicons** — `UIAppFonts` in `Info.plist` and `fonts.gradle` in
  `android/app/build.gradle`. A glyph name outside `components/Icon.tsx`'s
  list is a type error, not a "?" box.
- **react-native-screens** needs `MainActivity.onCreate(null)` on Android.
- **`pod install`** needs `LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8` on this Mac.
- **After changing `babel.config.js`**, start Metro with `--reset-cache`.

## Not built yet

- Keeping the screen awake while the board is open (needs a native module).
- Android has not been built or run; iOS has, on iPhone 16 Pro and iPad Pro 13.

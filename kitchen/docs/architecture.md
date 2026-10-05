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
navigation/        stackNavigation/ (native stack), hooks/useNavigation.ts, navigationService
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

Completed orders is pushed on top of the board, so the board stays mounted
underneath — it keeps polling and still announces the next ticket.

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

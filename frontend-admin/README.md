# Frontend Admin

`frontend-admin/` is the web control panel for the Restaurant RAG platform. It is a React + TypeScript + Vite app used by both `ADMIN` and `OWNER` accounts through one shared UI system.

The UI is shared. Access and data change by role.

Access boundary:

- only `ADMIN` and `OWNER` accounts may sign in here
- `CUSTOMER` accounts must be rejected with: `Customer accounts cannot access the admin panel.`

## What This App Does

This app supports two roles:

- `ADMIN`
  - platform dashboard
  - restaurant list and restaurant workspace access
  - user management
  - AI log visibility
  - reports, notifications, and settings

- `OWNER`
  - lands directly in their restaurant workspace
  - manages their own menu items
  - sees `NEW` launch badges for recently launched dishes
  - manages their own restaurant orders
  - can open role-scoped reports for their assigned restaurant
  - updates limited restaurant settings

## Tech Stack

- React 19
- TypeScript
- Vite
- native browser `fetch`
- localStorage for auth/session persistence
- `lucide-react` for icons

## Current Structure

```text
frontend-admin/
├── src/
│   ├── components/
│   │   ├── DataToolbar.tsx
│   │   ├── EmptyPanel.tsx
│   │   ├── KpiCard.tsx
│   │   ├── MiniChart.tsx
│   │   ├── Pagination.tsx
│   │   ├── PageIntro.tsx
│   │   ├── ResponsiveTable.tsx
│   │   ├── RestaurantMenuTable.tsx
│   │   ├── Sidebar.tsx
│   │   ├── StatusPill.tsx
│   │   ├── TableActions.tsx
│   │   └── ToastViewport.tsx
│   ├── hooks/
│   │   └── useAdminStore.ts
│   ├── layouts/
│   │   └── AdminLayout.tsx
│   ├── pages/
│   │   ├── AILogsPage.tsx
│   │   ├── AdminRestaurantsPage.tsx
│   │   ├── AdminUsersPage.tsx
│   │   ├── DashboardPage.tsx
│   │   ├── GeneratedCombosPage.tsx
│   │   ├── LoginPage.tsx
│   │   ├── MenuItemsPage.tsx
│   │   ├── NotificationsPage.tsx
│   │   ├── OrdersPage.tsx
│   │   ├── ReportsPage.tsx
│   │   ├── RestaurantDetailPage.tsx
│   │   └── SettingsPage.tsx
│   ├── services/
│   │   ├── api.ts
│   │   └── storage.ts
│   ├── store/
│   │   └── AdminStore.tsx
│   ├── types/
│   │   └── app.ts
│   ├── App.tsx
│   ├── index.css
│   └── main.tsx
├── package.json
└── README.md
```

## Important Files

- [src/App.tsx](/Users/imac/Desktop/restaurant-rag/frontend-admin/src/App.tsx)
  - custom pathname router
  - role-based redirects
  - invalid stored-role eviction on startup
  - restaurant workspace route matching

- [src/layouts/AdminLayout.tsx](/Users/imac/Desktop/restaurant-rag/frontend-admin/src/layouts/AdminLayout.tsx)
  - shared shell for all protected pages
  - sidebar and responsive admin layout

- [src/components/Sidebar.tsx](/Users/imac/Desktop/restaurant-rag/frontend-admin/src/components/Sidebar.tsx)
  - same sidebar component for both roles
  - visible items are filtered by role

- [src/store/AdminStore.tsx](/Users/imac/Desktop/restaurant-rag/frontend-admin/src/store/AdminStore.tsx)
  - stores `token`, `role`, `restaurantId`, `user`, and toast state
  - rejects non-admin-panel roles before session persistence
  - persists session in local storage

- [src/services/api.ts](/Users/imac/Desktop/restaurant-rag/frontend-admin/src/services/api.ts)
  - wraps all backend calls
  - central place for auth and admin data requests

- [src/pages/MenuItemsPage.tsx](/Users/imac/Desktop/restaurant-rag/frontend-admin/src/pages/MenuItemsPage.tsx)
  - standalone admin/owner menu management
  - create/edit form now supports optional launch-date override
  - menu tables show compact `NEW` launch state

- [src/components/RestaurantMenuTable.tsx](/Users/imac/Desktop/restaurant-rag/frontend-admin/src/components/RestaurantMenuTable.tsx)
  - shared restaurant-workspace menu management table
  - mirrors launch-date override and `NEW` badge behavior

- [src/components/RestaurantOffersManager.tsx](/Users/imac/Desktop/restaurant-rag/frontend-admin/src/components/RestaurantOffersManager.tsx)
  - shared restaurant-workspace offers / campaigns manager
  - powers owner/admin template management plus generated campaign visibility

## Current Routing and Flow

This app uses a custom history-based router, not React Router.

Main paths:

- `/dashboard`
- `/restaurants`
- `/admin/restaurants/:id`
- `/admin/restaurants/:id/locations`
- `/admin/restaurants/:restaurantId/locations/:locationId`
- `/generated-combos`
- `/menu-items`
- `/orders`
- `/users`
- `/ai-logs`
- `/reports`
- `/notifications`
- `/settings`

### Admin Flow

Admins can:

- open `/dashboard`
- open `/restaurants`
- open `/generated-combos`
- click any restaurant and navigate into that restaurant's locations workspace
- manage generated combos, users, AI logs, reports, notifications, and settings

### Owner Flow

Owners do not use a separate UI.

Instead:

- login response includes `restaurant_id`
- owner is redirected into `/admin/restaurants/{restaurant_id}/locations`
- sidebar hides restricted modules automatically
- owner data loads through the same page components, filtered by role
- owners can also open `/reports`, but backend analytics stay locked to their own restaurant

Login rule:

- `ADMIN` and `OWNER` are allowed
- `CUSTOMER` login attempts fail gracefully and do not create a stored session

## Shared Restaurant Workspace

The restaurant detail page is shared:

- [src/pages/RestaurantDetailPage.tsx](/Users/imac/Desktop/restaurant-rag/frontend-admin/src/pages/RestaurantDetailPage.tsx)

Route:

```text
/admin/restaurants/:id
```

Sections inside this page:

- restaurant details
- settings
- locations
- offers / campaigns
- menu items
- restaurant-specific orders

Behavior:

- `ADMIN`
  - can open any restaurant
  - can edit platform-level restaurant details
- `OWNER`
  - can open only their assigned restaurant
  - can manage offers, menu items, and orders from the same shared page

Location drill-down uses the same shared flow for both roles:

- `Restaurants`
- `Restaurant Locations`
- `Location Detail`
- `Details / Settings / Slots / General Settings / Menu Items / Orders`

Location detail now splits operational control cleanly:

- `Settings`
  - branch identity, address, phone, and opening/closing hours
- `Slots`
  - weekly delivery / pickup windows
  - multiple active slots per day
  - overlap protection enforced by the backend
- `General Settings`
  - open / active toggles
  - delivery / pickup enablement
  - delivery fee / minimum order
  - delivery ETA / pickup ETA
  - temporary closed reason / preparation metadata

## Offers / Campaigns

Restaurant-scoped offer management now lives inside the shared restaurant workspace.

Current behavior:

- `ADMIN` can manage offers for any restaurant
- `OWNER` can manage offers only for their assigned restaurant
- admin/owner configures reusable templates and can inspect generated campaign rows:
  - offer title
  - discount type/value
  - minimum spend
  - expiry / start window
  - restaurant / branch scope
  - item / category / cuisine targeting
- generated campaign rows show source, generation reason, matched-user counts, and performance
- Home/cart checkout use backend validation before applying any discount

Location operations now also control branch-level checkout configuration.

Current location settings include:

- fulfillment toggles:
  - `Delivery enabled`
  - `Pickup enabled`
- scheduling controls:
  - future-order toggle
  - max future days
  - slot interval
  - weekly delivery / pickup slot windows
- payment method toggles:
  - `Google Pay enabled`
  - `Razorpay enabled`
  - `Card payment enabled`
  - `Cash on delivery enabled`

Customer mobile uses these branch payment settings directly:

- only enabled methods appear on the Payment screen for that location
- disabled methods are hidden from the client
- backend still revalidates the selected method before creating the order

Offer states:

- `DRAFT`
- `ACTIVE`
- `PAUSED`
- `EXPIRED`
- `DISABLED`

## Current Role-Based Sidebar

`ADMIN` sees:

- Dashboard
- Restaurants
- Orders
- Users
- AI Logs
- Reports
- Notifications
- Settings

`OWNER` sees:

- Dashboard
- Restaurants
- Generated Combos
- Menu Items
- Orders
- Reports
- Settings

Owner access still uses the same shared restaurant and location pages as admin, but the visible data is limited to the assigned restaurant and its branches.

## New Item Launch Metadata

Admin and owner menu management now participates in the recommendation system automatically.

Current behavior:

- creating a menu item allows an optional `Launch date` override
- when no override is supplied, the backend sets `launched_at` automatically
- recently launched items show a compact `NEW` state in menu tables
- admins and owners do not need to manually assign AI tags like spicy or cuisine affinity
- recommendation labels are computed in the backend from menu metadata and user taste signals

## Table System

The admin panel uses a shared responsive table system:

- [src/components/ResponsiveTable.tsx](/Users/imac/Desktop/restaurant-rag/frontend-admin/src/components/ResponsiveTable.tsx)
- [src/components/TableActions.tsx](/Users/imac/Desktop/restaurant-rag/frontend-admin/src/components/TableActions.tsx)
- [src/components/Pagination.tsx](/Users/imac/Desktop/restaurant-rag/frontend-admin/src/components/Pagination.tsx)

Used by:

- restaurants
- users
- menu items
- orders
- generated combos
- restaurant detail tables

Behavior:

- desktop: sticky-header tables
- smaller screens: card-style mobile presentation
- shared empty and loading states

## Auth and Session Handling

Local storage key:

- `restaurant-rag-admin-auth`

Stored session shape includes:

- token
- role
- restaurantId
- user

Runtime behavior:

- if not authenticated, app shows `LoginPage`
- if a saved session contains a role outside `ADMIN`/`OWNER`, it is cleared before restore
- if authenticated as `OWNER` without `restaurantId`, access is blocked and the user is logged out
- if authenticated session role and `user.role` do not match, access is blocked and the user is logged out
- if owner tries to open another restaurant, the app redirects back to their own restaurant

## Backend APIs Used

Main auth:

- `POST /api/auth/login`

Backend login response requirements used by this app:

- response includes `role`
- response includes `restaurant_id` for owner accounts when available

Shared restaurant routes:

- `GET /api/restaurants/{restaurant_id}`
- `PATCH /api/restaurants/{restaurant_id}/settings`
- `GET /api/menu-items?restaurant_id=...&include_unavailable=true`
- `GET /api/orders?restaurant_id=...`

Admin-specific routes:

- `GET /api/admin/dashboard`
- `GET /api/admin/restaurants`
- `POST /api/restaurants`
- `PATCH /api/admin/restaurants/{restaurant_id}/approval`
- `PATCH /api/admin/restaurants/{restaurant_id}`
- `DELETE /api/admin/restaurants/{restaurant_id}`
- `GET /api/admin/users`
- `PATCH /api/admin/users/{user_id}`
- `GET /api/admin/ai-logs`
- `GET /api/admin/menu-items`

Shared order/menu routes:

- `POST /api/menu-items`
- `PUT /api/menu-items/{menu_item_id}`
- `PATCH /api/menu-items/{menu_item_id}/availability`
- `DELETE /api/menu-items/{menu_item_id}`
- `PATCH /api/orders/{order_id}/status`

## Environment Variable

Expected in `.env`:

```dotenv
VITE_API_BASE_URL=http://localhost:8000/api
```

Fallback base URL in code:

```text
http://localhost:8000/api
```

## Install

From `frontend-admin/`:

```bash
npm install
```

## Run Locally

From `frontend-admin/`:

```bash
npm run dev
```

## Build

From `frontend-admin/`:

```bash
npm run build
```

Preview build:

```bash
npm run preview
```

## Common Commands

```bash
npm run dev
npm run build
npm run lint
npm run preview
```

## Notes for New Developers

- there is one shared admin UI, not a separate owner UI
- update both `App.tsx` and `Sidebar.tsx` when adding a new route
- owner restrictions are enforced in both frontend navigation and backend APIs
- the restaurant workspace is the most important route for owner flows
- table behavior and spacing are centralized in `index.css` and shared table components
## Multi-location workspace

The restaurant workspace now includes branch management:

- admins and owners can open the `Locations` section inside a restaurant workspace
- branches can be created, edited, selected, and deactivated
- selected branch scope is reused for menu management, order review, and generated combos
- each branch can now manage its own pickup / delivery rules through `Slots` and `General Settings`
- owners still remain restricted to their assigned restaurant brand, but can manage all locations under it

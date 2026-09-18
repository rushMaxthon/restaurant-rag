/**
 * Every address this panel answers, in one list.
 *
 * It used to be four lists that had to agree with each other by hand: a
 * nested ternary deciding what to render, a `staticAllowed` map deciding who
 * may open it, and two `Set`s in the sidebar deciding what to show an admin
 * and what to show an owner. Nothing kept them in step, and they had already
 * drifted — an administrator was allowed to open Menu Items and Generated
 * Combos, and the sidebar never offered either.
 *
 * So a route declares all of it in one place: the address, who may open it,
 * which restaurant it is about, where it sits in the navigation, and what it
 * renders. Authorisation and rendering cannot disagree because they are read
 * off the same object.
 *
 * Order matters. `matchRoute` returns the first hit, so a literal path is
 * listed before a pattern that would also swallow it.
 */

import type { ReactNode } from "react";
import {
  BarChart3,
  BellRing,
  Bot,
  Layers3,
  LayoutDashboard,
  type LucideIcon,
  Palette,
  ReceiptText,
  Settings,
  SlidersHorizontal,
  Sparkles,
  Store,
  Building2,
  TicketPercent,
  Users,
  UtensilsCrossed,
} from "lucide-react";

import { AIManagerPage } from "./pages/AIManagerPage";
import { AILogsPage } from "./pages/AILogsPage";
import { AdminRestaurantsPage } from "./pages/AdminRestaurantsPage";
import { AdminUsersPage } from "./pages/AdminUsersPage";
import { BrandingPage } from "./pages/BrandingPage";
import { DashboardPage } from "./pages/DashboardPage";
import { GeneratedCombosPage } from "./pages/GeneratedCombosPage";
import { LocationDetailPage } from "./pages/LocationDetailPage";
import { LocationsPage } from "./pages/LocationsPage";
import { MenuItemEditorPage } from "./pages/MenuItemEditorPage";
import { MenuItemsPage } from "./pages/MenuItemsPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { OffersPage } from "./pages/OffersPage";
import { OrderDetailPage } from "./pages/OrderDetailPage";
import { OrdersPage } from "./pages/OrdersPage";
import { PreferencesPage } from "./pages/PreferencesPage";
import { ReportsPage } from "./pages/ReportsPage";
import { RestaurantDetailPage } from "./pages/RestaurantDetailPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TenantsPage } from "./pages/TenantsPage";
import type { ToastMessage, User, UserRole } from "./types/app";

export type RouteParams = Record<string, string>;

/** Everything a page needs that does not come out of its own URL. */
export interface RouteContext {
  token: string;
  role: UserRole;
  /** The restaurant this session belongs to. Always set for an owner. */
  restaurantId: string | null;
  user: User;
  navigate: (path: string) => void;
  pushToast: (title: string, description: string, tone?: ToastMessage["tone"]) => void;
}

/**
 * "Platform" sits between Overview and Intelligence: it is the operator's
 * own scope, above the per-restaurant work, and only an admin ever sees it —
 * `navFor` drops a section nobody in this role can open.
 */
export type NavSection =
  | "Overview"
  | "Platform"
  | "Intelligence"
  | "Manage"
  | "System";

export interface NavEntry {
  section: NavSection;
  label: string;
  icon: LucideIcon;
  /** An owner has one restaurant, so the link is named for theirs. */
  labelFor?: (role: UserRole) => string;
}

export interface RouteDef {
  id: string;
  /**
   * The address, written once. `"/orders/:orderId"`. The matcher and any
   * link pointing here are both derived from this, so they cannot disagree.
   */
  pattern: string;
  roles: UserRole[];
  /**
   * Which restaurant this URL is about, when it names one. An owner opening
   * an address that names a restaurant other than their own is sent back to
   * their own — one rule, rather than the five near-identical checks this
   * replaces.
   */
  restaurantOf?: (params: RouteParams) => string | null;
  /** Which sidebar entry lights up while this route is open. */
  activeNavPath?: string;
  /** Present when the route is somewhere you can navigate to directly. */
  nav?: NavEntry;
  render: (ctx: RouteContext, params: RouteParams) => ReactNode;
}

/**
 * `"/admin/restaurants/:restaurantId/locations/:locationId"` into a matcher.
 *
 * Readable enough to check against the address bar by eye, which a bare
 * regular expression is not — and these are the addresses that decide who
 * can see whose restaurant. Built once per pattern and kept, because
 * `matchRoute` runs on every render.
 */
type Matcher = (pathname: string) => RouteParams | null;

const MATCHERS = new Map<string, Matcher>();

function matcherFor(pattern: string): Matcher {
  const built = MATCHERS.get(pattern);
  if (built) {
    return built;
  }

  const names: string[] = [];
  const source = pattern.replace(/:([A-Za-z][A-Za-z0-9]*)/g, (_match, name: string) => {
    names.push(name);
    return "([^/]+)";
  });
  const expression = new RegExp(`^${source}$`);

  const matcher: Matcher = (pathname) => {
    const found = pathname.match(expression);
    if (!found) {
      return null;
    }
    const params: RouteParams = {};
    names.forEach((name, index) => {
      params[name] = found[index + 1];
    });
    return params;
  };

  MATCHERS.set(pattern, matcher);
  return matcher;
}

const BOTH: UserRole[] = ["ADMIN", "OWNER"];
const ADMIN_ONLY: UserRole[] = ["ADMIN"];
const OWNER_ONLY: UserRole[] = ["OWNER"];

export const ROUTES: RouteDef[] = [
  {
    id: "dashboard",
    pattern: "/dashboard",
    roles: BOTH,
    nav: { section: "Overview", label: "Dashboard", icon: LayoutDashboard },
    render: (ctx) => (
      <DashboardPage
        onNavigate={ctx.navigate}
        onToast={ctx.pushToast}
        restaurantId={ctx.restaurantId}
        role={ctx.role}
        token={ctx.token}
      />
    ),
  },
  {
    id: "reports",
    pattern: "/reports",
    roles: BOTH,
    nav: { section: "Overview", label: "Reports", icon: BarChart3 },
    render: (ctx) => (
      <ReportsPage
        onToast={ctx.pushToast}
        restaurantId={ctx.restaurantId}
        role={ctx.role}
        token={ctx.token}
      />
    ),
  },
  {
    id: "ai-manager",
    pattern: "/ai-manager",
    roles: BOTH,
    nav: { section: "Intelligence", label: "AI Manager", icon: Sparkles },
    render: () => <AIManagerPage />,
  },

  // --- one restaurant, by id ------------------------------------------------
  // Listed before `/restaurants` only for readability; the patterns cannot
  // collide. The longest address comes first within this group, because
  // `/menu-items/create` under a location would otherwise be read as a
  // location detail page with a strange id.
  {
    id: "menu-item-editor-create-under-location",
    pattern: "/admin/restaurants/:restaurantId/locations/:locationId/menu-items/create",
    roles: BOTH,
    restaurantOf: (params) => params.restaurantId,
    activeNavPath: "/restaurants",
    render: (ctx, params) => (
      <MenuItemEditorPage
        itemId={null}
        locationId={params.locationId}
        onNavigate={ctx.navigate}
        onToast={ctx.pushToast}
        restaurantId={params.restaurantId}
        role={ctx.role}
        token={ctx.token}
      />
    ),
  },
  {
    id: "menu-item-editor-edit",
    pattern: "/admin/restaurants/:restaurantId/locations/:locationId/menu-items/:itemId/edit",
    roles: BOTH,
    restaurantOf: (params) => params.restaurantId,
    activeNavPath: "/restaurants",
    render: (ctx, params) => (
      <MenuItemEditorPage
        itemId={params.itemId}
        locationId={params.locationId}
        onNavigate={ctx.navigate}
        onToast={ctx.pushToast}
        restaurantId={params.restaurantId}
        role={ctx.role}
        token={ctx.token}
      />
    ),
  },
  {
    id: "menu-item-editor-create",
    pattern: "/admin/restaurants/:restaurantId/menu-items/create",
    roles: BOTH,
    restaurantOf: (params) => params.restaurantId,
    activeNavPath: "/restaurants",
    render: (ctx, params) => (
      <MenuItemEditorPage
        itemId={null}
        locationId={null}
        onNavigate={ctx.navigate}
        onToast={ctx.pushToast}
        restaurantId={params.restaurantId}
        role={ctx.role}
        token={ctx.token}
      />
    ),
  },
  {
    id: "location-detail",
    pattern: "/admin/restaurants/:restaurantId/locations/:locationId",
    roles: BOTH,
    restaurantOf: (params) => params.restaurantId,
    activeNavPath: "/restaurants",
    render: (ctx, params) => (
      <LocationDetailPage
        assignedRestaurantId={ctx.restaurantId}
        key={`${params.restaurantId}:${params.locationId}`}
        locationId={params.locationId}
        onNavigate={ctx.navigate}
        onToast={ctx.pushToast}
        restaurantId={params.restaurantId}
        role={ctx.role}
        token={ctx.token}
      />
    ),
  },
  {
    id: "restaurant-locations",
    pattern: "/admin/restaurants/:restaurantId/locations",
    roles: BOTH,
    restaurantOf: (params) => params.restaurantId,
    activeNavPath: "/restaurants",
    render: (ctx, params) => (
      <LocationsPage
        assignedRestaurantId={ctx.restaurantId}
        onNavigate={ctx.navigate}
        onToast={ctx.pushToast}
        role={ctx.role}
        scopedRestaurantId={params.restaurantId}
        token={ctx.token}
      />
    ),
  },
  {
    // App identity is platform configuration, not something an owner edits.
    id: "restaurant-app-client",
    pattern: "/admin/restaurants/:restaurantId/app-client",
    roles: ADMIN_ONLY,
    activeNavPath: "/restaurants",
    render: (ctx, params) => (
      <RestaurantDetailPage
        assignedRestaurantId={ctx.restaurantId}
        initialSection="app_client"
        key={`${params.restaurantId}:app-client`}
        onNavigate={ctx.navigate}
        onToast={ctx.pushToast}
        restaurantId={params.restaurantId}
        role={ctx.role}
        token={ctx.token}
      />
    ),
  },
  {
    id: "restaurant-detail",
    pattern: "/admin/restaurants/:restaurantId",
    roles: BOTH,
    restaurantOf: (params) => params.restaurantId,
    activeNavPath: "/restaurants",
    render: (ctx, params) => (
      <RestaurantDetailPage
        assignedRestaurantId={ctx.restaurantId}
        initialSection="details"
        key={params.restaurantId}
        onNavigate={ctx.navigate}
        onToast={ctx.pushToast}
        restaurantId={params.restaurantId}
        role={ctx.role}
        token={ctx.token}
      />
    ),
  },

  // --- the platform's own scope ---------------------------------------------
  // Above Restaurants on purpose: an operator opens the panel to look at the
  // platform, and a restaurant is something they drill into from here.
  {
    id: "tenants",
    pattern: "/tenants",
    roles: ADMIN_ONLY,
    nav: { section: "Platform", label: "Tenants", icon: Building2 },
    render: (ctx) => (
      <TenantsPage onNavigate={ctx.navigate} onToast={ctx.pushToast} token={ctx.token} />
    ),
  },

  // --- everything else ------------------------------------------------------
  {
    id: "restaurants",
    pattern: "/restaurants",
    roles: BOTH,
    nav: {
      section: "Manage",
      label: "Restaurants",
      icon: Store,
      labelFor: (role) => (role === "OWNER" ? "My Restaurant" : "Restaurants"),
    },
    // An owner has exactly one, so the list is their own branches. The
    // redirect in `redirectFor` normally gets there first; this is what
    // renders if it does not.
    render: (ctx) =>
      ctx.role === "OWNER" && ctx.restaurantId ? (
        <LocationsPage
          assignedRestaurantId={ctx.restaurantId}
          onNavigate={ctx.navigate}
          onToast={ctx.pushToast}
          role={ctx.role}
          scopedRestaurantId={ctx.restaurantId}
          token={ctx.token}
        />
      ) : (
        <AdminRestaurantsPage
          onNavigate={ctx.navigate}
          onToast={ctx.pushToast}
          token={ctx.token}
        />
      ),
  },
  {
    id: "branding",
    pattern: "/branding",
    roles: OWNER_ONLY,
    nav: { section: "Manage", label: "Branding", icon: Palette },
    render: (ctx) => (
      <BrandingPage
        onToast={ctx.pushToast}
        restaurantId={ctx.restaurantId}
        restaurantName={ctx.user.restaurant_name ?? null}
        token={ctx.token}
      />
    ),
  },
  {
    id: "order-detail",
    pattern: "/orders/:orderId",
    roles: BOTH,
    activeNavPath: "/orders",
    render: (ctx, params) => (
      <OrderDetailPage
        key={params.orderId}
        onNavigate={ctx.navigate}
        onToast={ctx.pushToast}
        orderId={params.orderId}
        role={ctx.role}
        token={ctx.token}
      />
    ),
  },
  {
    id: "orders",
    pattern: "/orders",
    roles: BOTH,
    nav: { section: "Manage", label: "Orders", icon: ReceiptText },
    render: (ctx) => (
      <OrdersPage
        onNavigate={ctx.navigate}
        onToast={ctx.pushToast}
        role={ctx.role}
        token={ctx.token}
      />
    ),
  },
  {
    id: "menu-items",
    pattern: "/menu-items",
    roles: BOTH,
    nav: { section: "Manage", label: "Menu Items", icon: UtensilsCrossed },
    render: (ctx) => (
      <MenuItemsPage
        onNavigate={ctx.navigate}
        onToast={ctx.pushToast}
        restaurantId={ctx.restaurantId}
        role={ctx.role}
        token={ctx.token}
      />
    ),
  },
  {
    id: "offers",
    pattern: "/offers",
    roles: BOTH,
    nav: { section: "Manage", label: "Offers", icon: TicketPercent },
    render: (ctx) => (
      <OffersPage
        onNavigate={ctx.navigate}
        onToast={ctx.pushToast}
        restaurantId={ctx.restaurantId}
        role={ctx.role}
        token={ctx.token}
      />
    ),
  },
  {
    id: "generated-combos",
    pattern: "/generated-combos",
    roles: BOTH,
    nav: { section: "Manage", label: "Generated Combos", icon: Layers3 },
    render: (ctx) => (
      <GeneratedCombosPage
        onToast={ctx.pushToast}
        restaurantId={ctx.role === "OWNER" ? ctx.restaurantId ?? undefined : undefined}
        role={ctx.role}
        token={ctx.token}
      />
    ),
  },
  {
    id: "users",
    pattern: "/users",
    roles: BOTH,
    nav: { section: "Manage", label: "Users", icon: Users },
    render: (ctx) => (
      <AdminUsersPage
        currentUserId={ctx.user.id}
        onToast={ctx.pushToast}
        role={ctx.role}
        token={ctx.token}
      />
    ),
  },
  {
    id: "preferences",
    pattern: "/preferences",
    roles: BOTH,
    nav: { section: "Manage", label: "Preferences", icon: SlidersHorizontal },
    render: (ctx) => (
      <PreferencesPage onToast={ctx.pushToast} role={ctx.role} token={ctx.token} />
    ),
  },
  {
    id: "ai-logs",
    pattern: "/ai-logs",
    roles: ADMIN_ONLY,
    nav: { section: "System", label: "AI Logs", icon: Bot },
    render: (ctx) => <AILogsPage onToast={ctx.pushToast} token={ctx.token} />,
  },
  {
    id: "notifications",
    pattern: "/notifications",
    roles: ADMIN_ONLY,
    nav: { section: "System", label: "Notifications", icon: BellRing },
    render: (ctx) => <NotificationsPage onToast={ctx.pushToast} />,
  },
  {
    id: "settings",
    pattern: "/settings",
    roles: BOTH,
    nav: { section: "System", label: "Settings", icon: Settings },
    render: (ctx) => <SettingsPage onToast={ctx.pushToast} />,
  },
];

export interface RouteMatch {
  route: RouteDef;
  params: RouteParams;
}

/** The first route that claims this address, or null. */
export function matchRoute(pathname: string): RouteMatch | null {
  for (const route of ROUTES) {
    const params = matcherFor(route.pattern)(pathname);
    if (params) {
      return { route, params };
    }
  }
  return null;
}

export function mayOpen(route: RouteDef, role: UserRole): boolean {
  return route.roles.includes(role);
}

/** Where someone lands when they have nowhere else to be. */
export function defaultPathFor(role: UserRole, restaurantId: string | null): string {
  if (role === "OWNER" && restaurantId) {
    return `/admin/restaurants/${restaurantId}/locations`;
  }
  if (role === "ADMIN") {
    return "/dashboard";
  }
  return "/login";
}

/**
 * Where this address should send them instead, or null to stay put.
 *
 * Three reasons to move: the address moved and old links should still work,
 * an owner asked for a page about a restaurant that is not theirs, or the
 * route does not exist or is not theirs to open.
 */
export function redirectFor(
  pathname: string,
  role: UserRole,
  restaurantId: string | null,
): string | null {
  const home = defaultPathFor(role, restaurantId);

  // Addresses that moved. Kept because they are in browser histories and in
  // links people have already sent each other.
  const legacyLocationDetail = pathname.match(/^\/locations\/([^/]+)\/([^/]+)$/);
  if (legacyLocationDetail) {
    return `/admin/restaurants/${legacyLocationDetail[1]}/locations/${legacyLocationDetail[2]}`;
  }
  if (pathname === "/locations") {
    return role === "OWNER" && restaurantId
      ? `/admin/restaurants/${restaurantId}/locations`
      : "/restaurants";
  }
  // An owner's "all restaurants" is their own branches.
  if (pathname === "/restaurants" && role === "OWNER" && restaurantId) {
    return `/admin/restaurants/${restaurantId}/locations`;
  }

  const found = matchRoute(pathname);
  if (!found || !mayOpen(found.route, role)) {
    return home;
  }

  // One rule where there were five: an owner may only open an address that
  // names their own restaurant.
  if (role === "OWNER" && found.route.restaurantOf && restaurantId) {
    const named = found.route.restaurantOf(found.params);
    if (named && named !== restaurantId) {
      return home;
    }
  }

  return null;
}

export interface NavItem {
  path: string;
  label: string;
  icon: LucideIcon;
}

export interface NavGroup {
  label: NavSection;
  items: NavItem[];
}

const SECTION_ORDER: NavSection[] = [
  "Overview",
  "Platform",
  "Intelligence",
  "Manage",
  "System",
];

/**
 * The sidebar, built from the same routes it links to.
 *
 * Nothing can appear here that the role cannot open, and nothing they can
 * open is missing — which is how an administrator ended up allowed to reach
 * Menu Items through the address bar while the sidebar never offered it.
 */
export function navFor(role: UserRole): NavGroup[] {
  const groups = new Map<NavSection, NavItem[]>();

  for (const route of ROUTES) {
    if (!route.nav || !mayOpen(route, role)) {
      continue;
    }
    const literal = route.nav.labelFor ? route.nav.labelFor(role) : route.nav.label;
    const items = groups.get(route.nav.section) ?? [];
    items.push({ path: pathOf(route), label: literal, icon: route.nav.icon });
    groups.set(route.nav.section, items);
  }

  return SECTION_ORDER.filter((section) => groups.get(section)?.length).map((section) => ({
    label: section,
    items: groups.get(section) ?? [],
  }));
}

/**
 * The address a link should point at.
 *
 * The pattern itself, because a route that appears in the navigation never
 * takes parameters — there is nothing to fill in.
 */
function pathOf(route: RouteDef): string {
  return route.pattern;
}

/** Which sidebar entry should look selected for the address being shown. */
export function activeNavPathFor(pathname: string): string {
  const found = matchRoute(pathname);
  if (!found) {
    return pathname;
  }
  return found.route.activeNavPath ?? pathOf(found.route);
}

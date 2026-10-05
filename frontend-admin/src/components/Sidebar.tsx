import {
  ChevronDown,
  ChevronLeft,
  LogOut,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  SlidersHorizontal,
  Sun,
  X,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { applyTheme, storedTheme, type Theme } from "../services/theme";
import { useAdminStore } from "../hooks/useAdminStore";
import { useOrdersChanged } from "../hooks/useRealtime";
import { api } from "../services/api";
import {
  bestMatch,
  filterNav,
  isGroupOpen,
  readClosedGroups,
  writeClosedGroups,
} from "../services/navMenu";
import { TenantSwitcher } from "./TenantSwitcher";
import { activeNavPathFor, navFor, type NavSection } from "../routes";
import type { UserRole } from "../types/app";

/** How often the sidebar asks how many new orders are waiting. */
const WAITING_REFRESH_MS = 60_000;

/**
 * New orders waiting to be accepted, for the badge on Live orders.
 *
 * The one number worth putting in the navigation: it is the thing that goes
 * wrong while somebody is on another page. Today's only - the board folds
 * older ones away and so does this. Null until it is known, and on any error,
 * so a failed count shows no badge rather than a wrong one.
 */
function useWaitingOrders(token: string | null, activeRestaurantId: string | null): number | null {
  const [waiting, setWaiting] = useState<number | null>(null);
  const load = useCallback(() => {
    if (!token) return;
    const midnight = new Date();
    midnight.setHours(0, 0, 0, 0);
    api
      .getLiveOrders(token, { completedFrom: midnight, restaurantId: activeRestaurantId })
      .then((board) => {
        const placed = board.stages.find((stage) => stage.status === "PLACED");
        setWaiting(placed ? Math.max(0, placed.total - (placed.stale_total ?? 0)) : 0);
      })
      .catch(() => setWaiting(null));
  }, [activeRestaurantId, token]);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, WAITING_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);
  // The moment an order moves, when live updates are on.
  useOrdersChanged(load);
  return waiting;
}

interface SidebarProps {
  /** An icon rail rather than a full column. Desktop only: a phone's drawer
   *  is always full, because it is already out of the way when closed. */
  collapsed: boolean;
  onToggleCollapsed: () => void;
  currentPath: string;
  isMobileOpen: boolean;
  onNavigate: (path: string) => void;
  onCloseMobile: () => void;
  onLogout: () => void;
  role: UserRole;
  restaurantId: string | null;
}

/**
 * Which entry looks selected.
 *
 * A route says where it belongs in the navigation, so a page reached from
 * somewhere else — one branch, one order, the menu editor — keeps its
 * section lit without this file knowing the shape of those addresses.
 * `/locations/...` is the one exception: it is a retired address that
 * redirects, and the highlight should not flicker on the way through.
 */
function isItemActive(currentPath: string, itemPath: string): boolean {
  if (currentPath.startsWith("/locations")) {
    return itemPath === "/restaurants";
  }
  return activeNavPathFor(currentPath) === itemPath;
}

/**
 * The owner's own restaurant, for the brand block.
 *
 * The block used to read "Restaurant RAG / Restaurant workspace" under an
 * "RR" mark - the codebase's name, shown to a bakery owner as if it were
 * theirs. Null until loaded and on any error, when the block falls back to a
 * neutral "Your restaurant" rather than a wrong name.
 */
function useOwnRestaurant(
  token: string | null,
  restaurantId: string | null,
  enabled: boolean,
): { name: string; logo: string | null } | null {
  const [restaurant, setRestaurant] = useState<{ name: string; logo: string | null } | null>(null);
  useEffect(() => {
    if (!enabled || !token || !restaurantId) return;
    let live = true;
    api
      .getRestaurant(token, restaurantId)
      .then((detail) => {
        if (live) setRestaurant({ name: detail.name, logo: detail.logo_image_url ?? null });
      })
      .catch(() => {
        if (live) setRestaurant(null);
      });
    return () => {
      live = false;
    };
  }, [enabled, restaurantId, token]);
  return restaurant;
}

function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) {
    return "?";
  }
  const first = parts[0][0] ?? "";
  const last = parts.length > 1 ? (parts[parts.length - 1][0] ?? "") : "";
  return `${first}${last}`.toUpperCase();
}

/**
 * Light or dark, beside the sign-out button where the other personal controls
 * live. The storefront puts its own in the header for the same reason: it
 * belongs to the person, not to the page they happen to be on.
 */
function ThemeToggle() {
  // Read once, lazily, as the initial value rather than in an effect that then
  // calls setState — which is a second render for something known before the
  // first. Safe here because this panel is a client-only Vite app: there is no
  // server render for `localStorage` to disagree with.
  const [theme, setTheme] = useState<Theme>(storedTheme);

  // Applying is a side effect on the document and belongs in one, and doing it
  // on every change covers the first paint and each toggle with one rule
  // rather than two.
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const flip = () => setTheme((was) => (was === "dark" ? "light" : "dark"));

  return (
    <button
      aria-label={theme === "dark" ? "Use light mode" : "Use dark mode"}
      className="admin-sidebar__action"
      onClick={flip}
      title={theme === "dark" ? "Use light mode" : "Use dark mode"}
      type="button"
    >
      {theme === "dark" ? (
        <Sun size={15} strokeWidth={2.1} />
      ) : (
        <Moon size={15} strokeWidth={2.1} />
      )}
    </button>
  );
}

export function Sidebar({
  collapsed,
  onToggleCollapsed,
  currentPath,
  isMobileOpen,
  onNavigate,
  onCloseMobile,
  onLogout,
  role,
  restaurantId,
}: SidebarProps) {
  const { user, token, activeRestaurantId } = useAdminStore();
  // Built from the routes themselves, so nothing can be offered that this
  // role cannot open and nothing they can open is missing.
  const allSections = navFor(role);
  // Settings is the person's, not the platform's: it lives in the footer.
  const groups = allSections.filter((group) => group.section !== "Account");
  const settingsPath = allSections.find((group) => group.section === "Account")?.items[0]?.path;

  const [query, setQuery] = useState("");
  const [closed, setClosed] = useState<Set<NavSection>>(readClosedGroups);
  const searchRef = useRef<HTMLInputElement>(null);
  const waiting = useWaitingOrders(token, role === "ADMIN" ? activeRestaurantId : null);
  const ownRestaurant = useOwnRestaurant(token, restaurantId, role === "OWNER");

  // A rail of icons has no room for a search box or group headings: every
  // entry is shown, ungrouped, whatever was folded.
  const searching = !collapsed && query.trim().length > 0;
  const visibleSections = collapsed ? groups : filterNav(groups, query);
  const activeSection =
    groups.find((group) => group.items.some((item) => isItemActive(currentPath, item.path)))
      ?.section ?? null;

  const toggleGroup = (section: NavSection) => {
    setClosed((current) => {
      const next = new Set(current);
      if (next.has(section)) next.delete(section);
      else next.add(section);
      writeClosedGroups(next);
      return next;
    });
  };

  const go = (path: string) => {
    onNavigate(
      role === "OWNER" && restaurantId && path === "/restaurants"
        ? `/admin/restaurants/${restaurantId}/locations`
        : path,
    );
    setQuery("");
    onCloseMobile();
  };

  // "/" jumps to the search from anywhere that is not already a text field -
  // the same key GitHub and most docs sites use.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing =
        target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));
      if (event.key === "/" && !typing && !collapsed) {
        event.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [collapsed]);

  return (
    <>
      <div
        aria-hidden={!isMobileOpen}
        className={
          isMobileOpen
            ? "admin-sidebar__scrim admin-sidebar__scrim--open"
            : "admin-sidebar__scrim"
        }
        onClick={onCloseMobile}
      />
      <aside
        className={
          isMobileOpen
            ? `admin-sidebar admin-sidebar--${role.toLowerCase()} admin-sidebar--open`
            : `admin-sidebar admin-sidebar--${role.toLowerCase()}`
        }
      >
        <div className="admin-sidebar__top">
          {/* For an admin the switcher IS the brand block: the panel's
              identity while they are working is the restaurant they are
              working on. It returns null for an owner, who has one
              restaurant and nothing to switch between, and the plain brand
              block below renders instead. */}
          <TenantSwitcher onNavigate={onNavigate} onPicked={onCloseMobile} />
          {role === "OWNER" ? (
            <button
              className="admin-sidebar__brand"
              onClick={() => {
                onNavigate(
                  restaurantId
                    ? `/admin/restaurants/${restaurantId}/locations`
                    : "/dashboard",
                );
                onCloseMobile();
              }}
              type="button"
            >
              <div className="admin-sidebar__brand-mark">
                {ownRestaurant?.logo ? (
                  <img alt="" src={ownRestaurant.logo} />
                ) : (
                  getInitials(ownRestaurant?.name ?? "Your restaurant")
                )}
              </div>
              <div className="admin-sidebar__brand-copy">
                <strong title={ownRestaurant?.name}>{ownRestaurant?.name ?? "Your restaurant"}</strong>
                <span>Restaurant workspace</span>
              </div>
            </button>
          ) : null}
          {/* Desktop only (the stylesheet hides it in the drawer). The label
              says what it will do, and `aria-expanded` says what it is. */}
          <button
            aria-expanded={!collapsed}
            aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
            className="admin-sidebar__collapse"
            onClick={onToggleCollapsed}
            title={collapsed ? "Expand navigation" : "Collapse navigation"}
            type="button"
          >
            {collapsed ? (
              <PanelLeftOpen size={13} strokeWidth={2.2} />
            ) : (
              <PanelLeftClose size={13} strokeWidth={2.2} />
            )}
          </button>
          <button
            aria-label="Close navigation"
            className="admin-sidebar__close"
            onClick={onCloseMobile}
            type="button"
          >
            <ChevronLeft size={18} strokeWidth={2.2} />
          </button>
        </div>

        <div className="admin-sidebar__sections">
          {/* Inside the scrolling list, pinned to its top: the sidebar is a
              three-row grid, and a fourth child pushed the list under it. */}
          {!collapsed ? (
            <div className="admin-sidebar__search">
              <Search aria-hidden="true" size={14} />
              <input
                aria-label="Find a page"
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    const found = bestMatch(groups, query);
                    if (found) go(found.path);
                  } else if (event.key === "Escape") {
                    setQuery("");
                    event.currentTarget.blur();
                  }
                }}
                placeholder="Find a page"
                ref={searchRef}
                type="search"
                value={query}
              />
              {query ? (
                <button
                  aria-label="Clear the search"
                  className="admin-sidebar__search-clear"
                  onClick={() => setQuery("")}
                  type="button"
                >
                  <X size={13} />
                </button>
              ) : (
                <kbd title="Press / to search">/</kbd>
              )}
            </div>
          ) : null}
          {visibleSections.length === 0 ? (
            <p className="admin-sidebar__no-match">No page matches &ldquo;{query.trim()}&rdquo;.</p>
          ) : null}
          {visibleSections.map((section) => {
            const open =
              collapsed ||
              isGroupOpen(section.section, { closed, activeSection, searching });
            const groupId = `nav-group-${section.section.replace(/\W+/g, "-").toLowerCase()}`;
            return (
              <section className="admin-sidebar__section" key={section.section}>
                <button
                  aria-controls={groupId}
                  aria-expanded={open}
                  className="admin-sidebar__section-label admin-sidebar__section-toggle"
                  // The group holding this page cannot be folded: a page you
                  // are on is a page you should be able to see in the list.
                  disabled={collapsed || searching || section.section === activeSection}
                  onClick={() => toggleGroup(section.section)}
                  type="button"
                >
                  <span>{section.label}</span>
                  <ChevronDown aria-hidden="true" className="admin-sidebar__section-chevron" size={12} />
                </button>
                {open ? (
                  <div className="admin-sidebar__links" id={groupId}>
                    {section.items.map((item) => {
                      const Icon = item.icon;
                      const isActive = isItemActive(currentPath, item.path);
                      const label =
                        role === "OWNER" && item.path === "/restaurants" ? "My Restaurant" : item.label;
                      const badge = item.path === "/live-orders" && waiting ? waiting : null;

                      return (
                        <button
                          className={
                            isActive
                              ? "admin-sidebar__link admin-sidebar__link--active"
                              : "admin-sidebar__link"
                          }
                          aria-current={isActive ? "page" : undefined}
                          key={item.path}
                          // The rail shows icons alone, so the name moves to the
                          // tooltip. Expanded, a tooltip repeating the visible
                          // label is noise.
                          title={collapsed ? (badge ? `${label} (${badge} waiting)` : label) : undefined}
                          onClick={() => go(item.path)}
                          type="button"
                        >
                          <span className="admin-sidebar__link-copy">
                            <Icon size={17} strokeWidth={2.1} />
                            <span>{label}</span>
                          </span>
                          {badge ? (
                            <span
                              aria-label={`${badge} new order${badge === 1 ? "" : "s"} waiting`}
                              className="admin-sidebar__badge"
                            >
                              {badge > 99 ? "99+" : badge}
                            </span>
                          ) : null}
                        </button>
                      );
                    })}
                  </div>
                ) : null}
              </section>
            );
          })}
        </div>

        <div className="admin-sidebar__footer">
          <div className="admin-sidebar__profile" title={user?.email}>
            {user ? (
              <>
                <span className="admin-sidebar__profile-badge">
                  {getInitials(user.full_name)}
                </span>
                <span className="admin-sidebar__profile-copy">
                  <strong>{user.full_name}</strong>
                  <span
                    className={`admin-sidebar__profile-role admin-sidebar__profile-role--${role.toLowerCase()}`}
                  >
                    {role === "ADMIN" ? "Platform Admin" : "Restaurant Owner"}
                  </span>
                </span>
              </>
            ) : null}
          </div>
          {/* Under the name, not beside it. Two icon buttons in the same row
              left about 90px for the name, so every account read as
              "Bhagwati …" with the role badge tucked under the buttons. */}
          <div className="admin-sidebar__actions">
            {settingsPath ? (
              <button
                aria-current={isItemActive(currentPath, settingsPath) ? "page" : undefined}
                aria-label="Settings"
                className="admin-sidebar__action"
                onClick={() => go(settingsPath)}
                title="Settings"
                type="button"
              >
                <SlidersHorizontal size={15} strokeWidth={2.1} />
              </button>
            ) : null}
            <ThemeToggle />
            <button
              aria-label="Sign out"
              className="admin-sidebar__action admin-sidebar__action--danger"
              onClick={onLogout}
              title="Sign out"
              type="button"
            >
              <LogOut size={15} strokeWidth={2.1} />
              <span>Sign out</span>
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}

import {
  ChevronLeft,
  LogOut,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Sun,
} from "lucide-react";
import { useEffect, useState } from "react";

import { applyTheme, storedTheme, type Theme } from "../services/theme";
import { useAdminStore } from "../hooks/useAdminStore";
import { TenantSwitcher } from "./TenantSwitcher";
import { activeNavPathFor, navFor } from "../routes";
import type { UserRole } from "../types/app";

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
      {/* Names what the button will DO, like its aria-label. */}
      <span>{theme === "dark" ? "Light mode" : "Dark mode"}</span>
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
  const { user } = useAdminStore();
  // Built from the routes themselves, so nothing can be offered that this
  // role cannot open and nothing they can open is missing.
  const visibleSections = navFor(role);

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
              <div className="admin-sidebar__brand-mark">RR</div>
              <div className="admin-sidebar__brand-copy">
                <strong>Restaurant RAG</strong>
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
          {visibleSections.map((section) => (
            <section className="admin-sidebar__section" key={section.label}>
              <p className="admin-sidebar__section-label">{section.label}</p>
              <div className="admin-sidebar__links">
                {section.items.map((item) => {
                  const Icon = item.icon;
                  const isActive = isItemActive(currentPath, item.path);
                  const label =
                    role === "OWNER" && item.path === "/restaurants"
                      ? "My Restaurant"
                      : item.label;

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
                      title={collapsed ? label : undefined}
                      onClick={() => {
                        onNavigate(
                          role === "OWNER" &&
                            restaurantId &&
                            item.path === "/restaurants"
                            ? `/admin/restaurants/${restaurantId}/locations`
                            : item.path,
                        );
                        onCloseMobile();
                      }}
                      type="button"
                    >
                      <span className="admin-sidebar__link-copy">
                        <Icon size={17} strokeWidth={2.1} />
                        <span>{label}</span>
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
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

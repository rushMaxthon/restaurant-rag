import { ChevronLeft, LogOut } from "lucide-react";
import { useAdminStore } from "../hooks/useAdminStore";
import { activeNavPathFor, navFor } from "../routes";
import type { UserRole } from "../types/app";

interface SidebarProps {
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

export function Sidebar({
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
          <button
            className="admin-sidebar__brand"
            onClick={() => {
              onNavigate(
                role === "OWNER" && restaurantId
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
              <span>
                {role === "OWNER"
                  ? "Restaurant workspace"
                  : "Platform control center"}
              </span>
            </div>
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

                  return (
                    <button
                      className={
                        isActive
                          ? "admin-sidebar__link admin-sidebar__link--active"
                          : "admin-sidebar__link"
                      }
                      key={item.path}
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
                        <span>
                          {role === "OWNER" && item.path === "/restaurants"
                            ? "My Restaurant"
                            : item.label}
                        </span>
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
            <button
              aria-label="Sign out"
              className="admin-sidebar__signout"
              onClick={onLogout}
              title="Sign out"
              type="button"
            >
              <LogOut size={16} strokeWidth={2.1} />
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}

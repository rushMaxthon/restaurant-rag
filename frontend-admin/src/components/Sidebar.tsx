import type { LucideIcon } from "lucide-react";
import { useAdminStore } from "../hooks/useAdminStore";
import {
  BarChart3,
  BellRing,
  Bot,
  ChevronLeft,
  Layers3,
  LayoutDashboard,
  LogOut,
  Palette,
  ReceiptText,
  Settings,
  Sparkles,
  Store,
  TicketPercent,
  Users,
  UtensilsCrossed,
} from "lucide-react";
import type { UserRole } from "../types/app";

interface SidebarItem {
  path: string;
  label: string;
  icon: LucideIcon;
}

interface SidebarSection {
  label: string;
  items: SidebarItem[];
}

interface SidebarProps {
  currentPath: string;
  isMobileOpen: boolean;
  onNavigate: (path: string) => void;
  onCloseMobile: () => void;
  onLogout: () => void;
  role: UserRole;
  restaurantId: string | null;
}

const sidebarSections: SidebarSection[] = [
  {
    label: "Overview",
    items: [
      { path: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
      { path: "/reports", label: "Reports", icon: BarChart3 },
    ],
  },
  {
    label: "Intelligence",
    items: [{ path: "/ai-manager", label: "AI Manager", icon: Sparkles }],
  },
  {
    label: "Manage",
    items: [
      { path: "/restaurants", label: "Restaurants", icon: Store },
      { path: "/branding", label: "Branding", icon: Palette },
      { path: "/orders", label: "Orders", icon: ReceiptText },
      { path: "/menu-items", label: "Menu Items", icon: UtensilsCrossed },
      { path: "/offers", label: "Offers", icon: TicketPercent },
      { path: "/generated-combos", label: "Generated Combos", icon: Layers3 },
      { path: "/users", label: "Users", icon: Users },
    ],
  },
  {
    label: "System",
    items: [
      { path: "/ai-logs", label: "AI Logs", icon: Bot },
      { path: "/notifications", label: "Notifications", icon: BellRing },
      { path: "/settings", label: "Settings", icon: Settings },
    ],
  },
];

const ownerVisiblePaths = new Set([
  "/dashboard",
  "/restaurants",
  "/branding",
  "/offers",
  "/generated-combos",
  "/menu-items",
  "/orders",
  "/users",
  "/reports",
  "/ai-manager",
  "/settings",
]);

const adminVisiblePaths = new Set([
  "/dashboard",
  "/restaurants",
  "/offers",
  "/orders",
  "/users",
  "/ai-logs",
  "/reports",
  "/ai-manager",
  "/notifications",
  "/settings",
]);

function isItemActive(
  currentPath: string,
  itemPath: string,
  role: UserRole,
  restaurantId: string | null,
): boolean {
  if (currentPath === itemPath) {
    return true;
  }

  if (itemPath === "/restaurants" && currentPath.startsWith("/admin/restaurants/")) {
    return true;
  }

  if (itemPath === "/restaurants" && currentPath.startsWith("/locations/")) {
    return true;
  }

  if (itemPath === "/orders" && currentPath.startsWith("/orders/")) {
    return true;
  }

  if (
    role === "OWNER" &&
    itemPath === "/restaurants" &&
    restaurantId &&
    currentPath === `/admin/restaurants/${restaurantId}`
  ) {
    return true;
  }

  return false;
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
  const visibleSections =
    role === "OWNER"
      ? sidebarSections
          .map((section) => ({
            ...section,
            items: section.items.filter((item) =>
              ownerVisiblePaths.has(item.path),
            ),
          }))
          .filter((section) => section.items.length > 0)
      : sidebarSections
          .map((section) => ({
            ...section,
            items: section.items.filter((item) =>
              adminVisiblePaths.has(item.path),
            ),
          }))
          .filter((section) => section.items.length > 0);

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
                  const isActive = isItemActive(
                    currentPath,
                    item.path,
                    role,
                    restaurantId,
                  );

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

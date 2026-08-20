import type { PropsWithChildren } from "react";
import type { UserRole } from "../types/app";

interface NavItem {
  path: string;
  label: string;
}

interface SidebarLayoutProps extends PropsWithChildren {
  role: UserRole;
  currentPath: string;
  onNavigate: (path: string) => void;
  onLogout: () => void;
  userName: string;
}

const navByRole: Record<"ADMIN" | "OWNER", NavItem[]> = {
  ADMIN: [
    { path: "/dashboard", label: "Dashboard" },
    { path: "/restaurants", label: "Restaurants" },
    { path: "/users", label: "Users" },
  ],
  OWNER: [
    { path: "/menu", label: "Menu" },
    { path: "/orders", label: "Orders" },
  ],
};

export function SidebarLayout({
  children,
  role,
  currentPath,
  onNavigate,
  onLogout,
  userName,
}: SidebarLayoutProps) {
  const navItems = navByRole[role as "ADMIN" | "OWNER"];

  return (
    <div className="admin-shell">
      <aside className="sidebar">
        <button
          className="sidebar__brand"
          onClick={() => onNavigate(navItems[0].path)}
          type="button"
        >
          <span className="sidebar__logo">RR</span>
          <div>
            <strong>Control Room</strong>
            <span>
              {role === "ADMIN" ? "Platform admin" : "Workspace member"}
            </span>
          </div>
        </button>
        <nav className="sidebar__nav">
          {navItems.map((item) => (
            <button
              key={item.path}
              className={
                currentPath === item.path
                  ? "sidebar__link sidebar__link--active"
                  : "sidebar__link"
              }
              onClick={() => onNavigate(item.path)}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar__footer">
          <div className="sidebar__profile">
            <strong>{userName}</strong>
            <span>{role}</span>
          </div>
          <button className="sidebar__logout" onClick={onLogout} type="button">
            Logout
          </button>
        </div>
      </aside>
      <main className="admin-main">{children}</main>
    </div>
  );
}

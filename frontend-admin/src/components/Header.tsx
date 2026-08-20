import { Menu, Search } from "lucide-react";
import type { UserRole } from "../types/app";

interface HeaderProps {
  currentPath: string;
  onOpenMobileSidebar: () => void;
  role: UserRole;
  userName: string;
}

function getPageTitle(pathname: string): {
  title: string;
  description: string;
} {
  if (
    /^\/admin\/restaurants\/[^/]+\/locations\/[^/]+\/menu-items\/create$/.test(pathname) ||
    /^\/admin\/restaurants\/[^/]+\/locations\/[^/]+\/menu-items\/[^/]+\/edit$/.test(pathname)
  ) {
    return {
      title: "Menu Item Editor",
      description:
        "Create or update menu items inside the existing restaurant dashboard workspace.",
    };
  }

  if (
    /^\/admin\/restaurants\/[^/]+\/locations\/[^/]+$/.test(pathname) ||
    /^\/locations\/[^/]+\/[^/]+$/.test(pathname)
  ) {
    return {
      title: "Location Workspace",
      description:
        "Manage location details, settings, menu items, and orders for the selected branch.",
    };
  }

  if (/^\/admin\/restaurants\/[^/]+\/locations$/.test(pathname)) {
    return {
      title: "Restaurant Locations",
      description:
        "Review the selected restaurant's branches and open a location workspace.",
    };
  }

  if (pathname.startsWith("/admin/restaurants/")) {
    return {
      title: "Restaurant Workspace",
      description:
        "Inspect restaurant details, settings, menu items, and recent orders.",
    };
  }

  const pageByPath: Record<string, { title: string; description: string }> = {
    "/dashboard": {
      title: "Dashboard",
      description: "Track operations, restaurants, AI health, and system activity.",
    },
    "/restaurants": {
      title: "Restaurants",
      description: "Management area for the Restaurant RAG admin workspace.",
    },
    "/generated-combos": {
      title: "Generated Combos",
      description: "AI area for the Restaurant RAG admin workspace.",
    },
    "/orders": {
      title: "Orders",
      description: "Management area for the Restaurant RAG admin workspace.",
    },
    "/users": {
      title: "Users",
      description: "Users area for the Restaurant RAG admin workspace.",
    },
    "/ai-logs": {
      title: "AI Logs",
      description: "AI area for the Restaurant RAG admin workspace.",
    },
    "/reports": {
      title: "Reports",
      description: "Analytics area for the Restaurant RAG admin workspace.",
    },
    "/notifications": {
      title: "Notifications",
      description: "System area for the Restaurant RAG admin workspace.",
    },
    "/settings": {
      title: "Settings",
      description: "System area for the Restaurant RAG admin workspace.",
    },
  };

  if (pageByPath[pathname]) {
    return pageByPath[pathname];
  }

  return {
    title: "Dashboard",
    description: "Track operations, restaurants, AI health, and system activity.",
  };
}

export function Header({
  currentPath,
  onOpenMobileSidebar,
  role,
  userName,
}: HeaderProps) {
  const page = getPageTitle(currentPath);

  return (
    <header className="admin-header">
      <div className="admin-header__intro">
        <button
          aria-label="Open navigation"
          className="admin-header__menu-button"
          onClick={onOpenMobileSidebar}
          type="button"
        >
          <Menu size={20} strokeWidth={2.3} />
        </button>

        <div>
          <span className="admin-header__eyebrow">Admin Panel</span>
          <h1>{page.title}</h1>
          <p>{page.description}</p>
        </div>
      </div>

      <div className="admin-header__actions">
        <div className="admin-header__search">
          <Search size={16} strokeWidth={2.2} />
          <input
            placeholder="Search modules, actions, reports..."
            type="text"
          />
        </div>
        <div className="admin-header__user-chip">
          <span>{userName}</span>
          <strong>{role}</strong>
        </div>
      </div>
    </header>
  );
}

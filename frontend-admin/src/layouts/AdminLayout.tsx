import { type PropsWithChildren, useEffect, useState } from "react";
import { Menu, TriangleAlert } from "lucide-react";
import { Sidebar } from "../components/Sidebar";
import { storedSidebarCollapsed, storeSidebarCollapsed } from "../services/sidebarState";
import {
  WORKSPACE_SETTINGS_EVENT,
  readWorkspaceSettings,
} from "../services/workspaceSettings";
import type { UserRole } from "../types/app";

interface AdminLayoutProps extends PropsWithChildren {
  currentPath: string;
  onNavigate: (path: string) => void;
  onLogout: () => void;
  role: UserRole;
  restaurantId: string | null;
}

export function AdminLayout({
  children,
  currentPath,
  onNavigate,
  onLogout,
  role,
  restaurantId,
}: AdminLayoutProps) {
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [showMaintenanceBanner, setShowMaintenanceBanner] = useState(
    () => readWorkspaceSettings().maintenanceBanner,
  );
  const [compact, setCompact] = useState(() => readWorkspaceSettings().compactDashboard);
  // Held here rather than in the sidebar, because two things move with it:
  // the sidebar's own contents and the width of the grid column it sits in.
  const [sidebarCollapsed, setSidebarCollapsed] = useState(storedSidebarCollapsed);

  const toggleSidebar = () => {
    setSidebarCollapsed((was) => {
      storeSidebarCollapsed(!was);
      return !was;
    });
  };

  useEffect(() => {
    setIsMobileSidebarOpen(false);
  }, [currentPath]);

  useEffect(() => {
    const sync = () => {
      const next = readWorkspaceSettings();
      setShowMaintenanceBanner(next.maintenanceBanner);
      setCompact(next.compactDashboard);
    };
    window.addEventListener(WORKSPACE_SETTINGS_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(WORKSPACE_SETTINGS_EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return (
    <div
      className="admin-layout"
      data-density={compact ? "compact" : undefined}
      data-sidebar={sidebarCollapsed ? "collapsed" : undefined}
    >
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <Sidebar
        collapsed={sidebarCollapsed}
        currentPath={currentPath}
        isMobileOpen={isMobileSidebarOpen}
        onNavigate={onNavigate}
        onCloseMobile={() => setIsMobileSidebarOpen(false)}
        onLogout={onLogout}
        onToggleCollapsed={toggleSidebar}
        role={role}
        restaurantId={restaurantId}
      />
      <div className="admin-layout__main">
        {showMaintenanceBanner ? (
          <div className="maintenance-banner" role="status">
            <TriangleAlert size={15} strokeWidth={2.2} />
            <span>
              Maintenance mode notice is active — customers may experience
              interruptions while platform work is in progress.
            </span>
          </div>
        ) : null}
        <button
          aria-label="Open navigation"
          className="dashboard-menu-fab"
          onClick={() => setIsMobileSidebarOpen(true)}
          type="button"
        >
          <Menu size={20} strokeWidth={2.3} />
        </button>
        <main
          className="admin-layout__content admin-layout__content--flush"
          id="main-content"
          tabIndex={-1}
        >
          {children}
        </main>
      </div>
    </div>
  );
}

import { useEffect, useState } from "react";
import { ToastViewport } from "./components/ToastViewport";
import { useAdminStore } from "./hooks/useAdminStore";
import { AdminLayout } from "./layouts/AdminLayout";
import { AIManagerPage } from "./pages/AIManagerPage";
import { AILogsPage } from "./pages/AILogsPage";
import { AdminRestaurantsPage } from "./pages/AdminRestaurantsPage";
import { AdminUsersPage } from "./pages/AdminUsersPage";
import { DashboardPage } from "./pages/DashboardPage";
import { GeneratedCombosPage } from "./pages/GeneratedCombosPage";
import { LoginPage } from "./pages/LoginPage";
import { LocationDetailPage } from "./pages/LocationDetailPage";
import { LocationsPage } from "./pages/LocationsPage";
import { MenuItemEditorPage } from "./pages/MenuItemEditorPage";
import { MenuItemsPage } from "./pages/MenuItemsPage";
import { NotificationsPage } from "./pages/NotificationsPage";
import { OffersPage } from "./pages/OffersPage";
import { OrderDetailPage } from "./pages/OrderDetailPage";
import { OrdersPage } from "./pages/OrdersPage";
import { RestaurantDetailPage } from "./pages/RestaurantDetailPage";
import { ReportsPage } from "./pages/ReportsPage";
import { SettingsPage } from "./pages/SettingsPage";
import type { UserRole } from "./types/app";

function usePathname() {
  const [pathname, setPathname] = useState(window.location.pathname);

  useEffect(() => {
    const handlePopState = () => setPathname(window.location.pathname);
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  const navigate = (nextPath: string) => {
    if (pathname === nextPath) {
      return;
    }
    window.history.pushState({}, "", nextPath);
    setPathname(nextPath);
  };

  return { pathname, navigate };
}

function getRestaurantDetailId(pathname: string): string | null {
  const match = pathname.match(/^\/admin\/restaurants\/([^/]+)$/);
  return match?.[1] ?? null;
}

function getOrderDetailId(pathname: string): string | null {
  const match = pathname.match(/^\/orders\/([^/]+)$/);
  return match?.[1] ?? null;
}

function getRestaurantLocationsId(pathname: string): string | null {
  const match = pathname.match(/^\/admin\/restaurants\/([^/]+)\/locations$/);
  return match?.[1] ?? null;
}

function getRestaurantAppClientId(pathname: string): string | null {
  const match = pathname.match(/^\/admin\/restaurants\/([^/]+)\/app-client$/);
  return match?.[1] ?? null;
}

function getLocationDetailParams(pathname: string): {
  restaurantId: string;
  locationId: string;
} | null {
  const nestedMatch = pathname.match(
    /^\/admin\/restaurants\/([^/]+)\/locations\/([^/]+)$/,
  );
  if (nestedMatch) {
    return {
      restaurantId: nestedMatch[1],
      locationId: nestedMatch[2],
    };
  }

  const legacyMatch = pathname.match(/^\/locations\/([^/]+)\/([^/]+)$/);
  if (!legacyMatch) {
    return null;
  }
  return {
    restaurantId: legacyMatch[1],
    locationId: legacyMatch[2],
  };
}

function getMenuItemEditorParams(pathname: string): {
  restaurantId: string;
  locationId: string | null;
  itemId: string | null;
} | null {
  const globalCreateMatch = pathname.match(
    /^\/admin\/restaurants\/([^/]+)\/menu-items\/create$/,
  );
  if (globalCreateMatch) {
    return {
      restaurantId: globalCreateMatch[1],
      locationId: null,
      itemId: null,
    };
  }

  const createMatch = pathname.match(
    /^\/admin\/restaurants\/([^/]+)\/locations\/([^/]+)\/menu-items\/create$/,
  );
  if (createMatch) {
    return {
      restaurantId: createMatch[1],
      locationId: createMatch[2],
      itemId: null,
    };
  }

  const editMatch = pathname.match(
    /^\/admin\/restaurants\/([^/]+)\/locations\/([^/]+)\/menu-items\/([^/]+)\/edit$/,
  );
  if (!editMatch) {
    return null;
  }

  return {
    restaurantId: editMatch[1],
    locationId: editMatch[2],
    itemId: editMatch[3],
  };
}

function getDefaultPath(role: UserRole, restaurantId: string | null): string {
  if (role === "OWNER" && restaurantId) {
    return `/admin/restaurants/${restaurantId}/locations`;
  }

  if (role === "ADMIN") {
    return "/dashboard";
  }

  return "/login";
}

function isAllowedPath(
  role: UserRole,
  pathname: string,
  restaurantId: string | null,
): boolean {
  const staticAllowed: Record<UserRole, string[]> = {
    ADMIN: [
      "/dashboard",
      "/restaurants",
      "/offers",
      "/generated-combos",
      "/menu-items",
      "/orders",
      "/users",
      "/ai-logs",
      "/reports",
      "/ai-manager",
      "/notifications",
      "/settings",
    ],
    OWNER: [
      "/dashboard",
      "/restaurants",
      "/offers",
      "/generated-combos",
      "/menu-items",
      "/orders",
      "/users",
      "/reports",
      "/ai-manager",
      "/settings",
    ],
    CUSTOMER: [],
  };

  if (staticAllowed[role].includes(pathname)) {
    return true;
  }

  if (getOrderDetailId(pathname)) {
    return role === "ADMIN" || role === "OWNER";
  }

  const detailId = getRestaurantDetailId(pathname);
  if (detailId) {
    if (role === "ADMIN") {
      return true;
    }
    return role === "OWNER" && restaurantId === detailId;
  }

  const restaurantLocationsId = getRestaurantLocationsId(pathname);
  if (restaurantLocationsId) {
    if (role === "ADMIN") {
      return true;
    }
    return role === "OWNER" && restaurantId === restaurantLocationsId;
  }

  // App client configuration is platform-level, so it stays admin-only.
  if (getRestaurantAppClientId(pathname)) {
    return role === "ADMIN";
  }

  const locationDetail = getLocationDetailParams(pathname);
  if (locationDetail) {
    if (role === "ADMIN") {
      return true;
    }
    return role === "OWNER" && restaurantId === locationDetail.restaurantId;
  }

  const menuItemEditor = getMenuItemEditorParams(pathname);
  if (menuItemEditor) {
    if (role === "ADMIN") {
      return true;
    }
    return role === "OWNER" && restaurantId === menuItemEditor.restaurantId;
  }

  return false;
}

function App() {
  const { pathname, navigate } = usePathname();
  const {
    token,
    role,
    restaurantId,
    user,
    isAuthenticated,
    logout,
    toasts,
    dismissToast,
    pushToast,
  } = useAdminStore();
  useEffect(() => {
    if (!isAuthenticated || !user || !role) {
      return;
    }

    if ((role !== "ADMIN" && role !== "OWNER") || user.role !== role) {
      pushToast(
        "Access blocked",
        "Customer accounts cannot access the admin panel.",
        "error",
      );
      logout();
      navigate("/login");
      return;
    }

    if (role === "OWNER" && !restaurantId) {
      pushToast(
        "Access blocked",
        "This owner account is not linked to a restaurant yet.",
        "error",
      );
      logout();
      navigate("/login");
      return;
    }

    if (pathname === "/restaurants" && role === "OWNER" && restaurantId) {
      navigate(`/admin/restaurants/${restaurantId}/locations`);
      return;
    }

    if (pathname === "/locations") {
      if (role === "OWNER" && restaurantId) {
        navigate(`/admin/restaurants/${restaurantId}/locations`);
      } else if (role === "ADMIN") {
        navigate("/restaurants");
      }
      return;
    }

    const legacyLocationDetail = pathname.match(/^\/locations\/([^/]+)\/([^/]+)$/);
    if (legacyLocationDetail) {
      navigate(
        `/admin/restaurants/${legacyLocationDetail[1]}/locations/${legacyLocationDetail[2]}`,
      );
      return;
    }

    const detailId = getRestaurantDetailId(pathname);
    if (role === "OWNER" && detailId && restaurantId && detailId !== restaurantId) {
      navigate(`/admin/restaurants/${restaurantId}/locations`);
      return;
    }

    const restaurantLocationsId = getRestaurantLocationsId(pathname);
    if (
      role === "OWNER" &&
      restaurantLocationsId &&
      restaurantId &&
      restaurantLocationsId !== restaurantId
    ) {
      navigate(`/admin/restaurants/${restaurantId}/locations`);
      return;
    }

    const locationDetail = getLocationDetailParams(pathname);
    if (
      role === "OWNER" &&
      locationDetail &&
      restaurantId &&
      locationDetail.restaurantId !== restaurantId
    ) {
      navigate(`/admin/restaurants/${restaurantId}/locations`);
      return;
    }

    const menuItemEditor = getMenuItemEditorParams(pathname);
    if (
      role === "OWNER" &&
      menuItemEditor &&
      restaurantId &&
      menuItemEditor.restaurantId !== restaurantId
    ) {
      navigate(`/admin/restaurants/${restaurantId}/locations`);
      return;
    }

    if (!isAllowedPath(role, pathname, restaurantId)) {
      navigate(getDefaultPath(role, restaurantId));
    }
  }, [
    isAuthenticated,
    logout,
    navigate,
    pathname,
    pushToast,
    restaurantId,
    role,
    user,
  ]);

  const restaurantDetailId = getRestaurantDetailId(pathname);
  const restaurantLocationsId = getRestaurantLocationsId(pathname);
  const restaurantAppClientId = getRestaurantAppClientId(pathname);
  const locationDetail = getLocationDetailParams(pathname);
  const menuItemEditor = getMenuItemEditorParams(pathname);
  const orderDetailId = getOrderDetailId(pathname);

  if (!isAuthenticated || !token || !user || !role) {
    return (
      <>
        <LoginPage onSuccess={navigate} />
        <ToastViewport toasts={toasts} onDismiss={dismissToast} />
      </>
    );
  }

  const content =
    menuItemEditor ? (
      <MenuItemEditorPage
        itemId={menuItemEditor.itemId}
        locationId={menuItemEditor.locationId}
        onNavigate={navigate}
        onToast={pushToast}
        restaurantId={menuItemEditor.restaurantId}
        role={role}
        token={token}
      />
    ) : locationDetail ? (
      <LocationDetailPage
        assignedRestaurantId={restaurantId}
        key={`${locationDetail.restaurantId}:${locationDetail.locationId}`}
        locationId={locationDetail.locationId}
        onNavigate={navigate}
        onToast={pushToast}
        restaurantId={locationDetail.restaurantId}
        role={role}
        token={token}
      />
    ) : restaurantAppClientId ? (
      <RestaurantDetailPage
        assignedRestaurantId={restaurantId}
        initialSection="app_client"
        key={`${restaurantAppClientId}:app-client`}
        onNavigate={navigate}
        onToast={pushToast}
        restaurantId={restaurantAppClientId}
        role={role}
        token={token}
      />
    ) : restaurantLocationsId ? (
      <LocationsPage
        token={token}
        role={role}
        assignedRestaurantId={restaurantId}
        scopedRestaurantId={restaurantLocationsId}
        onNavigate={navigate}
        onToast={pushToast}
      />
    ) : restaurantDetailId ? (
      <RestaurantDetailPage
        assignedRestaurantId={restaurantId}
        initialSection="details"
        onNavigate={navigate}
        onToast={pushToast}
        key={restaurantDetailId}
        restaurantId={restaurantDetailId}
        role={role}
        token={token}
      />
    ) : pathname === "/restaurants" ? (
      role === "OWNER" && restaurantId ? (
        <LocationsPage
          token={token}
          role={role}
          assignedRestaurantId={restaurantId}
          scopedRestaurantId={restaurantId}
          onNavigate={navigate}
          onToast={pushToast}
        />
      ) : (
        <AdminRestaurantsPage token={token} onNavigate={navigate} onToast={pushToast} />
      )
    ) : pathname === "/locations" ? (
      <LocationsPage
        token={token}
        role={role}
        assignedRestaurantId={restaurantId}
        onNavigate={navigate}
        onToast={pushToast}
      />
    ) : pathname === "/menu-items" ? (
      <MenuItemsPage
        token={token}
        role={role}
        restaurantId={restaurantId}
        onNavigate={navigate}
        onToast={pushToast}
      />
    ) : pathname === "/offers" ? (
      <OffersPage
        token={token}
        role={role}
        restaurantId={restaurantId}
        onNavigate={navigate}
        onToast={pushToast}
      />
    ) : pathname === "/generated-combos" ? (
      <GeneratedCombosPage
        onToast={pushToast}
        restaurantId={role === "OWNER" ? restaurantId : undefined}
        role={role}
        token={token}
      />
    ) : orderDetailId ? (
      <OrderDetailPage
        key={orderDetailId}
        onNavigate={navigate}
        onToast={pushToast}
        orderId={orderDetailId}
        role={role}
        token={token}
      />
    ) : pathname === "/orders" ? (
      <OrdersPage
        token={token}
        role={role}
        onNavigate={navigate}
        onToast={pushToast}
      />
    ) : pathname === "/users" ? (
      <AdminUsersPage
        token={token}
        currentUserId={user.id}
        role={role}
        onToast={pushToast}
      />
    ) : pathname === "/ai-manager" ? (
      <AIManagerPage />
    ) : pathname === "/ai-logs" ? (
      <AILogsPage token={token} onToast={pushToast} />
    ) : pathname === "/reports" ? (
      <ReportsPage
        token={token}
        role={role}
        restaurantId={restaurantId}
        onToast={pushToast}
      />
    ) : pathname === "/notifications" ? (
      <NotificationsPage onToast={pushToast} />
    ) : pathname === "/settings" ? (
      <SettingsPage onToast={pushToast} />
    ) : (
      <DashboardPage
        onNavigate={navigate}
        token={token}
        role={role}
        restaurantId={restaurantId}
        onToast={pushToast}
      />
    );

  return (
    <>
      <AdminLayout
        currentPath={pathname}
        onNavigate={navigate}
        onLogout={() => {
          logout();
          navigate("/login");
        }}
        role={role}
        restaurantId={restaurantId}
      >
        {content}
      </AdminLayout>
      <ToastViewport toasts={toasts} onDismiss={dismissToast} />
    </>
  );
}

export default App;

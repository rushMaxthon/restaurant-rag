import { Eye, EyeOff, Flame, Pencil, Trash2, UtensilsCrossed } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { DataToolbar } from "../components/DataToolbar";
import { StatTiles, type StatTileItem } from "../components/StatTiles";
import { EmptyPanel } from "../components/EmptyPanel";
import { PageIntro } from "../components/PageIntro";
import { Pagination } from "../components/Pagination";
import { ResponsiveTable, type TableColumn } from "../components/ResponsiveTable";
import { StatusPill } from "../components/StatusPill";
import { readWorkspaceSettings } from "../services/workspaceSettings";
import { ApiError, api, formatCurrency } from "../services/api";
import { pluralize } from "../services/format";
import {
  getPageSnapshot,
  hasPageSnapshot,
  invalidatePageSnapshotsByPrefix,
  setPageSnapshot,
  tokenScope,
} from "../services/pageCache";
import type {
  AdminMenuItem,
  MenuItem,
  Restaurant,
  RestaurantLocation,
  UserRole,
} from "../types/app";

interface MenuItemsPageProps {
  token: string;
  role: UserRole;
  restaurantId: string | null;
  onNavigate: (path: string) => void;
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

type MenuRow = {
  id: string;
  restaurantId: string;
  restaurantName: string;
  restaurantCity: string;
  name: string;
  category: string;
  cuisineType: string | null;
  description: string | null;
  price: number | string;
  launchedAt: string;
  isNewLaunch: boolean;
  isNew: boolean;
  isVeg: boolean;
  isAvailable: boolean;
  isBestseller: boolean;
  recentValidOrderCount: number;
  recentValidOrderWindowDays: number;
  imageUrl: string | null;
  source: MenuItem | AdminMenuItem;
};

function formatLaunchLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Recent launch";
  }
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
  }).format(date);
}

interface MenuItemsSnapshot {
  rows: MenuRow[];
  restaurant: Restaurant | null;
  ownerLocations: RestaurantLocation[];
}

// Shared with MenuItemEditorPage: creating, editing or deleting an item from
// there is a genuine data change for the list this page shows, so that page
// invalidates everything under this prefix on a successful save.
export function buildMenuItemsCacheKeyPrefix(scope: string): string {
  return `menu-items:${scope}:`;
}

function buildMenuItemsCacheKey(
  scope: string,
  isAdmin: boolean,
  restaurantId: string | null,
): string {
  return `${buildMenuItemsCacheKeyPrefix(scope)}${isAdmin ? "admin" : restaurantId ?? ""}`;
}

export function MenuItemsPage({
  token,
  role,
  restaurantId,
  onNavigate,
  onToast,
}: MenuItemsPageProps) {
  const isAdmin = role === "ADMIN";
  const scope = tokenScope(token);
  const menuItemsKey = buildMenuItemsCacheKey(scope, isAdmin, restaurantId ?? null);
  const cachedMenuItems = getPageSnapshot<MenuItemsSnapshot>(menuItemsKey);

  const [restaurant, setRestaurant] = useState<Restaurant | null>(
    () => cachedMenuItems?.restaurant ?? null,
  );
  const [ownerLocations, setOwnerLocations] = useState<RestaurantLocation[]>(
    () => cachedMenuItems?.ownerLocations ?? [],
  );
  const [rows, setRows] = useState<MenuRow[]>(() => cachedMenuItems?.rows ?? []);
  // Only true when this account/restaurant has never been fetched this
  // session - not on every mount, so revisiting the menu keeps it visible
  // instead of showing a skeleton.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(() => !hasPageSnapshot(menuItemsKey));
  const [query, setQuery] = useState("");
  const [availability, setAvailability] = useState<
    "ALL" | "AVAILABLE" | "HIDDEN"
  >("ALL");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => readWorkspaceSettings().defaultPageSize);
  const [itemToDelete, setItemToDelete] = useState<MenuRow | null>(null);

  const mapOwnerItem = (
    item: MenuItem,
    assignedRestaurant: Restaurant | null,
  ): MenuRow => ({
    id: item.id,
    restaurantId: item.restaurant_id,
    restaurantName: assignedRestaurant?.name ?? "Assigned restaurant",
    restaurantCity: assignedRestaurant?.city ?? "Assigned city",
    name: item.name,
    category: item.category,
    cuisineType: item.cuisine_type,
    description: item.description,
    price: item.price,
    launchedAt: item.launched_at,
    isNewLaunch: item.is_new_launch,
    isNew: item.is_new,
    isVeg: item.is_veg,
    isAvailable: item.is_available,
    isBestseller: item.is_bestseller,
    recentValidOrderCount: item.recent_valid_order_count,
    recentValidOrderWindowDays: item.recent_valid_order_window_days,
    imageUrl: item.image_url,
    source: item,
  });

  const mapAdminItem = (item: AdminMenuItem): MenuRow => ({
    id: item.id,
    restaurantId: item.restaurant_id,
    restaurantName: item.restaurant_name,
    restaurantCity: item.restaurant_city,
    name: item.name,
    category: item.category,
    cuisineType: item.cuisine_type,
    description: item.description,
    price: item.price,
    launchedAt: item.launched_at,
    isNewLaunch: item.is_new_launch,
    isNew: item.is_new,
    isVeg: item.is_veg,
    isAvailable: item.is_available,
    isBestseller: item.is_bestseller,
    recentValidOrderCount: item.recent_valid_order_count,
    recentValidOrderWindowDays: item.recent_valid_order_window_days,
    imageUrl: item.image_url,
    source: item,
  });

  // `force`: bypasses the cache. Used by the explicit reload paths below and
  // never by the mount effect, which is what makes revisiting this page free.
  const load = async (force = false) => {
    if (!force) {
      const cached = getPageSnapshot<MenuItemsSnapshot>(menuItemsKey);
      if (cached) {
        setRows(cached.rows);
        setRestaurant(cached.restaurant);
        setOwnerLocations(cached.ownerLocations);
        setIsLoading(false);
        return;
      }
    }

    setIsLoading(true);
    try {
      if (isAdmin) {
        const items = await api.getAdminMenuItems(token);
        const nextRows = items.map(mapAdminItem);
        setRows(nextRows);
        setRestaurant(null);
        setOwnerLocations([]);
        setPageSnapshot<MenuItemsSnapshot>(menuItemsKey, {
          rows: nextRows,
          restaurant: null,
          ownerLocations: [],
        });
        return;
      }

      if (!restaurantId) {
        setRows([]);
        setRestaurant(null);
        setOwnerLocations([]);
        return;
      }

      const [ownedRestaurants, ownerItems, locations] = await Promise.all([
        api.getOwnerRestaurants(token),
        api.getMenuItems(token, restaurantId),
        api.getRestaurantLocations(token, restaurantId),
      ]);
      const assignedRestaurant =
        ownedRestaurants.find((entry) => entry.id === restaurantId) ??
        ownedRestaurants[0] ??
        null;
      const nextRows = ownerItems.map((item) =>
        mapOwnerItem(item, assignedRestaurant),
      );
      setRestaurant(assignedRestaurant);
      setOwnerLocations(locations);
      setRows(nextRows);
      setPageSnapshot<MenuItemsSnapshot>(menuItemsKey, {
        rows: nextRows,
        restaurant: assignedRestaurant,
        ownerLocations: locations,
      });
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to load menu items.";
      // Keeps the failure on screen after the toast fades, and gives it a way out.
      setLoadError(message);
      onToast("Menu unavailable", message, "error");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [isAdmin, restaurantId, token, menuItemsKey]);

  const availabilityTiles = useMemo<Array<StatTileItem<"ALL" | "AVAILABLE" | "HIDDEN">>>(() => {
    const available = rows.filter((row) => row.isAvailable).length;
    const bestsellers = rows.filter((row) => row.isBestseller).length;
    return [
      {
        key: "ALL",
        label: "All items",
        icon: UtensilsCrossed,
        value: rows.length,
        hint: `${bestsellers} bestsellers`,
      },
      {
        key: "AVAILABLE",
        label: "Available",
        icon: Flame,
        value: available,
        hint: "Visible to customers",
      },
      {
        key: "HIDDEN",
        label: "Hidden",
        icon: EyeOff,
        value: rows.length - available,
        hint: "Not currently orderable",
      },
    ];
  }, [rows]);

  const filteredRows = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return rows.filter((item) => {
      const matchesQuery =
        !normalized ||
        [
          item.name,
          item.category,
          item.description ?? "",
          item.restaurantName,
          item.restaurantCity,
        ].some((value) => value.toLowerCase().includes(normalized));
      const matchesAvailability =
        availability === "ALL" ||
        (availability === "AVAILABLE" ? item.isAvailable : !item.isAvailable);
      return matchesQuery && matchesAvailability;
    });
  }, [availability, query, rows]);

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / pageSize));
  const pageItems = filteredRows.slice(
    (page - 1) * pageSize,
    page * pageSize,
  );

  useEffect(() => {
    setPage(1);
  }, [availability, pageSize, query]);

  const columns: Array<TableColumn<MenuRow>> = [
    {
      id: "item",
      header: "Item",
      render: (item) => (
        <>
          <strong>{item.name}</strong>
          <span>
            {item.isNew
              ? `Just launched • ${formatLaunchLabel(item.launchedAt)}`
              : item.isNewLaunch
                ? "Launch flag enabled"
              : item.description ?? item.category}
          </span>
        </>
      ),
      hideOnMobile: true,
    },
    {
      id: "restaurant",
      header: "Restaurant",
      render: (item) => (
        <>
          <strong>{item.restaurantName}</strong>
          <span>{item.restaurantCity}</span>
        </>
      ),
      mobileLabel: "Restaurant",
      hideOnMobile: !isAdmin,
    },
    {
      id: "orders",
      header: "Orders",
      render: (item) => (
        <>
          <strong>{item.recentValidOrderCount}</strong>
          <span>Last {item.recentValidOrderWindowDays} days</span>
        </>
      ),
      mobileLabel: "Orders",
      align: "right",
    },
    {
      id: "price",
      header: "Price",
      render: (item) => formatCurrency(item.price),
      mobileLabel: "Price",
      align: "right",
    },
    {
      id: "status",
      header: "Status",
      render: (item) => (
        <div className="status-stack">
          {item.isNew ? <StatusPill status="NEW" /> : null}
          <StatusPill status={item.isAvailable ? "AVAILABLE" : "HIDDEN"} />
          {item.isBestseller ? <StatusPill status="BEST SELLER" /> : null}
        </div>
      ),
      mobileLabel: "Status",
    },
  ];

  const openCreatePage = () => {
    if (isAdmin || !restaurantId) {
      return;
    }

    if (ownerLocations.length === 0) {
      onToast(
        "Location required",
        "Create at least one location before adding menu items.",
        "info",
      );
      onNavigate(`/admin/restaurants/${restaurantId}/locations`);
      return;
    }

    onNavigate(`/admin/restaurants/${restaurantId}/menu-items/create`);
  };

  const openEditPage = (item: MenuRow) => {
    if (isAdmin) {
      return;
    }

    const source = item.source as MenuItem;
    const itemLocationId =
      source.restaurant_location_id ??
      ownerLocations.find((location) => location.is_active)?.id ??
      ownerLocations[0]?.id;
    if (!itemLocationId) {
      onToast(
        "Location unavailable",
        "This menu item is missing its location context.",
        "error",
      );
      return;
    }

    onNavigate(
      `/admin/restaurants/${item.restaurantId}/locations/${itemLocationId}/menu-items/${item.id}/edit`,
    );
  };

  const toggleAvailability = async (item: MenuRow) => {
    if (isAdmin) {
      return;
    }

    try {
      const updated = await api.updateMenuItemAvailability(
        token,
        item.id,
        !item.isAvailable,
      );
      setRows((current) =>
        current.map((entry) =>
          entry.id === updated.id ? mapOwnerItem(updated, restaurant) : entry,
        ),
      );
      // Genuine data change: the cached snapshot for this scope no longer
      // matches what the server has. Only affects the NEXT visit - this page
      // keeps showing the already-patched `rows` above.
      invalidatePageSnapshotsByPrefix(buildMenuItemsCacheKeyPrefix(scope));
      onToast(
        "Availability updated",
        `${updated.name} is now ${updated.is_available ? "available" : "hidden"}.`,
        "success",
      );
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to update availability.";
      onToast("Availability failed", message, "error");
    }
  };

  const requestRemoveItem = (item: MenuRow) => {
    if (isAdmin) {
      return;
    }
    setItemToDelete(item);
  };

  const removeItem = async () => {
    if (isAdmin || !itemToDelete) {
      return;
    }

    try {
      await api.deleteMenuItem(token, itemToDelete.id);
      setRows((current) => current.filter((entry) => entry.id !== itemToDelete.id));
      invalidatePageSnapshotsByPrefix(buildMenuItemsCacheKeyPrefix(scope));
      onToast(
        "Item deleted",
        `${itemToDelete.name} has been removed from the menu.`,
        "success",
      );
      setItemToDelete(null);
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to delete menu item.";
      onToast("Delete failed", message, "error");
    }
  };

  return (
    <div className="page-stack">
      <PageIntro
        eyebrow="Menu catalog"
        title="Menu items"
        description={
          isAdmin
            ? "Same menu workspace, but with full platform visibility across all restaurants."
            : `Same menu workspace, filtered automatically to ${restaurant?.name ?? "your assigned restaurant"}.`
        }
      />

      <StatTiles<"ALL" | "AVAILABLE" | "HIDDEN">
        active={availability}
        ariaLabel="Availability distribution"
        loading={isLoading}
        onSelect={setAvailability}
        tiles={availabilityTiles}
      />

      {!isAdmin && !restaurant ? (
        <section className="admin-surface">
          <EmptyPanel
            title="Restaurant not assigned"
            description="This owner account cannot create restaurants. Ask an admin to assign one restaurant."
          />
        </section>
      ) : null}

      {isAdmin || restaurant ? (
        <section className="admin-surface">
          <DataToolbar
            actions={
              <>
                <span className="toolbar-meta">
                  {pluralize(filteredRows.length, "item")}
                </span>
                {!isAdmin ? (
                  <>
                    <StatusPill
                      status={restaurant?.is_approved ? "APPROVED" : "PENDING"}
                    />
                    <button
                      className="primary-button"
                      onClick={openCreatePage}
                      type="button"
                    >
                      + Add New
                    </button>
                  </>
                ) : null}
              </>
            }
            filters={
              <select
                className="page-search page-search--select"
                onChange={(event) =>
                  setAvailability(event.target.value as typeof availability)
                }
                value={availability}
              >
                <option value="ALL">All availability</option>
                <option value="AVAILABLE">Available</option>
                <option value="HIDDEN">Hidden</option>
              </select>
            }
            onSearchChange={setQuery}
            searchPlaceholder="Search by dish, category, restaurant, or description"
            searchValue={query}
          />

          <ResponsiveTable
            actions={
              isAdmin
                ? [
                    {
                      id: "view",
                      label: "Read only",
                      icon: Eye,
                      onClick: () => undefined,
                      disabled: () => true,
                    },
                  ]
                : [
                    {
                      id: "edit",
                      label: "Edit item",
                      icon: Pencil,
                      onClick: openEditPage,
                    },
                    {
                      id: "toggle",
                      label: "Toggle availability",
                      icon: Eye,
                      onClick: toggleAvailability,
                      tone: "success",
                    },
                    {
                      id: "delete",
                      label: "Delete item",
                      icon: Trash2,
                      onClick: requestRemoveItem,
                      tone: "danger",
                    },
                  ]
            }
            columns={columns}
            emptyAction={
              !isAdmin && restaurantId ? (
                <button
                  className="primary-button"
                  onClick={() =>
                    onNavigate(`/admin/restaurants/${restaurantId}/locations`)
                  }
                  type="button"
                >
                  Add menu item
                </button>
              ) : query || availability !== "ALL" ? (
                <button
                  className="secondary-button"
                  onClick={() => {
                    setQuery("");
                    setAvailability("ALL");
                  }}
                  type="button"
                >
                  Clear filters
                </button>
              ) : null
            }
            emptyDescription="Use Add New to create the first item or adjust the current filters."
            emptyTitle="No menu items match this view"
            errorTitle="We couldn't load menu items"
            error={loadError}
            onRetry={() => {
              setLoadError(null);
              void load(true);
            }}
            keyExtractor={(item) => item.id}
            loading={isLoading}
            mobileStatus={(item) => (
              <div className="status-stack">
                {item.isNew ? <StatusPill status="NEW" /> : null}
                <StatusPill status={item.isAvailable ? "AVAILABLE" : "HIDDEN"} />
                {item.isBestseller ? <StatusPill status="BEST SELLER" /> : null}
              </div>
            )}
            mobileSubtitle={(item) =>
              item.isBestseller ? `${item.category} • Best seller` : item.category
            }
            mobileTitle={(item) => item.name}
            rows={pageItems}
          />
          <Pagination
            onPageChange={setPage}
            onPageSizeChange={setPageSize}
            page={page}
            pageSize={pageSize}
            totalItems={filteredRows.length}
            totalPages={totalPages}
          />
        </section>
      ) : null}

      <ConfirmDialog
        open={itemToDelete !== null}
        eyebrow="Menu item removal"
        title={itemToDelete ? `Delete ${itemToDelete.name}?` : "Delete menu item?"}
        description="This item will be removed from the assigned restaurant menu."
        confirmLabel="Delete item"
        onCancel={() => setItemToDelete(null)}
        onConfirm={() => {
          void removeItem();
        }}
        tone="danger"
      />
    </div>
  );
}

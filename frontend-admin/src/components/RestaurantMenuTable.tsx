import { Eye, Pencil, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { MenuItem, RestaurantDetail, UserRole } from "../types/app";
import { ApiError, api, formatCurrency } from "../services/api";
import { ConfirmDialog } from "./ConfirmDialog";
import { DataToolbar } from "./DataToolbar";
import { Pagination } from "./Pagination";
import { ResponsiveTable, type TableColumn } from "./ResponsiveTable";
import { StatusPill } from "./StatusPill";

interface RestaurantMenuTableProps {
  token: string;
  role: UserRole;
  restaurant: RestaurantDetail;
  selectedLocationId: string | null;
  onNavigate: (path: string) => void;
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

function formatLaunchLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Recent launch";
  }
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
  }).format(date);
}

export function RestaurantMenuTable({
  token,
  role,
  restaurant,
  selectedLocationId,
  onNavigate,
  onToast,
}: RestaurantMenuTableProps) {
  const [items, setItems] = useState<MenuItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("ALL");
  const [dietFilter, setDietFilter] = useState<"ALL" | "VEG" | "NON_VEG">(
    "ALL",
  );
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [busyItemId, setBusyItemId] = useState<string | null>(null);
  const [itemToDelete, setItemToDelete] = useState<MenuItem | null>(null);

  const canManage = role === "ADMIN" || role === "OWNER";

  const loadItems = async () => {
    setIsLoading(true);
    try {
      const response = await api.getMenuItems(token, restaurant.id, selectedLocationId);
      setItems(response);
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to load restaurant menu items.";
      onToast("Menu unavailable", message, "error");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadItems();
  }, [restaurant.id, selectedLocationId, token]);

  const categories = useMemo(
    () =>
      Array.from(
        new Set(items.map((item) => item.category.trim()).filter(Boolean)),
      ).sort((left, right) => left.localeCompare(right)),
    [items],
  );

  const filteredItems = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return items.filter((item) => {
      const matchesQuery =
        !normalized ||
        [
          item.name,
          item.category,
          item.description ?? "",
          item.cuisine_type ?? "",
        ].some((value) => value.toLowerCase().includes(normalized));
      const matchesCategory =
        categoryFilter === "ALL" || item.category === categoryFilter;
      const matchesDiet =
        dietFilter === "ALL" ||
        (dietFilter === "VEG" ? item.is_veg : !item.is_veg);
      return matchesQuery && matchesCategory && matchesDiet;
    });
  }, [categoryFilter, dietFilter, items, query]);

  const totalPages = Math.max(1, Math.ceil(filteredItems.length / pageSize));
  const pageItems = filteredItems.slice(
    (page - 1) * pageSize,
    page * pageSize,
  );

  useEffect(() => {
    setPage(1);
  }, [categoryFilter, dietFilter, pageSize, query]);

  useEffect(() => {
    setPage((current) => Math.min(current, totalPages));
  }, [totalPages]);

  const columns: Array<TableColumn<MenuItem>> = [
    {
      id: "name",
      header: "Name",
      render: (item) => (
        <>
          <strong>{item.name}</strong>
          <span>
            {item.is_new
              ? `Just launched • ${formatLaunchLabel(item.launched_at)}`
              : item.is_new_launch
                ? "Launch flag enabled"
              : item.cuisine_type ?? item.description ?? "Menu item"}
          </span>
        </>
      ),
      hideOnMobile: true,
    },
    {
      id: "orders",
      header: "Orders",
      render: (item) => (
        <>
          <strong>{item.recent_valid_order_count}</strong>
          <span>Last {item.recent_valid_order_window_days} days</span>
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
      id: "category",
      header: "Category",
      render: (item) => (
        <>
          <strong>{item.category}</strong>
          <span>{item.is_veg ? "Veg" : "Non-veg"}</span>
        </>
      ),
      mobileLabel: "Category",
    },
    {
      id: "availability",
      header: "Availability",
      render: (item) => (
        <div className="status-stack">
          {item.is_new ? <StatusPill status="NEW" /> : null}
          <StatusPill status={item.is_available ? "AVAILABLE" : "HIDDEN"} />
          {item.is_bestseller ? <StatusPill status="BEST SELLER" /> : null}
        </div>
      ),
      mobileLabel: "Availability",
    },
  ];

  const openCreatePage = () => {
    if (!selectedLocationId) {
      onToast(
        "Select a location first",
        "Choose an active branch before adding a menu item.",
        "info",
      );
      return;
    }

    onNavigate(
      `/admin/restaurants/${restaurant.id}/locations/${selectedLocationId}/menu-items/create`,
    );
  };

  const openEditPage = (item: MenuItem) => {
    const itemLocationId = item.restaurant_location_id ?? selectedLocationId;
    if (!itemLocationId) {
      onToast(
        "Location unavailable",
        "This menu item is missing its location context.",
        "error",
      );
      return;
    }

    onNavigate(
      `/admin/restaurants/${restaurant.id}/locations/${itemLocationId}/menu-items/${item.id}/edit`,
    );
  };

  const toggleAvailability = async (item: MenuItem) => {
    if (!canManage || busyItemId) {
      return;
    }

    setBusyItemId(item.id);
    try {
      const updated = await api.updateMenuItemAvailability(
        token,
        item.id,
        !item.is_available,
      );
      setItems((current) =>
        current.map((entry) => (entry.id === updated.id ? updated : entry)),
      );
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
      onToast("Update failed", message, "error");
    } finally {
      setBusyItemId(null);
    }
  };

  const requestDeleteItem = (item: MenuItem) => {
    if (!canManage || busyItemId) {
      return;
    }
    setItemToDelete(item);
  };

  const deleteItem = async () => {
    if (!canManage || busyItemId || !itemToDelete) {
      return;
    }

    setBusyItemId(itemToDelete.id);
    try {
      await api.deleteMenuItem(token, itemToDelete.id);
      setItems((current) =>
        current.filter((entry) => entry.id !== itemToDelete.id),
      );
      onToast("Menu item deleted", `${itemToDelete.name} was removed.`, "success");
      setItemToDelete(null);
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to delete the menu item.";
      onToast("Delete failed", message, "error");
    } finally {
      setBusyItemId(null);
    }
  };

  return (
    <div className="page-stack">
      <DataToolbar
        actions={
          canManage ? (
            <>
              <span className="toolbar-meta">{filteredItems.length} items</span>
              <button className="primary-button" onClick={openCreatePage} type="button">
                + Add Menu Item
              </button>
            </>
          ) : (
            <span className="toolbar-meta">{filteredItems.length} items</span>
          )
        }
        filters={
          <>
            <select
              className="page-search page-search--select"
              onChange={(event) => setCategoryFilter(event.target.value)}
              value={categoryFilter}
            >
              <option value="ALL">All categories</option>
              {categories.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
            <select
              className="page-search page-search--select"
              onChange={(event) =>
                setDietFilter(event.target.value as typeof dietFilter)
              }
              value={dietFilter}
            >
              <option value="ALL">Veg + Non-veg</option>
              <option value="VEG">Veg only</option>
              <option value="NON_VEG">Non-veg only</option>
            </select>
          </>
        }
        onSearchChange={setQuery}
        searchPlaceholder="Search by item, category, cuisine..."
        searchValue={query}
      />

      <ResponsiveTable
        actions={[
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
            onClick: requestDeleteItem,
            tone: "danger",
          },
        ]}
        columns={columns}
        emptyDescription="Try a different search, category, or diet filter."
        emptyTitle="No menu items match these filters"
        keyExtractor={(item) => item.id}
        loading={isLoading}
        mobileStatus={(item) => (
          <div className="status-stack">
            {item.is_new ? <StatusPill status="NEW" /> : null}
            <StatusPill status={item.is_available ? "AVAILABLE" : "HIDDEN"} />
            {item.is_bestseller ? <StatusPill status="BEST SELLER" /> : null}
          </div>
        )}
        mobileSubtitle={(item) => (item.is_bestseller ? `${item.category} • Best seller` : item.category)}
        mobileTitle={(item) => item.name}
        rows={pageItems}
      />
      <Pagination
        onPageChange={setPage}
        onPageSizeChange={setPageSize}
        page={page}
        pageSize={pageSize}
        totalItems={filteredItems.length}
        totalPages={totalPages}
      />

      <ConfirmDialog
        open={itemToDelete !== null}
        eyebrow="Menu item removal"
        title={itemToDelete ? `Delete ${itemToDelete.name}?` : "Delete menu item?"}
        description="This item will be removed from the current restaurant menu."
        confirmLabel="Delete item"
        busy={busyItemId === itemToDelete?.id}
        onCancel={() => {
          if (!busyItemId) {
            setItemToDelete(null);
          }
        }}
        onConfirm={() => {
          void deleteItem();
        }}
        tone="danger"
      />
    </div>
  );
}

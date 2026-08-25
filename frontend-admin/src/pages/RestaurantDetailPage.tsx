import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Eye,
  Layers3,
  ReceiptText,
  Settings2,
  Smartphone,
  Store,
  UtensilsCrossed,
} from "lucide-react";
import { Modal } from "../components/Modal";
import { AppClientFields } from "../components/AppClientFields";
import {
  toAppClientForm,
  toBundleId,
  trimAppClientForm,
  validateAppClientForm,
  type AppClientFormErrors,
  type AppClientFormValues,
  type DerivedAppClientField,
} from "../services/appClient";
import { Checkbox } from "../components/common/Checkbox";
import { DataToolbar } from "../components/DataToolbar";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { EmptyPanel } from "../components/EmptyPanel";
import { Breadcrumbs } from "../components/Breadcrumbs";
import { PageIntro } from "../components/PageIntro";
import { Pagination } from "../components/Pagination";
import { ResponsiveTable, type TableColumn } from "../components/ResponsiveTable";
import { RestaurantMenuTable } from "../components/RestaurantMenuTable";
import { RestaurantOffersManager } from "../components/RestaurantOffersManager";
import { StatusPill } from "../components/StatusPill";
import { GeneratedCombosPage } from "./GeneratedCombosPage";
import { buildAdminRestaurantsCacheKeyPrefix } from "./AdminRestaurantsPage";
import { buildOrdersCacheKeyPrefix } from "./OrdersPage";
import {
  ApiError,
  api,
  formatCurrency,
  formatDate,
} from "../services/api";
import {
  getPageSnapshot,
  hasPageSnapshot,
  invalidatePageSnapshot,
  invalidatePageSnapshotsByPrefix,
  setPageSnapshot,
  tokenScope,
} from "../services/pageCache";
import type {
  AppClient,
  Order,
  OrderStatus,
  RestaurantDetail,
  RestaurantLocation,
  UserRole,
} from "../types/app";

interface RestaurantDetailPageProps {
  token: string;
  role: UserRole;
  restaurantId: string;
  assignedRestaurantId: string | null;
  initialSection?: SectionKey;
  onNavigate: (path: string) => void;
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

type RestaurantForm = {
  name: string;
  description: string;
  cuisine_type: string;
  address_line_1: string;
  address_line_2: string;
  city: string;
  state: string;
  country: string;
  postal_code: string;
  phone_number: string;
  minimum_order_amount: string;
  delivery_fee: string;
  logo_image_url: string;
  cover_image_url: string;
  is_open: boolean;
};

type LocationForm = {
  branch_name: string;
  address_line_1: string;
  address_line_2: string;
  city: string;
  state: string;
  postal_code: string;
  phone_number: string;
  delivery_fee: string;
  minimum_order_amount: string;
  estimated_delivery_time: string;
  is_open: boolean;
  is_active: boolean;
};

type SectionKey =
  | "details"
  | "settings"
  | "app_client"
  | "offers"
  | "locations"
  | "generated_combos"
  | "menu"
  | "orders";

const nextStatusMap: Partial<Record<OrderStatus, OrderStatus>> = {
  PLACED: "ACCEPTED",
  ACCEPTED: "PREPARING",
  PREPARING: "OUT_FOR_DELIVERY",
  OUT_FOR_DELIVERY: "DELIVERED",
};

function toEditForm(restaurant: RestaurantDetail): RestaurantForm {
  return {
    name: restaurant.name,
    description: restaurant.description ?? "",
    cuisine_type: restaurant.cuisine_type,
    address_line_1: restaurant.address_line_1,
    address_line_2: restaurant.address_line_2 ?? "",
    city: restaurant.city,
    state: restaurant.state,
    country: restaurant.country,
    postal_code: restaurant.postal_code,
    phone_number: restaurant.phone_number ?? "",
    minimum_order_amount: String(restaurant.minimum_order_amount),
    delivery_fee: String(restaurant.delivery_fee),
    logo_image_url: restaurant.logo_image_url ?? "",
    cover_image_url: restaurant.cover_image_url ?? "",
    is_open: restaurant.is_open,
  };
}

function toLocationForm(location?: RestaurantLocation | null): LocationForm {
  return {
    branch_name: location?.branch_name ?? "",
    address_line_1: location?.address_line_1 ?? "",
    address_line_2: location?.address_line_2 ?? "",
    city: location?.city ?? "",
    state: location?.state ?? "",
    postal_code: location?.postal_code ?? "",
    phone_number: location?.phone_number ?? "",
    delivery_fee: String(location?.delivery_fee ?? 0),
    minimum_order_amount: String(location?.minimum_order_amount ?? 0),
    estimated_delivery_time: String(location?.estimated_delivery_time ?? 30),
    is_open: location?.is_open ?? false,
    is_active: location?.is_active ?? true,
  };
}

interface RestaurantDetailSnapshot {
  restaurant: RestaurantDetail;
  orders: Order[];
}

function buildRestaurantDetailKey(scope: string, restaurantId: string): string {
  return `restaurant-detail:${scope}:${restaurantId}`;
}

/**
 * For other pages that edit the same restaurant/locations from elsewhere
 * (LocationsPage manages locations for the same restaurant this page shows a
 * copy of) - call after a mutation there so this page's cache doesn't show
 * pre-edit data on the next visit.
 */
export function invalidateRestaurantDetailCache(scope: string, restaurantId: string): void {
  invalidatePageSnapshot(buildRestaurantDetailKey(scope, restaurantId));
}

function buildRestaurantAppClientKey(scope: string, restaurantId: string): string {
  return `restaurant-app-client:${scope}:${restaurantId}`;
}

export function RestaurantDetailPage({
  token,
  role,
  restaurantId,
  assignedRestaurantId,
  initialSection = "details",
  onNavigate,
  onToast,
}: RestaurantDetailPageProps) {
  const isAdmin = role === "ADMIN";
  const backPath = isAdmin
    ? "/restaurants"
    : assignedRestaurantId
      ? `/admin/restaurants/${assignedRestaurantId}/locations`
      : "/dashboard";

  const scope = tokenScope(token);
  // App.tsx already remounts this page fresh per restaurantId (it's part of
  // the `key`), so a different restaurant never seeing another's cache is
  // guaranteed there too - this key is what makes returning to the SAME
  // restaurant, after navigating away and back, free.
  const detailKey = buildRestaurantDetailKey(scope, restaurantId);
  const appClientKey = buildRestaurantAppClientKey(scope, restaurantId);
  const cachedDetail = getPageSnapshot<RestaurantDetailSnapshot>(detailKey);
  const cachedAppClient = getPageSnapshot<AppClient>(appClientKey);

  const [restaurant, setRestaurant] = useState<RestaurantDetail | null>(
    () => cachedDetail?.restaurant ?? null,
  );
  const [orders, setOrders] = useState<Order[]>(() => cachedDetail?.orders ?? []);
  // Only true when this restaurant has never been fetched this session - not
  // on every mount, so revisiting it keeps showing its data instead of a
  // skeleton.
  const [isLoading, setIsLoading] = useState(() => !hasPageSnapshot(detailKey));
  const [activeSection, setActiveSection] = useState<SectionKey>(initialSection);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [isEditSubmitting, setIsEditSubmitting] = useState(false);
  const [isSettingsSubmitting, setIsSettingsSubmitting] = useState(false);
  const [editForm, setEditForm] = useState<RestaurantForm | null>(
    () => (cachedDetail ? toEditForm(cachedDetail.restaurant) : null),
  );
  const [selectedLocationId, setSelectedLocationId] = useState<string | null>(
    () =>
      cachedDetail?.restaurant.locations.find((location) => location.is_active)?.id
      ?? cachedDetail?.restaurant.locations[0]?.id
      ?? null,
  );
  const [isLocationModalOpen, setIsLocationModalOpen] = useState(false);
  const [editingLocationId, setEditingLocationId] = useState<string | null>(null);
  const [locationForm, setLocationForm] = useState<LocationForm>(toLocationForm());
  const [isLocationSubmitting, setIsLocationSubmitting] = useState(false);
  const [locationToDeactivate, setLocationToDeactivate] = useState<RestaurantLocation | null>(null);
  const [appClient, setAppClient] = useState<AppClient | null>(() => cachedAppClient ?? null);
  const [appClientForm, setAppClientForm] = useState<AppClientFormValues | null>(
    () =>
      cachedAppClient && cachedDetail
        ? toAppClientForm(cachedAppClient, cachedDetail.restaurant.name)
        : null,
  );
  const [appClientErrors, setAppClientErrors] = useState<AppClientFormErrors>({});
  const [appClientLoadError, setAppClientLoadError] = useState<string | null>(null);
  const [isAppClientSubmitting, setIsAppClientSubmitting] = useState(false);
  const [orderQuery, setOrderQuery] = useState("");
  const [orderStatusFilter, setOrderStatusFilter] = useState<"ALL" | OrderStatus>(
    "ALL",
  );
  const [orderPage, setOrderPage] = useState(1);
  const [orderPageSize, setOrderPageSize] = useState(10);
  const sectionOptions = useMemo<
    Array<{
      key: SectionKey;
      label: string;
      icon: typeof Store;
    }>
  >(
    () => {
      const baseSections: Array<{
        key: SectionKey;
        label: string;
        icon: typeof Store;
      }> = [
        { key: "details", label: "Details", icon: Store },
        { key: "settings", label: "Settings", icon: Settings2 },
        { key: "offers", label: "Offers", icon: ReceiptText },
      ];

      if (isAdmin) {
        baseSections.push(
          { key: "app_client", label: "Mobile App", icon: Smartphone },
          { key: "locations", label: "Locations", icon: Eye },
          {
            key: "generated_combos",
            label: "Generated Combos",
            icon: Layers3,
          },
          { key: "menu", label: "Menu Items", icon: UtensilsCrossed },
        );
      }

      baseSections.push({ key: "orders", label: "Orders", icon: ReceiptText });
      return baseSections;
    },
    [isAdmin],
  );

  useEffect(() => {
    if (
      role === "OWNER" &&
      assignedRestaurantId &&
      restaurantId !== assignedRestaurantId
    ) {
      onNavigate(`/admin/restaurants/${assignedRestaurantId}/locations`);
    }
  }, [assignedRestaurantId, onNavigate, restaurantId, role]);

  useEffect(() => {
    if (
      role === "OWNER" &&
      assignedRestaurantId &&
      restaurantId !== assignedRestaurantId
    ) {
      return;
    }

    const cached = getPageSnapshot<RestaurantDetailSnapshot>(detailKey);
    if (cached) {
      setRestaurant(cached.restaurant);
      setSelectedLocationId(
        cached.restaurant.locations.find((location) => location.is_active)?.id
        ?? cached.restaurant.locations[0]?.id
        ?? null,
      );
      setEditForm(toEditForm(cached.restaurant));
      setOrders(cached.orders);
      setIsLoading(false);
      return;
    }

    let active = true;

    Promise.all([
      api.getRestaurant(token, restaurantId),
      api.getOrders(token, restaurantId),
    ])
      .then(([detail, restaurantOrders]) => {
        if (!active) {
          return;
        }
        setRestaurant(detail);
        setSelectedLocationId(
          detail.locations.find((location) => location.is_active)?.id
          ?? detail.locations[0]?.id
          ?? null,
        );
        setEditForm(toEditForm(detail));
        setOrders(restaurantOrders);
        setIsLoading(false);
        setPageSnapshot<RestaurantDetailSnapshot>(detailKey, {
          restaurant: detail,
          orders: restaurantOrders,
        });
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        const message =
          error instanceof ApiError
            ? error.message
            : "Unable to load the restaurant workspace.";
        setIsLoading(false);
        onToast("Restaurant unavailable", message, "error");
        if (role === "OWNER" && assignedRestaurantId) {
          onNavigate(`/admin/restaurants/${assignedRestaurantId}/locations`);
        } else {
          onNavigate(backPath);
        }
      });

    return () => {
      active = false;
    };
  }, [assignedRestaurantId, backPath, onNavigate, onToast, restaurantId, role, token, detailKey]);

  // Loaded lazily so the app client request only happens when the tab is opened.
  useEffect(() => {
    if (
      !isAdmin
      || activeSection !== "app_client"
      || !restaurant
      || appClientForm
      || appClientLoadError
    ) {
      return;
    }

    const cachedClient = getPageSnapshot<AppClient>(appClientKey);
    if (cachedClient) {
      setAppClient(cachedClient);
      setAppClientForm(toAppClientForm(cachedClient, restaurant.name));
      return;
    }

    let active = true;

    api
      .getRestaurantAppClient(token, restaurant.id)
      .then((loaded) => {
        if (!active) {
          return;
        }
        setAppClient(loaded);
        setAppClientForm(toAppClientForm(loaded, restaurant.name));
        setPageSnapshot(appClientKey, loaded);
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        const message =
          error instanceof ApiError ? error.message : "Unable to load the app client.";
        setAppClientLoadError(message);
        onToast("App client unavailable", message, "error");
      });

    return () => {
      active = false;
    };
  }, [
    activeSection,
    appClientForm,
    appClientLoadError,
    appClientKey,
    isAdmin,
    onToast,
    restaurant,
    token,
  ]);

  const updateAppClientField = (field: DerivedAppClientField, value: string) => {
    setAppClientForm((current) => {
      if (!current) {
        return current;
      }
      if (field !== "app_key") {
        return { ...current, [field]: value };
      }

      // Bundle IDs follow the app key only while they still match it.
      const previousBundleId = toBundleId(current.app_key);
      const nextBundleId = toBundleId(value);
      return {
        ...current,
        app_key: value,
        ios_bundle_id:
          current.ios_bundle_id === previousBundleId ? nextBundleId : current.ios_bundle_id,
        android_package_name:
          current.android_package_name === previousBundleId
            ? nextBundleId
            : current.android_package_name,
      };
    });
    setAppClientErrors((current) => ({ ...current, [field]: undefined }));
  };

  const saveAppClient = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!restaurant || !appClientForm || isAppClientSubmitting) {
      return;
    }

    const validationErrors = validateAppClientForm(appClientForm);
    if (Object.keys(validationErrors).length > 0) {
      setAppClientErrors(validationErrors);
      onToast("Check the app details", "Some app client fields need to be corrected.", "error");
      return;
    }

    setAppClientErrors({});
    setIsAppClientSubmitting(true);
    try {
      const saved = await api.saveRestaurantAppClient(
        token,
        restaurant.id,
        trimAppClientForm(appClientForm),
      );
      setAppClient(saved);
      setAppClientForm(toAppClientForm(saved, restaurant.name));
      setPageSnapshot(appClientKey, saved);
      onToast(
        appClient ? "App settings updated" : "App client created",
        `${restaurant.name} now uses app key "${saved.app_key}".`,
        "success",
      );
    } catch (error: unknown) {
      const message =
        error instanceof ApiError ? error.message : "Unable to save the app client.";
      onToast("Save failed", message, "error");
    } finally {
      setIsAppClientSubmitting(false);
    }
  };

  const filteredOrders = useMemo(() => {
    const normalized = orderQuery.trim().toLowerCase();
    return orders.filter((order) => {
      const matchesQuery =
        !normalized ||
        [
          order.id,
          order.customer.full_name,
          order.customer.email,
          order.payment_reference ?? "",
        ].some((value) => value.toLowerCase().includes(normalized));
      const matchesStatus =
        orderStatusFilter === "ALL" || order.status === orderStatusFilter;
      const matchesLocation =
        !selectedLocationId || order.restaurant_location_id === selectedLocationId;
      return matchesQuery && matchesStatus && matchesLocation;
    });
  }, [orderQuery, orderStatusFilter, orders, selectedLocationId]);

  const selectedLocation = useMemo(
    () => restaurant?.locations.find((location) => location.id === selectedLocationId) ?? null,
    [restaurant?.locations, selectedLocationId],
  );

  const totalOrderPages = Math.max(
    1,
    Math.ceil(filteredOrders.length / orderPageSize),
  );
  const currentOrderPage = Math.min(orderPage, totalOrderPages);
  const orderPageItems = filteredOrders.slice(
    (currentOrderPage - 1) * orderPageSize,
    currentOrderPage * orderPageSize,
  );

  const openEditModal = () => {
    if (!restaurant) {
      return;
    }
    setEditForm(toEditForm(restaurant));
    setIsEditOpen(true);
  };

  const closeEditModal = () => {
    setIsEditOpen(false);
    setIsEditSubmitting(false);
    if (restaurant) {
      setEditForm(toEditForm(restaurant));
    }
  };

  const openCreateLocationModal = () => {
    setEditingLocationId(null);
    setLocationForm(toLocationForm());
    setIsLocationModalOpen(true);
  };

  const openEditLocationModal = (location: RestaurantLocation) => {
    setEditingLocationId(location.id);
    setLocationForm(toLocationForm(location));
    setIsLocationModalOpen(true);
  };

  const closeLocationModal = () => {
    setIsLocationModalOpen(false);
    setEditingLocationId(null);
    setLocationForm(toLocationForm());
    setIsLocationSubmitting(false);
  };

  const saveRestaurant = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!restaurant || !editForm || isEditSubmitting) {
      return;
    }

    setIsEditSubmitting(true);
    try {
      const updated = isAdmin
        ? await (async () => {
            await api.updateRestaurant(token, restaurant.id, {
              name: editForm.name.trim(),
              description: editForm.description.trim() || null,
              cuisine_type: editForm.cuisine_type.trim(),
              address_line_1: editForm.address_line_1.trim(),
              address_line_2: editForm.address_line_2.trim() || null,
              city: editForm.city.trim(),
              state: editForm.state.trim(),
              country: editForm.country.trim(),
              postal_code: editForm.postal_code.trim(),
              phone_number: editForm.phone_number.trim() || null,
              minimum_order_amount: Number(editForm.minimum_order_amount),
              delivery_fee: Number(editForm.delivery_fee),
              logo_image_url: editForm.logo_image_url.trim() || null,
              cover_image_url: editForm.cover_image_url.trim() || null,
              is_open: editForm.is_open,
            });
            return api.getRestaurant(token, restaurant.id);
          })()
        : await api.updateRestaurantSettings(token, restaurant.id, {
            name: editForm.name.trim(),
            description: editForm.description.trim() || null,
            cuisine_type: editForm.cuisine_type.trim(),
            address_line_1: editForm.address_line_1.trim(),
            address_line_2: editForm.address_line_2.trim() || null,
            city: editForm.city.trim(),
            state: editForm.state.trim(),
            country: editForm.country.trim(),
            postal_code: editForm.postal_code.trim(),
            phone_number: editForm.phone_number.trim() || null,
            logo_image_url: editForm.logo_image_url.trim() || null,
            cover_image_url: editForm.cover_image_url.trim() || null,
            is_open: editForm.is_open,
          });

      setRestaurant(updated);
      setEditForm(toEditForm(updated));
      // Genuine data change: this page's own cache and the admin restaurants
      // list (name/city/status can show there too) both need to reflect it
      // on their next visit.
      setPageSnapshot<RestaurantDetailSnapshot>(detailKey, { restaurant: updated, orders });
      invalidatePageSnapshotsByPrefix(buildAdminRestaurantsCacheKeyPrefix(scope));
      closeEditModal();
      onToast("Restaurant updated", `${updated.name} was saved.`, "success");
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to update the restaurant.";
      onToast("Update failed", message, "error");
      setIsEditSubmitting(false);
    }
  };

  const updateSettings = async (payload: {
    is_open?: boolean;
    is_active?: boolean;
  }) => {
    if (!restaurant || isSettingsSubmitting) {
      return;
    }

    setIsSettingsSubmitting(true);
    try {
      const updated = await api.updateRestaurantSettings(
        token,
        restaurant.id,
        payload,
      );
      setRestaurant(updated);
      setEditForm(toEditForm(updated));
      setPageSnapshot<RestaurantDetailSnapshot>(detailKey, { restaurant: updated, orders });
      invalidatePageSnapshotsByPrefix(buildAdminRestaurantsCacheKeyPrefix(scope));
      onToast(
        "Settings updated",
        `${updated.name} settings were refreshed.`,
        "success",
      );
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to update restaurant settings.";
      onToast("Settings failed", message, "error");
    } finally {
      setIsSettingsSubmitting(false);
    }
  };

  const submitLocation = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!restaurant || isLocationSubmitting) {
      return;
    }

    setIsLocationSubmitting(true);
    const payload = {
      branch_name: locationForm.branch_name.trim(),
      address_line_1: locationForm.address_line_1.trim(),
      address_line_2: locationForm.address_line_2.trim() || null,
      city: locationForm.city.trim(),
      state: locationForm.state.trim(),
      postal_code: locationForm.postal_code.trim(),
      phone_number: locationForm.phone_number.trim() || null,
      delivery_fee: Number(locationForm.delivery_fee),
      minimum_order_amount: Number(locationForm.minimum_order_amount),
      estimated_delivery_time: Number(locationForm.estimated_delivery_time),
      is_open: locationForm.is_open,
      is_active: locationForm.is_active,
    };

    try {
      const nextLocation = editingLocationId
        ? await api.updateRestaurantLocation(token, restaurant.id, editingLocationId, payload)
        : await api.createRestaurantLocation(token, restaurant.id, payload);

      setRestaurant((current) => {
        if (!current) {
          return current;
        }
        const next = {
          ...current,
          locations: editingLocationId
            ? current.locations.map((location) => location.id === nextLocation.id ? nextLocation : location)
            : [...current.locations, nextLocation],
        };
        setPageSnapshot<RestaurantDetailSnapshot>(detailKey, { restaurant: next, orders });
        return next;
      });
      setSelectedLocationId(nextLocation.id);
      closeLocationModal();
      onToast(
        editingLocationId ? "Location updated" : "Location created",
        `${nextLocation.branch_name} is ready to manage.`,
        "success",
      );
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to save this restaurant location.";
      onToast("Location save failed", message, "error");
      setIsLocationSubmitting(false);
    }
  };

  const requestDeactivateLocation = (location: RestaurantLocation) => {
    setLocationToDeactivate(location);
  };

  const deactivateLocation = async () => {
    if (!restaurant || !locationToDeactivate) {
      return;
    }

    try {
      const nextLocation = await api.deactivateRestaurantLocation(
        token,
        restaurant.id,
        locationToDeactivate.id,
      );
      setRestaurant((current) => {
        if (!current) {
          return current;
        }
        const next = {
          ...current,
          locations: current.locations.map((entry) => entry.id === nextLocation.id ? nextLocation : entry),
        };
        setPageSnapshot<RestaurantDetailSnapshot>(detailKey, { restaurant: next, orders });
        return next;
      });
      onToast(
        "Location deactivated",
        `${locationToDeactivate.branch_name} is now inactive.`,
        "success",
      );
      setLocationToDeactivate(null);
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to deactivate this location.";
      onToast("Deactivation failed", message, "error");
    }
  };

  const advanceOrderStatus = async (order: Order) => {
    const nextStatus = nextStatusMap[order.status];
    if (!nextStatus || role !== "OWNER") {
      return;
    }

    try {
      const updated = await api.updateOrderStatus(token, order.id, nextStatus);
      setOrders((current) => {
        const next = current.map((entry) => (entry.id === updated.id ? updated : entry));
        if (restaurant) {
          setPageSnapshot<RestaurantDetailSnapshot>(detailKey, { restaurant, orders: next });
        }
        return next;
      });
      // The global Orders list (OrdersPage) shows the same underlying order
      // data through different filters - it needs to know this is now stale.
      invalidatePageSnapshotsByPrefix(buildOrdersCacheKeyPrefix(scope));
      onToast(
        "Order updated",
        `${order.customer.full_name}'s order moved to ${nextStatus.replaceAll("_", " ")}.`,
        "success",
      );
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to update order status.";
      onToast("Status update failed", message, "error");
    }
  };

  const orderColumns: Array<TableColumn<Order>> = [
    {
      id: "order",
      header: "Order ID",
      render: (order) => (
        <>
          <strong>#{order.id.slice(0, 8)}</strong>
          <span>{order.items.length} items</span>
        </>
      ),
      hideOnMobile: true,
    },
    {
      id: "customer",
      header: "Customer",
      render: (order) => (
        <>
          <strong>{order.customer.full_name}</strong>
          <span>{order.customer.email}</span>
        </>
      ),
      mobileLabel: "Customer",
    },
    {
      id: "status",
      header: "Status",
      render: (order) => <StatusPill status={order.status} />,
      mobileLabel: "Status",
    },
    {
      id: "amount",
      header: "Amount",
      render: (order) => formatCurrency(order.total_amount),
      mobileLabel: "Amount",
      align: "right",
    },
    {
      id: "placed",
      header: "Placed",
      render: (order) => formatDate(order.placed_at),
      mobileLabel: "Placed",
    },
  ];

  if (
    role === "OWNER" &&
    assignedRestaurantId &&
    restaurantId !== assignedRestaurantId
  ) {
    return null;
  }

  if (isLoading) {
    return (
      <div className="page-stack">
        <div className="admin-surface">
          <div className="hint-text">Loading restaurant workspace...</div>
        </div>
      </div>
    );
  }

  if (!restaurant) {
    return (
      <div className="page-stack">
        <EmptyPanel
          title="Restaurant not found"
          description="The requested restaurant could not be loaded."
        />
      </div>
    );
  }

  return (
    <div className="page-stack">
      {isAdmin ? (
        <Breadcrumbs
          items={[
            { label: "Restaurants", path: "/restaurants" },
            { label: restaurant?.name ?? "Restaurant" },
          ]}
          onNavigate={onNavigate}
        />
      ) : null}
      <PageIntro
        eyebrow={isAdmin ? "Restaurant workspace" : "Assigned restaurant"}
        title={restaurant.name}
        description={
          isAdmin
            ? "Review the restaurant profile, settings, menu catalogue, and recent order activity in one place."
            : "Manage your restaurant details, live settings, menu catalogue, and recent order activity from one workspace."
        }
        actions={
          <button
            className="secondary-button"
            onClick={() => onNavigate(backPath)}
            type="button"
          >
            ← Back
          </button>
        }
      />

      <section className="admin-surface restaurant-detail-hero">
        <div className="restaurant-detail-hero__copy">
          <span className="eyebrow">Live overview</span>
          <h2>{restaurant.name}</h2>
          <p>
            {restaurant.cuisine_type} · {restaurant.city}, {restaurant.state}
          </p>
        </div>
        <div className="restaurant-detail-hero__metrics">
          <div className="restaurant-metric-card">
            <strong>{orders.length}</strong>
            <span>Orders tracked</span>
          </div>
          <div className="restaurant-metric-card">
            <strong>{formatCurrency(restaurant.minimum_order_amount)}</strong>
            <span>Minimum order</span>
          </div>
          <div className="restaurant-metric-card">
            <strong>{restaurant.is_open ? 'Open' : 'Closed'}</strong>
            <span>Current service state</span>
          </div>
        </div>
      </section>

      <nav className="segmented-tabs" aria-label="Restaurant sections">
        {sectionOptions.map((section) => {
          const Icon = section.icon;
          const isActive = activeSection === section.key;
          return (
            <button
              className={
                isActive
                  ? "segmented-tabs__item segmented-tabs__item--active"
                  : "segmented-tabs__item"
              }
              key={section.key}
              onClick={() => setActiveSection(section.key)}
              type="button"
            >
              <Icon size={16} strokeWidth={2.1} />
              <span>{section.label}</span>
            </button>
          );
        })}
      </nav>

      {restaurant.locations.length > 0 ? (
        <section className="admin-surface">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Active branch scope</span>
              <h2>{selectedLocation?.branch_name ?? "All restaurant locations"}</h2>
              <p className="hint-text">
                Switch the working branch to scope menu, orders, and generated combos.
              </p>
            </div>
            <select
              className="page-search page-search--select"
              onChange={(event) => setSelectedLocationId(event.target.value || null)}
              value={selectedLocationId ?? ""}
            >
              {restaurant.locations.map((location) => (
                <option key={location.id} value={location.id}>
                  {location.branch_name} · {location.city}
                </option>
              ))}
            </select>
          </div>
        </section>
      ) : null}

      {activeSection === "details" ? (
        <section className="admin-surface page-stack">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Restaurant details</span>
              <h2>Profile & ownership</h2>
              <p className="hint-text">
                Core restaurant identity, ownership, and lifecycle controls.
              </p>
            </div>
            <div className="table-actions">
              {isAdmin ? (
                <>
                  <button className="secondary-button" onClick={openEditModal} type="button">
                    Edit details
                  </button>
                  <button
                    className="primary-button"
                    disabled={isSettingsSubmitting}
                    onClick={() =>
                      void updateSettings({ is_active: !restaurant.is_active })
                    }
                    type="button"
                  >
                    {restaurant.is_active ? "Disable restaurant" : "Enable restaurant"}
                  </button>
                </>
              ) : (
                <button className="secondary-button" onClick={openEditModal} type="button">
                  Edit basic details
                </button>
              )}
            </div>
          </div>

          <div className="detail-grid">
            <div>
              <strong>Restaurant name</strong>
              <span>{restaurant.name}</span>
            </div>
            <div>
              <strong>Owner name</strong>
              <span>{restaurant.owner.full_name}</span>
            </div>
            <div>
              <strong>Owner email</strong>
              <span>{restaurant.owner.email}</span>
            </div>
            <div>
              <strong>Lifecycle status</strong>
              <span>
                <StatusPill status={restaurant.is_active ? "ACTIVE" : "INACTIVE"} />
              </span>
            </div>
            <div>
              <strong>Approval</strong>
              <span>
                <StatusPill status={restaurant.is_approved ? "APPROVED" : "PENDING"} />
              </span>
            </div>
            <div>
              <strong>Created date</strong>
              <span>{formatDate(restaurant.created_at)}</span>
            </div>
          </div>
        </section>
      ) : null}

      {activeSection === "settings" ? (
        <section className="admin-surface page-stack">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Operational controls</span>
              <h2>Settings</h2>
              <p className="hint-text">
                Update the live restaurant status and reserved operational settings.
              </p>
            </div>
          </div>

          <div className="settings-list">
            <button
              className="settings-row"
              disabled={isSettingsSubmitting}
              onClick={() => void updateSettings({ is_open: !restaurant.is_open })}
              type="button"
            >
              <div>
                <strong>Restaurant availability</strong>
                <span>
                  Decide whether customers can currently place orders from this restaurant.
                </span>
              </div>
              <span className={restaurant.is_open ? "toggle-pill toggle-pill--on" : "toggle-pill"}>
                {restaurant.is_open ? "Open" : "Closed"}
              </span>
            </button>

            <button
              className="settings-row"
              disabled={!isAdmin || isSettingsSubmitting}
              onClick={() =>
                isAdmin
                  ? void updateSettings({ is_active: !restaurant.is_active })
                  : undefined
              }
              type="button"
            >
              <div>
                <strong>Visibility & access</strong>
                <span>
                  Control whether the restaurant remains active in the platform catalogue.
                </span>
              </div>
              <span
                className={
                  restaurant.is_active ? "toggle-pill toggle-pill--on" : "toggle-pill"
                }
              >
                {restaurant.is_active ? "Visible" : "Disabled"}
              </span>
            </button>

            <div className="settings-row settings-row--static">
              <div>
                <strong>Future controls</strong>
                <span>
                  Delivery zones, payout settings, and escalation preferences can land here next.
                </span>
              </div>
              <StatusPill status="Planned" />
            </div>
          </div>
        </section>
      ) : null}

      {activeSection === "app_client" ? (
        <section className="admin-surface page-stack">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Mobile app</span>
              <h2>App client</h2>
              <p className="hint-text">
                {appClient
                  ? "Bundle IDs and app settings used by this restaurant's branded mobile app."
                  : "This restaurant has no app client yet. Save this form to create one."}
              </p>
            </div>
            {appClient ? <StatusPill status={appClient.status} /> : <StatusPill status="PENDING" />}
          </div>

          {appClientLoadError ? (
            <div className="page-stack">
              <p className="hint-text">{appClientLoadError}</p>
              <div>
                <button
                  className="secondary-button"
                  onClick={() => setAppClientLoadError(null)}
                  type="button"
                >
                  Retry
                </button>
              </div>
            </div>
          ) : !appClientForm ? (
            <p className="hint-text">Loading app client...</p>
          ) : (
            <form className="form-grid" onSubmit={saveAppClient}>
              <AppClientFields
                disabled={isAppClientSubmitting}
                errors={appClientErrors}
                onDerivedFieldChange={updateAppClientField}
                onFieldChange={(field, value) => {
                  setAppClientForm((current) => (current ? { ...current, [field]: value } : current));
                  setAppClientErrors((current) => ({ ...current, [field]: undefined }));
                }}
                values={appClientForm}
              />
              <div className="form-grid__wide modal-actions">
                <button
                  className="secondary-button"
                  disabled={isAppClientSubmitting}
                  onClick={() => {
                    setAppClientForm(toAppClientForm(appClient, restaurant.name));
                    setAppClientErrors({});
                  }}
                  type="button"
                >
                  Reset
                </button>
                <button className="primary-button" disabled={isAppClientSubmitting} type="submit">
                  {isAppClientSubmitting
                    ? "Saving..."
                    : appClient
                      ? "Save App Settings"
                      : "Create App Client"}
                </button>
              </div>
            </form>
          )}
        </section>
      ) : null}

      {activeSection === "offers" ? (
        <RestaurantOffersManager
          token={token}
          restaurant={restaurant}
          onToast={onToast}
        />
      ) : null}

      {activeSection === "locations" ? (
        <section className="admin-surface page-stack">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Branch operations</span>
              <h2>Locations</h2>
              <p className="hint-text">
                Manage addresses, delivery settings, estimated timing, and live branch status.
              </p>
            </div>
            <button className="primary-button" onClick={openCreateLocationModal} type="button">
              + Add location
            </button>
          </div>

          <div className="detail-grid">
            {restaurant.locations.map((location) => (
              <div key={location.id}>
                <strong>{location.branch_name}</strong>
                <span>{location.address_line_1}, {location.city}</span>
                <span>
                  {formatCurrency(location.delivery_fee)} delivery · Min {formatCurrency(location.minimum_order_amount)} · {location.estimated_delivery_time} min
                </span>
                <span className="status-stack">
                  <StatusPill status={location.is_active ? "ACTIVE" : "INACTIVE"} />
                  <StatusPill status={location.is_open ? "OPEN" : "CLOSED"} />
                </span>
                <div className="table-actions">
                  <button
                    className="secondary-button"
                    onClick={() =>
                      onNavigate(
                        `/admin/restaurants/${restaurant.id}/locations/${location.id}`,
                      )
                    }
                    type="button"
                  >
                    Open workspace
                  </button>
                  <button className="secondary-button" onClick={() => openEditLocationModal(location)} type="button">
                    Edit
                  </button>
                  <button
                    className="secondary-button"
                    onClick={() => requestDeactivateLocation(location)}
                    type="button"
                  >
                    Deactivate
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <ConfirmDialog
        open={locationToDeactivate !== null}
        eyebrow="Branch status"
        title={
          locationToDeactivate
            ? `Deactivate ${locationToDeactivate.branch_name}?`
            : "Deactivate location?"
        }
        description="The branch will be marked inactive and closed, and customers will no longer be able to place orders there."
        confirmLabel="Deactivate branch"
        onCancel={() => setLocationToDeactivate(null)}
        onConfirm={() => {
          void deactivateLocation();
        }}
        tone="danger"
      />

      {activeSection === "generated_combos" ? (
        <section className="admin-surface page-stack">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Restaurant-generated insights</span>
              <h2>Generated combos</h2>
              <p className="hint-text">
                Review auto-detected combos for this restaurant only, including included items,
                order strength, confidence, and active status.
              </p>
            </div>
          </div>

          <GeneratedCombosPage
            embedded
            onToast={onToast}
            restaurantId={restaurant.id}
            locationId={selectedLocationId}
            role={role}
            token={token}
          />
        </section>
      ) : null}

      {activeSection === "menu" ? (
        <section className="admin-surface page-stack">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Catalogue management</span>
              <h2>Menu items</h2>
              <p className="hint-text">
                Search, filter, add, update, or hide menu items for this restaurant.
              </p>
            </div>
          </div>
          <RestaurantMenuTable
            token={token}
            role={role}
            restaurant={restaurant}
            selectedLocationId={selectedLocationId}
            onNavigate={onNavigate}
            onToast={onToast}
          />
        </section>
      ) : null}

      {activeSection === "orders" ? (
        <section className="admin-surface page-stack">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Recent activity</span>
              <h2>Orders</h2>
              <p className="hint-text">
                Review recent order flow, totals, and status progression for this restaurant.
              </p>
            </div>
          </div>

          <DataToolbar
            actions={<span className="toolbar-meta">{filteredOrders.length} orders</span>}
            filters={
              <select
                className="page-search page-search--select"
                onChange={(event) => {
                  setOrderStatusFilter(event.target.value as typeof orderStatusFilter);
                  setOrderPage(1);
                }}
                value={orderStatusFilter}
              >
                <option value="ALL">All statuses</option>
                <option value="PLACED">Placed</option>
                <option value="ACCEPTED">Accepted</option>
                <option value="PREPARING">Preparing</option>
                <option value="OUT_FOR_DELIVERY">Out for delivery</option>
                <option value="DELIVERED">Delivered</option>
              </select>
            }
            onSearchChange={(value) => {
              setOrderQuery(value);
              setOrderPage(1);
            }}
            searchPlaceholder="Search by order id, customer, or payment ref..."
            searchValue={orderQuery}
          />

          <ResponsiveTable
            actions={
              role === "OWNER"
                ? [
                    {
                      id: "advance",
                      label: "Advance order",
                      icon: ArrowRight,
                      onClick: advanceOrderStatus,
                      hidden: (order) => !nextStatusMap[order.status],
                      tone: "success",
                    },
                  ]
                : [
                    {
                      id: "readonly",
                      label: "Read only",
                      icon: Eye,
                      onClick: () => undefined,
                      disabled: () => true,
                    },
                  ]
            }
            columns={orderColumns}
            emptyDescription="Try another search or status filter for this restaurant."
            emptyTitle="No orders match the current filters"
            keyExtractor={(order) => order.id}
            mobileStatus={(order) => <StatusPill status={order.status} />}
            mobileSubtitle={(order) => order.customer.full_name}
            mobileTitle={(order) => `#${order.id.slice(0, 8)}`}
            rows={orderPageItems}
          />
          <Pagination
            onPageChange={setOrderPage}
            onPageSizeChange={(value) => {
              setOrderPageSize(value);
              setOrderPage(1);
            }}
            page={currentOrderPage}
            pageSize={orderPageSize}
            totalItems={filteredOrders.length}
            totalPages={totalOrderPages}
          />
        </section>
      ) : null}

      {isEditOpen && editForm ? (
        <Modal onClose={closeEditModal}>
            <div className="panel__header modal-card__header">
              <div>
                <span className="eyebrow">Restaurant editor</span>
                <h2>Edit {restaurant.name}</h2>
                <p className="hint-text">
                  {isAdmin
                    ? "Update the restaurant profile without leaving this workspace."
                    : "Refresh the restaurant basics you manage day to day from the same workspace."}
                </p>
              </div>
              <button
                aria-label="Close edit restaurant form"
                className="modal-close"
                onClick={closeEditModal}
                type="button"
              >
                ×
              </button>
            </div>

            <form className="form-grid modal-card__body" onSubmit={saveRestaurant}>
              <label className="field form-grid__wide">
                <span>Restaurant Name</span>
                <input
                  required
                  value={editForm.name}
                  onChange={(event) =>
                    setEditForm((current) =>
                      current
                        ? {
                            ...current,
                            name: event.target.value,
                          }
                        : current,
                    )
                  }
                />
              </label>
              <label className="field">
                <span>Cuisine</span>
                <input
                  required
                  value={editForm.cuisine_type}
                  onChange={(event) =>
                    setEditForm((current) =>
                      current
                        ? {
                            ...current,
                            cuisine_type: event.target.value,
                          }
                        : current,
                    )
                  }
                />
              </label>
              <label className="field">
                <span>City</span>
                <input
                  required
                  value={editForm.city}
                  onChange={(event) =>
                    setEditForm((current) =>
                      current
                        ? {
                            ...current,
                            city: event.target.value,
                          }
                        : current,
                    )
                  }
                />
              </label>
              <label className="field form-grid__wide">
                <span>Address line 1</span>
                <input
                  required
                  value={editForm.address_line_1}
                  onChange={(event) =>
                    setEditForm((current) =>
                      current
                        ? {
                            ...current,
                            address_line_1: event.target.value,
                          }
                        : current,
                    )
                  }
                />
              </label>
              <label className="field">
                <span>State</span>
                <input
                  required
                  value={editForm.state}
                  onChange={(event) =>
                    setEditForm((current) =>
                      current
                        ? {
                            ...current,
                            state: event.target.value,
                          }
                        : current,
                    )
                  }
                />
              </label>
              <label className="field">
                <span>Country</span>
                <input
                  required
                  value={editForm.country}
                  onChange={(event) =>
                    setEditForm((current) =>
                      current
                        ? {
                            ...current,
                            country: event.target.value,
                          }
                        : current,
                    )
                  }
                />
              </label>
              <label className="field">
                <span>Postal code</span>
                <input
                  required
                  value={editForm.postal_code}
                  onChange={(event) =>
                    setEditForm((current) =>
                      current
                        ? {
                            ...current,
                            postal_code: event.target.value,
                          }
                        : current,
                    )
                  }
                />
              </label>
              <label className="field">
                <span>Phone number</span>
                <input
                  value={editForm.phone_number}
                  onChange={(event) =>
                    setEditForm((current) =>
                      current
                        ? {
                            ...current,
                            phone_number: event.target.value,
                          }
                        : current,
                    )
                  }
                />
              </label>
              {isAdmin ? (
                <>
                  <label className="field">
                    <span>Minimum order amount</span>
                    <input
                      min="0"
                      required
                      step="0.01"
                      type="number"
                      value={editForm.minimum_order_amount}
                      onChange={(event) =>
                        setEditForm((current) =>
                          current
                            ? {
                                ...current,
                                minimum_order_amount: event.target.value,
                              }
                            : current,
                        )
                      }
                    />
                  </label>
                  <label className="field">
                    <span>Delivery fee</span>
                    <input
                      min="0"
                      required
                      step="0.01"
                      type="number"
                      value={editForm.delivery_fee}
                      onChange={(event) =>
                        setEditForm((current) =>
                          current
                            ? {
                                ...current,
                                delivery_fee: event.target.value,
                              }
                            : current,
                        )
                      }
                    />
                  </label>
                </>
              ) : null}
              <label className="field form-grid__wide">
                <span>Description</span>
                <textarea
                  rows={4}
                  value={editForm.description}
                  onChange={(event) =>
                    setEditForm((current) =>
                      current
                        ? {
                            ...current,
                            description: event.target.value,
                          }
                        : current,
                    )
                  }
                />
              </label>
              <label className="field">
                <span>Logo image URL</span>
                <input
                  type="url"
                  value={editForm.logo_image_url}
                  onChange={(event) =>
                    setEditForm((current) =>
                      current
                        ? {
                            ...current,
                            logo_image_url: event.target.value,
                          }
                        : current,
                    )
                  }
                />
              </label>
              <label className="field">
                <span>Cover image URL</span>
                <input
                  type="url"
                  value={editForm.cover_image_url}
                  onChange={(event) =>
                    setEditForm((current) =>
                      current
                        ? {
                            ...current,
                            cover_image_url: event.target.value,
                          }
                        : current,
                    )
                  }
                />
              </label>
              <div className="field form-grid__wide field--inline">
                <Checkbox
                  checked={editForm.is_open}
                  label="Open for orders"
                  onChange={(checked) =>
                    setEditForm((current) =>
                      current
                        ? {
                            ...current,
                            is_open: checked,
                          }
                        : current,
                    )
                  }
                />
              </div>
              <div className="form-grid__wide modal-actions">
                <button className="secondary-button" onClick={closeEditModal} type="button">
                  Cancel
                </button>
                <button className="primary-button" disabled={isEditSubmitting} type="submit">
                  {isEditSubmitting ? "Saving..." : "Save Changes"}
                </button>
              </div>
            </form>
          </Modal>
      ) : null}

      {isLocationModalOpen ? (
        <Modal onClose={closeLocationModal}>
            <div className="panel__header modal-card__header">
              <div>
                <span className="eyebrow">Location editor</span>
                <h2>{editingLocationId ? "Edit branch" : "Add branch"}</h2>
                <p className="hint-text">
                  Configure branch-level address, delivery settings, timing, and live status.
                </p>
              </div>
              <button aria-label="Close branch form" className="modal-close" onClick={closeLocationModal} type="button">
                ×
              </button>
            </div>

            <form className="form-grid modal-card__body" onSubmit={submitLocation}>
              <label className="field">
                <span>Branch name</span>
                <input required value={locationForm.branch_name} onChange={(event) => setLocationForm((current) => ({...current, branch_name: event.target.value}))} />
              </label>
              <label className="field">
                <span>City</span>
                <input required value={locationForm.city} onChange={(event) => setLocationForm((current) => ({...current, city: event.target.value}))} />
              </label>
              <label className="field form-grid__wide">
                <span>Address line 1</span>
                <input required value={locationForm.address_line_1} onChange={(event) => setLocationForm((current) => ({...current, address_line_1: event.target.value}))} />
              </label>
              <label className="field">
                <span>State</span>
                <input required value={locationForm.state} onChange={(event) => setLocationForm((current) => ({...current, state: event.target.value}))} />
              </label>
              <label className="field">
                <span>Postal code</span>
                <input required value={locationForm.postal_code} onChange={(event) => setLocationForm((current) => ({...current, postal_code: event.target.value}))} />
              </label>
              <label className="field">
                <span>Phone number</span>
                <input value={locationForm.phone_number} onChange={(event) => setLocationForm((current) => ({...current, phone_number: event.target.value}))} />
              </label>
              <label className="field">
                <span>Delivery fee</span>
                <input min="0" required step="0.01" type="number" value={locationForm.delivery_fee} onChange={(event) => setLocationForm((current) => ({...current, delivery_fee: event.target.value}))} />
              </label>
              <label className="field">
                <span>Minimum order</span>
                <input min="0" required step="0.01" type="number" value={locationForm.minimum_order_amount} onChange={(event) => setLocationForm((current) => ({...current, minimum_order_amount: event.target.value}))} />
              </label>
              <label className="field">
                <span>ETA (minutes)</span>
                <input min="1" required step="1" type="number" value={locationForm.estimated_delivery_time} onChange={(event) => setLocationForm((current) => ({...current, estimated_delivery_time: event.target.value}))} />
              </label>
              <div className="field form-grid__wide field--inline">
                <Checkbox
                  checked={locationForm.is_open}
                  label="Open now"
                  onChange={(checked) => setLocationForm((current) => ({...current, is_open: checked}))}
                />
                <Checkbox
                  checked={locationForm.is_active}
                  label="Active"
                  onChange={(checked) => setLocationForm((current) => ({...current, is_active: checked}))}
                />
              </div>
              <div className="form-grid__wide modal-actions">
                <button className="secondary-button" onClick={closeLocationModal} type="button">
                  Cancel
                </button>
                <button className="primary-button" disabled={isLocationSubmitting} type="submit">
                  {isLocationSubmitting ? "Saving..." : editingLocationId ? "Save Branch" : "Create Branch"}
                </button>
              </div>
            </form>
          </Modal>
      ) : null}
    </div>
  );
}

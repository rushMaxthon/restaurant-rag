import {
  ArrowLeft,
  ArrowRight,
  Clock3,
  Eye,
  PencilLine,
  Plus,
  ReceiptText,
  Settings2,
  Store,
  ToggleLeft,
  ToggleRight,
  Trash2,
  Truck,
  UtensilsCrossed,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Checkbox } from "../components/common/Checkbox";
import { DataToolbar } from "../components/DataToolbar";
import { EmptyPanel } from "../components/EmptyPanel";
import { Breadcrumbs } from "../components/Breadcrumbs";
import { PageIntro } from "../components/PageIntro";
import { Pagination } from "../components/Pagination";
import { ResponsiveTable, type TableColumn } from "../components/ResponsiveTable";
import { RestaurantMenuTable } from "../components/RestaurantMenuTable";
import { StatusPill } from "../components/StatusPill";
import { ApiError, api, formatCurrency, formatDate } from "../services/api";
import { buildOrdersCacheKeyPrefix } from "./OrdersPage";
import { invalidateRestaurantDetailCache } from "./RestaurantDetailPage";
import { buildLocationsRestaurantKey } from "./LocationsPage";
import {
  getPageSnapshot,
  hasPageSnapshot,
  invalidatePageSnapshot,
  invalidatePageSnapshotsByPrefix,
  setPageSnapshot,
  tokenScope,
} from "../services/pageCache";
import {
  ORDER_FILTER_STATUSES,
  type LocationDayOfWeek,
  type LocationFulfillmentSlot,
  type Order,
  type OrderFulfillmentType,
  type OrderStatus,
  type RestaurantDetail,
  type RestaurantLocation,
  type UserRole,
} from "../types/app";

interface LocationDetailPageProps {
  token: string;
  role: UserRole;
  restaurantId: string;
  locationId: string;
  assignedRestaurantId: string | null;
  onNavigate: (path: string) => void;
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

type LocationSettingsForm = {
  branch_name: string;
  address_line_1: string;
  address_line_2: string;
  city: string;
  state: string;
  postal_code: string;
  phone_number: string;
  opening_time: string;
  closing_time: string;
};

type LocationGeneralSettingsForm = {
  is_open: boolean;
  is_active: boolean;
  delivery_enabled: boolean;
  pickup_enabled: boolean;
  google_pay_enabled: boolean;
  razorpay_enabled: boolean;
  card_payment_enabled: boolean;
  cash_on_delivery_enabled: boolean;
  future_order_enabled: boolean;
  delivery_fee: string;
  minimum_order_amount: string;
  estimated_delivery_time: string;
  estimated_pickup_time: string;
  max_future_days: string;
  slot_interval_minutes: string;
  temporary_closed_reason: string;
  preparation_time_minutes: string;
  service_radius_km: string;
};

type SlotFormState = {
  day_of_week: LocationDayOfWeek;
  fulfillment_type: OrderFulfillmentType;
  start_time: string;
  end_time: string;
  is_active: boolean;
};

type LocationTab =
  | "details"
  | "settings"
  | "slots"
  | "general_settings"
  | "menu"
  | "orders";

const nextStatusMap: Partial<Record<OrderStatus, OrderStatus>> = {
  PLACED: "ACCEPTED",
  ACCEPTED: "PREPARING",
  PREPARING: "OUT_FOR_DELIVERY",
  OUT_FOR_DELIVERY: "DELIVERED",
};

const dayOptions: LocationDayOfWeek[] = [
  "MONDAY",
  "TUESDAY",
  "WEDNESDAY",
  "THURSDAY",
  "FRIDAY",
  "SATURDAY",
  "SUNDAY",
];

function toTimeInputValue(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  return value.slice(0, 5);
}

function formatDayOfWeek(value: LocationDayOfWeek): string {
  return value.charAt(0) + value.slice(1).toLowerCase();
}

function formatSlotTime(value: string): string {
  return value.slice(0, 5);
}

function formatSlotTimeLabel(value: string): string {
  const [hoursText, minutesText] = value.slice(0, 5).split(":");
  const hours = Number(hoursText);
  const minutes = Number(minutesText);
  if (Number.isNaN(hours) || Number.isNaN(minutes)) {
    return value;
  }
  return new Intl.DateTimeFormat("en-IN", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(new Date(2000, 0, 1, hours, minutes));
}

function toLocationSettingsForm(location: RestaurantLocation): LocationSettingsForm {
  return {
    branch_name: location.branch_name,
    address_line_1: location.address_line_1,
    address_line_2: location.address_line_2 ?? "",
    city: location.city,
    state: location.state,
    postal_code: location.postal_code,
    phone_number: location.phone_number ?? "",
    opening_time: toTimeInputValue(location.opening_time),
    closing_time: toTimeInputValue(location.closing_time),
  };
}

function toGeneralSettingsForm(location: RestaurantLocation): LocationGeneralSettingsForm {
  return {
    is_open: location.is_open,
    is_active: location.is_active,
    delivery_enabled: location.delivery_enabled,
    pickup_enabled: location.pickup_enabled,
    google_pay_enabled: location.google_pay_enabled,
    razorpay_enabled: location.razorpay_enabled,
    card_payment_enabled: location.card_payment_enabled,
    cash_on_delivery_enabled: location.cash_on_delivery_enabled,
    future_order_enabled: location.future_order_enabled,
    delivery_fee: String(location.delivery_fee),
    minimum_order_amount: String(location.minimum_order_amount),
    estimated_delivery_time: String(location.estimated_delivery_time),
    estimated_pickup_time: String(location.estimated_pickup_time),
    max_future_days: String(location.max_future_days),
    slot_interval_minutes: String(location.slot_interval_minutes),
    temporary_closed_reason: location.temporary_closed_reason ?? "",
    preparation_time_minutes: location.preparation_time_minutes == null ? "" : String(location.preparation_time_minutes),
    service_radius_km: location.service_radius_km == null ? "" : String(location.service_radius_km),
  };
}

function emptySlotForm(): SlotFormState {
  return {
    day_of_week: "MONDAY",
    fulfillment_type: "DELIVERY",
    start_time: "10:30",
    end_time: "22:00",
    is_active: true,
  };
}

function emptySlotFormForType(fulfillmentType: OrderFulfillmentType): SlotFormState {
  return {
    ...emptySlotForm(),
    fulfillment_type: fulfillmentType,
  };
}

function toSlotForm(slot: LocationFulfillmentSlot): SlotFormState {
  return {
    day_of_week: slot.day_of_week,
    fulfillment_type: slot.fulfillment_type,
    start_time: formatSlotTime(slot.start_time),
    end_time: formatSlotTime(slot.end_time),
    is_active: slot.is_active,
  };
}

interface LocationDetailSnapshot {
  restaurant: RestaurantDetail;
  orders: Order[];
}

function buildLocationDetailKey(scope: string, restaurantId: string, locationId: string): string {
  return `location-detail:${scope}:${restaurantId}:${locationId}`;
}

export function LocationDetailPage({
  token,
  role,
  restaurantId,
  locationId,
  assignedRestaurantId,
  onNavigate,
  onToast,
}: LocationDetailPageProps) {
  const scope = tokenScope(token);
  const detailKey = buildLocationDetailKey(scope, restaurantId, locationId);
  const cachedDetail = getPageSnapshot<LocationDetailSnapshot>(detailKey);
  const cachedLocation = cachedDetail?.restaurant.locations.find(
    (entry) => entry.id === locationId,
  ) ?? null;

  const [restaurant, setRestaurant] = useState<RestaurantDetail | null>(
    () => cachedDetail?.restaurant ?? null,
  );
  const [location, setLocation] = useState<RestaurantLocation | null>(
    () => cachedLocation,
  );
  // Only true when this restaurant/location pair has never been fetched this
  // session - not on every mount, so revisiting it keeps showing its data
  // instead of a skeleton.
  const [isLoading, setIsLoading] = useState(() => !hasPageSnapshot(detailKey));
  const [activeTab, setActiveTab] = useState<LocationTab>("details");
  const [settingsForm, setSettingsForm] = useState<LocationSettingsForm | null>(
    () => (cachedLocation ? toLocationSettingsForm(cachedLocation) : null),
  );
  const [generalSettingsForm, setGeneralSettingsForm] = useState<LocationGeneralSettingsForm | null>(
    () => (cachedLocation ? toGeneralSettingsForm(cachedLocation) : null),
  );
  const [slots, setSlots] = useState<LocationFulfillmentSlot[]>(
    () => cachedLocation?.fulfillment_slots ?? [],
  );
  const [slotForm, setSlotForm] = useState<SlotFormState>(() => emptySlotFormForType("PICKUP"));
  const [slotView, setSlotView] = useState<OrderFulfillmentType>("PICKUP");
  const [editingSlotId, setEditingSlotId] = useState<string | null>(null);
  const [isSavingSettings, setIsSavingSettings] = useState(false);
  const [isSavingGeneralSettings, setIsSavingGeneralSettings] = useState(false);
  const [isSavingSlot, setIsSavingSlot] = useState(false);
  const [deletingSlotId, setDeletingSlotId] = useState<string | null>(null);
  const [orders, setOrders] = useState<Order[]>(() => cachedDetail?.orders ?? []);
  const [updatingOrderIds, setUpdatingOrderIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [orderQuery, setOrderQuery] = useState("");
  const [orderStatusFilter, setOrderStatusFilter] = useState<"ALL" | OrderStatus>(
    "ALL",
  );
  const [orderPage, setOrderPage] = useState(1);
  const [orderPageSize, setOrderPageSize] = useState(10);

  useEffect(() => {
    if (role === "OWNER" && assignedRestaurantId && restaurantId !== assignedRestaurantId) {
      onNavigate(`/admin/restaurants/${assignedRestaurantId}/locations`);
    }
  }, [assignedRestaurantId, onNavigate, restaurantId, role]);

  // `ordersForCache`: the orders array to pair with `detail` when writing the
  // cache. Taken explicitly rather than read from the `orders` state variable,
  // because `reloadLocationDetails` calls this WITHOUT having just fetched
  // orders - closing over `orders` there is fine (it reflects the current,
  // unrelated-to-this-mutation list), but `loadLocationWorkspace` DOES fetch a
  // fresh list in the same call, and reading state instead of that fresh
  // value would cache a render behind (React state setters don't apply
  // synchronously - the bug this comment is here to prevent).
  const hydrateLocation = (detail: RestaurantDetail, ordersForCache: Order[]) => {
    const matchedLocation = detail.locations.find((entry) => entry.id === locationId) ?? null;
    setRestaurant(detail);
    setLocation(matchedLocation);
    setSettingsForm(matchedLocation ? toLocationSettingsForm(matchedLocation) : null);
    setGeneralSettingsForm(matchedLocation ? toGeneralSettingsForm(matchedLocation) : null);
    setSlots(matchedLocation?.fulfillment_slots ?? []);
    setPageSnapshot<LocationDetailSnapshot>(detailKey, {
      restaurant: detail,
      orders: ordersForCache,
    });
  };

  const loadLocationWorkspace = async () => {
    const [detail, locationOrders] = await Promise.all([
      api.getRestaurant(token, restaurantId),
      api.getOrders(token, restaurantId, locationId),
    ]);
    hydrateLocation(detail, locationOrders);
    setOrders(locationOrders);
  };

  // Always hits the network - called after a slot/settings mutation to
  // resync with the server, so bypassing the cache is the point.
  const reloadLocationDetails = async () => {
    const detail = await api.getRestaurant(token, restaurantId);
    hydrateLocation(detail, orders);
  };

  useEffect(() => {
    if (role === "OWNER" && assignedRestaurantId && restaurantId !== assignedRestaurantId) {
      return;
    }

    const cached = getPageSnapshot<LocationDetailSnapshot>(detailKey);
    if (cached) {
      const matchedLocation =
        cached.restaurant.locations.find((entry) => entry.id === locationId) ?? null;
      setRestaurant(cached.restaurant);
      setLocation(matchedLocation);
      setSettingsForm(matchedLocation ? toLocationSettingsForm(matchedLocation) : null);
      setGeneralSettingsForm(matchedLocation ? toGeneralSettingsForm(matchedLocation) : null);
      setSlots(matchedLocation?.fulfillment_slots ?? []);
      setOrders(cached.orders);
      setIsLoading(false);
      return;
    }

    let active = true;
    setIsLoading(true);
    loadLocationWorkspace()
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        const message =
          error instanceof ApiError
            ? error.message
            : "Unable to load this location workspace.";
        onToast("Location unavailable", message, "error");
      })
      .finally(() => {
        if (active) {
          setIsLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [assignedRestaurantId, detailKey, locationId, onToast, restaurantId, role, token]);

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
      return matchesQuery && matchesStatus;
    });
  }, [orderQuery, orderStatusFilter, orders]);

  const totalOrderPages = Math.max(1, Math.ceil(filteredOrders.length / orderPageSize));
  const currentOrderPage = Math.min(orderPage, totalOrderPages);
  const orderPageItems = filteredOrders.slice(
    (currentOrderPage - 1) * orderPageSize,
    currentOrderPage * orderPageSize,
  );

  useEffect(() => {
    setOrderPage(1);
  }, [orderPageSize, orderQuery, orderStatusFilter]);

  const syncLocation = (updatedLocation: RestaurantLocation) => {
    setLocation(updatedLocation);
    setRestaurant((current) => {
      if (!current) {
        return current;
      }
      const next = {
        ...current,
        locations: current.locations.map((entry) =>
          entry.id === updatedLocation.id ? updatedLocation : entry,
        ),
      };
      // Genuine data change: this page's own cache is refreshed directly.
      // RestaurantDetailPage and LocationsPage show the same branch (name,
      // city, open/active state) - invalidated so neither shows the pre-edit
      // version on its next visit.
      setPageSnapshot<LocationDetailSnapshot>(detailKey, { restaurant: next, orders });
      invalidateRestaurantDetailCache(scope, restaurantId);
      invalidatePageSnapshot(buildLocationsRestaurantKey(scope, restaurantId));
      return next;
    });
    setSettingsForm(toLocationSettingsForm(updatedLocation));
    setGeneralSettingsForm(toGeneralSettingsForm(updatedLocation));
    setSlots(updatedLocation.fulfillment_slots ?? []);
  };

  const visibleSlots = useMemo(
    () =>
      [...slots]
        .filter((slot) => slot.fulfillment_type === slotView)
        .sort((left, right) => {
          const leftDay = dayOptions.indexOf(left.day_of_week);
          const rightDay = dayOptions.indexOf(right.day_of_week);
          if (leftDay !== rightDay) {
            return leftDay - rightDay;
          }
          return left.start_time.localeCompare(right.start_time);
        }),
    [slotView, slots],
  );

  const submitSettings = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!restaurant || !location || !settingsForm || isSavingSettings) {
      return;
    }

    setIsSavingSettings(true);
    try {
      const updated = await api.updateRestaurantLocation(token, restaurant.id, location.id, {
        branch_name: settingsForm.branch_name.trim(),
        address_line_1: settingsForm.address_line_1.trim(),
        address_line_2: settingsForm.address_line_2.trim() || null,
        city: settingsForm.city.trim(),
        state: settingsForm.state.trim(),
        postal_code: settingsForm.postal_code.trim(),
        phone_number: settingsForm.phone_number.trim() || null,
        opening_time: settingsForm.opening_time || null,
        closing_time: settingsForm.closing_time || null,
      });
      syncLocation(updated);
      onToast("Location updated", `${updated.branch_name} details were saved.`, "success");
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to update this location.";
      onToast("Location save failed", message, "error");
    } finally {
      setIsSavingSettings(false);
    }
  };

  const submitGeneralSettings = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!restaurant || !location || !generalSettingsForm || isSavingGeneralSettings) {
      return;
    }

    setIsSavingGeneralSettings(true);
    try {
      const updated = await api.updateRestaurantLocationGeneralSettings(
        token,
        restaurant.id,
        location.id,
        {
          is_open: generalSettingsForm.is_open,
          is_active: generalSettingsForm.is_active,
          delivery_enabled: generalSettingsForm.delivery_enabled,
          pickup_enabled: generalSettingsForm.pickup_enabled,
          google_pay_enabled: generalSettingsForm.google_pay_enabled,
          razorpay_enabled: generalSettingsForm.razorpay_enabled,
          card_payment_enabled: generalSettingsForm.card_payment_enabled,
          cash_on_delivery_enabled: generalSettingsForm.cash_on_delivery_enabled,
          future_order_enabled: generalSettingsForm.future_order_enabled,
          delivery_fee: Number(generalSettingsForm.delivery_fee),
          minimum_order_amount: Number(generalSettingsForm.minimum_order_amount),
          estimated_delivery_time: Number(generalSettingsForm.estimated_delivery_time),
          estimated_pickup_time: Number(generalSettingsForm.estimated_pickup_time),
          max_future_days: Number(generalSettingsForm.max_future_days),
          slot_interval_minutes: Number(generalSettingsForm.slot_interval_minutes),
          temporary_closed_reason: generalSettingsForm.temporary_closed_reason.trim() || null,
          preparation_time_minutes:
            generalSettingsForm.preparation_time_minutes.trim() === ""
              ? null
              : Number(generalSettingsForm.preparation_time_minutes),
          service_radius_km:
            generalSettingsForm.service_radius_km.trim() === ""
              ? null
              : Number(generalSettingsForm.service_radius_km),
        },
      );
      syncLocation(updated);
      onToast("General settings saved", `${updated.branch_name} fulfillment rules were updated.`, "success");
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to update fulfillment settings.";
      onToast("General settings failed", message, "error");
    } finally {
      setIsSavingGeneralSettings(false);
    }
  };

  const resetSlotEditor = () => {
    setEditingSlotId(null);
    setSlotForm(emptySlotFormForType(slotView));
  };

  const changeSlotView = (fulfillmentType: OrderFulfillmentType) => {
    setSlotView(fulfillmentType);
    setEditingSlotId(null);
    setSlotForm(emptySlotFormForType(fulfillmentType));
  };

  const submitSlot = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!restaurant || !location || isSavingSlot) {
      return;
    }
    if (!slotForm.start_time || !slotForm.end_time) {
      onToast("Slot validation", "Start and end time are required.", "error");
      return;
    }
    if (slotForm.start_time >= slotForm.end_time) {
      onToast("Slot validation", "Start time must be before end time.", "error");
      return;
    }

    setIsSavingSlot(true);
    try {
      if (editingSlotId) {
        await api.updateRestaurantLocationSlot(
          token,
          restaurant.id,
          location.id,
          editingSlotId,
          slotForm,
        );
        onToast("Slot updated", "The branch availability slot was updated.", "success");
      } else {
        await api.createRestaurantLocationSlot(
          token,
          restaurant.id,
          location.id,
          slotForm,
        );
        onToast("Slot created", "The new fulfillment slot is now live.", "success");
      }
      resetSlotEditor();
      await reloadLocationDetails();
    } catch (error: unknown) {
      const message =
        error instanceof ApiError ? error.message : "Unable to save this slot.";
      onToast("Slot save failed", message, "error");
    } finally {
      setIsSavingSlot(false);
    }
  };

  const editSlot = (slot: LocationFulfillmentSlot) => {
    setSlotView(slot.fulfillment_type);
    setEditingSlotId(slot.id);
    setSlotForm(toSlotForm(slot));
  };

  const toggleSlot = async (slot: LocationFulfillmentSlot) => {
    if (!restaurant || !location) {
      return;
    }
    try {
      await api.updateRestaurantLocationSlot(
        token,
        restaurant.id,
        location.id,
        slot.id,
        { is_active: !slot.is_active },
      );
      onToast(
        slot.is_active ? "Slot disabled" : "Slot enabled",
        `${formatDayOfWeek(slot.day_of_week)} ${slot.fulfillment_type.toLowerCase()} slot updated.`,
        "success",
      );
      await reloadLocationDetails();
    } catch (error: unknown) {
      const message =
        error instanceof ApiError ? error.message : "Unable to update slot state.";
      onToast("Slot update failed", message, "error");
    }
  };

  const deleteSlot = async (slot: LocationFulfillmentSlot) => {
    if (!restaurant || !location || deletingSlotId) {
      return;
    }
    setDeletingSlotId(slot.id);
    try {
      await api.deleteRestaurantLocationSlot(token, restaurant.id, location.id, slot.id);
      onToast("Slot deleted", "The fulfillment slot was removed.", "success");
      if (editingSlotId === slot.id) {
        resetSlotEditor();
      }
      await reloadLocationDetails();
    } catch (error: unknown) {
      const message =
        error instanceof ApiError ? error.message : "Unable to delete this slot.";
      onToast("Slot delete failed", message, "error");
    } finally {
      setDeletingSlotId(null);
    }
  };

  const advanceOrderStatus = async (order: Order) => {
    const nextStatus = nextStatusMap[order.status];
    if (!nextStatus || role !== "OWNER" || updatingOrderIds.has(order.id)) {
      return;
    }

    const previousOrder = order;
    setUpdatingOrderIds((current) => {
      const next = new Set(current);
      next.add(order.id);
      return next;
    });
    setOrders((current) =>
      current.map((entry) =>
        entry.id === order.id ? { ...entry, status: nextStatus } : entry,
      ),
    );

    try {
      const updated = await api.updateOrderStatus(token, order.id, nextStatus);
      setOrders((current) => {
        const next = current.map((entry) => (entry.id === updated.id ? updated : entry));
        if (restaurant) {
          setPageSnapshot<LocationDetailSnapshot>(detailKey, { restaurant, orders: next });
        }
        return next;
      });
      // The global Orders list and RestaurantDetailPage's own orders tab show
      // the same underlying order through different filters.
      invalidatePageSnapshotsByPrefix(buildOrdersCacheKeyPrefix(scope));
      invalidateRestaurantDetailCache(scope, restaurantId);
      onToast(
        "Order updated",
        `${order.customer.full_name}'s order moved to ${nextStatus.replaceAll("_", " ")}.`,
        "success",
      );
    } catch (error: unknown) {
      setOrders((current) =>
        current.map((entry) =>
          entry.id === previousOrder.id ? previousOrder : entry,
        ),
      );
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to update order status.";
      onToast("Status update failed", message, "error");
    } finally {
      setUpdatingOrderIds((current) => {
        const next = new Set(current);
        next.delete(order.id);
        return next;
      });
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
      id: "fulfillment",
      header: "Fulfillment",
      render: (order) => <StatusPill status={order.fulfillment_type} />,
      mobileLabel: "Fulfillment",
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
  const orderActions = [
    {
      id: "view",
      label: "View order",
      icon: Eye,
      onClick: (order: Order) => onNavigate(`/admin/orders/${order.id}`),
    },
    {
      id: "advance",
      label: "Advance status",
      icon: ArrowRight,
      onClick: (order: Order) => {
        void advanceOrderStatus(order);
      },
      hidden: (order: Order) => role !== "OWNER" || !nextStatusMap[order.status],
      disabled: (order: Order) => updatingOrderIds.has(order.id),
    },
  ];

  if (isLoading) {
    return (
      <div className="page-stack">
        <section className="admin-surface">
          <div className="hint-text">Loading location workspace...</div>
        </section>
      </div>
    );
  }

  if (!restaurant || !location || !settingsForm || !generalSettingsForm) {
    return (
      <div className="page-stack">
        <EmptyPanel
          title="Location not found"
          description="The requested branch could not be loaded for this restaurant."
        />
      </div>
    );
  }

  return (
    <div className="page-stack">
      <Breadcrumbs
        items={[
          role === "OWNER"
            ? { label: "My Restaurant", path: `/admin/restaurants/${restaurantId}/locations` }
            : { label: "Restaurants", path: "/restaurants" },
          ...(role === "OWNER"
            ? []
            : [{ label: restaurant.name, path: `/admin/restaurants/${restaurantId}/locations` }]),
          { label: location.branch_name },
        ]}
        onNavigate={onNavigate}
      />
      <PageIntro
        eyebrow="Branch workspace"
        title={location.branch_name}
        description={`Manage branch settings, slots, menu items, and orders for ${restaurant.name}.`}
        actions={
          <button
            className="secondary-button"
            onClick={() => onNavigate(`/admin/restaurants/${restaurant.id}/locations`)}
            type="button"
          >
            <ArrowLeft size={16} strokeWidth={2.1} />
            <span>Back to locations</span>
          </button>
        }
      />

      <section className="admin-surface restaurant-detail-hero">
        <div className="restaurant-detail-hero__copy">
          <span className="eyebrow">{restaurant.name}</span>
          <h2>{location.branch_name}</h2>
          <p>
            {location.address_line_1}, {location.city}, {location.state}
          </p>
        </div>
        <div className="restaurant-detail-hero__metrics">
          <div className="restaurant-metric-card">
            <strong>{location.estimated_delivery_time} min</strong>
            <span>Delivery ETA</span>
          </div>
          <div className="restaurant-metric-card">
            <strong>{location.estimated_pickup_time} min</strong>
            <span>Pickup ETA</span>
          </div>
          <div className="restaurant-metric-card">
            <strong>{location.is_open ? "Open" : "Closed"}</strong>
            <span>{location.is_active ? "Active branch" : "Inactive branch"}</span>
          </div>
        </div>
      </section>

      <nav className="segmented-tabs" aria-label="Location detail tabs">
        {[
          { key: "details", label: "Details", icon: Store },
          { key: "settings", label: "Settings", icon: Settings2 },
          { key: "slots", label: "Slots", icon: Clock3 },
          { key: "general_settings", label: "General Settings", icon: Truck },
          { key: "menu", label: "Menu Items", icon: UtensilsCrossed },
          { key: "orders", label: "Orders", icon: ReceiptText },
        ].map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.key;
          return (
            <button
              className={
                isActive
                  ? "segmented-tabs__item segmented-tabs__item--active"
                  : "segmented-tabs__item"
              }
              key={tab.key}
              onClick={() => setActiveTab(tab.key as LocationTab)}
              type="button"
            >
              <Icon size={16} strokeWidth={2.1} />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </nav>

      {activeTab === "details" ? (
        <section className="admin-surface page-stack">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Branch profile</span>
              <h2>Details</h2>
              <p className="hint-text">
                Read-only branch summary for operations, support, and audit visibility.
              </p>
            </div>
          </div>
          <div className="detail-grid">
            <div>
              <strong>Branch name</strong>
              <span>{location.branch_name}</span>
            </div>
            <div>
              <strong>Restaurant</strong>
              <span>{restaurant.name}</span>
            </div>
            <div>
              <strong>Address</strong>
              <span>
                {[location.address_line_1, location.address_line_2, location.city, location.state, location.postal_code]
                  .filter(Boolean)
                  .join(", ")}
              </span>
            </div>
            <div>
              <strong>Phone</strong>
              <span>{location.phone_number ?? "Not set"}</span>
            </div>
            <div>
              <strong>Delivery fee</strong>
              <span>{formatCurrency(location.delivery_fee)}</span>
            </div>
            <div>
              <strong>Minimum order</strong>
              <span>{formatCurrency(location.minimum_order_amount)}</span>
            </div>
            <div>
              <strong>Delivery</strong>
              <span className="status-stack">
                <StatusPill status={location.delivery_enabled ? "ENABLED" : "DISABLED"} />
                <StatusPill status={location.delivery_available_now ? "AVAILABLE" : "CLOSED"} />
              </span>
            </div>
            <div>
              <strong>Pickup</strong>
              <span className="status-stack">
                <StatusPill status={location.pickup_enabled ? "ENABLED" : "DISABLED"} />
                <StatusPill status={location.pickup_available_now ? "AVAILABLE" : "CLOSED"} />
              </span>
            </div>
            <div>
              <strong>Estimated delivery time</strong>
              <span>{location.estimated_delivery_time} minutes</span>
            </div>
            <div>
              <strong>Estimated pickup time</strong>
              <span>{location.estimated_pickup_time} minutes</span>
            </div>
            <div>
              <strong>Hours</strong>
              <span>
                {location.opening_time && location.closing_time
                  ? `${location.opening_time.slice(0, 5)} - ${location.closing_time.slice(0, 5)}`
                  : "Not set"}
              </span>
            </div>
            <div>
              <strong>Service status</strong>
              <span className="status-stack">
                <StatusPill status={location.is_open ? "OPEN" : "CLOSED"} />
                <StatusPill status={location.is_active ? "ACTIVE" : "INACTIVE"} />
              </span>
            </div>
            <div>
              <strong>Closed reason</strong>
              <span>{location.temporary_closed_reason ?? "Not set"}</span>
            </div>
            <div>
              <strong>Preparation time</strong>
              <span>
                {location.preparation_time_minutes == null
                  ? "Not set"
                  : `${location.preparation_time_minutes} min`}
              </span>
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === "settings" ? (
        <section className="admin-surface page-stack">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Branch profile</span>
              <h2>Settings</h2>
              <p className="hint-text">
                Edit branch identity, address, phone, and legacy display hours.
              </p>
            </div>
          </div>
          <form className="form-grid" onSubmit={submitSettings}>
            <label className="field">
              <span>Branch name</span>
              <input
                required
                value={settingsForm.branch_name}
                onChange={(event) =>
                  setSettingsForm((current) =>
                    current ? { ...current, branch_name: event.target.value } : current,
                  )
                }
              />
            </label>
            <label className="field">
              <span>City</span>
              <input
                required
                value={settingsForm.city}
                onChange={(event) =>
                  setSettingsForm((current) =>
                    current ? { ...current, city: event.target.value } : current,
                  )
                }
              />
            </label>
            <label className="field form-grid__wide">
              <span>Address line 1</span>
              <input
                required
                value={settingsForm.address_line_1}
                onChange={(event) =>
                  setSettingsForm((current) =>
                    current ? { ...current, address_line_1: event.target.value } : current,
                  )
                }
              />
            </label>
            <label className="field form-grid__wide">
              <span>Address line 2</span>
              <input
                value={settingsForm.address_line_2}
                onChange={(event) =>
                  setSettingsForm((current) =>
                    current ? { ...current, address_line_2: event.target.value } : current,
                  )
                }
              />
            </label>
            <label className="field">
              <span>State</span>
              <input
                required
                value={settingsForm.state}
                onChange={(event) =>
                  setSettingsForm((current) =>
                    current ? { ...current, state: event.target.value } : current,
                  )
                }
              />
            </label>
            <label className="field">
              <span>Postal code</span>
              <input
                required
                value={settingsForm.postal_code}
                onChange={(event) =>
                  setSettingsForm((current) =>
                    current ? { ...current, postal_code: event.target.value } : current,
                  )
                }
              />
            </label>
            <label className="field">
              <span>Phone</span>
              <input
                value={settingsForm.phone_number}
                onChange={(event) =>
                  setSettingsForm((current) =>
                    current ? { ...current, phone_number: event.target.value } : current,
                  )
                }
              />
            </label>
            <label className="field">
              <span>Opening time</span>
              <input
                type="time"
                value={settingsForm.opening_time}
                onChange={(event) =>
                  setSettingsForm((current) =>
                    current ? { ...current, opening_time: event.target.value } : current,
                  )
                }
              />
            </label>
            <label className="field">
              <span>Closing time</span>
              <input
                type="time"
                value={settingsForm.closing_time}
                onChange={(event) =>
                  setSettingsForm((current) =>
                    current ? { ...current, closing_time: event.target.value } : current,
                  )
                }
              />
            </label>
            <div className="form-grid__wide modal-actions">
              <button
                className="secondary-button"
                onClick={() => setSettingsForm(toLocationSettingsForm(location))}
                type="button"
              >
                Reset
              </button>
              <button
                className="primary-button"
                disabled={isSavingSettings}
                type="submit"
              >
                {isSavingSettings ? "Saving..." : "Save settings"}
              </button>
            </div>
          </form>
        </section>
      ) : null}

      {activeTab === "slots" ? (
        <section className="admin-surface page-stack">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Weekly availability</span>
              <h2>Slots</h2>
              <p className="hint-text">
                Create separate pickup and delivery time windows for each weekday.
              </p>
            </div>
          </div>
          <div className="slot-mode-tabs" role="tablist" aria-label="Fulfillment slots">
            {[
              { value: "PICKUP" as const, label: "Pickup" },
              { value: "DELIVERY" as const, label: "Delivery" },
            ].map((option) => (
              <button
                aria-selected={slotView === option.value}
                className={
                  slotView === option.value
                    ? "slot-mode-tabs__item slot-mode-tabs__item--active"
                    : "slot-mode-tabs__item"
                }
                key={option.value}
                onClick={() => changeSlotView(option.value)}
                role="tab"
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>

          <form className="slot-form-card" onSubmit={submitSlot}>
            <label className="field slot-form-card__field">
              <span>Day</span>
              <select
                value={slotForm.day_of_week}
                onChange={(event) =>
                  setSlotForm((current) => ({
                    ...current,
                    day_of_week: event.target.value as LocationDayOfWeek,
                  }))
                }
              >
                {dayOptions.map((day) => (
                  <option key={day} value={day}>
                    {formatDayOfWeek(day)}
                  </option>
                ))}
              </select>
            </label>
            <label className="field slot-form-card__field">
              <span>Start time</span>
              <input
                required
                type="time"
                value={slotForm.start_time}
                onChange={(event) =>
                  setSlotForm((current) => ({ ...current, start_time: event.target.value }))
                }
              />
            </label>
            <label className="field slot-form-card__field">
              <span>End time</span>
              <input
                required
                type="time"
                value={slotForm.end_time}
                onChange={(event) =>
                  setSlotForm((current) => ({ ...current, end_time: event.target.value }))
                }
              />
            </label>
            <div className="field slot-form-card__field slot-form-card__toggle">
              <span>Status</span>
              <Checkbox
                checked={slotForm.is_active}
                className="slot-form-card__checkbox"
                label="Active"
                onChange={(checked) =>
                  setSlotForm((current) => ({ ...current, is_active: checked }))
                }
                size="sm"
                variant="ghost"
              />
            </div>
            <div className="slot-form-card__actions">
              {editingSlotId ? (
                <button className="secondary-button" onClick={resetSlotEditor} type="button">
                  Cancel
                </button>
              ) : null}
              <button className="primary-button slot-form-card__submit" disabled={isSavingSlot} type="submit">
                <Plus size={16} strokeWidth={2.1} />
                <span>
                  {isSavingSlot
                    ? "Saving..."
                    : editingSlotId
                      ? "Update"
                      : "Add"}
                </span>
              </button>
            </div>
          </form>

          {visibleSlots.length === 0 ? (
            <EmptyPanel
              title={`No ${slotView === "DELIVERY" ? "delivery" : "pickup"} slots yet`}
              description={`Add ${slotView === "DELIVERY" ? "delivery" : "pickup"} windows so checkout can validate branch availability correctly.`}
            />
          ) : (
            <div className="table-container slot-table">
              <div className="table-scroll">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Day</th>
                      <th>Time</th>
                      <th>Status</th>
                      <th className="admin-table__actions-head">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleSlots.map((slot) => (
                      <tr className="admin-table__row" key={slot.id}>
                        <td>
                          <div className="admin-table__cell-content">
                            <strong>{formatDayOfWeek(slot.day_of_week)}</strong>
                          </div>
                        </td>
                        <td>
                          <div className="admin-table__cell-content">
                            <strong>
                              {formatSlotTimeLabel(slot.start_time)} - {formatSlotTimeLabel(slot.end_time)}
                            </strong>
                          </div>
                        </td>
                        <td>
                          <div className="status-stack">
                            <StatusPill status={slot.is_active ? "ACTIVE" : "DISABLED"} />
                          </div>
                        </td>
                        <td className="admin-table__actions-cell">
                          <div className="table-actions">
                            <button
                              aria-label={`Edit ${formatDayOfWeek(slot.day_of_week)} slot`}
                              className="table-icon-button"
                              onClick={() => editSlot(slot)}
                              type="button"
                            >
                              <PencilLine size={15} strokeWidth={2.1} />
                            </button>
                            <button
                              aria-label={slot.is_active ? "Disable slot" : "Enable slot"}
                              className={
                                slot.is_active
                                  ? "table-icon-button"
                                  : "table-icon-button table-icon-button--success"
                              }
                              onClick={() => void toggleSlot(slot)}
                              type="button"
                            >
                              {slot.is_active ? (
                                <ToggleRight size={16} strokeWidth={2.1} />
                              ) : (
                                <ToggleLeft size={16} strokeWidth={2.1} />
                              )}
                            </button>
                            <button
                              aria-label={`Delete ${formatDayOfWeek(slot.day_of_week)} slot`}
                              className="table-icon-button table-icon-button--danger"
                              disabled={deletingSlotId === slot.id}
                              onClick={() => void deleteSlot(slot)}
                              type="button"
                            >
                              <Trash2 size={15} strokeWidth={2.1} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      ) : null}

      {activeTab === "general_settings" ? (
        <section className="admin-surface page-stack">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Fulfillment controls</span>
              <h2>General Settings</h2>
              <p className="hint-text">
                Manage pickup, delivery, fees, minimum order, ETAs, and temporary closure controls.
              </p>
            </div>
          </div>
          <form className="form-grid" onSubmit={submitGeneralSettings}>
            <div className="field form-grid__wide field--inline">
              <Checkbox
                checked={generalSettingsForm.is_open}
                label="Location open"
                onChange={(checked) =>
                  setGeneralSettingsForm((current) =>
                    current ? { ...current, is_open: checked } : current,
                  )
                }
              />
              <Checkbox
                checked={generalSettingsForm.is_active}
                label="Location active"
                onChange={(checked) =>
                  setGeneralSettingsForm((current) =>
                    current ? { ...current, is_active: checked } : current,
                  )
                }
              />
              <Checkbox
                checked={generalSettingsForm.delivery_enabled}
                label="Delivery enabled"
                onChange={(checked) =>
                  setGeneralSettingsForm((current) =>
                    current ? { ...current, delivery_enabled: checked } : current,
                  )
                }
              />
              <Checkbox
                checked={generalSettingsForm.pickup_enabled}
                label="Pickup enabled"
                onChange={(checked) =>
                  setGeneralSettingsForm((current) =>
                    current ? { ...current, pickup_enabled: checked } : current,
                  )
                }
              />
              <Checkbox
                checked={generalSettingsForm.future_order_enabled}
                label="Future order enabled"
                onChange={(checked) =>
                  setGeneralSettingsForm((current) =>
                    current ? { ...current, future_order_enabled: checked } : current,
                  )
                }
              />
            </div>
            {/* Only Card (Stripe) and Cash on Delivery are settled by the
                platform. Google Pay and Razorpay have no gateway behind them:
                the backend rejects those methods and the app never offers
                them, so enabling one here would be a silent no-op. The
                toggles stay visible but disabled rather than being deleted,
                so the column values remain legible and re-enabling them is a
                one-line change once a provider exists. */}
            <div className="field form-grid__wide field--inline">
              <Checkbox
                checked={generalSettingsForm.card_payment_enabled}
                label="Card payment enabled (Stripe)"
                onChange={(checked) =>
                  setGeneralSettingsForm((current) =>
                    current ? { ...current, card_payment_enabled: checked } : current,
                  )
                }
              />
              <Checkbox
                checked={generalSettingsForm.cash_on_delivery_enabled}
                label="Cash on delivery enabled"
                onChange={(checked) =>
                  setGeneralSettingsForm((current) =>
                    current ? { ...current, cash_on_delivery_enabled: checked } : current,
                  )
                }
              />
              <Checkbox
                checked={generalSettingsForm.google_pay_enabled}
                disabled
                label="Google Pay (not available)"
                onChange={() => undefined}
              />
              <Checkbox
                checked={generalSettingsForm.razorpay_enabled}
                disabled
                label="Razorpay (not available)"
                onChange={() => undefined}
              />
            </div>
            <p className="field form-grid__wide hint-text">
              Customers can pay by card (Stripe) or cash on delivery. Google Pay
              and Razorpay are not supported yet — their saved values are shown
              for reference only and are ignored at checkout.
            </p>
            <label className="field">
              <span>Delivery fee</span>
              <input
                min="0"
                required
                step="0.01"
                type="number"
                value={generalSettingsForm.delivery_fee}
                onChange={(event) =>
                  setGeneralSettingsForm((current) =>
                    current ? { ...current, delivery_fee: event.target.value } : current,
                  )
                }
              />
            </label>
            <label className="field">
              <span>Minimum order</span>
              <input
                min="0"
                required
                step="0.01"
                type="number"
                value={generalSettingsForm.minimum_order_amount}
                onChange={(event) =>
                  setGeneralSettingsForm((current) =>
                    current ? { ...current, minimum_order_amount: event.target.value } : current,
                  )
                }
              />
            </label>
            <label className="field">
              <span>Estimated delivery time</span>
              <input
                min="1"
                required
                step="1"
                type="number"
                value={generalSettingsForm.estimated_delivery_time}
                onChange={(event) =>
                  setGeneralSettingsForm((current) =>
                    current ? { ...current, estimated_delivery_time: event.target.value } : current,
                  )
                }
              />
            </label>
            <label className="field">
              <span>Estimated pickup time</span>
              <input
                min="1"
                required
                step="1"
                type="number"
                value={generalSettingsForm.estimated_pickup_time}
                onChange={(event) =>
                  setGeneralSettingsForm((current) =>
                    current ? { ...current, estimated_pickup_time: event.target.value } : current,
                  )
                }
              />
            </label>
            <label className="field">
              <span>Max future days</span>
              <input
                min="1"
                required
                step="1"
                type="number"
                value={generalSettingsForm.max_future_days}
                onChange={(event) =>
                  setGeneralSettingsForm((current) =>
                    current ? { ...current, max_future_days: event.target.value } : current,
                  )
                }
              />
            </label>
            <label className="field">
              <span>Slot interval</span>
              <select
                value={generalSettingsForm.slot_interval_minutes}
                onChange={(event) =>
                  setGeneralSettingsForm((current) =>
                    current ? { ...current, slot_interval_minutes: event.target.value } : current,
                  )
                }
              >
                <option value="15">15 mins</option>
                <option value="30">30 mins</option>
              </select>
            </label>
            <label className="field form-grid__wide">
              <span>Temporary closed reason</span>
              <input
                value={generalSettingsForm.temporary_closed_reason}
                onChange={(event) =>
                  setGeneralSettingsForm((current) =>
                    current
                      ? { ...current, temporary_closed_reason: event.target.value }
                      : current,
                  )
                }
              />
            </label>
            <label className="field">
              <span>Preparation time</span>
              <input
                min="0"
                step="1"
                type="number"
                value={generalSettingsForm.preparation_time_minutes}
                onChange={(event) =>
                  setGeneralSettingsForm((current) =>
                    current
                      ? { ...current, preparation_time_minutes: event.target.value }
                      : current,
                  )
                }
              />
            </label>
            <label className="field">
              <span>Service radius (km)</span>
              <input
                min="0"
                step="0.1"
                type="number"
                value={generalSettingsForm.service_radius_km}
                onChange={(event) =>
                  setGeneralSettingsForm((current) =>
                    current ? { ...current, service_radius_km: event.target.value } : current,
                  )
                }
              />
            </label>
            <div className="form-grid__wide modal-actions">
              <button
                className="secondary-button"
                onClick={() => setGeneralSettingsForm(toGeneralSettingsForm(location))}
                type="button"
              >
                Reset
              </button>
              <button
                className="primary-button"
                disabled={isSavingGeneralSettings}
                type="submit"
              >
                {isSavingGeneralSettings ? "Saving..." : "Save general settings"}
              </button>
            </div>
          </form>
        </section>
      ) : null}

      {activeTab === "menu" ? (
        <section className="admin-surface page-stack">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Location catalogue</span>
              <h2>Menu items</h2>
              <p className="hint-text">
                This table is scoped to {location.branch_name} only, including launch and bestseller metadata.
              </p>
            </div>
          </div>
          <RestaurantMenuTable
            token={token}
            role={role}
            restaurant={restaurant}
            selectedLocationId={location.id}
            onNavigate={onNavigate}
            onToast={onToast}
          />
        </section>
      ) : null}

      {activeTab === "orders" ? (
        <section className="admin-surface page-stack">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Branch activity</span>
              <h2>Orders</h2>
              <p className="hint-text">
                Review only the orders placed against {location.branch_name}.
              </p>
            </div>
          </div>
          <DataToolbar
            actions={<span className="toolbar-meta">{filteredOrders.length} orders</span>}
            filters={
              <select
                className="page-search page-search--select"
                onChange={(event) =>
                  setOrderStatusFilter(event.target.value as typeof orderStatusFilter)
                }
                value={orderStatusFilter}
              >
                <option value="ALL">All statuses</option>
                {/* Driven by the shared list rather than `nextStatusMap`, which
                    only knows the advanceable statuses and so silently omitted
                    DELIVERED, PAYMENT_PENDING and CANCELLED. */}
                {ORDER_FILTER_STATUSES.map((statusValue) => (
                  <option key={statusValue} value={statusValue}>
                    {statusValue.replaceAll("_", " ")}
                  </option>
                ))}
              </select>
            }
            onSearchChange={setOrderQuery}
            searchPlaceholder="Search orders or customers"
            searchValue={orderQuery}
          />

          <ResponsiveTable
            actions={orderActions}
            columns={orderColumns}
            emptyDescription={`No orders have been placed against ${location.branch_name} yet.`}
            emptyTitle="No branch orders yet"
            keyExtractor={(order) => order.id}
            mobileStatus={(order) => <StatusPill status={order.status} />}
            mobileSubtitle={(order) => `${order.customer.full_name} • ${order.fulfillment_type}`}
            mobileTitle={(order) => `#${order.id.slice(0, 8)}`}
            rows={orderPageItems}
          />

          <Pagination
            onPageChange={setOrderPage}
            onPageSizeChange={setOrderPageSize}
            page={currentOrderPage}
            pageSize={orderPageSize}
            totalPages={totalOrderPages}
            totalItems={filteredOrders.length}
          />
        </section>
      ) : null}
    </div>
  );
}

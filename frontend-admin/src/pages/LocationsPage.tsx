import {
  Ban,
  CheckCircle2,
  DoorClosed,
  DoorOpen,
  Eye,
  Pencil,
  PlusCircle,
  Power,
  Store,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Checkbox } from "../components/common/Checkbox";
import { DataToolbar } from "../components/DataToolbar";
import { StatTiles, type StatTileItem } from "../components/StatTiles";
import { pluralize } from "../services/format";
import { EmptyPanel } from "../components/EmptyPanel";
import { PageIntro } from "../components/PageIntro";
import { Pagination } from "../components/Pagination";
import { ResponsiveTable, type TableColumn } from "../components/ResponsiveTable";
import { StatusPill } from "../components/StatusPill";
import { ApiError, api, formatCurrency, formatDate } from "../services/api";
import type { Restaurant, RestaurantDetail, RestaurantLocation, UserRole } from "../types/app";

interface LocationsPageProps {
  token: string;
  role: UserRole;
  assignedRestaurantId: string | null;
  scopedRestaurantId?: string | null;
  onNavigate: (path: string) => void;
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

type LocationFormState = {
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
  opening_time: string;
  closing_time: string;
  is_open: boolean;
  is_active: boolean;
};

const emptyLocationForm: LocationFormState = {
  branch_name: "",
  address_line_1: "",
  address_line_2: "",
  city: "",
  state: "",
  postal_code: "",
  phone_number: "",
  delivery_fee: "0",
  minimum_order_amount: "0",
  estimated_delivery_time: "30",
  opening_time: "",
  closing_time: "",
  is_open: false,
  is_active: true,
};

function toTimeInputValue(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  return value.slice(0, 5);
}

function toLocationForm(location?: RestaurantLocation | null): LocationFormState {
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
    opening_time: toTimeInputValue(location?.opening_time),
    closing_time: toTimeInputValue(location?.closing_time),
    is_open: location?.is_open ?? false,
    is_active: location?.is_active ?? true,
  };
}

export function LocationsPage({
  token,
  role,
  assignedRestaurantId,
  scopedRestaurantId = null,
  onNavigate,
  onToast,
}: LocationsPageProps) {
  const isAdmin = role === "ADMIN";
  const isScopedToRestaurant = scopedRestaurantId !== null;
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [selectedRestaurantId, setSelectedRestaurantId] = useState<string | null>(
    scopedRestaurantId ?? (role === "OWNER" ? assignedRestaurantId : null),
  );
  const [restaurant, setRestaurant] = useState<RestaurantDetail | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<
    "ALL" | "OPEN" | "CLOSED" | "ACTIVE" | "INACTIVE"
  >("ALL");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [busyLocationId, setBusyLocationId] = useState<string | null>(null);
  const [isLocationModalOpen, setIsLocationModalOpen] = useState(false);
  const [editingLocationId, setEditingLocationId] = useState<string | null>(null);
  const [locationForm, setLocationForm] = useState<LocationFormState>(emptyLocationForm);
  const [isLocationSubmitting, setIsLocationSubmitting] = useState(false);

  useEffect(() => {
    if (scopedRestaurantId) {
      setSelectedRestaurantId(scopedRestaurantId);
      return;
    }

    if (!isAdmin) {
      setSelectedRestaurantId(assignedRestaurantId);
      return;
    }

    let active = true;
    api
      .getAdminRestaurants(token)
      .then((rows) => {
        if (!active) {
          return;
        }
        setRestaurants(rows);
        setSelectedRestaurantId((current) => current ?? rows[0]?.id ?? null);
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        const message =
          error instanceof ApiError
            ? error.message
            : "Unable to load restaurants for the locations workspace.";
        onToast("Restaurants unavailable", message, "error");
      });

    return () => {
      active = false;
    };
  }, [assignedRestaurantId, isAdmin, onToast, scopedRestaurantId, token]);

  useEffect(() => {
    if (!selectedRestaurantId) {
      setRestaurant(null);
      setIsLoading(false);
      return;
    }

    let active = true;
    setIsLoading(true);
    api
      .getRestaurant(token, selectedRestaurantId)
      .then((detail) => {
        if (!active) {
          return;
        }
        setRestaurant(detail);
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        const message =
          error instanceof ApiError
            ? error.message
            : "Unable to load locations for this restaurant.";
        setRestaurant(null);
        onToast("Locations unavailable", message, "error");
      })
      .finally(() => {
        if (active) {
          setIsLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [onToast, selectedRestaurantId, token]);

  const locationTiles = useMemo<
    Array<StatTileItem<"ALL" | "OPEN" | "CLOSED" | "ACTIVE" | "INACTIVE">>
  >(() => {
    const branches = restaurant?.locations ?? [];
    const countBy = (predicate: (location: (typeof branches)[number]) => boolean) =>
      branches.filter(predicate).length;
    return [
      { key: "ALL", label: "All branches", icon: Store, value: branches.length, hint: "For this restaurant" },
      { key: "OPEN", label: "Open now", icon: DoorOpen, value: countBy((l) => l.is_open), hint: "Accepting orders" },
      { key: "CLOSED", label: "Closed", icon: DoorClosed, value: countBy((l) => !l.is_open), hint: "Not serving right now" },
      { key: "ACTIVE", label: "Active", icon: CheckCircle2, value: countBy((l) => l.is_active), hint: "Enabled branches" },
      { key: "INACTIVE", label: "Inactive", icon: Ban, value: countBy((l) => !l.is_active), hint: "Deactivated branches" },
    ];
  }, [restaurant?.locations]);

  const filteredLocations = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return (restaurant?.locations ?? []).filter((location) => {
      const matchesQuery =
        !normalized ||
        [
          location.branch_name,
          location.address_line_1,
          location.address_line_2 ?? "",
          location.city,
          location.state,
        ].some((value) => value.toLowerCase().includes(normalized));
      const matchesStatus =
        statusFilter === "ALL" ||
        (statusFilter === "OPEN" && location.is_open) ||
        (statusFilter === "CLOSED" && !location.is_open) ||
        (statusFilter === "ACTIVE" && location.is_active) ||
        (statusFilter === "INACTIVE" && !location.is_active);
      return matchesQuery && matchesStatus;
    });
  }, [query, restaurant?.locations, statusFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredLocations.length / pageSize));
  const pageItems = filteredLocations.slice((page - 1) * pageSize, page * pageSize);

  useEffect(() => {
    setPage(1);
  }, [pageSize, query, selectedRestaurantId, statusFilter]);

  const columns: Array<TableColumn<RestaurantLocation>> = [
    {
      id: "branch",
      header: "Location / Branch",
      render: (location) => (
        <>
          <strong>{location.branch_name}</strong>
          <span>{restaurant?.name ?? "Restaurant branch"}</span>
        </>
      ),
      hideOnMobile: true,
    },
    {
      id: "address",
      header: "Address / Area",
      render: (location) => (
        <>
          <strong>{location.address_line_1}</strong>
          <span>
            {[location.address_line_2, location.city, location.state]
              .filter(Boolean)
              .join(", ")}
          </span>
        </>
      ),
      mobileLabel: "Address",
    },
    {
      id: "status",
      header: "Status",
      render: (location) => (
        <div className="status-stack">
          <StatusPill status={location.is_open ? "OPEN" : "CLOSED"} />
          <StatusPill status={location.is_active ? "ACTIVE" : "INACTIVE"} />
        </div>
      ),
      mobileLabel: "Status",
    },
    {
      id: "delivery_fee",
      header: "Delivery Fee",
      render: (location) => formatCurrency(location.delivery_fee),
      mobileLabel: "Delivery Fee",
      align: "right",
    },
    {
      id: "minimum_order",
      header: "Minimum Order",
      render: (location) => formatCurrency(location.minimum_order_amount),
      mobileLabel: "Minimum Order",
      align: "right",
    },
    {
      id: "estimated_time",
      header: "Estimated Time",
      render: (location) => `${location.estimated_delivery_time} min`,
      mobileLabel: "ETA",
      align: "right",
    },
  ];

  const closeLocationModal = () => {
    setIsLocationModalOpen(false);
    setEditingLocationId(null);
    setLocationForm(emptyLocationForm);
    setIsLocationSubmitting(false);
  };

  const openCreateLocationModal = () => {
    setEditingLocationId(null);
    setLocationForm(emptyLocationForm);
    setIsLocationModalOpen(true);
  };

  const openEditLocationModal = (location: RestaurantLocation) => {
    setEditingLocationId(location.id);
    setLocationForm(toLocationForm(location));
    setIsLocationModalOpen(true);
  };

  const syncLocation = (nextLocation: RestaurantLocation) => {
    setRestaurant((current) =>
      current
        ? {
            ...current,
            locations: current.locations.some((location) => location.id === nextLocation.id)
              ? current.locations.map((location) =>
                  location.id === nextLocation.id ? nextLocation : location,
                )
              : [...current.locations, nextLocation],
          }
        : current,
    );
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
      opening_time: locationForm.opening_time || null,
      closing_time: locationForm.closing_time || null,
      is_open: locationForm.is_open,
      is_active: locationForm.is_active,
    };

    try {
      const nextLocation = editingLocationId
        ? await api.updateRestaurantLocation(
            token,
            restaurant.id,
            editingLocationId,
            payload,
          )
        : await api.createRestaurantLocation(token, restaurant.id, payload);
      syncLocation(nextLocation);
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
          : "Unable to save this location.";
      onToast("Location save failed", message, "error");
      setIsLocationSubmitting(false);
    }
  };

  const setLocationActiveState = async (
    location: RestaurantLocation,
    nextIsActive: boolean,
  ) => {
    if (!restaurant || busyLocationId) {
      return;
    }

    setBusyLocationId(location.id);
    try {
      const updated = await api.updateRestaurantLocation(
        token,
        restaurant.id,
        location.id,
        {
          is_active: nextIsActive,
          is_open: nextIsActive ? location.is_open : false,
        },
      );
      syncLocation(updated);
      onToast(
        nextIsActive ? "Location activated" : "Location deactivated",
        `${location.branch_name} is now ${nextIsActive ? "active" : "inactive"}.`,
        "success",
      );
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to update this location.";
      onToast("Location update failed", message, "error");
    } finally {
      setBusyLocationId(null);
    }
  };

  const selectedRestaurantSummary =
    restaurant ??
    restaurants.find((entry) => entry.id === selectedRestaurantId) ??
    null;

  return (
    <div className="page-stack">
      <PageIntro
        eyebrow="Branch management"
        title="Locations"
        description="Review every branch for the current restaurant, then open a location workspace for settings, menu items, and orders."
        actions={
          selectedRestaurantSummary ? (
            <button
              className="secondary-button"
              onClick={() => onNavigate(`/admin/restaurants/${selectedRestaurantSummary.id}`)}
              type="button"
            >
              <Store size={16} strokeWidth={2.1} />
              <span>Open restaurant</span>
            </button>
          ) : null
        }
      />

      {isAdmin && !isScopedToRestaurant ? (
        <section className="admin-surface">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Restaurant scope</span>
              <h2>{selectedRestaurantSummary?.name ?? "Select a restaurant"}</h2>
              <p className="hint-text">
                Switch the active restaurant to manage its branches without leaving the locations workspace.
              </p>
            </div>
            <select
              className="page-search page-search--select"
              onChange={(event) => setSelectedRestaurantId(event.target.value || null)}
              value={selectedRestaurantId ?? ""}
            >
              <option value="">Choose restaurant</option>
              {restaurants.map((entry) => (
                <option key={entry.id} value={entry.id}>
                  {entry.name} · {entry.city}
                </option>
              ))}
            </select>
          </div>
        </section>
      ) : null}

      {selectedRestaurantSummary ? (
        <section className="admin-surface restaurant-detail-hero">
          <div className="restaurant-detail-hero__copy">
            <span className="eyebrow">Master list</span>
            <h2>{selectedRestaurantSummary.name}</h2>
            <p>
              {selectedRestaurantSummary.city}, {selectedRestaurantSummary.state}
            </p>
          </div>
        </section>
      ) : null}

      {selectedRestaurantId ? (
        <StatTiles<"ALL" | "OPEN" | "CLOSED" | "ACTIVE" | "INACTIVE">
          active={statusFilter}
          ariaLabel="Branch status distribution"
          loading={isLoading}
          onSelect={setStatusFilter}
          tiles={locationTiles}
        />
      ) : null}

      <section className="admin-surface">
        <DataToolbar
          actions={
            <>
              <span className="toolbar-meta">{pluralize(filteredLocations.length, 'location')}</span>
              {selectedRestaurantId ? (
                <button
                  className="primary-button"
                  onClick={openCreateLocationModal}
                  type="button"
                >
                  <PlusCircle size={16} strokeWidth={2.1} />
                  <span>Add location</span>
                </button>
              ) : null}
            </>
          }
          filters={
            <select
              className="page-search page-search--select"
              onChange={(event) =>
                setStatusFilter(event.target.value as typeof statusFilter)
              }
              value={statusFilter}
            >
              <option value="ALL">All statuses</option>
              <option value="OPEN">Open</option>
              <option value="CLOSED">Closed</option>
              <option value="ACTIVE">Active</option>
              <option value="INACTIVE">Inactive</option>
            </select>
          }
          onSearchChange={setQuery}
          searchPlaceholder="Search by branch, area, city, or address"
          searchValue={query}
        />

        {!selectedRestaurantId && !isLoading ? (
          <EmptyPanel
            title="Select a restaurant"
            description="Choose a restaurant first to open its branch list and location management tools."
          />
        ) : (
          <>
            <ResponsiveTable
              actions={[
                {
                  id: "view",
                  label: "Open location",
                  icon: Eye,
                  onClick: (location) =>
                    onNavigate(
                      `/admin/restaurants/${location.restaurant_id}/locations/${location.id}`,
                    ),
                },
                {
                  id: "edit",
                  label: "Edit location",
                  icon: Pencil,
                  onClick: openEditLocationModal,
                },
                {
                  id: "activate",
                  label: "Activate location",
                  icon: CheckCircle2,
                  hidden: (location) => location.is_active,
                  disabled: (location) => busyLocationId === location.id,
                  onClick: (location) => void setLocationActiveState(location, true),
                  tone: "success",
                },
                {
                  id: "deactivate",
                  label: "Deactivate location",
                  icon: Power,
                  hidden: (location) => !location.is_active,
                  disabled: (location) => busyLocationId === location.id,
                  onClick: (location) => void setLocationActiveState(location, false),
                },
              ]}
              columns={columns}
              emptyDescription="Add the first branch or adjust the current restaurant and filters."
              emptyTitle="No locations match this view"
              keyExtractor={(location) => location.id}
              loading={isLoading}
              mobileStatus={(location) => (
                <div className="status-stack">
                  <StatusPill status={location.is_open ? "OPEN" : "CLOSED"} />
                  <StatusPill status={location.is_active ? "ACTIVE" : "INACTIVE"} />
                </div>
              )}
              mobileSubtitle={(location) => `${location.city} • ${location.address_line_1}`}
              mobileTitle={(location) => location.branch_name}
              onRowClick={(location) =>
                onNavigate(
                  `/admin/restaurants/${location.restaurant_id}/locations/${location.id}`,
                )
              }
              rows={pageItems}
            />
            <Pagination
              onPageChange={setPage}
              onPageSizeChange={setPageSize}
              page={page}
              pageSize={pageSize}
              totalItems={filteredLocations.length}
              totalPages={totalPages}
            />
          </>
        )}
      </section>

      {isLocationModalOpen && restaurant ? (
        <div className="modal-overlay" onClick={closeLocationModal} role="presentation">
          <section
            className="modal-card"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
          >
            <div className="panel__header modal-card__header">
              <div>
                <span className="eyebrow">Location editor</span>
                <h2>{editingLocationId ? "Edit branch" : "Add branch"}</h2>
                <p className="hint-text">
                  Update address, timing, delivery settings, and live branch availability.
                </p>
              </div>
              <button
                aria-label="Close location form"
                className="modal-close"
                onClick={closeLocationModal}
                type="button"
              >
                ×
              </button>
            </div>

            <form className="form-grid modal-card__body" onSubmit={submitLocation}>
              <label className="field">
                <span>Branch name</span>
                <input
                  required
                  value={locationForm.branch_name}
                  onChange={(event) =>
                    setLocationForm((current) => ({
                      ...current,
                      branch_name: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="field">
                <span>City</span>
                <input
                  required
                  value={locationForm.city}
                  onChange={(event) =>
                    setLocationForm((current) => ({ ...current, city: event.target.value }))
                  }
                />
              </label>
              <label className="field form-grid__wide">
                <span>Address line 1</span>
                <input
                  required
                  value={locationForm.address_line_1}
                  onChange={(event) =>
                    setLocationForm((current) => ({
                      ...current,
                      address_line_1: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="field form-grid__wide">
                <span>Address line 2</span>
                <input
                  value={locationForm.address_line_2}
                  onChange={(event) =>
                    setLocationForm((current) => ({
                      ...current,
                      address_line_2: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="field">
                <span>State</span>
                <input
                  required
                  value={locationForm.state}
                  onChange={(event) =>
                    setLocationForm((current) => ({ ...current, state: event.target.value }))
                  }
                />
              </label>
              <label className="field">
                <span>Postal code</span>
                <input
                  required
                  value={locationForm.postal_code}
                  onChange={(event) =>
                    setLocationForm((current) => ({
                      ...current,
                      postal_code: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="field">
                <span>Phone</span>
                <input
                  value={locationForm.phone_number}
                  onChange={(event) =>
                    setLocationForm((current) => ({
                      ...current,
                      phone_number: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="field">
                <span>Estimated time (minutes)</span>
                <input
                  min="1"
                  required
                  step="1"
                  type="number"
                  value={locationForm.estimated_delivery_time}
                  onChange={(event) =>
                    setLocationForm((current) => ({
                      ...current,
                      estimated_delivery_time: event.target.value,
                    }))
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
                  value={locationForm.delivery_fee}
                  onChange={(event) =>
                    setLocationForm((current) => ({
                      ...current,
                      delivery_fee: event.target.value,
                    }))
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
                  value={locationForm.minimum_order_amount}
                  onChange={(event) =>
                    setLocationForm((current) => ({
                      ...current,
                      minimum_order_amount: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="field">
                <span>Opening time</span>
                <input
                  type="time"
                  value={locationForm.opening_time}
                  onChange={(event) =>
                    setLocationForm((current) => ({
                      ...current,
                      opening_time: event.target.value,
                    }))
                  }
                />
              </label>
              <label className="field">
                <span>Closing time</span>
                <input
                  type="time"
                  value={locationForm.closing_time}
                  onChange={(event) =>
                    setLocationForm((current) => ({
                      ...current,
                      closing_time: event.target.value,
                    }))
                  }
                />
              </label>
              <div className="field form-grid__wide field--inline">
                <Checkbox
                  checked={locationForm.is_open}
                  label="Open now"
                  onChange={(checked) =>
                    setLocationForm((current) => ({
                      ...current,
                      is_open: checked,
                    }))
                  }
                />
                <Checkbox
                  checked={locationForm.is_active}
                  label="Active"
                  onChange={(checked) =>
                    setLocationForm((current) => ({
                      ...current,
                      is_active: checked,
                    }))
                  }
                />
              </div>
              <div className="form-grid__wide modal-actions">
                <button
                  className="secondary-button"
                  onClick={closeLocationModal}
                  type="button"
                >
                  Cancel
                </button>
                <button
                  className="primary-button"
                  disabled={isLocationSubmitting}
                  type="submit"
                >
                  {isLocationSubmitting
                    ? "Saving..."
                    : editingLocationId
                      ? "Save location"
                      : "Create location"}
                </button>
              </div>
            </form>
          </section>
        </div>
      ) : null}

      {restaurant && restaurant.locations.length > 0 ? (
        <section className="admin-surface">
          <div className="panel__header">
            <div>
              <span className="eyebrow">Audit trail</span>
              <h2>Recent branch updates</h2>
              <p className="hint-text">
                A quick snapshot of when each location was last refreshed.
              </p>
            </div>
          </div>
          <div className="detail-grid">
            {restaurant.locations.slice(0, 4).map((location) => (
              <div key={location.id}>
                <strong>{location.branch_name}</strong>
                <span>Created {formatDate(location.created_at)}</span>
                <span>Updated {formatDate(location.updated_at)}</span>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

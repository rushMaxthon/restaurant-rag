import { ArrowLeft, Check, MapPin } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  buildMenuItemUpsertPayload,
  createEmptyMenuItemFormState,
  createMenuItemFormStateFromItem,
  MenuItemCustomizationEditor,
  type MenuItemFormState,
} from "../components/MenuItemCustomizationEditor";
import { Checkbox } from "../components/common/Checkbox";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { EmptyPanel } from "../components/EmptyPanel";
import { Breadcrumbs } from "../components/Breadcrumbs";
import { PageIntro } from "../components/PageIntro";
import { ApiError, api } from "../services/api";
import type {
  MenuItem,
  MenuItemUpsertPayload,
  RestaurantLocation,
  UserRole,
} from "../types/app";

interface MenuItemEditorPageProps {
  token: string;
  role: UserRole;
  restaurantId: string;
  locationId: string | null;
  itemId?: string | null;
  onNavigate: (path: string) => void;
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

interface DuplicatePrompt {
  payload: MenuItemUpsertPayload;
  conflictingNames: string;
  remainingCount: number;
}

function buildLocationMenuPath(restaurantId: string, locationId: string): string {
  return `/admin/restaurants/${restaurantId}/locations/${locationId}`;
}

function getConflictingLocationIds(error: ApiError): string[] {
  if (
    error.detail !== null &&
    typeof error.detail === "object" &&
    Array.isArray((error.detail as { conflicting_location_ids?: unknown }).conflicting_location_ids)
  ) {
    return (error.detail as { conflicting_location_ids: unknown[] }).conflicting_location_ids.filter(
      (entry): entry is string => typeof entry === "string",
    );
  }
  return [];
}

export function MenuItemEditorPage({
  token,
  role,
  restaurantId,
  locationId,
  itemId = null,
  onNavigate,
  onToast,
}: MenuItemEditorPageProps) {
  const isEditing = Boolean(itemId);
  const isMultiLocationCreate = !itemId && !locationId;
  const backPath = useMemo(
    () =>
      locationId ? buildLocationMenuPath(restaurantId, locationId) : "/menu-items",
    [locationId, restaurantId],
  );
  const [form, setForm] = useState<MenuItemFormState>(createEmptyMenuItemFormState);
  const [restaurantName, setRestaurantName] = useState("Restaurant");
  const [location, setLocation] = useState<RestaurantLocation | null>(null);
  const [locations, setLocations] = useState<RestaurantLocation[]>([]);
  const [selectedLocationIds, setSelectedLocationIds] = useState<string[]>([]);
  const [duplicatePrompt, setDuplicatePrompt] = useState<DuplicatePrompt | null>(null);
  const [item, setItem] = useState<MenuItem | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const allSelected =
    locations.length > 0 && selectedLocationIds.length === locations.length;

  useEffect(() => {
    let active = true;

    const loadEditor = async () => {
      setIsLoading(true);
      setLoadError(null);

      try {
        const restaurantDetail =
          role === "ADMIN"
            ? await api.getAdminRestaurant(token, restaurantId)
            : await api.getRestaurant(token, restaurantId);

        if (!active) {
          return;
        }

        setRestaurantName(restaurantDetail.name);

        if (!locationId) {
          const allLocations = restaurantDetail.locations ?? [];
          if (allLocations.length === 0) {
            throw new Error(
              "Create at least one location before adding menu items.",
            );
          }
          const activeLocations = allLocations.filter((entry) => entry.is_active);
          setLocations(allLocations);
          setSelectedLocationIds(
            (activeLocations.length > 0 ? activeLocations : allLocations).map(
              (entry) => entry.id,
            ),
          );
          setItem(null);
          setForm(createEmptyMenuItemFormState());
          setIsLoading(false);
          return;
        }

        const matchedLocation =
          restaurantDetail.locations.find((entry) => entry.id === locationId) ?? null;

        if (!matchedLocation) {
          throw new Error("The selected location could not be found.");
        }

        setLocation(matchedLocation);

        if (!itemId) {
          setItem(null);
          setForm(createEmptyMenuItemFormState());
          setIsLoading(false);
          return;
        }

        const menuItems = await api.getMenuItems(token, restaurantId, locationId);
        if (!active) {
          return;
        }

        const matchedItem = menuItems.find((entry) => entry.id === itemId) ?? null;
        if (!matchedItem) {
          throw new Error("The selected menu item could not be found.");
        }

        setItem(matchedItem);
        setForm(createMenuItemFormStateFromItem(matchedItem));
        setIsLoading(false);
      } catch (error: unknown) {
        if (!active) {
          return;
        }
        const message =
          error instanceof ApiError || error instanceof Error
            ? error.message
            : "Unable to load the menu item editor.";
        setLoadError(message);
        setIsLoading(false);
      }
    };

    void loadEditor();

    return () => {
      active = false;
    };
  }, [itemId, locationId, restaurantId, role, token]);

  const submitBulkCreate = async (
    payload: MenuItemUpsertPayload,
    skipDuplicates: boolean,
  ) => {
    try {
      const result = await api.createMenuItemsBulk(token, {
        ...payload,
        restaurant_id: restaurantId,
        restaurant_location_ids: selectedLocationIds,
        skip_duplicates: skipDuplicates,
      });
      const createdName = result.created[0]?.name ?? form.name.trim();
      const createdCount = result.created.length;
      const branchLabel = createdCount === 1 ? "branch" : "branches";
      onToast(
        "Menu item created",
        result.skipped.length > 0
          ? `${createdName} was added to ${createdCount} ${branchLabel}. Skipped ${result.skipped.length} where it already exists.`
          : `${createdName} is now listed at ${createdCount} ${branchLabel}.`,
        "success",
      );
      onNavigate(backPath);
    } catch (error: unknown) {
      if (
        !skipDuplicates &&
        error instanceof ApiError &&
        error.status === 409
      ) {
        const conflictingIds = getConflictingLocationIds(error);
        const remainingCount = selectedLocationIds.filter(
          (id) => !conflictingIds.includes(id),
        ).length;
        if (conflictingIds.length > 0 && remainingCount > 0) {
          const conflictingNames = locations
            .filter((entry) => conflictingIds.includes(entry.id))
            .map((entry) => entry.branch_name)
            .join(", ");
          setDuplicatePrompt({
            payload,
            conflictingNames,
            remainingCount,
          });
          setIsSubmitting(false);
          return;
        }
      }
      setDuplicatePrompt(null);
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to save the menu item.";
      onToast("Create failed", message, "error");
      setIsSubmitting(false);
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isSubmitting || (!isMultiLocationCreate && !location)) {
      return;
    }
    if (isMultiLocationCreate && selectedLocationIds.length === 0) {
      onToast(
        "Select a location",
        "Choose at least one branch for this menu item.",
        "error",
      );
      return;
    }

    let payload;
    try {
      payload = buildMenuItemUpsertPayload(form);
    } catch (error: unknown) {
      onToast(
        "Invalid menu item",
        error instanceof Error
          ? error.message
          : "Check the menu item setup and try again.",
        "error",
      );
      return;
    }

    setIsSubmitting(true);
    if (isMultiLocationCreate) {
      await submitBulkCreate(payload, false);
      return;
    }

    try {
      if (itemId && location) {
        const updated = await api.updateMenuItem(token, itemId, {
          ...payload,
          restaurant_location_id: location.id,
        });
        onToast("Menu item updated", `${updated.name} was saved.`, "success");
      } else if (location) {
        const created = await api.createMenuItem(token, {
          restaurant_id: restaurantId,
          restaurant_location_id: location.id,
          ...payload,
        });
        onToast("Menu item created", `${created.name} is now listed.`, "success");
      }
      onNavigate(backPath);
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : "Unable to save the menu item.";
      onToast(isEditing ? "Update failed" : "Create failed", message, "error");
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="page-stack">
        <PageIntro
          eyebrow="Menu management"
          title={isEditing ? "Edit menu item" : "Add menu item"}
          description="Loading the editor inside the current restaurant workspace."
          actions={
            <button
              className="secondary-button"
              onClick={() => onNavigate(backPath)}
              type="button"
            >
              <ArrowLeft size={16} strokeWidth={2.1} />
              <span>Back to menu</span>
            </button>
          }
        />
        <section className="admin-surface">
          <EmptyPanel
            title="Loading menu item editor"
            description="Fetching location details and the latest menu configuration."
          />
        </section>
      </div>
    );
  }

  if (loadError || (!isMultiLocationCreate && !location)) {
    return (
      <div className="page-stack">
        <PageIntro
          eyebrow="Menu management"
          title="Menu item editor unavailable"
          description="The editor could not be opened inside this location workspace."
          actions={
            <button
              className="secondary-button"
              onClick={() => onNavigate(backPath)}
              type="button"
            >
              <ArrowLeft size={16} strokeWidth={2.1} />
              <span>Back to menu</span>
            </button>
          }
        />
        <section className="admin-surface">
          <EmptyPanel
            title="Unable to load menu item form"
            description={loadError ?? "Check the selected location and try again."}
          />
        </section>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <Breadcrumbs
        items={
          isMultiLocationCreate
            ? [
                { label: "Menu items", path: "/menu-items" },
                { label: "Add menu item" },
              ]
            : [
                role === "OWNER"
                  ? { label: "My Restaurant", path: `/admin/restaurants/${restaurantId}/locations` }
                  : { label: "Restaurants", path: "/restaurants" },
                ...(role === "OWNER"
                  ? []
                  : [{ label: restaurantName, path: `/admin/restaurants/${restaurantId}/locations` }]),
                {
                  label: location?.branch_name ?? "Location",
                  path: `/admin/restaurants/${restaurantId}/locations/${locationId}`,
                },
                { label: isEditing ? (item?.name ?? "Edit item") : "Add menu item" },
              ]
        }
        onNavigate={onNavigate}
      />
      <PageIntro
        eyebrow="Menu management"
        title={isEditing ? `Edit ${item?.name ?? "menu item"}` : "Add menu item"}
        description={
          isEditing
            ? "Update pricing, launch details, sizes, and customization groups without leaving the dashboard."
            : isMultiLocationCreate
              ? "Create a menu item once and publish it to every selected branch in a single action."
              : "Create a new menu item for this location with the same catalog structure used across the admin workspace."
        }
        actions={
          <button
            className="secondary-button"
            onClick={() => onNavigate(backPath)}
            type="button"
          >
            <ArrowLeft size={16} strokeWidth={2.1} />
            <span>Back to menu</span>
          </button>
        }
      />

      <section className="admin-surface page-stack">
        {isMultiLocationCreate ? (
          <div className="branch-picker">
            <div className="branch-picker__header">
              <div className="branch-picker__heading">
                <span className="eyebrow">Locations</span>
                <h2>Where should this item be available?</h2>
                <p className="hint-text">
                  Pick the branches to publish to — the item is created at each
                  one in a single action.
                </p>
              </div>
              <div className="branch-picker__controls">
                <span className="branch-picker__count">
                  {selectedLocationIds.length} of {locations.length} selected
                </span>
                <button
                  className="secondary-button secondary-button--ghost"
                  onClick={() =>
                    setSelectedLocationIds(
                      allSelected ? [] : locations.map((entry) => entry.id),
                    )
                  }
                  type="button"
                >
                  {allSelected ? "Clear all" : "Select all"}
                </button>
              </div>
            </div>

            <div aria-label="Locations" className="branch-picker__grid" role="group">
              {locations.map((entry) => {
                const isSelected = selectedLocationIds.includes(entry.id);
                return (
                  <button
                    aria-checked={isSelected}
                    className={
                      isSelected
                        ? "branch-card branch-card--selected"
                        : "branch-card"
                    }
                    key={entry.id}
                    onClick={() =>
                      setSelectedLocationIds((current) =>
                        isSelected
                          ? current.filter((id) => id !== entry.id)
                          : [...current, entry.id],
                      )
                    }
                    role="checkbox"
                    type="button"
                  >
                    <span aria-hidden="true" className="branch-card__icon">
                      <MapPin size={16} strokeWidth={2.2} />
                    </span>
                    <span className="branch-card__copy">
                      <span className="branch-card__name">
                        {entry.branch_name}
                        {entry.is_active ? null : (
                          <span className="branch-card__flag">Inactive</span>
                        )}
                      </span>
                      <span className="branch-card__meta">
                        {entry.city}, {entry.state}
                      </span>
                    </span>
                    <span aria-hidden="true" className="branch-card__check">
                      <Check size={13} strokeWidth={3} />
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ) : location ? (
          <div className="panel__header">
            <div>
              <span className="eyebrow">Location catalog</span>
              <h2>{location.branch_name}</h2>
              <p className="hint-text">
                {location.address_line_1}, {location.city}, {location.state}
              </p>
            </div>
          </div>
        ) : null}

        <form className="form-grid" onSubmit={handleSubmit}>
          <label className="field">
            <span>Name</span>
            <input
              placeholder="Paneer Tikka"
              required
              value={form.name}
              onChange={(event) =>
                setForm((current) => ({ ...current, name: event.target.value }))
              }
            />
          </label>
          <label className="field">
            <span>Category</span>
            <input
              placeholder="Starters"
              required
              value={form.category}
              onChange={(event) =>
                setForm((current) => ({ ...current, category: event.target.value }))
              }
            />
          </label>
          <label className="field">
            <span>Cuisine</span>
            <input
              placeholder="Indian"
              value={form.cuisine_type}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  cuisine_type: event.target.value,
                }))
              }
            />
          </label>
          <label className="field">
            <span>Launch date</span>
            <input
              type="datetime-local"
              value={form.launched_at}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  launched_at: event.target.value,
                }))
              }
            />
            <small className="hint-text">
              Used to determine how long a manually marked launch stays active.
            </small>
          </label>

          <MenuItemCustomizationEditor form={form} onChange={setForm} />

          <label className="field form-grid__wide">
            <span>Image URL</span>
            <input
              placeholder="https://..."
              value={form.image_url}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  image_url: event.target.value,
                }))
              }
            />
          </label>
          <label className="field form-grid__wide">
            <span>Description</span>
            <textarea
              placeholder="Describe the dish..."
              rows={4}
              value={form.description}
              onChange={(event) =>
                setForm((current) => ({
                  ...current,
                  description: event.target.value,
                }))
              }
            />
          </label>

          <div className="form-grid__wide menu-item-modal__checkboxes">
            <Checkbox
              checked={form.is_veg}
              label="Veg"
              onChange={(checked) =>
                setForm((current) => ({
                  ...current,
                  is_veg: checked,
                }))
              }
            />
            <Checkbox
              checked={form.is_available}
              label="Available"
              onChange={(checked) =>
                setForm((current) => ({
                  ...current,
                  is_available: checked,
                }))
              }
            />
            <Checkbox
              checked={form.is_new_launch}
              label="Mark as new launch"
              onChange={(checked) =>
                setForm((current) => ({
                  ...current,
                  is_new_launch: checked,
                }))
              }
            />
          </div>

          <div className="form-actions form-grid__wide">
            <button
              className="secondary-button"
              onClick={() => onNavigate(backPath)}
              type="button"
            >
              Cancel
            </button>
            <button className="primary-button" disabled={isSubmitting} type="submit">
              {isSubmitting
                ? isEditing
                  ? "Saving..."
                  : "Creating..."
                : isEditing
                  ? "Save menu item"
                  : isMultiLocationCreate
                    ? `Create at ${selectedLocationIds.length} ${selectedLocationIds.length === 1 ? "branch" : "branches"}`
                    : "Create menu item"}
            </button>
          </div>
        </form>
      </section>

      <ConfirmDialog
        confirmLabel={`Create for remaining ${duplicatePrompt?.remainingCount ?? 0}`}
        description={`This item already exists at: ${duplicatePrompt?.conflictingNames ?? ""}. Skip those branches and create it only for the remaining ${duplicatePrompt?.remainingCount ?? 0} selected?`}
        eyebrow="Duplicate menu item"
        busy={isSubmitting}
        onCancel={() => setDuplicatePrompt(null)}
        onConfirm={() => {
          if (!duplicatePrompt || isSubmitting) {
            return;
          }
          setIsSubmitting(true);
          void submitBulkCreate(duplicatePrompt.payload, true);
        }}
        open={duplicatePrompt !== null}
        title="Item already listed at some branches"
      />
    </div>
  );
}

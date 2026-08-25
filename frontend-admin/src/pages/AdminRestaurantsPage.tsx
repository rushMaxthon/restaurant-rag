import { BadgeCheck, CheckCircle2, Clock3, Eye, Pencil, Smartphone, Store, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Checkbox } from '../components/common/Checkbox';
import { Modal } from '../components/Modal';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { DataToolbar } from '../components/DataToolbar';
import { StatTiles, type StatTileItem } from '../components/StatTiles';
import { readWorkspaceSettings } from '../services/workspaceSettings';
import { pluralize } from '../services/format';
import { PageIntro } from '../components/PageIntro';
import { Pagination } from '../components/Pagination';
import { ApiError, api, formatDate } from '../services/api';
import {
  getPageSnapshot,
  hasPageSnapshot,
  setPageSnapshot,
  tokenScope,
} from '../services/pageCache';
import { ResponsiveTable, type TableColumn } from '../components/ResponsiveTable';
import { StatusPill } from '../components/StatusPill';
import { AppClientFields } from '../components/AppClientFields';
import {
  emptyAppClientForm,
  toAppKey,
  toBundleId,
  toOrderNumberPrefix,
  trimAppClientForm,
  validateAppClientForm,
  type AppClientFormErrors,
  type AppClientFormValues,
  type DerivedAppClientField,
} from '../services/appClient';
import type { Restaurant } from '../types/app';

interface AdminRestaurantsPageProps {
  token: string;
  onNavigate: (path: string) => void;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

type CreateRestaurantForm = {
  name: string;
  owner_name: string;
  owner_email: string;
  owner_password: string;
} & AppClientFormValues;

type EditRestaurantForm = {
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

const emptyCreateForm: CreateRestaurantForm = {
  name: '',
  owner_name: '',
  owner_email: '',
  owner_password: '',
  ...emptyAppClientForm,
};

const emptyEditForm: EditRestaurantForm = {
  name: '',
  description: '',
  cuisine_type: '',
  address_line_1: '',
  address_line_2: '',
  city: '',
  state: '',
  country: 'India',
  postal_code: '',
  phone_number: '',
  minimum_order_amount: '0',
  delivery_fee: '0',
  logo_image_url: '',
  cover_image_url: '',
  is_open: false,
};

// Shared with RestaurantDetailPage: editing a restaurant's own details there
// is a genuine data change for the list this page shows.
export function buildAdminRestaurantsCacheKeyPrefix(scope: string): string {
  return `admin-restaurants:${scope}`;
}

export function AdminRestaurantsPage({ token, onNavigate, onToast }: AdminRestaurantsPageProps) {
  const scope = tokenScope(token);
  const restaurantsKey = buildAdminRestaurantsCacheKeyPrefix(scope);
  const [restaurants, setRestaurants] = useState<Restaurant[]>(
    () => getPageSnapshot<Restaurant[]>(restaurantsKey) ?? [],
  );
  // Only true when nothing has been fetched yet this session - not on every
  // mount, so revisiting this page keeps showing its data instead of a
  // skeleton.
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(() => !hasPageSnapshot(restaurantsKey));
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'APPROVED' | 'PENDING'>('ALL');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => readWorkspaceSettings().defaultPageSize);

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [isCreateSubmitting, setIsCreateSubmitting] = useState(false);
  const [createForm, setCreateForm] = useState<CreateRestaurantForm>(emptyCreateForm);
  const [createErrors, setCreateErrors] = useState<AppClientFormErrors>({});
  const [editedAppFields, setEditedAppFields] = useState<DerivedAppClientField[]>([]);

  const [selectedRestaurant, setSelectedRestaurant] = useState<Restaurant | null>(null);
  const [restaurantToDelete, setRestaurantToDelete] = useState<Restaurant | null>(null);
  const [pendingApprovalRevoke, setPendingApprovalRevoke] = useState<Restaurant | null>(null);
  const [editForm, setEditForm] = useState<EditRestaurantForm>(emptyEditForm);
  const [isEditOpen, setIsEditOpen] = useState(false);
  const [isEditSubmitting, setIsEditSubmitting] = useState(false);
  const [isDeleteSubmitting, setIsDeleteSubmitting] = useState(false);

  // `force`: bypasses the cache. The create flow below always forces, since it
  // needs the newly created restaurant in the list; the mount effect never
  // does, which is what makes revisiting this page free.
  const loadRestaurants = async (force = false) => {
    if (!force) {
      const cached = getPageSnapshot<Restaurant[]>(restaurantsKey);
      if (cached) {
        setRestaurants(cached);
        setIsLoading(false);
        return;
      }
    }

    setIsLoading(true);
    try {
      const rows = await api.getAdminRestaurants(token);
      setRestaurants(rows);
      setLoadError(null);
      setPageSnapshot(restaurantsKey, rows);
    } catch (error: unknown) {
      const message = error instanceof ApiError ? error.message : 'Unable to load restaurants.';
      // Keeps the failure on screen after the toast fades, and gives it a way out.
      setLoadError(message);
      onToast('Restaurants unavailable', message, 'error');
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadRestaurants();
  }, [token, restaurantsKey]);

  const approvalTiles = useMemo<Array<StatTileItem<'ALL' | 'APPROVED' | 'PENDING'>>>(() => {
    const approved = restaurants.filter((restaurant) => restaurant.is_approved);
    const pending = restaurants.filter((restaurant) => !restaurant.is_approved);
    return [
      {
        key: 'ALL',
        label: 'All restaurants',
        icon: Store,
        value: restaurants.length,
        hint: `${restaurants.filter((restaurant) => restaurant.is_open).length} open now`,
      },
      {
        key: 'APPROVED',
        label: 'Approved',
        icon: BadgeCheck,
        value: approved.length,
        hint: 'Live on the platform',
      },
      {
        key: 'PENDING',
        label: 'Pending approval',
        icon: Clock3,
        value: pending.length,
        hint: 'Awaiting review',
      },
    ];
  }, [restaurants]);

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return restaurants.filter((restaurant) =>
      (!normalized ||
        [restaurant.name, restaurant.city, restaurant.cuisine_type, restaurant.slug].some((value) =>
          value.toLowerCase().includes(normalized),
        )) &&
      (statusFilter === 'ALL' || (statusFilter === 'APPROVED' ? restaurant.is_approved : !restaurant.is_approved)),
    );
  }, [query, restaurants, statusFilter]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const pageItems = filtered.slice((page - 1) * pageSize, page * pageSize);

  useEffect(() => {
    setPage(1);
  }, [pageSize, query, statusFilter]);

  const columns: Array<TableColumn<Restaurant>> = [
    {
      id: 'name',
      header: 'Name',
      render: (restaurant) => (
        <>
          <strong>{restaurant.name}</strong>
          <span>{restaurant.slug}</span>
        </>
      ),
      hideOnMobile: true,
    },
    {
      id: 'cuisine',
      header: 'Cuisine',
      render: (restaurant) => restaurant.cuisine_type,
      mobileLabel: 'Cuisine',
    },
    {
      id: 'city',
      header: 'City',
      render: (restaurant) => restaurant.city,
      mobileLabel: 'City',
    },
    {
      id: 'status',
      header: 'Status',
      render: (restaurant) => (
        <div className="status-stack">
          <StatusPill status={restaurant.is_approved ? 'APPROVED' : 'PENDING'} />
          <StatusPill status={restaurant.is_open ? 'OPEN' : 'CLOSED'} />
        </div>
      ),
      mobileLabel: 'Status',
    },
    {
      id: 'created',
      header: 'Created',
      render: (restaurant) => formatDate(restaurant.created_at),
      mobileLabel: 'Created',
    },
  ];

  const syncRestaurant = (updated: Restaurant) => {
    setRestaurants((current) => {
      const next = current.map((entry) => (entry.id === updated.id ? updated : entry));
      // Genuine data change: keep the cache in step with what's now on
      // screen, so a later visit doesn't show the pre-edit snapshot.
      setPageSnapshot(restaurantsKey, next);
      return next;
    });
  };

  const closeCreateModal = () => {
    setIsCreateOpen(false);
    setIsCreateSubmitting(false);
    setCreateForm(emptyCreateForm);
    setCreateErrors({});
    setEditedAppFields([]);
  };

  /** Keeps the app identity in sync with the restaurant name until it is edited by hand. */
  const updateRestaurantName = (name: string) => {
    setCreateForm((current) => {
      const derivedAppKey = editedAppFields.includes('app_key') ? current.app_key : toAppKey(name);
      const derivedBundleId = toBundleId(derivedAppKey);
      return {
        ...current,
        name,
        app_key: derivedAppKey,
        ios_bundle_id: editedAppFields.includes('ios_bundle_id') ? current.ios_bundle_id : derivedBundleId,
        android_package_name: editedAppFields.includes('android_package_name')
          ? current.android_package_name
          : derivedBundleId,
        order_number_prefix: editedAppFields.includes('order_number_prefix')
          ? current.order_number_prefix
          : toOrderNumberPrefix(name),
      };
    });
  };

  const updateAppField = (field: DerivedAppClientField, value: string) => {
    setEditedAppFields((current) => (current.includes(field) ? current : [...current, field]));
    setCreateForm((current) => {
      if (field !== 'app_key') {
        return { ...current, [field]: value };
      }

      // The bundle IDs follow the app key until they are edited on their own.
      const derivedBundleId = toBundleId(value);
      return {
        ...current,
        app_key: value,
        ios_bundle_id: editedAppFields.includes('ios_bundle_id') ? current.ios_bundle_id : derivedBundleId,
        android_package_name: editedAppFields.includes('android_package_name')
          ? current.android_package_name
          : derivedBundleId,
      };
    });
    setCreateErrors((current) => ({ ...current, [field]: undefined }));
  };

  const closeEditModal = () => {
    setSelectedRestaurant(null);
    setIsEditOpen(false);
    setIsEditSubmitting(false);
    setEditForm(emptyEditForm);
  };

  const submitCreateRestaurant = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isCreateSubmitting) {
      return;
    }

    const validationErrors = validateAppClientForm(createForm);
    if (Object.keys(validationErrors).length > 0) {
      setCreateErrors(validationErrors);
      onToast('Check the app details', 'Some app client fields need to be corrected.', 'error');
      return;
    }

    setCreateErrors({});
    setIsCreateSubmitting(true);
    try {
      const created = await api.createRestaurant(token, {
        name: createForm.name.trim(),
        owner_name: createForm.owner_name.trim(),
        owner_email: createForm.owner_email.trim(),
        owner_password: createForm.owner_password,
        ...trimAppClientForm(createForm),
      });
      await loadRestaurants(true);
      closeCreateModal();
      onToast(
        'Restaurant created',
        `${created.name}, the linked owner account, and app client "${created.app_client.app_key}" were created successfully.`,
        'success',
      );
    } catch (error: unknown) {
      const message =
        error instanceof ApiError
          ? error.message
          : 'Unable to create the restaurant and owner account.';
      onToast('Create failed', message, 'error');
      setIsCreateSubmitting(false);
    }
  };

  const toggleApproval = async (restaurant: Restaurant) => {
    try {
      const updated = await api.updateRestaurantApproval(token, restaurant.id, !restaurant.is_approved);
      syncRestaurant(updated);
      onToast(
        'Restaurant updated',
        `${updated.name} is now ${updated.is_approved ? 'approved' : 'pending'}.`,
        'success',
      );
    } catch (error: unknown) {
      const message = error instanceof ApiError ? error.message : 'Unable to update restaurant status.';
      onToast('Approval failed', message, 'error');
    }
  };

  const openRestaurantWorkspace = (restaurantId: string) => {
    onNavigate(`/admin/restaurants/${restaurantId}/locations`);
  };

  const openEditModal = async (restaurantId: string) => {
    try {
      const restaurant = await api.getAdminRestaurant(token, restaurantId);
      setSelectedRestaurant(restaurant);
      setEditForm({
        name: restaurant.name,
        description: restaurant.description ?? '',
        cuisine_type: restaurant.cuisine_type,
        address_line_1: restaurant.address_line_1,
        address_line_2: restaurant.address_line_2 ?? '',
        city: restaurant.city,
        state: restaurant.state,
        country: restaurant.country,
        postal_code: restaurant.postal_code,
        phone_number: restaurant.phone_number ?? '',
        minimum_order_amount: String(restaurant.minimum_order_amount),
        delivery_fee: String(restaurant.delivery_fee),
        logo_image_url: restaurant.logo_image_url ?? '',
        cover_image_url: restaurant.cover_image_url ?? '',
        is_open: restaurant.is_open,
      });
      setIsEditOpen(true);
    } catch (error: unknown) {
      const message = error instanceof ApiError ? error.message : 'Unable to load restaurant for editing.';
      onToast('Edit failed', message, 'error');
    }
  };

  const submitEditRestaurant = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedRestaurant || isEditSubmitting) {
      return;
    }

    setIsEditSubmitting(true);
    try {
      const updated = await api.updateRestaurant(token, selectedRestaurant.id, {
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
      syncRestaurant(updated);
      closeEditModal();
      onToast('Restaurant updated', `${updated.name} was updated successfully.`, 'success');
    } catch (error: unknown) {
      const message = error instanceof ApiError ? error.message : 'Unable to update restaurant.';
      onToast('Update failed', message, 'error');
      setIsEditSubmitting(false);
    }
  };

  const requestDeleteRestaurant = (restaurant: Restaurant) => {
    if (isDeleteSubmitting) {
      return;
    }
    setRestaurantToDelete(restaurant);
  };

  const deleteRestaurant = async () => {
    if (!restaurantToDelete || isDeleteSubmitting) {
      return;
    }

    setIsDeleteSubmitting(true);
    try {
      await api.deleteRestaurant(token, restaurantToDelete.id);
      setRestaurants((current) => {
        const next = current.filter((entry) => entry.id !== restaurantToDelete.id);
        setPageSnapshot(restaurantsKey, next);
        return next;
      });
      onToast(
        'Restaurant deleted',
        `${restaurantToDelete.name} was archived successfully.`,
        'success',
      );
      setRestaurantToDelete(null);
    } catch (error: unknown) {
      const message = error instanceof ApiError ? error.message : 'Unable to delete restaurant.';
      onToast('Delete failed', message, 'error');
    } finally {
      setIsDeleteSubmitting(false);
    }
  };

  return (
    <div className="page-stack">
      <PageIntro
        eyebrow="Moderation"
        title="Restaurants"
        description="Approve, edit, and manage every restaurant with better search, filtering, and lifecycle controls."
      />

      <StatTiles<'ALL' | 'APPROVED' | 'PENDING'>
        active={statusFilter}
        ariaLabel="Approval distribution"
        loading={isLoading}
        onSelect={setStatusFilter}
        tiles={approvalTiles}
      />

      <section className="admin-surface">
        <DataToolbar
          actions={
            <>
              <span className="toolbar-meta">{pluralize(filtered.length, 'restaurant')}</span>
              <button className="primary-button" onClick={() => setIsCreateOpen(true)} type="button">
                + Add New Restaurant
              </button>
            </>
          }
          filters={
            <select
              className="page-search page-search--select"
              onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}
              value={statusFilter}
            >
              <option value="ALL">All statuses</option>
              <option value="APPROVED">Approved</option>
              <option value="PENDING">Pending</option>
            </select>
          }
          onSearchChange={setQuery}
          searchPlaceholder="Filter by name, city, cuisine"
          searchValue={query}
        />
        <ResponsiveTable
          actions={[
            {
              id: 'view',
              label: 'Open workspace',
              icon: Eye,
              onClick: (restaurant) => openRestaurantWorkspace(restaurant.id),
            },
            {
              id: 'edit',
              label: 'Edit restaurant',
              icon: Pencil,
              onClick: (restaurant) => openEditModal(restaurant.id),
            },
            {
              id: 'app-client',
              label: 'App settings',
              icon: Smartphone,
              onClick: (restaurant) => onNavigate(`/admin/restaurants/${restaurant.id}/app-client`),
            },
            {
              id: 'approval',
              label: 'Toggle approval',
              icon: CheckCircle2,
              onClick: (restaurant) =>
                restaurant.is_approved
                  ? setPendingApprovalRevoke(restaurant)
                  : void toggleApproval(restaurant),
              tone: 'success',
            },
            {
              id: 'delete',
              label: 'Archive restaurant',
              icon: Trash2,
              onClick: requestDeleteRestaurant,
              tone: 'danger',
              disabled: () => isDeleteSubmitting,
            },
          ]}
          columns={columns}
          emptyAction={
            <button
              className="primary-button"
              onClick={() => setIsCreateOpen(true)}
              type="button"
            >
              + Add New Restaurant
            </button>
          }
          emptyDescription="Try a different search or approval filter."
          emptyTitle="No restaurants match the current filters"
          error={loadError}
          onRetry={() => {
            setLoadError(null);
            void loadRestaurants(true);
          }}
          keyExtractor={(restaurant) => restaurant.id}
          loading={isLoading}
          mobileStatus={(restaurant) => (
            <StatusPill status={restaurant.is_approved ? 'APPROVED' : 'PENDING'} />
          )}
          mobileSubtitle={(restaurant) => restaurant.slug}
          mobileTitle={(restaurant) => restaurant.name}
          onRowClick={(restaurant) => openRestaurantWorkspace(restaurant.id)}
          rows={pageItems}
        />
        <Pagination
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
          page={page}
          pageSize={pageSize}
          totalItems={filtered.length}
          totalPages={totalPages}
        />
      </section>

      <ConfirmDialog
        open={restaurantToDelete !== null}
        eyebrow="Restaurant archive"
        title={
          restaurantToDelete
            ? `Archive ${restaurantToDelete.name}?`
            : 'Archive restaurant?'
        }
        description="This will remove the restaurant from the active admin list while preserving historical data."
        confirmLabel="Archive restaurant"
        busy={isDeleteSubmitting}
        onCancel={() => {
          if (!isDeleteSubmitting) {
            setRestaurantToDelete(null);
          }
        }}
        onConfirm={() => {
          void deleteRestaurant();
        }}
        tone="danger"
      />

      <ConfirmDialog
        confirmLabel="Revoke approval"
        description={
          pendingApprovalRevoke
            ? `${pendingApprovalRevoke.name} will be hidden from customers until it is approved again.`
            : ''
        }
        eyebrow="Moderation"
        onCancel={() => setPendingApprovalRevoke(null)}
        onConfirm={() => {
          if (pendingApprovalRevoke) {
            void toggleApproval(pendingApprovalRevoke);
          }
          setPendingApprovalRevoke(null);
        }}
        open={Boolean(pendingApprovalRevoke)}
        title={
          pendingApprovalRevoke
            ? `Revoke approval for ${pendingApprovalRevoke.name}?`
            : 'Revoke approval?'
        }
        tone="danger"
      />

      {isCreateOpen ? (
        <Modal onClose={closeCreateModal} labelledBy="add-restaurant-title">
            <div className="panel__header modal-card__header">
              <div>
                <span className="eyebrow">Admin action</span>
                <h2 id="add-restaurant-title">Add New Restaurant</h2>
                <p className="hint-text">
                  Create the restaurant, its linked owner account, and its app client in one step.
                </p>
              </div>
              <button aria-label="Close add restaurant form" className="modal-close" onClick={closeCreateModal} type="button">
                ×
              </button>
            </div>

            <form className="form-grid modal-card__body" onSubmit={submitCreateRestaurant}>
              <div className="form-grid__section">
                <h3>Restaurant &amp; owner</h3>
                <p>The brand identity and the owner account that will manage it.</p>
              </div>
              <label className="field form-grid__wide">
                <span>Restaurant Name</span>
                <input
                  placeholder="Spice Route Kitchen"
                  required
                  value={createForm.name}
                  onChange={(event) => updateRestaurantName(event.target.value)}
                />
              </label>
              <label className="field">
                <span>Owner Name</span>
                <input
                  placeholder="Aarav Mehta"
                  required
                  value={createForm.owner_name}
                  onChange={(event) => setCreateForm((current) => ({ ...current, owner_name: event.target.value }))}
                />
              </label>
              <label className="field">
                <span>Owner Email</span>
                <input
                  type="email"
                  placeholder="owner@example.com"
                  required
                  value={createForm.owner_email}
                  onChange={(event) => setCreateForm((current) => ({ ...current, owner_email: event.target.value }))}
                />
              </label>
              <label className="field form-grid__wide">
                <span>Owner Password</span>
                <input
                  type="password"
                  minLength={8}
                  placeholder="Minimum 8 characters"
                  required
                  value={createForm.owner_password}
                  onChange={(event) => setCreateForm((current) => ({ ...current, owner_password: event.target.value }))}
                />
              </label>

              <div className="form-grid__section">
                <h3>App client</h3>
                <p>
                  Identity for this brand&apos;s mobile app. The app key, bundle IDs, and order prefix follow the
                  restaurant name until you edit them.
                </p>
              </div>
              <AppClientFields
                errors={createErrors}
                onDerivedFieldChange={updateAppField}
                onFieldChange={(field, value) => {
                  setCreateForm((current) => ({ ...current, [field]: value }));
                  setCreateErrors((current) => ({ ...current, [field]: undefined }));
                }}
                values={createForm}
              />

              <div className="form-grid__wide modal-actions">
                <button className="secondary-button" onClick={closeCreateModal} type="button">
                  Cancel
                </button>
                <button className="primary-button" disabled={isCreateSubmitting} type="submit">
                  {isCreateSubmitting ? 'Creating...' : 'Create Restaurant'}
                </button>
              </div>
            </form>
          </Modal>
      ) : null}
      {isEditOpen && selectedRestaurant ? (
        <Modal onClose={closeEditModal}>
            <div className="panel__header modal-card__header">
              <div>
                <span className="eyebrow">Restaurant editor</span>
                <h2>Edit {selectedRestaurant.name}</h2>
                <p className="hint-text">Update the operational details visible across the platform.</p>
              </div>
              <button aria-label="Close edit restaurant form" className="modal-close" onClick={closeEditModal} type="button">
                ×
              </button>
            </div>

            <form className="form-grid modal-card__body" onSubmit={submitEditRestaurant}>
              <label className="field form-grid__wide">
                <span>Restaurant Name</span>
                <input
                  required
                  value={editForm.name}
                  onChange={(event) => setEditForm((current) => ({ ...current, name: event.target.value }))}
                />
              </label>
              <label className="field">
                <span>Cuisine</span>
                <input
                  required
                  value={editForm.cuisine_type}
                  onChange={(event) => setEditForm((current) => ({ ...current, cuisine_type: event.target.value }))}
                />
              </label>
              <label className="field">
                <span>City</span>
                <input
                  required
                  value={editForm.city}
                  onChange={(event) => setEditForm((current) => ({ ...current, city: event.target.value }))}
                />
              </label>
              <label className="field form-grid__wide">
                <span>Address line 1</span>
                <input
                  required
                  value={editForm.address_line_1}
                  onChange={(event) => setEditForm((current) => ({ ...current, address_line_1: event.target.value }))}
                />
              </label>
              <label className="field">
                <span>Address line 2</span>
                <input
                  value={editForm.address_line_2}
                  onChange={(event) => setEditForm((current) => ({ ...current, address_line_2: event.target.value }))}
                />
              </label>
              <label className="field">
                <span>State</span>
                <input
                  required
                  value={editForm.state}
                  onChange={(event) => setEditForm((current) => ({ ...current, state: event.target.value }))}
                />
              </label>
              <label className="field">
                <span>Country</span>
                <input
                  required
                  value={editForm.country}
                  onChange={(event) => setEditForm((current) => ({ ...current, country: event.target.value }))}
                />
              </label>
              <label className="field">
                <span>Postal code</span>
                <input
                  required
                  value={editForm.postal_code}
                  onChange={(event) => setEditForm((current) => ({ ...current, postal_code: event.target.value }))}
                />
              </label>
              <label className="field">
                <span>Phone</span>
                <input
                  value={editForm.phone_number}
                  onChange={(event) => setEditForm((current) => ({ ...current, phone_number: event.target.value }))}
                />
              </label>
              <label className="field">
                <span>Minimum order amount</span>
                <input
                  min="0"
                  step="0.01"
                  type="number"
                  value={editForm.minimum_order_amount}
                  onChange={(event) => setEditForm((current) => ({ ...current, minimum_order_amount: event.target.value }))}
                />
              </label>
              <label className="field">
                <span>Delivery fee</span>
                <input
                  min="0"
                  step="0.01"
                  type="number"
                  value={editForm.delivery_fee}
                  onChange={(event) => setEditForm((current) => ({ ...current, delivery_fee: event.target.value }))}
                />
              </label>
              <label className="field form-grid__wide">
                <span>Description</span>
                <textarea
                  value={editForm.description}
                  onChange={(event) => setEditForm((current) => ({ ...current, description: event.target.value }))}
                />
              </label>
              <label className="field form-grid__wide">
                <span>Logo image URL</span>
                <input
                  value={editForm.logo_image_url}
                  onChange={(event) => setEditForm((current) => ({ ...current, logo_image_url: event.target.value }))}
                />
              </label>
              <label className="field form-grid__wide">
                <span>Cover image URL</span>
                <input
                  value={editForm.cover_image_url}
                  onChange={(event) => setEditForm((current) => ({ ...current, cover_image_url: event.target.value }))}
                />
              </label>
              <Checkbox
                checked={editForm.is_open}
                className="form-grid__wide"
                label="Open for orders"
                onChange={(checked) =>
                  setEditForm((current) => ({ ...current, is_open: checked }))
                }
              />
              <div className="form-grid__wide modal-actions">
                <button className="secondary-button" onClick={closeEditModal} type="button">
                  Cancel
                </button>
                <button className="primary-button" disabled={isEditSubmitting} type="submit">
                  {isEditSubmitting ? 'Saving...' : 'Save Changes'}
                </button>
              </div>
            </form>
          </Modal>
      ) : null}
    </div>
  );
}

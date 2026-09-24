/**
 * The logins a kitchen order board runs on.
 *
 * Until this screen existed the only way to create one was a curl call, so in
 * practice kitchens ran on the owner's own login — the token that also edits
 * the menu, spends marketing budget and reads revenue, left signed in on a
 * tablet on a wall. That is the whole reason `UserRole.KITCHEN` was added
 * (migration 0071); this is what makes it usable.
 *
 * **Every rule here belongs to the backend.** `resolve_order_board_scope`
 * decides which restaurant a caller may touch, the composite foreign key on
 * `users` decides whether a branch may be paired with a restaurant, and
 * `ck_users_kitchen_assignment` decides whether an assignment is well-formed
 * at all. This page picks; the server refuses. Nothing below is a substitute
 * for any of it — the field limits restated in `services/kitchenStaff.ts`
 * exist so a mistake is caught beside the field rather than as a 422 after
 * Create.
 *
 * There is no delete. Removing a login would take its audit trail with it —
 * `order_status_events.actor_user_id` points at these rows — so an account
 * that should stop working is deactivated, which the backend answers by
 * bumping `token_version` and ending the sessions already issued.
 */

import { ChefHat, Pencil, Power, Store, UserPlus } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { DataToolbar } from '../components/DataToolbar';
import { Modal } from '../components/Modal';
import { PageIntro } from '../components/PageIntro';
import { Pagination } from '../components/Pagination';
import { ResponsiveTable, type TableColumn } from '../components/ResponsiveTable';
import { StatePanel } from '../components/StatePanel';
import { StatusPill } from '../components/StatusPill';
import { RestaurantScopePicker } from '../components/marketing/RestaurantScopePicker';
import { useMarketingScope } from '../hooks/useMarketingScope';
import { ApiError, api, formatDate } from '../services/api';
import { pluralize } from '../services/format';
import {
  EMPTY_STAFF_FORM,
  branchLabel,
  buildStaffUpdate,
  hasErrors,
  validateStaffForm,
  type StaffFormErrors,
  type StaffFormValues,
} from '../services/kitchenStaff';
import { readWorkspaceSettings } from '../services/workspaceSettings';
import type { KitchenStaff, RestaurantLocation, UserRole } from '../types/app';

interface KitchenStaffPageProps {
  token: string;
  role: UserRole;
  /** The owner's own restaurant. Null for an admin, who chooses one. */
  restaurantId: string | null;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

type StatusFilter = 'ALL' | 'ACTIVE' | 'INACTIVE';

export function KitchenStaffPage({ token, role, restaurantId, onToast }: KitchenStaffPageProps) {
  const isAdmin = role === 'ADMIN';
  // The same hook the marketing screens use. Reused rather than reimplemented
  // because it already solves the one failure this page would otherwise
  // repeat: an admin with no restaurant chosen gets `400 restaurant_id is
  // required` and a screen that reads as broken instead of as a question.
  const scope = useMarketingScope();

  // Which restaurant this page is about. An admin picks; an owner has one and
  // may not name it — the backend refuses a `restaurant_id` that disagrees
  // with `Restaurant.owner_id`, so theirs is sent as null.
  const viewedRestaurantId = isAdmin ? scope.selectedRestaurantId : restaurantId;
  const scopeParam = isAdmin ? scope.selectedRestaurantId || null : null;
  const ready = isAdmin ? scope.ready : Boolean(restaurantId);

  const [staff, setStaff] = useState<KitchenStaff[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadNonce, setReloadNonce] = useState(0);

  /**
   * Loading is DERIVED, not stored.
   *
   * The obvious shape — `setIsLoading(true)` at the top of the fetch effect —
   * is a synchronous setState inside an effect, which cascades a render and
   * is what `react-hooks/set-state-in-effect` is pointing at. Comparing the
   * key the effect is fetching for against the key it last finished says the
   * same thing with no extra state and no extra render, and it covers the
   * case a boolean gets wrong anyway: switching restaurant shows the spinner
   * again immediately, because the key changed.
   */
  const loadKey = `${scopeParam ?? 'own'}|${reloadNonce}`;
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const isLoading = ready && loadedKey !== loadKey && loadError === null;

  /**
   * Branches, tagged with the restaurant they belong to.
   *
   * Tagged rather than cleared in an effect for the same reason, and it also
   * removes a real flicker: an admin switching restaurant would otherwise see
   * the previous restaurant's branches in the dropdowns until the new fetch
   * landed, which on this page means offering an assignment the server would
   * refuse.
   */
  const [branchData, setBranchData] = useState<{
    restaurantId: string;
    rows: RestaurantLocation[];
  } | null>(null);
  const branches =
    branchData && branchData.restaurantId === viewedRestaurantId ? branchData.rows : [];

  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => readWorkspaceSettings().defaultPageSize);

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [createForm, setCreateForm] = useState<StaffFormValues>(EMPTY_STAFF_FORM);
  const [createErrors, setCreateErrors] = useState<StaffFormErrors>({});
  const [isCreating, setIsCreating] = useState(false);

  const [editStaff, setEditStaff] = useState<KitchenStaff | null>(null);
  const [editForm, setEditForm] = useState<StaffFormValues>(EMPTY_STAFF_FORM);
  const [editErrors, setEditErrors] = useState<StaffFormErrors>({});
  const [isSaving, setIsSaving] = useState(false);

  const [pendingDeactivation, setPendingDeactivation] = useState<KitchenStaff | null>(null);
  const [isTogglingId, setIsTogglingId] = useState<string | null>(null);

  // Not cached in `pageCache`, unlike the sibling list screens. A staff list
  // is short, changes because of what happens on this very page, and is the
  // answer to "who can open the kitchen right now" — a stale one read from a
  // previous session is the wrong kind of convenience.
  useEffect(() => {
    if (!ready) {
      return;
    }
    let cancelled = false;
    // Every setState below is in a promise callback, never in the effect body
    // — the distinction the lint rule draws, and the one that keeps this to a
    // single render per answer.
    api
      .getKitchenStaff(token, scopeParam)
      .then((rows) => {
        if (cancelled) {
          return;
        }
        setStaff(rows);
        setLoadError(null);
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        setLoadError(
          error instanceof ApiError ? error.message : 'Unable to load kitchen staff.',
        );
      })
      .finally(() => {
        if (!cancelled) {
          setLoadedKey(loadKey);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [ready, scopeParam, token, loadKey]);

  // The branches this restaurant has, for both the assignment dropdowns and
  // the filter. A failure here is not fatal: the list still renders, and
  // "All branches" remains a valid assignment.
  useEffect(() => {
    if (!viewedRestaurantId) {
      return;
    }
    const restaurantId = viewedRestaurantId;
    let cancelled = false;
    api
      .getRestaurantLocations(token, restaurantId)
      .then((rows) => {
        if (!cancelled) {
          setBranchData({ restaurantId, rows });
        }
      })
      .catch(() => {
        // Not fatal. The list still renders and "All branches" is still a
        // valid assignment; only the per-branch choices are missing.
        if (!cancelled) {
          setBranchData({ restaurantId, rows: [] });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, viewedRestaurantId]);

  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    return staff.filter((row) => {
      const matchesQuery =
        !normalized ||
        [row.full_name, row.email, row.branch_name ?? '']
          .some((value) => value.toLowerCase().includes(normalized));
      const matchesStatus =
        statusFilter === 'ALL' || (statusFilter === 'ACTIVE' ? row.is_active : !row.is_active);
      return matchesQuery && matchesStatus;
    });
  }, [query, statusFilter, staff]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const pageItems = filtered.slice((page - 1) * pageSize, page * pageSize);

  // Adjusted during render rather than in an effect — React's own
  // recommendation for "reset state when something changes", and it avoids the
  // extra render an effect costs. Without it, narrowing a filter while on page
  // three leaves the table on a page that no longer has rows.
  const filterKey = `${pageSize}|${query}|${statusFilter}|${scopeParam ?? ''}`;
  const [lastFilterKey, setLastFilterKey] = useState(filterKey);
  if (filterKey !== lastFilterKey) {
    setLastFilterKey(filterKey);
    setPage(1);
  }

  const syncStaff = useCallback((updated: KitchenStaff) => {
    setStaff((current) => current.map((row) => (row.id === updated.id ? updated : row)));
  }, []);

  const openCreate = () => {
    setCreateForm(EMPTY_STAFF_FORM);
    setCreateErrors({});
    setIsCreateOpen(true);
  };

  const submitCreate = async () => {
    const errors = validateStaffForm(createForm, 'create');
    if (hasErrors(errors)) {
      setCreateErrors(errors);
      return;
    }
    setIsCreating(true);
    try {
      const created = await api.createKitchenStaff(token, {
        full_name: createForm.full_name.trim(),
        email: createForm.email.trim(),
        password: createForm.password,
        phone_number: createForm.phone_number.trim() || null,
        // '' is "every branch", which the API expresses by omitting the field.
        restaurant_location_id: createForm.restaurant_location_id || null,
        restaurant_id: scopeParam,
      });
      setStaff((current) => [created, ...current]);
      setIsCreateOpen(false);
      onToast(
        'Kitchen account created',
        `${created.full_name} can now sign into the kitchen board for ${branchLabel(created).toLowerCase()}.`,
        'success',
      );
    } catch (error: unknown) {
      const message =
        error instanceof ApiError ? error.message : 'Unable to create this kitchen account.';
      // A clash is about one field, so it belongs beside that field. Anything
      // else is about the request and belongs in a toast.
      if (error instanceof ApiError && error.status === 409) {
        setCreateErrors({ email: message });
      } else {
        onToast('Could not create account', message, 'error');
      }
    } finally {
      setIsCreating(false);
    }
  };

  const openEdit = (row: KitchenStaff) => {
    setEditStaff(row);
    setEditForm({
      ...EMPTY_STAFF_FORM,
      full_name: row.full_name,
      email: row.email,
      phone_number: row.phone_number ?? '',
      restaurant_location_id: row.restaurant_location_id ?? '',
    });
    setEditErrors({});
  };

  const submitEdit = async () => {
    if (!editStaff) {
      return;
    }
    const errors = validateStaffForm(editForm, 'edit');
    if (hasErrors(errors)) {
      setEditErrors(errors);
      return;
    }
    const payload = buildStaffUpdate(editStaff, {
      full_name: editForm.full_name,
      restaurant_location_id: editForm.restaurant_location_id,
    });
    if (Object.keys(payload).length === 0) {
      // Nothing changed. A no-op PATCH that reassigns the same branch still
      // bumps `token_version` server-side, which would sign a cook out of a
      // board they are standing at for no reason at all.
      setEditStaff(null);
      return;
    }

    setIsSaving(true);
    try {
      const updated = await api.updateKitchenStaff(token, editStaff.id, payload, scopeParam);
      syncStaff(updated);
      setEditStaff(null);
      onToast(
        'Kitchen account updated',
        payload.restaurant_location_id || payload.clear_restaurant_location
          ? `${updated.full_name} now works ${branchLabel(updated).toLowerCase()} and has been signed out of the board.`
          : `${updated.full_name} was updated.`,
        'success',
      );
    } catch (error: unknown) {
      const message =
        error instanceof ApiError ? error.message : 'Unable to update this kitchen account.';
      onToast('Could not save changes', message, 'error');
    } finally {
      setIsSaving(false);
    }
  };

  const setActive = async (row: KitchenStaff, isActive: boolean) => {
    setIsTogglingId(row.id);
    try {
      const updated = await api.updateKitchenStaff(
        token,
        row.id,
        { is_active: isActive },
        scopeParam,
      );
      syncStaff(updated);
      onToast(
        isActive ? 'Account reactivated' : 'Account deactivated',
        isActive
          ? `${updated.full_name} can sign into the kitchen board again.`
          : `${updated.full_name} has been signed out of the board immediately.`,
        'success',
      );
    } catch (error: unknown) {
      const message =
        error instanceof ApiError ? error.message : 'Unable to change this account.';
      onToast('Could not change the account', message, 'error');
    } finally {
      setIsTogglingId(null);
    }
  };

  const columns: Array<TableColumn<KitchenStaff>> = [
    {
      id: 'person',
      header: 'Kitchen account',
      render: (row) => (
        <div className="usr-cell">
          <div className="usr-cell__copy">
            <strong>{row.full_name}</strong>
            <span>{row.email}</span>
          </div>
        </div>
      ),
      mobileLabel: 'Account',
      hideOnMobile: true,
    },
    {
      id: 'branch',
      header: 'Assigned branch',
      render: (row) => (
        <span className="kds-branch">
          <Store size={12} strokeWidth={2.2} />
          {branchLabel(row)}
        </span>
      ),
      mobileLabel: 'Branch',
    },
    {
      id: 'status',
      header: 'Status',
      render: (row) => <StatusPill status={row.is_active ? 'ACTIVE' : 'INACTIVE'} />,
      mobileLabel: 'Status',
    },
    {
      id: 'added',
      header: 'Added',
      render: (row) => formatDate(row.created_at),
      mobileLabel: 'Added',
    },
  ];

  if (!ready) {
    return (
      <div className="page-stack">
        <PageIntro
          eyebrow="Kitchen"
          title="Kitchen staff"
          description="The logins your kitchen order board runs on."
        />
        <StatePanel
          action={<RestaurantScopePicker scope={scope} />}
          description={
            scope.restaurants.length > 0
              ? 'Kitchen accounts belong to one restaurant. Choose which.'
              : 'No restaurants are available on this account yet.'
          }
          icon={ChefHat}
          title="Whose kitchen?"
        />
      </div>
    );
  }

  const activeCount = staff.filter((row) => row.is_active).length;

  return (
    <div className="page-stack">
      <PageIntro
        actions={
          <button className="primary-button" onClick={openCreate} type="button">
            <UserPlus size={16} strokeWidth={2.2} />
            Add kitchen staff
          </button>
        }
        eyebrow="Kitchen"
        title="Kitchen staff"
        description="Accounts that open the order board. Each one sees a single branch, or every branch of this restaurant — and nothing else."
      />

      <section className="admin-surface">
        <DataToolbar
          actions={
            <span className="toolbar-meta">
              {pluralize(filtered.length, 'account')} · {activeCount} active
            </span>
          }
          filters={
            <>
              {isAdmin ? <RestaurantScopePicker scope={scope} /> : null}
              <select
                className="page-search page-search--select"
                onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
                value={statusFilter}
              >
                <option value="ALL">All statuses</option>
                <option value="ACTIVE">Active</option>
                <option value="INACTIVE">Inactive</option>
              </select>
            </>
          }
          onSearchChange={setQuery}
          searchPlaceholder="Filter by name, email, or branch"
          searchValue={query}
        />

        <ResponsiveTable
          actions={[
            {
              id: 'edit',
              label: 'Edit account',
              icon: Pencil,
              onClick: (row: KitchenStaff) => openEdit(row),
            },
            {
              id: 'deactivate',
              label: 'Deactivate account',
              icon: Power,
              onClick: (row: KitchenStaff) => setPendingDeactivation(row),
              hidden: (row: KitchenStaff) => !row.is_active,
              disabled: (row: KitchenStaff) => isTogglingId === row.id,
              tone: 'danger' as const,
            },
            {
              id: 'activate',
              label: 'Reactivate account',
              icon: Power,
              onClick: (row: KitchenStaff) => void setActive(row, true),
              hidden: (row: KitchenStaff) => row.is_active,
              disabled: (row: KitchenStaff) => isTogglingId === row.id,
              tone: 'success' as const,
            },
          ]}
          columns={columns}
          emptyAction={
            query || statusFilter !== 'ALL' ? (
              <button
                className="secondary-button"
                onClick={() => {
                  setQuery('');
                  setStatusFilter('ALL');
                }}
                type="button"
              >
                Clear filters
              </button>
            ) : (
              <button className="primary-button" onClick={openCreate} type="button">
                Add kitchen staff
              </button>
            )
          }
          emptyDescription={
            query || statusFilter !== 'ALL'
              ? 'Try a different status or search query.'
              : 'Create one and the kitchen can open the board without anyone signing in as the owner.'
          }
          emptyTitle={
            query || statusFilter !== 'ALL'
              ? 'No accounts match the current filters'
              : 'No kitchen accounts yet'
          }
          error={loadError}
          errorTitle="We couldn't load kitchen staff"
          keyExtractor={(row) => row.id}
          loading={isLoading}
          mobileStatus={(row) => <StatusPill status={row.is_active ? 'ACTIVE' : 'INACTIVE'} />}
          mobileSubtitle={(row) => `${row.email} · ${branchLabel(row)}`}
          mobileTitle={(row) => row.full_name}
          onRetry={() => {
            setLoadError(null);
            setReloadNonce((current) => current + 1);
          }}
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

      {isCreateOpen ? (
        <Modal
          busy={isCreating}
          className="modal-card--compact"
          labelledBy="create-kitchen-title"
          onClose={() => setIsCreateOpen(false)}
        >
          <div className="panel__header modal-card__header">
            <div>
              <span className="eyebrow">Kitchen account</span>
              <h2 id="create-kitchen-title">Add kitchen staff</h2>
              <p className="hint-text">
                They sign into the kitchen board with this email and password.
              </p>
            </div>
            <button
              aria-label="Close"
              className="modal-close"
              onClick={() => setIsCreateOpen(false)}
              type="button"
            >
              ×
            </button>
          </div>

          <form
            className="form-grid modal-card__body"
            onSubmit={(event) => {
              event.preventDefault();
              void submitCreate();
            }}
          >
            <label className={`field${createErrors.full_name ? ' field--invalid' : ''}`}>
              <span>Full name</span>
              <input
                autoFocus
                disabled={isCreating}
                onChange={(event) =>
                  setCreateForm((current) => ({ ...current, full_name: event.target.value }))
                }
                placeholder="Night Cook"
                value={createForm.full_name}
              />
              {createErrors.full_name ? (
                <small className="field__error">{createErrors.full_name}</small>
              ) : null}
            </label>

            <label className={`field${createErrors.phone_number ? ' field--invalid' : ''}`}>
              <span>Phone (optional)</span>
              <input
                disabled={isCreating}
                onChange={(event) =>
                  setCreateForm((current) => ({ ...current, phone_number: event.target.value }))
                }
                value={createForm.phone_number}
              />
              {createErrors.phone_number ? (
                <small className="field__error">{createErrors.phone_number}</small>
              ) : null}
            </label>

            <label className={`field${createErrors.email ? ' field--invalid' : ''}`}>
              <span>Email</span>
              <input
                autoComplete="off"
                disabled={isCreating}
                onChange={(event) =>
                  setCreateForm((current) => ({ ...current, email: event.target.value }))
                }
                placeholder="cook@example.com"
                type="email"
                value={createForm.email}
              />
              <small className={createErrors.email ? 'field__error' : 'hint-text'}>
                {createErrors.email ?? 'Cannot be changed afterwards.'}
              </small>
            </label>

            <label className={`field${createErrors.password ? ' field--invalid' : ''}`}>
              <span>Password</span>
              <input
                autoComplete="new-password"
                disabled={isCreating}
                onChange={(event) =>
                  setCreateForm((current) => ({ ...current, password: event.target.value }))
                }
                type="password"
                value={createForm.password}
              />
              <small className={createErrors.password ? 'field__error' : 'hint-text'}>
                {createErrors.password ?? 'At least 8 characters. Share it with the kitchen.'}
              </small>
            </label>

            <label className="field form-grid__wide">
              <span>Branch</span>
              <select
                disabled={isCreating}
                onChange={(event) =>
                  setCreateForm((current) => ({
                    ...current,
                    restaurant_location_id: event.target.value,
                  }))
                }
                value={createForm.restaurant_location_id}
              >
                {/* Not a "none" placeholder: every branch is a real assignment,
                    and the right one for a single-branch restaurant. */}
                <option value="">All branches of this restaurant</option>
                {branches.map((branch) => (
                  <option key={branch.id} value={branch.id}>
                    {branch.branch_name}
                  </option>
                ))}
              </select>
              <small className="hint-text">
                A pinned account sees only that branch’s orders and gets no branch picker.
              </small>
            </label>

            <div className="form-grid__wide modal-actions">
              <button
                className="secondary-button"
                disabled={isCreating}
                onClick={() => setIsCreateOpen(false)}
                type="button"
              >
                Cancel
              </button>
              <button className="primary-button" disabled={isCreating} type="submit">
                {isCreating ? 'Creating…' : 'Create account'}
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

      {editStaff ? (
        <Modal
          busy={isSaving}
          className="modal-card--compact"
          labelledBy="edit-kitchen-title"
          onClose={() => setEditStaff(null)}
        >
          <div className="panel__header modal-card__header">
            <div>
              <span className="eyebrow">Kitchen account</span>
              <h2 id="edit-kitchen-title">Edit {editStaff.full_name}</h2>
              <p className="hint-text">{editStaff.email}</p>
            </div>
            <button
              aria-label="Close"
              className="modal-close"
              onClick={() => setEditStaff(null)}
              type="button"
            >
              ×
            </button>
          </div>

          <form
            className="form-grid modal-card__body"
            onSubmit={(event) => {
              event.preventDefault();
              void submitEdit();
            }}
          >
            <label className={`field${editErrors.full_name ? ' field--invalid' : ''}`}>
              <span>Full name</span>
              <input
                autoFocus
                disabled={isSaving}
                onChange={(event) =>
                  setEditForm((current) => ({ ...current, full_name: event.target.value }))
                }
                value={editForm.full_name}
              />
              {editErrors.full_name ? (
                <small className="field__error">{editErrors.full_name}</small>
              ) : null}
            </label>

            <label className="field">
              <span>Email</span>
              {/* Read-only because the server refuses to change it: re-pointing
                  a live login at a different person is how a revoked account
                  quietly comes back. */}
              <input readOnly value={editStaff.email} />
              <small className="hint-text">Deactivate and create another instead.</small>
            </label>

            <label className="field form-grid__wide">
              <span>Branch</span>
              <select
                disabled={isSaving}
                onChange={(event) =>
                  setEditForm((current) => ({
                    ...current,
                    restaurant_location_id: event.target.value,
                  }))
                }
                value={editForm.restaurant_location_id}
              >
                <option value="">All branches of this restaurant</option>
                {branches.map((branch) => (
                  <option key={branch.id} value={branch.id}>
                    {branch.branch_name}
                  </option>
                ))}
              </select>
              <small className="hint-text">
                Moving someone signs them out, so the old branch’s board closes on their tablet.
              </small>
            </label>

            <div className="form-grid__wide modal-actions">
              <button
                className="secondary-button"
                disabled={isSaving}
                onClick={() => setEditStaff(null)}
                type="button"
              >
                Cancel
              </button>
              <button className="primary-button" disabled={isSaving} type="submit">
                {isSaving ? 'Saving…' : 'Save changes'}
              </button>
            </div>
          </form>
        </Modal>
      ) : null}

      <ConfirmDialog
        busy={Boolean(pendingDeactivation && isTogglingId === pendingDeactivation.id)}
        cancelLabel="Keep active"
        confirmLabel="Deactivate account"
        description={
          pendingDeactivation
            ? `${pendingDeactivation.full_name} (${pendingDeactivation.email}) will be signed out of the kitchen board immediately. Their past order history is kept, and you can reactivate the account at any time.`
            : ''
        }
        eyebrow="Kitchen access"
        onCancel={() => setPendingDeactivation(null)}
        onConfirm={() => {
          if (pendingDeactivation) {
            void setActive(pendingDeactivation, false);
          }
          setPendingDeactivation(null);
        }}
        open={Boolean(pendingDeactivation)}
        title={
          pendingDeactivation ? `Deactivate ${pendingDeactivation.full_name}?` : 'Deactivate account?'
        }
        tone="danger"
      />
    </div>
  );
}

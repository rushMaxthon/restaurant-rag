import { ChefHat, Eye, Pencil, Power, Shield, Store, UserRound, Users as UsersIcon } from 'lucide-react';
import { useEffect, useState } from 'react';
import { Modal } from '../components/Modal';
import { ConfirmDialog } from '../components/ConfirmDialog';
import { DataToolbar } from '../components/DataToolbar';
import { StatTiles, type StatTileItem } from '../components/StatTiles';
import { PageIntro } from '../components/PageIntro';
import { Pagination } from '../components/Pagination';
import { ResponsiveTable, type TableColumn } from '../components/ResponsiveTable';
import { readWorkspaceSettings } from '../services/workspaceSettings';
import { ApiError, api, formatDate } from '../services/api';
import { pluralize } from '../services/format';
import { StatusPill } from '../components/StatusPill';
import type { AdminUserStats, User, UserRole } from '../types/app';

interface AdminUsersPageProps {
  token: string;
  currentUserId: string;
  /** Owners see only their own app's customers; the backend does the scoping. */
  role: UserRole;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

type RoleFilter = 'ALL' | UserRole;

// Exhaustive on purpose. `/admin/users` returns EVERY account to an admin, so
// a role missing from this map is not a cosmetic gap — `meta.icon` throws and
// takes the whole page down. Kitchen accounts started appearing here the
// moment the role existed.
const ROLE_META: Record<UserRole, { label: string; icon: typeof Shield }> = {
  ADMIN: { label: 'Admin', icon: Shield },
  OWNER: { label: 'Owner', icon: Store },
  CUSTOMER: { label: 'Customer', icon: UserRound },
  KITCHEN: { label: 'Kitchen', icon: ChefHat },
};

// Shared with NotificationsPage, which fetches the exact same user list to
// estimate its audience size - one fetch serves both.
export function buildAdminUsersCacheKey(scope: string): string {
  return `admin-users:${scope}`;
}

export function AdminUsersPage({
  token,
  currentUserId,
  role,
  onToast,
}: AdminUsersPageProps) {
  // An owner's list is already narrowed to their customers server-side, so the
  // role dimension (tiles, filter, column) carries no information for them.
  const isOwnerView = role === 'OWNER';
  // One page at a time, filtered by the server (2026-10-07 security review:
  // this page used to download every account and filter it here). The
  // backend still scopes it per session: an owner's is their own customers.
  const [users, setUsers] = useState<User[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<AdminUserStats | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Bumped by Try again, and after an edit, so the page and tiles refetch.
  const [reloadNonce, setReloadNonce] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [query, setQuery] = useState('');
  // What the server is asked for: the search box, a moment after typing stops.
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState<RoleFilter>('ALL');
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'ACTIVE' | 'INACTIVE'>('ALL');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(() => readWorkspaceSettings().defaultPageSize);
  const [pendingDeactivation, setPendingDeactivation] = useState<User | null>(null);
  const [viewUser, setViewUser] = useState<User | null>(null);
  const [editUser, setEditUser] = useState<User | null>(null);
  const [editForm, setEditForm] = useState({ full_name: '', phone_number: '', default_address: '' });
  const [isEditSubmitting, setIsEditSubmitting] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    let current = true;
    api
      .getAdminUsers(token, {
        page,
        pageSize,
        search: search || undefined,
        role: roleFilter === 'ALL' ? null : roleFilter,
        status: statusFilter === 'ALL' ? null : statusFilter,
      })
      .then(({ rows, total: count }) => {
        if (!current) return;
        setUsers(rows);
        setTotal(count);
        setLoadError(null);
      })
      .catch((error: unknown) => {
        if (!current) return;
        const message = error instanceof ApiError ? error.message : 'Unable to load users.';
        // Keeps the failure on screen after the toast fades, and gives it a way out.
        setLoadError(message);
        onToast('Users unavailable', message, 'error');
      })
      .finally(() => {
        if (current) setIsLoading(false);
      });
    return () => {
      current = false;
    };
  }, [onToast, page, pageSize, reloadNonce, roleFilter, search, statusFilter, token]);

  useEffect(() => {
    let current = true;
    api
      .getAdminUserStats(token)
      .then((next) => {
        if (current) setStats(next);
      })
      .catch(() => {
        // The tiles stay at zero; the list's own error says what went wrong.
      });
    return () => {
      current = false;
    };
  }, [reloadNonce, token]);

  const noCount = { total: 0, active: 0 };
  const roleStats = stats ?? { all: noCount, ADMIN: noCount, OWNER: noCount, KITCHEN: noCount, CUSTOMER: noCount };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  useEffect(() => {
    setPage(1);
  }, [pageSize, search, roleFilter, statusFilter]);

  const syncUser = (updated: User) => {
    setUsers((current) => current.map((entry) => (entry.id === updated.id ? updated : entry)));
  };

  // Re-fetched rather than reused from the list so the modal reflects the
  // server's current state, and so the scope check runs for this exact user.
  const openUser = async (user: User, mode: 'view' | 'edit') => {
    try {
      const fresh = await api.getAdminUser(token, user.id);
      syncUser(fresh);
      if (mode === 'view') {
        setViewUser(fresh);
        return;
      }
      setEditForm({
        full_name: fresh.full_name,
        phone_number: fresh.phone_number ?? '',
        default_address: fresh.default_address ?? '',
      });
      setEditUser(fresh);
    } catch (error: unknown) {
      const message = error instanceof ApiError ? error.message : 'Unable to load this customer.';
      onToast('Customer unavailable', message, 'error');
    }
  };

  const submitEditUser = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editUser || isEditSubmitting) {
      return;
    }

    setIsEditSubmitting(true);
    try {
      const updated = await api.updateAdminUserDetails(token, editUser.id, {
        full_name: editForm.full_name.trim(),
        phone_number: editForm.phone_number.trim() || null,
        default_address: editForm.default_address.trim() || null,
      });
      syncUser(updated);
      setEditUser(null);
      onToast('Customer updated', `${updated.full_name} was updated successfully.`, 'success');
    } catch (error: unknown) {
      const message = error instanceof ApiError ? error.message : 'Unable to update this customer.';
      onToast('Update failed', message, 'error');
    } finally {
      setIsEditSubmitting(false);
    }
  };

  const columns: Array<TableColumn<User>> = [
    {
      id: 'user',
      header: 'User',
      render: (user) => (
        <div className="usr-cell">
          <div className="usr-cell__copy">
            <strong>
              {user.full_name}
              {user.id === currentUserId ? (
                <em className="usr-you">You</em>
              ) : null}
            </strong>
            <span>{user.email}</span>
          </div>
        </div>
      ),
      mobileLabel: 'User',
      hideOnMobile: true,
    },
    {
      id: 'role',
      header: 'Role',
      render: (user) => {
        const meta = ROLE_META[user.role];
        const Icon = meta.icon;
        return (
          <span className={`usr-role usr-role--${user.role.toLowerCase()}`}>
            <Icon size={12} strokeWidth={2.2} />
            {meta.label}
          </span>
        );
      },
      mobileLabel: 'Role',
    },
    {
      id: 'app',
      header: 'App / Restaurant',
      render: (user) => {
        // Only customers belong to an app; staff are platform-wide.
        if (!user.app_label) {
          return <span className="usr-app usr-app--platform">Platform</span>;
        }
        return (
          <div className="usr-app">
            <strong>{user.app_label}</strong>
            <span>
              {user.app_mode === 'MARKETPLACE'
                ? 'Marketplace'
                : user.restaurant_name ?? 'Single restaurant'}
            </span>
          </div>
        );
      },
      mobileLabel: 'App',
    },
    {
      id: 'status',
      header: 'Status',
      render: (user) => <StatusPill status={user.is_active ? 'ACTIVE' : 'INACTIVE'} />,
      mobileLabel: 'Status',
    },
    {
      id: 'joined',
      header: 'Joined',
      render: (user) => formatDate(user.created_at),
      mobileLabel: 'Joined',
    },
  ];

  const toggleUser = async (user: User) => {
    try {
      const updated = await api.updateUserStatus(token, user.id, !user.is_active);
      syncUser(updated);
      onToast('User updated', `${updated.full_name} is now ${updated.is_active ? 'active' : 'inactive'}.`, 'success');
    } catch (error: unknown) {
      const message = error instanceof ApiError ? error.message : 'Unable to update user status.';
      onToast('User update failed', message, 'error');
    }
  };

  const roleTiles: Array<StatTileItem<RoleFilter>> = [
    { key: 'ALL', label: 'All accounts', icon: UsersIcon, value: roleStats.all.total, hint: `${roleStats.all.active} active` },
    { key: 'ADMIN', label: 'Admins', icon: Shield, value: roleStats.ADMIN.total, hint: `${roleStats.ADMIN.active} active` },
    { key: 'OWNER', label: 'Owners', icon: Store, value: roleStats.OWNER.total, hint: `${roleStats.OWNER.active} active` },
    { key: 'KITCHEN', label: 'Kitchen', icon: ChefHat, value: roleStats.KITCHEN.total, hint: `${roleStats.KITCHEN.active} active` },
    { key: 'CUSTOMER', label: 'Customers', icon: UserRound, value: roleStats.CUSTOMER.total, hint: `${roleStats.CUSTOMER.active} active` },
  ];

  return (
    <div className="page-stack">
      <PageIntro
        help="users"
        eyebrow={isOwnerView ? 'My restaurant' : 'Access control'}
        title={isOwnerView ? 'Customers' : 'Users'}
        description={
          isOwnerView
            ? 'Customers who signed up in your restaurant app.'
            : 'Everyone who can sign in. Search by name or role, and switch an account off when it should no longer have access.'
        }
      />

      <StatTiles<RoleFilter>
        active={roleFilter}
        ariaLabel={isOwnerView ? 'Customer totals' : 'Role distribution'}
        loading={isLoading}
        onSelect={setRoleFilter}
        tiles={isOwnerView ? roleTiles.filter((tile) => tile.key === 'ALL') : roleTiles}
      />

      <section className="admin-surface">
        <DataToolbar
          actions={
            <span className="toolbar-meta">
              {pluralize(total, isOwnerView ? 'customer' : 'account')}
            </span>
          }
          filters={
            <>
              {isOwnerView ? null : (
                <select
                  className="page-search page-search--select"
                  onChange={(event) => setRoleFilter(event.target.value as RoleFilter)}
                  value={roleFilter}
                >
                  <option value="ALL">All roles</option>
                  <option value="ADMIN">Admins</option>
                  <option value="OWNER">Owners</option>
                  <option value="KITCHEN">Kitchen staff</option>
                  <option value="CUSTOMER">Customers</option>
                </select>
              )}
              <select
                className="page-search page-search--select"
                onChange={(event) => setStatusFilter(event.target.value as typeof statusFilter)}
                value={statusFilter}
              >
                <option value="ALL">All statuses</option>
                <option value="ACTIVE">Active</option>
                <option value="INACTIVE">Inactive</option>
              </select>
            </>
          }
          onSearchChange={setQuery}
          searchPlaceholder="Filter by name, email, or role"
          searchValue={query}
        />
        <ResponsiveTable
          actions={[
            {
              id: 'view',
              label: 'View customer details',
              icon: Eye,
              onClick: (user) => void openUser(user, 'view'),
            },
            {
              id: 'edit',
              label: 'Edit customer details',
              icon: Pencil,
              onClick: (user) => void openUser(user, 'edit'),
            },
            // Account status is a platform decision, so owners get a
            // details-only view of their customers.
            ...(isOwnerView ? [] : [
            {
              id: 'deactivate',
              label: 'Deactivate account',
              icon: Power,
              onClick: (user: User) => setPendingDeactivation(user),
              hidden: (user: User) => !user.is_active,
              disabled: (user: User) => user.id === currentUserId,
              tone: 'danger' as const,
            },
            {
              id: 'activate',
              label: 'Activate account',
              icon: Power,
              onClick: toggleUser,
              hidden: (user: User) => user.is_active,
              disabled: (user: User) => user.id === currentUserId,
              tone: 'success' as const,
            },
            ]),
          ]}
          columns={
            // Every row is a customer of this one app, so the role column
            // would repeat the same value on every line.
            isOwnerView ? columns.filter((column) => column.id !== 'role') : columns
          }
          emptyAction={
            query || roleFilter !== 'ALL' || statusFilter !== 'ALL' ? (
              <button
                className="secondary-button"
                onClick={() => {
                  setQuery('');
                  setRoleFilter('ALL');
                  setStatusFilter('ALL');
                }}
                type="button"
              >
                Clear filters
              </button>
            ) : null
          }
          emptyDescription="Try a different role, status, or search query."
          emptyTitle="No users match the current filters"
          errorTitle="We couldn't load users"
          error={loadError}
          onRetry={() => {
            setLoadError(null);
            setReloadNonce((current) => current + 1);
          }}
          keyExtractor={(user) => user.id}
          loading={isLoading}
          mobileStatus={(user) => (
            <StatusPill status={user.is_active ? 'ACTIVE' : 'INACTIVE'} />
          )}
          mobileSubtitle={(user) => user.email}
          mobileTitle={(user) => user.full_name}
          rows={users}
        />
        <Pagination
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
          page={page}
          pageSize={pageSize}
          totalItems={total}
          totalPages={totalPages}
        />
      </section>

      <ConfirmDialog
        confirmLabel="Deactivate account"
        description={
          pendingDeactivation
            ? `${pendingDeactivation.full_name} (${pendingDeactivation.email}) will immediately lose access to the platform. You can reactivate the account at any time.`
            : ''
        }
        eyebrow="Access control"
        onCancel={() => setPendingDeactivation(null)}
        onConfirm={() => {
          if (pendingDeactivation) {
            void toggleUser(pendingDeactivation);
          }
          setPendingDeactivation(null);
        }}
        open={Boolean(pendingDeactivation)}
        title={
          pendingDeactivation
            ? `Deactivate ${pendingDeactivation.full_name}?`
            : 'Deactivate account?'
        }
        tone="danger"
      />

      {viewUser ? (
        <Modal onClose={() => setViewUser(null)} labelledBy="view-customer-title" className="modal-card--compact">
            <div className="panel__header modal-card__header">
              <div>
                <span className="eyebrow">Customer details</span>
                <h2 id="view-customer-title">{viewUser.full_name}</h2>
                <p className="hint-text">{viewUser.app_label ?? 'Platform account'}</p>
              </div>
              <button aria-label="Close customer details" className="modal-close" onClick={() => setViewUser(null)} type="button">
                ×
              </button>
            </div>

            <div className="form-grid modal-card__body">
              <label className="field">
                <span>Email</span>
                <input readOnly value={viewUser.email} />
              </label>
              <label className="field">
                <span>Phone</span>
                <input readOnly value={viewUser.phone_number ?? '—'} />
              </label>
              <label className="field">
                <span>App / Restaurant</span>
                <input readOnly value={viewUser.app_label ?? 'Platform'} />
              </label>
              <label className="field">
                <span>Status</span>
                <input readOnly value={viewUser.is_active ? 'Active' : 'Inactive'} />
              </label>
              <label className="field form-grid__wide">
                <span>Default address</span>
                <textarea readOnly value={viewUser.default_address ?? '—'} />
              </label>
              <label className="field">
                <span>Joined</span>
                <input readOnly value={formatDate(viewUser.created_at)} />
              </label>
              <label className="field">
                <span>Last updated</span>
                <input readOnly value={formatDate(viewUser.updated_at)} />
              </label>
              <div className="form-grid__wide modal-actions">
                <button className="secondary-button" onClick={() => setViewUser(null)} type="button">
                  Close
                </button>
                <button
                  className="primary-button"
                  onClick={() => {
                    const target = viewUser;
                    setViewUser(null);
                    void openUser(target, 'edit');
                  }}
                  type="button"
                >
                  Edit details
                </button>
              </div>
            </div>
          </Modal>
      ) : null}

      {editUser ? (
        <Modal onClose={() => setEditUser(null)} labelledBy="edit-customer-title" className="modal-card--compact">
            <div className="panel__header modal-card__header">
              <div>
                <span className="eyebrow">Customer editor</span>
                <h2 id="edit-customer-title">Edit {editUser.full_name}</h2>
                <p className="hint-text">{editUser.email}</p>
              </div>
              <button aria-label="Close customer editor" className="modal-close" onClick={() => setEditUser(null)} type="button">
                ×
              </button>
            </div>

            <form className="form-grid modal-card__body" onSubmit={submitEditUser}>
              <label className="field form-grid__wide">
                <span>Full name</span>
                <input
                  minLength={2}
                  required
                  value={editForm.full_name}
                  onChange={(event) => setEditForm((current) => ({ ...current, full_name: event.target.value }))}
                />
              </label>
              <label className="field form-grid__wide">
                <span>Phone</span>
                <input
                  // The phone is a login; only the customer or the platform
                  // admin may change it. The server refuses an owner who does.
                  disabled={isOwnerView}
                  placeholder="+91 90000 00000"
                  value={editForm.phone_number}
                  onChange={(event) => setEditForm((current) => ({ ...current, phone_number: event.target.value }))}
                />
                <small className="hint-text">
                  {isOwnerView
                    ? 'The customer signs in with this number, so only they (or the platform admin) can change it.'
                    : 'Used to sign in, so it must be unique within this app.'}
                </small>
              </label>
              <label className="field form-grid__wide">
                <span>Default address</span>
                <textarea
                  value={editForm.default_address}
                  onChange={(event) => setEditForm((current) => ({ ...current, default_address: event.target.value }))}
                />
              </label>
              <label className="field form-grid__wide">
                <span>Email</span>
                <input disabled readOnly value={editUser.email} />
                <small className="hint-text">
                  Email is part of the sign-in identity for this app and cannot be changed here.
                </small>
              </label>
              <div className="form-grid__wide modal-actions">
                <button className="secondary-button" onClick={() => setEditUser(null)} type="button">
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

import {
  Building2,
  CircleSlash,
  Eye,
  Globe,
  PauseCircle,
  PlayCircle,
  Store,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { DataToolbar } from '../components/DataToolbar';
import { Modal } from '../components/Modal';
import { PageIntro } from '../components/PageIntro';
import { Pagination } from '../components/Pagination';
import { ResponsiveTable, type TableColumn } from '../components/ResponsiveTable';
import { StatTiles, type StatTileItem } from '../components/StatTiles';
import { StatusPill } from '../components/StatusPill';
import { useAdminStore } from '../hooks/useAdminStore';
import { ApiError, api, formatDate } from '../services/api';
import {
  getPageSnapshot,
  hasPageSnapshot,
  setPageSnapshot,
  tokenScope,
} from '../services/pageCache';
import type { AppClientStatus, TenantSummary } from '../types/app';

/**
 * Who is on this platform.
 *
 * Every other screen here answers a question about one restaurant. This one
 * answers the operator's question — six restaurants today, and the plan is
 * many — and it is the only place `app_clients.status` can be changed, which
 * makes it the sharpest control in the panel: anything other than ACTIVE stops
 * that tenant's storefront and app from answering at all.
 *
 * So the lifecycle dialog asks for a reason rather than a confirmation. The
 * server requires one; a "Suspend / Cancel" pair would have made that a
 * validation error instead of a question, and the reason is the whole point —
 * a storefront that stops answering generates a support call within the hour.
 */
interface TenantsPageProps {
  token: string;
  onNavigate: (path: string) => void;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
}

type StatusFilter = 'ALL' | AppClientStatus;

const PAGE_SIZE_OPTIONS = [10, 25, 50];

/** What the dialog says, per lifecycle move. */
const LIFECYCLE_COPY: Record<
  AppClientStatus,
  { eyebrow: string; title: string; description: string; confirmLabel: string; danger: boolean }
> = {
  SUSPENDED: {
    eyebrow: 'Take off the air',
    title: 'Suspend this tenant',
    description:
      'Their storefront and app stop answering immediately. Existing orders are untouched and nothing is deleted — you can restore them from here.',
    confirmLabel: 'Suspend tenant',
    danger: true,
  },
  OFFBOARDED: {
    eyebrow: 'Leave the platform',
    title: 'Offboard this tenant',
    description:
      'For a restaurant that has left. Their storefront stops answering and this cannot be undone from the panel — a suspension is the reversible version.',
    confirmLabel: 'Offboard tenant',
    danger: true,
  },
  ACTIVE: {
    eyebrow: 'Back on the air',
    title: 'Restore this tenant',
    description:
      'Their storefront and app start answering again straight away. A note is optional here — a working storefront explains itself.',
    confirmLabel: 'Restore tenant',
    danger: false,
  },
};

function cacheKey(scope: string): string {
  return `platform-tenants:${scope}`;
}

/** The searchable text of a tenant, so the filter matches what a person reads. */
function haystack(tenant: TenantSummary): string {
  return [
    tenant.display_name,
    tenant.app_key,
    tenant.restaurant_name,
    tenant.cuisine_type,
    tenant.city,
    tenant.primary_host,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

export function TenantsPage({ token, onNavigate, onToast }: TenantsPageProps) {
  const { refreshTenants } = useAdminStore();
  const scope = tokenScope(token);
  const key = cacheKey(scope);

  const [tenants, setTenants] = useState<TenantSummary[]>(
    () => getPageSnapshot<TenantSummary[]>(key) ?? [],
  );
  const [loading, setLoading] = useState(() => !hasPageSnapshot(key));
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE_OPTIONS[0]);

  // The tenant whose lifecycle is being changed, and to what.
  const [lifecycle, setLifecycle] = useState<{
    tenant: TenantSummary;
    next: AppClientStatus;
  } | null>(null);
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);

  async function load(): Promise<void> {
    setError(null);
    try {
      const rows = await api.listTenants(token);
      setTenants(rows);
      setPageSnapshot(key, rows);
    } catch (caught: unknown) {
      setError(caught instanceof ApiError ? caught.message : 'Could not load tenants');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const counts = useMemo(() => {
    const byStatus = { ACTIVE: 0, SUSPENDED: 0, OFFBOARDED: 0 };
    tenants.forEach((tenant) => {
      byStatus[tenant.status] += 1;
    });
    return byStatus;
  }, [tenants]);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return tenants.filter((tenant) => {
      if (statusFilter !== 'ALL' && tenant.status !== statusFilter) {
        return false;
      }
      return needle ? haystack(tenant).includes(needle) : true;
    });
  }, [search, statusFilter, tenants]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const visible = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);

  // A filter that leaves fewer pages than you are on would otherwise show an
  // empty table rather than the rows that matched.
  useEffect(() => {
    setPage(1);
  }, [search, statusFilter, pageSize]);

  const tiles: Array<StatTileItem<StatusFilter>> = [
    {
      key: 'ALL',
      label: 'All tenants',
      icon: Building2,
      value: tenants.length,
      hint: 'On the platform',
    },
    {
      key: 'ACTIVE',
      label: 'Active',
      icon: PlayCircle,
      value: counts.ACTIVE,
      hint: 'Storefront answering',
    },
    {
      key: 'SUSPENDED',
      label: 'Suspended',
      icon: PauseCircle,
      value: counts.SUSPENDED,
      hint: 'Temporarily off the air',
    },
    {
      key: 'OFFBOARDED',
      label: 'Offboarded',
      icon: CircleSlash,
      value: counts.OFFBOARDED,
      hint: 'Left the platform',
    },
  ];

  const columns: Array<TableColumn<TenantSummary>> = [
    {
      id: 'tenant',
      header: 'Tenant',
      render: (tenant) => (
        <>
          <strong>{tenant.display_name}</strong>
          <span>{tenant.app_key}</span>
        </>
      ),
    },
    {
      id: 'storefront',
      header: 'Storefront',
      render: (tenant) =>
        tenant.primary_host ? (
          <>
            <strong className="tenant-host">
              <Globe size={13} strokeWidth={2} />
              {tenant.primary_host}
            </strong>
            {tenant.custom_host_count > 0 ? (
              <span>
                +{tenant.custom_host_count} own domain
                {tenant.custom_host_count === 1 ? '' : 's'}
              </span>
            ) : null}
          </>
        ) : (
          // Worth naming rather than showing a dash: a tenant with no address
          // has a working mobile identity and a storefront that 404s, which is
          // a bug somebody should chase, not a blank cell.
          <span>No address issued</span>
        ),
    },
    {
      id: 'menu',
      header: 'Menu',
      align: 'right',
      hideOnMobile: true,
      render: (tenant) => (
        <>
          <strong className="tabular">{tenant.menu_item_count}</strong>
          <span>
            {tenant.location_count} branch{tenant.location_count === 1 ? '' : 'es'}
          </span>
        </>
      ),
    },
    {
      id: 'activity',
      header: 'Activity',
      align: 'right',
      hideOnMobile: true,
      render: (tenant) => (
        <>
          <strong className="tabular">{tenant.order_count}</strong>
          <span>
            {tenant.customer_count} customer{tenant.customer_count === 1 ? '' : 's'}
          </span>
        </>
      ),
    },
    {
      id: 'status',
      header: 'Status',
      render: (tenant) => (
        <>
          <StatusPill status={tenant.status} />
          {tenant.status_note ? (
            <span title={tenant.status_note}>{tenant.status_note}</span>
          ) : null}
          {/* Only while the tenant is off the air. A restored one keeps its
              provenance in the database, but a green Active pill with a name
              and a date under it reads as an unexplained warning. */}
          {tenant.status !== 'ACTIVE' && tenant.status_changed_by && tenant.status_changed_at ? (
            <span>
              {tenant.status_changed_by} · {formatDate(tenant.status_changed_at)}
            </span>
          ) : null}
        </>
      ),
    },
  ];

  function openLifecycle(tenant: TenantSummary, next: AppClientStatus): void {
    setLifecycle({ tenant, next });
    setNote('');
  }

  async function applyLifecycle(): Promise<void> {
    if (!lifecycle) {
      return;
    }
    setSaving(true);
    try {
      const updated = await api.updateTenantStatus(token, lifecycle.tenant.id, {
        status: lifecycle.next,
        note: note.trim() || null,
      });
      const rows = tenants.map((tenant) => (tenant.id === updated.id ? updated : tenant));
      setTenants(rows);
      setPageSnapshot(key, rows);
      // The switcher in the rail reads the store's copy, so a tenant suspended
      // here would otherwise keep its old pill until the next full reload.
      void refreshTenants();
      setLifecycle(null);
      onToast(
        `${updated.display_name} is ${updated.status.toLowerCase()}`,
        updated.status === 'ACTIVE'
          ? 'Their storefront is answering again.'
          : 'Their storefront and app have stopped answering.',
        'success',
      );
    } catch (caught: unknown) {
      onToast(
        'Could not change this tenant',
        caught instanceof ApiError ? caught.message : 'Something went wrong',
        'error',
      );
    } finally {
      setSaving(false);
    }
  }

  const copy = lifecycle ? LIFECYCLE_COPY[lifecycle.next] : null;
  // The server refuses a suspension or an offboarding without a reason, so the
  // button says so rather than letting the request come back as an error.
  const needsNote = Boolean(lifecycle && lifecycle.next !== 'ACTIVE');
  const canSubmit = !needsNote || note.trim().length > 0;

  return (
    <div className="page-stack">
      <PageIntro
        description="Every restaurant running on this platform, what it is carrying, and whether its storefront is answering."
        eyebrow="Platform"
        title="Tenants"
      />

      <StatTiles
        active={statusFilter}
        ariaLabel="Tenants by lifecycle state"
        loading={loading}
        onSelect={setStatusFilter}
        tiles={tiles}
      />

      <DataToolbar
        onSearchChange={setSearch}
        searchLabel="Search tenants"
        searchPlaceholder="Filter by name, app key, city, address"
        searchValue={search}
      />

      <ResponsiveTable
        actions={[
          {
            id: 'open',
            label: 'Open restaurant',
            icon: Eye,
            hidden: (tenant) => tenant.restaurant_id === null,
            onClick: (tenant) => onNavigate(`/admin/restaurants/${tenant.restaurant_id}`),
          },
          {
            id: 'suspend',
            label: 'Suspend',
            icon: PauseCircle,
            tone: 'danger',
            hidden: (tenant) => tenant.status !== 'ACTIVE',
            onClick: (tenant) => openLifecycle(tenant, 'SUSPENDED'),
          },
          {
            id: 'restore',
            label: 'Restore',
            icon: PlayCircle,
            hidden: (tenant) => tenant.status !== 'SUSPENDED',
            onClick: (tenant) => openLifecycle(tenant, 'ACTIVE'),
          },
          {
            id: 'offboard',
            label: 'Offboard',
            icon: CircleSlash,
            tone: 'danger',
            hidden: (tenant) => tenant.status === 'OFFBOARDED',
            onClick: (tenant) => openLifecycle(tenant, 'OFFBOARDED'),
          },
        ]}
        columns={columns}
        emptyDescription={
          search || statusFilter !== 'ALL'
            ? 'Nothing matches the current search and filter.'
            : 'Onboard a restaurant and it appears here with its own storefront address.'
        }
        emptyTitle={search || statusFilter !== 'ALL' ? 'No tenants match' : 'No tenants yet'}
        error={error}
        errorTitle="Tenants didn't load"
        keyExtractor={(tenant) => tenant.id}
        loading={loading}
        mobileStatus={(tenant) => <StatusPill status={tenant.status} />}
        mobileSubtitle={(tenant) => tenant.primary_host ?? tenant.app_key}
        mobileTitle={(tenant) => tenant.display_name}
        onRetry={() => {
          setLoading(true);
          void load();
        }}
        rows={visible}
      />

      {filtered.length > 0 ? (
        <Pagination
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
          page={currentPage}
          pageSize={pageSize}
          pageSizeOptions={PAGE_SIZE_OPTIONS}
          totalItems={filtered.length}
          totalPages={totalPages}
        />
      ) : null}

      {lifecycle && copy ? (
        <Modal busy={saving} labelledBy="tenant-lifecycle-title" onClose={() => setLifecycle(null)}>
          <div className="panel__header modal-card__header">
            <div>
              <span className="eyebrow">{copy.eyebrow}</span>
              <h2 id="tenant-lifecycle-title">{copy.title}</h2>
              <p className="hint-text">{copy.description}</p>
            </div>
            <button
              aria-label="Close this dialog"
              className="modal-close"
              onClick={() => setLifecycle(null)}
              type="button"
            >
              ×
            </button>
          </div>

          <div className="modal-card__body">
            <div className="tenant-subject">
              <Store size={16} strokeWidth={2} />
              <div>
                <strong>{lifecycle.tenant.display_name}</strong>
                <span>{lifecycle.tenant.primary_host ?? lifecycle.tenant.app_key}</span>
              </div>
            </div>

            <label className="field">
              <span>{needsNote ? 'Reason' : 'Reason (optional)'}</span>
              <textarea
                autoFocus
                maxLength={500}
                onChange={(event) => setNote(event.target.value)}
                placeholder={
                  needsNote
                    ? 'Unpaid invoice, contract ended, at the restaurant’s request…'
                    : 'Anything worth recording about this change'
                }
                value={note}
              />
              <small>
                {needsNote
                  ? 'Shown beside this tenant so anyone looking can see why their storefront is down.'
                  : 'Restoring clears the previous reason.'}
              </small>
            </label>
          </div>

          <div className="modal-actions">
            <button
              className="secondary-button"
              disabled={saving}
              onClick={() => setLifecycle(null)}
              type="button"
            >
              Cancel
            </button>
            <button
              className={copy.danger ? 'primary-button primary-button--danger' : 'primary-button'}
              disabled={saving || !canSubmit}
              onClick={() => void applyLifecycle()}
              type="button"
            >
              {saving ? 'Saving…' : copy.confirmLabel}
            </button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}

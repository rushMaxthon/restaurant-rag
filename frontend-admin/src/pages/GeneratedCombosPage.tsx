import {
  Archive,
  ChevronDown,
  Eye,
  Info,
  Layers3,
  Loader2,
  RefreshCw,
  Sparkles,
  TrendingUp,
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { DataToolbar } from '../components/DataToolbar';
import { StatTiles, type StatTileItem } from '../components/StatTiles';
import { pluralize } from '../services/format';
import { EmptyPanel } from '../components/EmptyPanel';
import { PageIntro } from '../components/PageIntro';
import { Pagination } from '../components/Pagination';
import { ResponsiveTable, type TableColumn } from '../components/ResponsiveTable';
import { resolveStatusPillTone, StatusPill } from '../components/StatusPill';
import { ApiError, api, formatCurrency, formatDate } from '../services/api';
import type { GeneratedCombo, UserRole } from '../types/app';

interface GeneratedCombosPageProps {
  token: string;
  role: UserRole;
  restaurantId?: string | null;
  locationId?: string | null;
  onToast: (title: string, description: string, tone?: 'success' | 'error' | 'info') => void;
  embedded?: boolean;
}

function formatConfidenceScore(value: number | string): string {
  const numeric = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(numeric)) {
    return String(value);
  }
  return numeric.toFixed(2);
}

function toNumber(value: number | string): number {
  const numeric = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(numeric) ? numeric : 0;
}

function comboLifecycleHint(combo: GeneratedCombo): string {
  if (combo.status === 'DRAFT') {
    const remaining = Math.max(combo.remaining_unique_users_to_publish ?? 0, 0);
    return `Needs ${remaining} more customer${remaining === 1 ? '' : 's'}`;
  }
  if (combo.status === 'LIVE') {
    return 'Visible to customers';
  }
  return 'No longer active';
}

function comboVisibilityLabel(combo: GeneratedCombo): string {
  if (combo.status === 'DRAFT') {
    const remaining = Math.max(combo.remaining_unique_users_to_publish ?? 0, 0);
    return `Needs ${remaining} more customer${remaining === 1 ? '' : 's'}`;
  }
  if (combo.status === 'LIVE') {
    return 'Visible to customers';
  }
  return 'Archived';
}

function comboVisibilityDescription(combo: GeneratedCombo): string {
  if (combo.status === 'DRAFT') {
    return 'Still maturing from fresh ordering patterns.';
  }
  if (combo.status === 'LIVE') {
    return 'Appears on customer-facing combo surfaces.';
  }
  return 'Retained for admin history and analytics only.';
}

function comboShortHelper(combo: GeneratedCombo): string {
  if (combo.description) {
    return combo.description;
  }
  return `Auto-discovered from ${combo.order_count} successful orders across ${combo.unique_user_count} customer${combo.unique_user_count === 1 ? '' : 's'}.`;
}

function comboItemsPreview(combo: GeneratedCombo): string {
  const names = combo.items.map((item) => item.name);
  if (names.length <= 3) {
    return names.join(' + ');
  }
  return `${names.slice(0, 3).join(' + ')} +${names.length - 3} more`;
}

function comboStatusActions(combo: GeneratedCombo): Array<{ label: string; status: GeneratedCombo['status'] }> {
  if (combo.status === 'DRAFT') {
    return [{ label: 'Move to Live', status: 'LIVE' }];
  }
  if (combo.status === 'LIVE') {
    return [{ label: 'Move to Archived', status: 'ARCHIVED' }];
  }
  return [{ label: 'Restore to Live', status: 'LIVE' }];
}

function GeneratedCombosWorkspace({
  token,
  role,
  restaurantId,
  locationId,
  onToast,
  embedded = false,
}: GeneratedCombosPageProps) {
  const [rows, setRows] = useState<GeneratedCombo[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'DRAFT' | 'LIVE' | 'ARCHIVED'>('ALL');
  const [restaurantFilter, setRestaurantFilter] = useState<string>('ALL');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [rebuilding, setRebuilding] = useState(false);
  const [selectedCombo, setSelectedCombo] = useState<GeneratedCombo | null>(null);
  const [openStatusMenuId, setOpenStatusMenuId] = useState<string | null>(null);
  const [statusUpdatingId, setStatusUpdatingId] = useState<string | null>(null);
  const isAdmin = role === 'ADMIN';
  const isRestaurantScoped = Boolean(restaurantId) || role === 'OWNER';

  const loadRows = async () => {
    setLoading(true);
    setErrorMessage(null);
    try {
      const combos = await api.getManagedGeneratedCombos(
        token,
        restaurantId ?? undefined,
        locationId ?? undefined,
      );
      setRows(combos);
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : 'Unable to load generated combos.';
      setRows([]);
      setErrorMessage(message);
      onToast('Generated combos unavailable', message, 'error');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let active = true;

    api
      .getManagedGeneratedCombos(token, restaurantId ?? undefined, locationId ?? undefined)
      .then((combos) => {
        if (!active) {
          return;
        }
        setRows(combos);
        setErrorMessage(null);
        setLoading(false);
      })
      .catch((error) => {
        if (!active) {
          return;
        }
        const message =
          error instanceof ApiError
            ? error.message
            : 'Unable to load generated combos.';
        setRows([]);
        setErrorMessage(message);
        setLoading(false);
        onToast('Generated combos unavailable', message, 'error');
      });

    return () => {
      active = false;
    };
  }, [locationId, onToast, restaurantId, token]);

  useEffect(() => {
    if (openStatusMenuId === null) {
      return undefined;
    }

    const handleDocumentClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('[data-combo-status-control="true"]')) {
        return;
      }
      setOpenStatusMenuId(null);
    };

    document.addEventListener('mousedown', handleDocumentClick);
    return () => {
      document.removeEventListener('mousedown', handleDocumentClick);
    };
  }, [openStatusMenuId]);

  const filtered = useMemo(() => {
    const normalizedRestaurantFilter = restaurantFilter.trim().toLowerCase();
    const normalized = query.trim().toLowerCase();
    return rows.filter((combo) => {
      const matchesQuery =
        !normalized ||
        [
          combo.combo_name,
          combo.restaurant_name,
          combo.description ?? '',
          ...combo.items.map((item) => item.name),
        ].some((value) => value.toLowerCase().includes(normalized));
      const matchesRestaurant =
        restaurantFilter === 'ALL' ||
        combo.restaurant_id === restaurantFilter ||
        combo.restaurant_name.toLowerCase() === normalizedRestaurantFilter;
      const matchesStatus =
        statusFilter === 'ALL' ||
        combo.status === statusFilter;
      return matchesQuery && matchesStatus && matchesRestaurant;
    });
  }, [query, restaurantFilter, rows, statusFilter]);

  const restaurantOptions = useMemo(
    () =>
      Array.from(
        rows.reduce((map, combo) => {
          if (!map.has(combo.restaurant_id)) {
            map.set(combo.restaurant_id, combo.restaurant_name);
          }
          return map;
        }, new Map<string, string>()),
      )
        .map(([id, name]) => ({ id, name }))
        .sort((left, right) => left.name.localeCompare(right.name)),
    [rows],
  );

  const summaryScopeRows = useMemo(() => {
    if (restaurantFilter === 'ALL') {
      return rows;
    }
    return rows.filter((combo) => combo.restaurant_id === restaurantFilter);
  }, [restaurantFilter, rows]);

  const summaryTiles = useMemo<Array<StatTileItem<'ALL' | 'DRAFT' | 'LIVE' | 'ARCHIVED'>>>(() => {
    const liveCount = summaryScopeRows.filter((combo) => combo.status === 'LIVE').length;
    const draftCount = summaryScopeRows.filter((combo) => combo.status === 'DRAFT').length;
    const archivedCount = summaryScopeRows.filter((combo) => combo.status === 'ARCHIVED').length;
    const revenueInfluence = summaryScopeRows.reduce(
      (total, combo) => total + toNumber(combo.suggested_combo_price) * combo.order_count,
      0,
    );

    const tiles: Array<StatTileItem<'ALL' | 'DRAFT' | 'LIVE' | 'ARCHIVED'>> = [
      {
        key: 'ALL',
        label: 'All combos',
        icon: Layers3,
        value: summaryScopeRows.length,
        hint: 'Across lifecycle stages',
      },
      { key: 'LIVE', label: 'Live', icon: Sparkles, value: liveCount, hint: 'Customer visible' },
      { key: 'DRAFT', label: 'Draft', icon: Layers3, value: draftCount, hint: 'Still maturing' },
      { key: 'ARCHIVED', label: 'Archived', icon: Archive, value: archivedCount, hint: 'Retired' },
    ];
    if (revenueInfluence > 0) {
      tiles.push({
        key: 'ALL',
        label: 'Revenue influence',
        icon: TrendingUp,
        value: formatCurrency(revenueInfluence),
        hint: 'Historic combo impact',
        isStatic: true,
      });
    }
    return tiles;
  }, [summaryScopeRows]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(page, totalPages);
  const pageItems = filtered.slice(
    (currentPage - 1) * pageSize,
    currentPage * pageSize,
  );

  const updateComboStatus = async (
    combo: GeneratedCombo,
    nextStatus: GeneratedCombo['status'],
  ) => {
    if (combo.status === nextStatus) {
      setOpenStatusMenuId(null);
      return;
    }

    const previousRows = rows;
    const previousSelectedCombo = selectedCombo;
    const optimisticCombo: GeneratedCombo = {
      ...combo,
      status: nextStatus,
      manual_status_override: nextStatus,
      is_customer_visible: nextStatus === 'LIVE',
      is_active: nextStatus !== 'ARCHIVED',
      remaining_unique_users_to_publish:
        nextStatus === 'DRAFT'
          ? combo.remaining_unique_users_to_publish
          : 0,
    };

    setStatusUpdatingId(combo.id);
    setOpenStatusMenuId(null);
    setRows((current) =>
      current.map((entry) => (entry.id === combo.id ? optimisticCombo : entry)),
    );
    setSelectedCombo((current) =>
      current && current.id === combo.id ? optimisticCombo : current,
    );

    try {
      const updated = await api.updateGeneratedComboStatus(
        token,
        combo.id,
        nextStatus,
      );
      setRows((current) =>
        current.map((entry) => (entry.id === updated.id ? updated : entry)),
      );
      setSelectedCombo((current) =>
        current && current.id === updated.id ? updated : current,
      );
      setOpenStatusMenuId(null);
      const successDescription =
        updated.status === 'LIVE'
          ? 'Combo moved to LIVE.'
          : updated.status === 'ARCHIVED'
            ? 'Combo archived successfully.'
            : 'Combo restored successfully.';
      onToast('Status updated', successDescription, 'success');
    } catch (error) {
      const message =
        error instanceof ApiError
          ? error.message
          : 'Unable to update combo status.';
      setRows(previousRows);
      setSelectedCombo(previousSelectedCombo);
      onToast('Update failed', message, 'error');
    } finally {
      setStatusUpdatingId(null);
    }
  };

  const renderStatusControl = (combo: GeneratedCombo) => {
    const actionsForCombo = comboStatusActions(combo);
    const isOpen = openStatusMenuId === combo.id;
    const hint = comboLifecycleHint(combo);
    const isUpdating = statusUpdatingId === combo.id;

    return (
      <div
        className="combo-status-control"
        data-combo-status-control="true"
        onClick={(event) => event.stopPropagation()}
      >
        <button
          aria-expanded={isOpen}
          aria-haspopup="menu"
          className={`combo-status-trigger${isUpdating ? ' combo-status-trigger--loading' : ''}`}
          disabled={isUpdating}
          onClick={(event) => {
            event.stopPropagation();
            setOpenStatusMenuId((current) => (current === combo.id ? null : combo.id));
          }}
          title={hint}
          type="button"
        >
          <span
            className={`status-pill status-pill--${resolveStatusPillTone(combo.status)} status-pill--interactive`}
          >
            <span>{combo.status.replaceAll('_', ' ')}</span>
            {isUpdating ? (
              <Loader2 className="combo-status-spinner" size={13} strokeWidth={2.1} />
            ) : (
              <ChevronDown
                className={`combo-status-trigger__chevron${isOpen ? ' combo-status-trigger__chevron--open' : ''}`}
                size={13}
                strokeWidth={2.2}
              />
            )}
          </span>
        </button>
        {isOpen && !isUpdating ? (
          <div className="combo-status-menu" role="menu">
            {actionsForCombo.map((action) => (
              <button
                className="combo-status-menu__item"
                key={`${combo.id}-${action.label}`}
                onClick={(event) => {
                  event.stopPropagation();
                  void updateComboStatus(combo, action.status);
                }}
                role="menuitem"
                type="button"
              >
                {action.label}
              </button>
            ))}
          </div>
        ) : null}
        <span title={hint}>{hint}</span>
      </div>
    );
  };

  const columns: Array<TableColumn<GeneratedCombo>> = [
    {
      id: 'combo',
      header: 'Combo',
      render: (combo) => (
        <div className="generated-combos-combo-cell">
          <strong>{combo.combo_name}</strong>
          <span>{comboItemsPreview(combo)}</span>
          <span>{comboShortHelper(combo)}</span>
        </div>
      ),
    },
    {
      id: 'restaurant',
      header: 'Restaurant',
      render: (combo) => (
        <div className="generated-combos-restaurant-cell">
          <strong>{combo.restaurant_name}</strong>
          <span>{combo.restaurant_location_name}</span>
        </div>
      ),
      mobileLabel: 'Restaurant',
    },
    {
      id: 'performance',
      header: 'Performance',
      render: (combo) => (
        <div className="generated-combos-performance-cell">
          <div className="generated-combos-performance-metric">
            <span>Orders</span>
            <strong>{combo.order_count}</strong>
          </div>
          <div className="generated-combos-performance-metric">
            <span>Users</span>
            <strong>{combo.unique_user_count}</strong>
          </div>
          <div className="generated-combos-performance-metric">
            <span>Confidence</span>
            <strong>{formatConfidenceScore(combo.confidence_score)}</strong>
          </div>
        </div>
      ),
      mobileLabel: 'Performance',
    },
    {
      id: 'visibility',
      header: 'Visibility',
      render: (combo) => (
        <div className="generated-combos-visibility-cell">
          {renderStatusControl(combo)}
          <div className="generated-combos-visibility-copy">
            <span
              className={`generated-combos-visibility-badge generated-combos-visibility-badge--${combo.status.toLowerCase()}`}
            >
              {comboVisibilityLabel(combo)}
            </span>
            <span>{comboVisibilityDescription(combo)}</span>
          </div>
        </div>
      ),
      mobileLabel: 'Visibility',
      hideOnMobile: true,
    },
    {
      id: 'updated',
      header: 'Updated',
      render: (combo) => (
        <div className="generated-combos-updated-cell">
          <strong>{formatDate(combo.last_seen_at)}</strong>
          <span>Last seen</span>
        </div>
      ),
      mobileLabel: 'Updated',
    },
  ];

  const actions = [
    {
      id: 'view',
      label: 'View details',
      icon: Eye,
      onClick: (combo: GeneratedCombo) => {
        setSelectedCombo(combo);
      },
    },
  ];

  const table = errorMessage ? (
    <section className="admin-surface page-stack">
      <EmptyPanel
        description={errorMessage}
        title="Unable to load generated combos"
      />
      <div className="page-intro__actions">
        <button className="secondary-button" onClick={() => void loadRows()} type="button">
          Try again
        </button>
      </div>
    </section>
  ) : (
    <>
      <ResponsiveTable
        actions={actions}
        columns={columns}
        emptyDescription={
          rows.length === 0
            ? 'No combo trends discovered yet. Once customers start ordering together, combos will automatically appear here.'
            : 'No generated combos match the current filters. Try a broader search or switch lifecycle filters.'
        }
        emptyTitle={rows.length === 0 ? 'No combo trends discovered yet' : 'No combos match these filters'}
        keyExtractor={(row) => row.id}
        loading={loading}
        mobileStatus={(row) => renderStatusControl(row)}
        mobileSubtitle={(row) => `${row.restaurant_name} · ${comboVisibilityLabel(row)}`}
        mobileTitle={(row) => row.combo_name}
        rows={pageItems}
      />

      <Pagination
        page={currentPage}
        onPageChange={setPage}
        onPageSizeChange={(value) => {
          setPageSize(value);
          setPage(1);
        }}
        pageSize={pageSize}
        totalItems={filtered.length}
        totalPages={totalPages}
      />

      <div className="combo-confidence-note">
          <Info size={15} strokeWidth={2} />
          <span>
          <strong>Confidence Score:</strong> Calculated using order frequency, unique customers, and recent activity. Higher scores indicate stronger combo trends and more reliable customer demand.
        </span>
      </div>
    </>
  );

  if (embedded) {
    return (
      <div className="page-stack">
        <DataToolbar
          actions={<span className="toolbar-meta">{pluralize(filtered.length, 'combo')}</span>}
          filters={
            <>
              <select
                className="page-search page-search--select"
                onChange={(event) => {
                  setStatusFilter(event.target.value as typeof statusFilter);
                  setPage(1);
                }}
                value={statusFilter}
              >
                <option value="ALL">All statuses</option>
                <option value="DRAFT">Draft</option>
                <option value="LIVE">Live</option>
                <option value="ARCHIVED">Archived</option>
              </select>
              {!isRestaurantScoped ? (
                <select
                  className="page-search page-search--select"
                  onChange={(event) => {
                    setRestaurantFilter(event.target.value);
                    setPage(1);
                  }}
                  value={restaurantFilter}
                >
                  <option value="ALL">All restaurants</option>
                  {restaurantOptions.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.name}
                    </option>
                  ))}
                </select>
              ) : null}
            </>
          }
          onSearchChange={(value) => {
            setQuery(value);
            setPage(1);
          }}
          searchPlaceholder="Search combos or included items..."
          searchValue={query}
        />
        {table}
      </div>
    );
  }

  return (
    <div className="page-stack">
      <PageIntro
        actions={
          isAdmin ? (
            <button
              className="primary-button"
              disabled={rebuilding}
              onClick={async () => {
                setRebuilding(true);
                try {
                  const result = await api.rebuildAdminGeneratedCombos(token);
                  await loadRows();
                  onToast(
                    'Combos rebuilt',
                    `Created ${result.created_count}, updated ${result.updated_count}, deactivated ${result.deactivated_count}.`,
                    'success',
                  );
                } catch (error) {
                  const message =
                    error instanceof ApiError
                      ? error.message
                      : 'Unable to rebuild combos.';
                  onToast('Rebuild failed', message, 'error');
                } finally {
                  setRebuilding(false);
                }
              }}
              type="button"
            >
              <RefreshCw size={16} strokeWidth={2.1} />
              <span>{rebuilding ? 'Rebuilding...' : 'Rebuild combos'}</span>
            </button>
          ) : undefined
        }
        description="Review customer ordering patterns and manage combo visibility across lifecycle stages."
        eyebrow={isAdmin ? 'AI Combos' : 'Assigned restaurant'}
        title="Generated Combos"
      />

      <StatTiles<'ALL' | 'DRAFT' | 'LIVE' | 'ARCHIVED'>
        active={statusFilter}
        ariaLabel="Combo lifecycle distribution"
        onSelect={(key) => {
          setStatusFilter(key);
          setPage(1);
        }}
        tiles={summaryTiles}
      />

      <DataToolbar
        actions={<span className="toolbar-meta">{pluralize(filtered.length, 'combo')}</span>}
        filters={
          <>
            <select
              className="page-search page-search--select"
              onChange={(event) => {
                setStatusFilter(event.target.value as typeof statusFilter);
                setPage(1);
              }}
              value={statusFilter}
            >
              <option value="ALL">All statuses</option>
              <option value="DRAFT">Draft</option>
              <option value="LIVE">Live</option>
              <option value="ARCHIVED">Archived</option>
            </select>
            {!isRestaurantScoped ? (
              <select
                className="page-search page-search--select"
                onChange={(event) => {
                  setRestaurantFilter(event.target.value);
                  setPage(1);
                }}
                value={restaurantFilter}
              >
                <option value="ALL">All restaurants</option>
                {restaurantOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.name}
                  </option>
                ))}
              </select>
            ) : null}
          </>
        }
        onSearchChange={(value) => {
          setQuery(value);
          setPage(1);
        }}
        searchPlaceholder={
          isRestaurantScoped
            ? 'Search combos or included items...'
            : 'Search combos, restaurants, or included items...'
        }
        searchValue={query}
      />

      {table}

      {selectedCombo ? (
        <div
          className="modal-overlay"
          onClick={() => setSelectedCombo(null)}
          role="presentation"
        >
          <section
            className="modal-card combo-detail-modal"
            onClick={(event) => event.stopPropagation()}
            role="dialog"
          >
            <div className="panel__header modal-card__header">
              <div>
                <span className="eyebrow">Generated combo details</span>
                <h2>{selectedCombo.combo_name}</h2>
                <p className="hint-text">
                  Review combo composition, ordering confidence, and customer visibility at a glance.
                </p>
              </div>
              <button
                aria-label="Close generated combo details"
                className="modal-close"
                onClick={() => setSelectedCombo(null)}
                type="button"
              >
                ×
              </button>
            </div>

            <div className="modal-card__body combo-detail-modal__body">
              <div className="combo-detail-grid">
                <div>
                  <strong>Restaurant</strong>
                  <span>{selectedCombo.restaurant_name}</span>
                </div>
                <div>
                  <strong>Status</strong>
                  {renderStatusControl(selectedCombo)}
                </div>
                <div>
                  <strong>Customer visibility</strong>
                  <span>{comboLifecycleHint(selectedCombo)}</span>
                </div>
                <div>
                  <strong>Original total</strong>
                  <span>{formatCurrency(selectedCombo.original_total_price)}</span>
                </div>
                <div>
                  <strong>Suggested combo price</strong>
                  <span>{formatCurrency(selectedCombo.suggested_combo_price)}</span>
                </div>
                <div>
                  <strong>Order count</strong>
                  <span>{selectedCombo.order_count}</span>
                </div>
                <div>
                  <strong>Unique users</strong>
                  <span>{selectedCombo.unique_user_count}</span>
                </div>
                <div>
                  <strong>Remaining to go live</strong>
                  <span>{selectedCombo.status === 'DRAFT' ? selectedCombo.remaining_unique_users_to_publish : 0}</span>
                </div>
                <div>
                  <strong>Confidence score</strong>
                  <span>{formatConfidenceScore(selectedCombo.confidence_score)}</span>
                </div>
                <div>
                  <strong>Generated from orders</strong>
                  <span>{selectedCombo.generated_from_orders ? 'Yes' : 'No'}</span>
                </div>
                <div>
                  <strong>Created</strong>
                  <span>{formatDate(selectedCombo.created_at)}</span>
                </div>
                <div>
                  <strong>Updated</strong>
                  <span>{formatDate(selectedCombo.updated_at)}</span>
                </div>
              </div>

              <div className="combo-detail-section">
                <strong>Lifecycle note</strong>
                <p className="hint-text">{comboLifecycleHint(selectedCombo)}</p>
              </div>

              <div className="combo-detail-section">
                <strong>Included items</strong>
                <div className="combo-detail-items">
                  {selectedCombo.items.map((item) => (
                    <div className="combo-detail-item" key={item.menu_item_id}>
                      <div>
                        <strong>{item.name}</strong>
                        <span>{item.category}</span>
                      </div>
                      <div className="combo-detail-item__meta">
                        <span>Qty {item.quantity}</span>
                        <StatusPill status={item.is_veg ? 'VEG' : 'NON VEG'} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="modal-actions">
                <button
                  className="secondary-button"
                  onClick={() => setSelectedCombo(null)}
                  type="button"
                >
                  Close
                </button>
              </div>
            </div>
          </section>
        </div>
      ) : null}
    </div>
  );
}

export function GeneratedCombosPage(props: GeneratedCombosPageProps) {
  return <GeneratedCombosWorkspace {...props} />;
}

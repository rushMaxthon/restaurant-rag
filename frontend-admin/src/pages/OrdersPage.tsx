import {
  ArrowRight,
  Check,
  ChefHat,
  Eye,
  PackageCheck,
  ReceiptText,
  ShoppingBag,
  Truck,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { DataToolbar } from "../components/DataToolbar";
import { StatTiles, type StatTileItem } from "../components/StatTiles";
import { PageIntro } from "../components/PageIntro";
import { Pagination } from "../components/Pagination";
import {
  ResponsiveTable,
  type TableColumn,
  type TableSortState,
} from "../components/ResponsiveTable";
import { StatusPill } from "../components/StatusPill";
import { readWorkspaceSettings } from "../services/workspaceSettings";
import { ApiError, api, formatCurrency, formatDate } from "../services/api";
import { humanizeEnum, pluralize } from "../services/format";
import {
  getPageSnapshot,
  hasPageSnapshot,
  invalidatePageSnapshotsByPrefix,
  setPageSnapshot,
  tokenScope,
} from "../services/pageCache";
import {
  ORDER_FILTER_STATUSES,
  type Order,
  type OrderStatus,
  type UserRole,
} from "../types/app";

interface OrdersPageProps {
  token: string;
  role: UserRole;
  onNavigate: (path: string) => void;
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

const nextStatusMap: Partial<Record<OrderStatus, OrderStatus>> = {
  PLACED: "ACCEPTED",
  ACCEPTED: "PREPARING",
  PREPARING: "OUT_FOR_DELIVERY",
  OUT_FOR_DELIVERY: "DELIVERED",
};

const STATUS_KEYS: OrderStatus[] = [
  "PLACED",
  "ACCEPTED",
  "PREPARING",
  "OUT_FOR_DELIVERY",
  "DELIVERED",
];

type TileCounts = Partial<Record<"ALL" | OrderStatus, number>>;

interface OrdersSnapshot {
  orders: Order[];
  total: number;
}

// This page is remounted from scratch every time it's navigated to (see the
// note in services/pageCache.ts), so these keys have to encode every input
// that changes what the API returns — including the auth scope, or one
// admin's cached page would flash on screen for the next admin to sign in.
const ORDERS_CACHE_PREFIX = "orders";

// Exported so any other page that changes an order's status (e.g.
// RestaurantDetailPage's own Orders tab) can invalidate this list too - the
// same order data, just viewed through a different filtered lens.
export function buildOrdersCacheKeyPrefix(scope: string): string {
  return `${ORDERS_CACHE_PREFIX}:${scope}:`;
}

function buildOrdersListKey(
  scope: string,
  params: {
    page: number;
    pageSize: number;
    query: string;
    status: "ALL" | OrderStatus;
    sort: TableSortState | null;
  },
): string {
  return [
    ORDERS_CACHE_PREFIX,
    scope,
    "list",
    params.page,
    params.pageSize,
    params.query,
    params.status,
    params.sort?.id ?? "",
    params.sort?.direction ?? "",
  ].join(":");
}

function buildOrdersTilesKey(scope: string, query: string): string {
  return [ORDERS_CACHE_PREFIX, scope, "tiles", query].join(":");
}

// The literal defaults every useState below starts from. Used to compute the
// cache key for the very first render, before any filter has been touched.
const DEFAULT_SORT: TableSortState = { id: "placed_at", direction: "desc" };
const DEFAULT_PAGE = 1;
const DEFAULT_QUERY = "";
const DEFAULT_STATUS_FILTER = "ALL" as const;

export function OrdersPage({ token, role, onNavigate, onToast }: OrdersPageProps) {
  const isAdmin = role === "ADMIN";
  const scope = tokenScope(token);
  // Read on render, not at module scope: a module constant is evaluated once
  // when the bundle loads, so changing the preference only took effect after a
  // full reload rather than on the next visit.
  const defaultPageSize = readWorkspaceSettings().defaultPageSize;
  const initialListKey = buildOrdersListKey(scope, {
    page: DEFAULT_PAGE,
    pageSize: defaultPageSize,
    query: DEFAULT_QUERY,
    status: DEFAULT_STATUS_FILTER,
    sort: DEFAULT_SORT,
  });
  const initialTilesKey = buildOrdersTilesKey(scope, DEFAULT_QUERY);

  const [orders, setOrders] = useState<Order[]>(
    () => getPageSnapshot<OrdersSnapshot>(initialListKey)?.orders ?? [],
  );
  const [total, setTotal] = useState(
    () => getPageSnapshot<OrdersSnapshot>(initialListKey)?.total ?? 0,
  );
  const [tileCounts, setTileCounts] = useState<TileCounts>(
    () => getPageSnapshot<TileCounts>(initialTilesKey) ?? {},
  );
  // Only true when this exact combination of filters has never been fetched
  // (or was invalidated by a mutation) — not on every mount. A page that was
  // already loaded keeps showing its data instead of a skeleton.
  const [isLoading, setIsLoading] = useState(() => !hasPageSnapshot(initialListKey));
  const [loadError, setLoadError] = useState<string | null>(null);
  // Bumped by the error panel's Try again, which is what re-runs the fetch
  // effect: the filter combination has not changed, so nothing else would.
  const [reloadNonce, setReloadNonce] = useState(0);
  const [updatingOrderIds, setUpdatingOrderIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [debouncedQuery, setDebouncedQuery] = useState(DEFAULT_QUERY);
  const [statusFilter, setStatusFilter] = useState<"ALL" | OrderStatus>(
    DEFAULT_STATUS_FILTER,
  );
  const [sort, setSort] = useState<TableSortState | null>(DEFAULT_SORT);
  const [page, setPage] = useState(DEFAULT_PAGE);
  const [pageSize, setPageSize] = useState(defaultPageSize);
  const onToastRef = useRef(onToast);

  useEffect(() => {
    onToastRef.current = onToast;
  }, [onToast]);

  useEffect(() => {
    const handle = window.setTimeout(() => setDebouncedQuery(query), 350);
    return () => window.clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    setPage(1);
  }, [pageSize, debouncedQuery, statusFilter, sort]);

  // Server-side page fetch: only the visible slice is loaded.
  useEffect(() => {
    let active = true;
    const listKey = buildOrdersListKey(scope, {
      page,
      pageSize,
      query: debouncedQuery,
      status: statusFilter,
      sort,
    });

    const cached = getPageSnapshot<OrdersSnapshot>(listKey);
    if (cached) {
      // Already fetched for this exact combination — either the lazy-init
      // seed on first mount, or an earlier fetch during this same mount that
      // a filter toggle is now revisiting. No skeleton, no network call.
      setOrders(cached.orders);
      setTotal(cached.total);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    api
      .getOrdersPage(token, {
        page,
        pageSize,
        search: debouncedQuery || undefined,
        status: statusFilter === "ALL" ? null : statusFilter,
        sort,
      })
      .then(({ rows, total: totalCount }) => {
        if (!active) {
          return;
        }
        setOrders(rows);
        setTotal(totalCount);
        setLoadError(null);
        setPageSnapshot<OrdersSnapshot>(listKey, { orders: rows, total: totalCount });
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        const message =
          error instanceof ApiError ? error.message : "Unable to load orders.";
        // The toast is the immediate signal; the panel is what stays on screen
        // once it fades, and is the only thing offering a way to recover.
        setLoadError(message);
        onToastRef.current("Orders unavailable", message, "error");
      })
      .finally(() => {
        if (active) {
          setIsLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [token, scope, page, pageSize, debouncedQuery, statusFilter, sort, reloadNonce]);

  // Tile counts come from cheap COUNT-only requests (limit=1 + X-Total-Count).
  useEffect(() => {
    let active = true;
    const tilesKey = buildOrdersTilesKey(scope, debouncedQuery);

    const cached = getPageSnapshot<TileCounts>(tilesKey);
    if (cached) {
      setTileCounts(cached);
      return;
    }

    void Promise.all([
      api.getOrdersCount(token, { search: debouncedQuery || undefined }),
      ...STATUS_KEYS.map((status) =>
        api.getOrdersCount(token, {
          search: debouncedQuery || undefined,
          status,
        }),
      ),
    ]).then(([all, ...byStatus]) => {
      if (!active) {
        return;
      }
      const next: TileCounts = { ALL: all };
      STATUS_KEYS.forEach((status, index) => {
        next[status] = byStatus[index];
      });
      setTileCounts(next);
      setPageSnapshot(tilesKey, next);
    });

    return () => {
      active = false;
    };
  }, [token, scope, debouncedQuery]);

  const statusTiles = useMemo<Array<StatTileItem<"ALL" | OrderStatus>>>(
    () => [
      {
        key: "ALL",
        label: "All orders",
        icon: ReceiptText,
        value: tileCounts.ALL ?? "…",
        hint: debouncedQuery ? "Matching current search" : "Across every status",
      },
      { key: "PLACED", label: "Placed", icon: ShoppingBag, value: tileCounts.PLACED ?? "…", hint: "Awaiting acceptance" },
      { key: "ACCEPTED", label: "Accepted", icon: Check, value: tileCounts.ACCEPTED ?? "…", hint: "Confirmed by kitchen" },
      { key: "PREPARING", label: "Preparing", icon: ChefHat, value: tileCounts.PREPARING ?? "…", hint: "In the kitchen" },
      { key: "OUT_FOR_DELIVERY", label: "Out for delivery", icon: Truck, value: tileCounts.OUT_FOR_DELIVERY ?? "…", hint: "On the way" },
      { key: "DELIVERED", label: "Delivered", icon: PackageCheck, value: tileCounts.DELIVERED ?? "…", hint: "Completed" },
    ],
    [tileCounts, debouncedQuery],
  );

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const handleSortChange = (columnId: string) => {
    setSort((current) =>
      current?.id === columnId
        ? { id: columnId, direction: current.direction === "asc" ? "desc" : "asc" }
        : { id: columnId, direction: "desc" },
    );
  };

  const columns: Array<TableColumn<Order>> = [
    {
      id: "order",
      header: "Order ID",
      render: (order) => (
        <>
          <strong>#{order.id.slice(0, 8)}</strong>
          <span>{pluralize(order.items.length, "item")}</span>
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
      id: "restaurant",
      header: "Restaurant",
      render: (order) => (
        <>
          <strong>{order.restaurant.name}</strong>
          <span>{order.restaurant.city}</span>
        </>
      ),
      mobileLabel: "Restaurant",
    },
    {
      id: "total_amount",
      header: "Amount",
      render: (order) => formatCurrency(order.total_amount),
      mobileLabel: "Amount",
      align: "right",
      sortable: true,
    },
    {
      id: "status",
      header: "Status",
      render: (order) => <StatusPill status={order.status} />,
      mobileLabel: "Status",
      sortable: true,
    },
    {
      id: "placed_at",
      header: "Placed",
      render: (order) => formatDate(order.placed_at),
      mobileLabel: "Placed",
      sortable: true,
    },
  ];

  const viewOrder = (order: Order) => {
    onNavigate(`/orders/${order.id}`);
  };

  const advanceStatus = async (order: Order) => {
    const nextStatus = nextStatusMap[order.status];
    if (!nextStatus || isAdmin || updatingOrderIds.has(order.id)) {
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
      setOrders((current) =>
        current.map((entry) => (entry.id === updated.id ? updated : entry)),
      );
      // A genuine data change: every cached list/tile combination for this
      // session is now stale (the moved order may no longer belong in some
      // filtered views, and the tile counts have shifted). The visible page
      // keeps its already-patched local state; this only affects what the
      // NEXT visit to Orders fetches.
      invalidatePageSnapshotsByPrefix(`${ORDERS_CACHE_PREFIX}:${scope}:`);
      onToastRef.current(
        "Order updated",
        `${order.restaurant.name} order moved to ${nextStatus.replaceAll("_", " ")}.`,
        "success",
      );
    } catch (error: unknown) {
      setOrders((current) =>
        current.map((entry) =>
          entry.id === previousOrder.id ? previousOrder : entry,
        ),
      );
      const message =
        error instanceof ApiError ? error.message : "Unable to update order.";
      onToastRef.current("Status update failed", message, "error");
    } finally {
      setUpdatingOrderIds((current) => {
        const next = new Set(current);
        next.delete(order.id);
        return next;
      });
    }
  };

  return (
    <div className="page-stack">
      <PageIntro
        eyebrow="Operations"
        title="Orders"
        description={
          isAdmin
            ? "Same orders workspace, but with platform-wide visibility across every restaurant."
            : "Same orders workspace, automatically filtered to your assigned restaurant and its customers."
        }
      />

      <StatTiles<"ALL" | OrderStatus>
        active={statusFilter}
        ariaLabel="Order status distribution"
        onSelect={setStatusFilter}
        tiles={statusTiles}
      />

      <section className="admin-surface">
        <DataToolbar
          actions={<span className="toolbar-meta">{pluralize(total, "order")}</span>}
          filters={
            <select
              className="page-search page-search--select"
              onChange={(event) =>
                setStatusFilter(event.target.value as typeof statusFilter)
              }
              value={statusFilter}
            >
              <option value="ALL">All statuses</option>
              {ORDER_FILTER_STATUSES.map((statusValue) => (
                <option key={statusValue} value={statusValue}>
                  {humanizeEnum(statusValue)}
                </option>
              ))}
            </select>
          }
          onSearchChange={setQuery}
          searchPlaceholder="Search by order id, customer, restaurant..."
          searchValue={query}
        />

        <ResponsiveTable
          actions={[
            {
              id: "view",
              label: "View order",
              icon: Eye,
              onClick: viewOrder,
            },
            ...(isAdmin
              ? []
              : [
                  {
                    id: "advance",
                    label: "Advance status",
                    icon: ArrowRight,
                    onClick: advanceStatus,
                    hidden: (order: Order) => !nextStatusMap[order.status],
                    disabled: (order: Order) => updatingOrderIds.has(order.id),
                    tone: "success" as const,
                  },
                ]),
          ]}
          columns={columns}
          emptyAction={
            query || statusFilter !== "ALL" ? (
              <button
                className="secondary-button"
                onClick={() => {
                  setQuery("");
                  setStatusFilter("ALL");
                }}
                type="button"
              >
                Clear filters
              </button>
            ) : null
          }
          emptyDescription="Try another search or status filter."
          emptyTitle="No orders match the current filters"
          errorTitle="We couldn't load your orders"
          error={loadError}
          keyExtractor={(order) => order.id}
          loading={isLoading}
          onRetry={() => {
            setLoadError(null);
            setReloadNonce((current) => current + 1);
          }}
          mobileStatus={(order) => <StatusPill status={order.status} />}
          mobileSubtitle={(order) => order.restaurant.name}
          mobileTitle={(order) => `#${order.id.slice(0, 8)}`}
          onRowClick={viewOrder}
          onSortChange={handleSortChange}
          rows={orders}
          sortState={sort}
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
    </div>
  );
}

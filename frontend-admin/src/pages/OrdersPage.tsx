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
import { ApiError, api, formatCurrency, formatDate } from "../services/api";
import { humanizeEnum, pluralize } from "../services/format";
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

export function OrdersPage({ token, role, onNavigate, onToast }: OrdersPageProps) {
  const isAdmin = role === "ADMIN";
  const [orders, setOrders] = useState<Order[]>([]);
  const [total, setTotal] = useState(0);
  const [tileCounts, setTileCounts] = useState<TileCounts>({});
  const [isLoading, setIsLoading] = useState(true);
  const [updatingOrderIds, setUpdatingOrderIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"ALL" | OrderStatus>("ALL");
  const [sort, setSort] = useState<TableSortState | null>({
    id: "placed_at",
    direction: "desc",
  });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
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
      })
      .catch((error: unknown) => {
        if (!active) {
          return;
        }
        const message =
          error instanceof ApiError ? error.message : "Unable to load orders.";
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
  }, [token, page, pageSize, debouncedQuery, statusFilter, sort]);

  // Tile counts come from cheap COUNT-only requests (limit=1 + X-Total-Count).
  useEffect(() => {
    let active = true;

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
    });

    return () => {
      active = false;
    };
  }, [token, debouncedQuery]);

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
          keyExtractor={(order) => order.id}
          loading={isLoading}
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

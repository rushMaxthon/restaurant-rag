import {
  Activity,
  Bot,
  DollarSign,
  Flame,
  IndianRupee,
  RefreshCw,
  ShieldCheck,
  ShoppingBag,
  Store,
  UtensilsCrossed,
} from "lucide-react";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AreaTrendChart,
  VerticalBarsChart as SharedVerticalBarsChart,
  type ChartDatum,
} from "../components/AnimatedCharts";
import { EmptyPanel } from "../components/EmptyPanel";
import { ResponsiveTable, type TableColumn } from "../components/ResponsiveTable";
import { StatusPill } from "../components/StatusPill";
import {
  ApiError,
  api,
  formatCurrency,
  formatDate,
  toNumber,
} from "../services/api";
import { formatResponseTime, pluralize } from "../services/format";
import type {
  AdminAILog,
  AdminDashboardStats,
  MenuItem,
  Order,
  Restaurant,
  User,
  UserRole,
} from "../types/app";

interface DashboardPageProps {
  token: string;
  role: UserRole;
  restaurantId: string | null;
  onNavigate: (path: string) => void;
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

type DashboardWindow = "7d" | "30d";

function formatTimestamp(value: Date | null): string {
  if (!value) {
    return "Not refreshed yet";
  }
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(value);
}

function getWindowDays(window: DashboardWindow): number {
  return window === "30d" ? 30 : 7;
}

function getWindowStart(days: number): Date {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - (days - 1));
  return start;
}

function getPreviousWindowStart(days: number): Date {
  const start = getWindowStart(days);
  start.setDate(start.getDate() - days);
  return start;
}

function isBetween(dateValue: string, start: Date, end: Date) {
  const date = new Date(dateValue);
  return date >= start && date < end;
}

function formatTrend(current: number, previous: number): string {
  if (previous === 0) {
    return current > 0 ? "+100% vs previous period" : "No change vs previous period";
  }
  const percentage = ((current - previous) / previous) * 100;
  const sign = percentage >= 0 ? "+" : "";
  return `${sign}${percentage.toFixed(1)}% vs previous period`;
}

function formatCompactCurrency(value: number) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    notation: "compact",
    maximumFractionDigits: value >= 1000 ? 1 : 0,
  }).format(value);
}

function DashboardHeader({
  loading,
  lastUpdatedAt,
  timeWindow,
  onChangeWindow,
  onRefresh,
}: {
  loading: boolean;
  lastUpdatedAt: Date | null;
  timeWindow: DashboardWindow;
  onChangeWindow: (value: DashboardWindow) => void;
  onRefresh: () => void;
}) {
  return (
    <section className="dashboard-admin-hero">
      <div className="dashboard-admin-hero__copy">
        <h1>Platform pulse at a glance</h1>
        <p>
          Monitor orders, revenue, AI chat interactions, and operational status across platforms.
        </p>
      </div>
      <div className="dashboard-admin-hero__actions">
        <label className="dashboard-admin-hero__window">
          <select
            onChange={(event) => onChangeWindow(event.target.value as DashboardWindow)}
            value={timeWindow}
          >
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
          </select>
        </label>
        <div className="dashboard-admin-hero__status">{formatTimestamp(lastUpdatedAt)}</div>
        <button
          className="secondary-button dashboard-admin-hero__refresh"
          disabled={loading}
          onClick={onRefresh}
          type="button"
        >
          <RefreshCw className={loading ? "reports-spin" : undefined} size={16} />
          Refresh
        </button>
      </div>
    </section>
  );
}

function DashboardMetricCard({
  accentClass,
  icon,
  label,
  value,
  trend,
  description,
}: {
  accentClass: string;
  icon: ReactNode;
  label: string;
  value: string;
  trend: string;
  description: string;
}) {
  return (
    <article className={`dashboard-admin-metric ${accentClass}`}>
      <div className="dashboard-admin-metric__top">
        <span>{label}</span>
        <div className="dashboard-admin-metric__icon">{icon}</div>
      </div>
      <strong>{value}</strong>
      <small>{trend}</small>
      <p>{description}</p>
    </article>
  );
}

function DashboardAreaChart({
  title,
  subtitle,
  data,
}: {
  title: string;
  subtitle: string;
  data: ChartDatum[];
}) {
  if (!data.length) {
    return (
      <section className="admin-surface dashboard-admin-panel">
        <div className="admin-surface__header">
          <div>
            <span className="eyebrow">Trend</span>
            <h2>{title}</h2>
          </div>
        </div>
        <EmptyPanel description="Data will appear here once matching activity is available." title={subtitle} />
      </section>
    );
  }

  return (
    <section className="admin-surface dashboard-admin-panel dashboard-admin-panel--chart">
      <div className="admin-surface__header">
        <div>
          <span className="eyebrow">Trend</span>
          <h2>{title}</h2>
        </div>
      </div>
      <p className="hint-text">{subtitle}</p>
      <AreaTrendChart className="dashboard-admin-area-chart" data={data} seriesLabel="Orders" />
    </section>
  );
}

function DashboardBarsChart({
  title,
  subtitle,
  data,
}: {
  title: string;
  subtitle: string;
  data: ChartDatum[];
}) {
  return (
    <section className="admin-surface dashboard-admin-panel dashboard-admin-panel--chart">
      <div className="admin-surface__header">
        <div>
          <span className="eyebrow">Revenue trend</span>
          <h2>{title}</h2>
        </div>
      </div>
      <p className="hint-text">{subtitle}</p>
      {data.length ? (
        <SharedVerticalBarsChart
          className="dashboard-admin-bars"
          data={data}
          valueFormatter={formatCompactCurrency}
        />
      ) : (
        <EmptyPanel description="Revenue bars appear when paid orders are available." title="No revenue data yet" />
      )}
    </section>
  );
}

export function DashboardPage({
  token,
  role,
  restaurantId,
  onNavigate,
  onToast,
}: DashboardPageProps) {
  const isAdmin = role === "ADMIN";
  const [loading, setLoading] = useState(true);
  const [timeWindow, setTimeWindow] = useState<DashboardWindow>("7d");
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);
  const [stats, setStats] = useState<AdminDashboardStats | null>(null);
  const [restaurants, setRestaurants] = useState<Restaurant[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [menuItems, setMenuItems] = useState<MenuItem[]>([]);
  const [aiLogs, setAiLogs] = useState<AdminAILog[]>([]);
  const [assignedRestaurant, setAssignedRestaurant] =
    useState<Restaurant | null>(null);

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    try {
      if (isAdmin) {
        const [
          dashboardStats,
          restaurantRows,
          userRows,
          orderRows,
          aiLogRows,
        ] = await Promise.all([
          api.getAdminDashboard(token),
          api.getAdminRestaurants(token),
          api.getAdminUsers(token),
          api.getOrders(token),
          api.getAdminAILogs(token),
        ]);
        setStats(dashboardStats);
        setRestaurants(restaurantRows);
        setUsers(userRows);
        setOrders(orderRows);
        setAiLogs(aiLogRows);
      } else {
        if (!restaurantId) {
          onToast(
            "Dashboard unavailable",
            "No restaurant is assigned to this owner account.",
            "error",
          );
          return;
        }

        const [ownedRestaurants, orderRows, menuRows] = await Promise.all([
          api.getOwnerRestaurants(token),
          api.getOrders(token),
          api.getMenuItems(token, restaurantId),
        ]);

        const currentRestaurant =
          ownedRestaurants.find((entry) => entry.id === restaurantId) ??
          ownedRestaurants[0] ??
          null;

        setAssignedRestaurant(currentRestaurant);
        setOrders(orderRows);
        setMenuItems(menuRows);
      }

      setLastUpdatedAt(new Date());
    } catch (error: unknown) {
      const message =
        error instanceof ApiError ? error.message : "Unable to load dashboard.";
      onToast("Dashboard unavailable", message, "error");
    } finally {
      setLoading(false);
    }
  }, [isAdmin, onToast, restaurantId, token]);

  useEffect(() => {
    let active = true;
    void (async () => {
      setLoading(true);
      try {
        if (isAdmin) {
          const [
            dashboardStats,
            restaurantRows,
            userRows,
            orderRows,
            aiLogRows,
          ] = await Promise.all([
            api.getAdminDashboard(token),
            api.getAdminRestaurants(token),
            api.getAdminUsers(token),
            api.getOrders(token),
            api.getAdminAILogs(token),
          ]);
          if (!active) {
            return;
          }
          setStats(dashboardStats);
          setRestaurants(restaurantRows);
          setUsers(userRows);
          setOrders(orderRows);
          setAiLogs(aiLogRows);
        } else {
          if (!restaurantId) {
            onToast(
              "Dashboard unavailable",
              "No restaurant is assigned to this owner account.",
              "error",
            );
            return;
          }

          const [ownedRestaurants, orderRows, menuRows] = await Promise.all([
            api.getOwnerRestaurants(token),
            api.getOrders(token),
            api.getMenuItems(token, restaurantId),
          ]);
          if (!active) {
            return;
          }
          const currentRestaurant =
            ownedRestaurants.find((entry) => entry.id === restaurantId) ??
            ownedRestaurants[0] ??
            null;
          setAssignedRestaurant(currentRestaurant);
          setOrders(orderRows);
          setMenuItems(menuRows);
        }
        if (active) {
          setLastUpdatedAt(new Date());
        }
      } catch (error: unknown) {
        if (!active) {
          return;
        }
        const message =
          error instanceof ApiError
            ? error.message
            : "Unable to load dashboard.";
        onToast("Dashboard unavailable", message, "error");
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [isAdmin, onToast, restaurantId, token]);

  const windowDays = getWindowDays(timeWindow);
  const currentWindowStart = useMemo(() => getWindowStart(windowDays), [windowDays]);
  const previousWindowStart = useMemo(() => getPreviousWindowStart(windowDays), [windowDays]);
  const currentWindowEnd = useMemo(() => lastUpdatedAt ?? new Date(), [lastUpdatedAt]);

  const chartDays = useMemo(() => {
    const labelFormatter = new Intl.DateTimeFormat("en-IN", {
      month: "short",
      day: "numeric",
    });
    const metaFormatter = new Intl.DateTimeFormat("en-IN", {
      weekday: "short",
      month: "short",
      day: "numeric",
    });
    return Array.from({ length: windowDays }, (_, index) => {
      const date = new Date(currentWindowStart);
      date.setDate(currentWindowStart.getDate() + index);
      return {
        key: date.toDateString(),
        label: labelFormatter.format(date),
        meta: metaFormatter.format(date),
      };
    });
  }, [currentWindowStart, windowDays]);

  const ordersByDay = useMemo(
    () =>
      chartDays.map((day) => ({
        label: day.label,
        meta: day.meta,
        value: orders.filter(
          (order) => new Date(order.placed_at).toDateString() === day.key,
        ).length,
      })),
    [chartDays, orders],
  );

  const revenueByDay = useMemo(
    () =>
      chartDays.map((day) => ({
        label: day.label,
        meta: day.meta,
        value: Math.round(
          orders
            .filter(
              (order) => new Date(order.placed_at).toDateString() === day.key,
            )
            .reduce((total, order) => total + toNumber(order.total_amount), 0),
        ),
      })),
    [chartDays, orders],
  );

  const todayKey = new Date().toDateString();
  const todaysOrders = useMemo(
    () =>
      orders.filter(
        (order) => new Date(order.placed_at).toDateString() === todayKey,
      ),
    [orders, todayKey],
  );

  const todaysRevenue = useMemo(
    () =>
      todaysOrders.reduce(
        (total, order) => total + toNumber(order.total_amount),
        0,
      ),
    [todaysOrders],
  );

  const windowOrders = useMemo(
    () =>
      orders.filter((order) =>
        isBetween(order.placed_at, currentWindowStart, currentWindowEnd),
      ),
    [currentWindowEnd, currentWindowStart, orders],
  );

  const previousWindowOrders = useMemo(
    () =>
      orders.filter((order) =>
        isBetween(order.placed_at, previousWindowStart, currentWindowStart),
      ),
    [currentWindowStart, orders, previousWindowStart],
  );

  const pendingRestaurants = useMemo(
    () =>
      restaurants.filter((restaurant) => !restaurant.is_approved).slice(0, 5),
    [restaurants],
  );

  const recentOrders = useMemo(
    () =>
      [...windowOrders]
        .sort(
          (left, right) =>
            new Date(right.placed_at).getTime() -
            new Date(left.placed_at).getTime(),
        )
        .slice(0, 5),
    [windowOrders],
  );

  const recentRestaurants = useMemo(
    () =>
      [...restaurants]
        .sort(
          (left, right) =>
            new Date(right.created_at).getTime() -
            new Date(left.created_at).getTime(),
        )
        .slice(0, 5),
    [restaurants],
  );

  const recentUsers = useMemo(
    () =>
      [...users]
        .sort(
          (left, right) =>
            new Date(right.created_at).getTime() -
            new Date(left.created_at).getTime(),
        )
        .slice(0, 5),
    [users],
  );

  const windowAiLogs = useMemo(
    () =>
      aiLogs.filter((entry) =>
        isBetween(entry.created_at, currentWindowStart, currentWindowEnd),
      ),
    [aiLogs, currentWindowEnd, currentWindowStart],
  );

  const previousWindowAiLogs = useMemo(
    () =>
      aiLogs.filter((entry) =>
        isBetween(entry.created_at, previousWindowStart, currentWindowStart),
      ),
    [aiLogs, currentWindowStart, previousWindowStart],
  );

  const recentAiLogs = useMemo(
    () =>
      [...windowAiLogs]
        .sort(
          (left, right) =>
            new Date(right.created_at).getTime() -
            new Date(left.created_at).getTime(),
        )
        .slice(0, 5),
    [windowAiLogs],
  );

  const topRestaurants = useMemo(() => {
    const map = new Map<
      string,
      { name: string; revenue: number; orders: number; cuisine: string }
    >();

    for (const order of windowOrders) {
      const current = map.get(order.restaurant_id);
      map.set(order.restaurant_id, {
        name: order.restaurant.name,
        revenue: (current?.revenue ?? 0) + toNumber(order.total_amount),
        orders: (current?.orders ?? 0) + 1,
        cuisine: order.restaurant.cuisine_type,
      });
    }

    return Array.from(map.values())
      .sort((left, right) => right.revenue - left.revenue)
      .slice(0, 5);
  }, [windowOrders]);

  const topItems = useMemo(() => {
    const counts = new Map<
      string,
      {
        name: string;
        quantity: number;
        revenue: number;
        category?: string;
        description?: string | null;
      }
    >();

    for (const order of orders) {
      for (const item of order.items) {
        const current = counts.get(item.menu_item_id);
        const sourceMenu = menuItems.find(
          (entry) => entry.id === item.menu_item_id,
        );
        counts.set(item.menu_item_id, {
          name: item.item_name_snapshot,
          quantity: (current?.quantity ?? 0) + item.quantity,
          revenue: (current?.revenue ?? 0) + toNumber(item.total_price),
          category: sourceMenu?.category ?? current?.category,
          description: sourceMenu?.description ?? current?.description ?? null,
        });
      }
    }

    return Array.from(counts.entries())
      .map(([id, value]) => ({ id, ...value }))
      .sort((left, right) => right.quantity - left.quantity)
      .slice(0, 5);
  }, [menuItems, orders]);

  const aiStats = useMemo(() => {
    const total = aiLogs.length;
    const failures = aiLogs.filter((entry) => !entry.success).length;
    const responseTimes = aiLogs
      .map((entry) => entry.response_time_ms)
      .filter((value): value is number => value !== null);
    const avgResponse =
      responseTimes.length > 0
        ? Math.round(
            responseTimes.reduce((totalTime, value) => totalTime + value, 0) /
              responseTimes.length,
          )
        : 0;

    const uniqueSessions = new Set(aiLogs.map((entry) => entry.session_id)).size;
    const uniqueSessionsWindow = new Set(
      windowAiLogs.map((entry) => entry.session_id),
    ).size;
    const uniqueSessionsPrevious = new Set(
      previousWindowAiLogs.map((entry) => entry.session_id),
    ).size;

    return {
      total,
      failures,
      avgResponse,
      uniqueSessions,
      uniqueSessionsWindow,
      uniqueSessionsPrevious,
    };
  }, [aiLogs, previousWindowAiLogs, windowAiLogs]);

  const ordersTrend = useMemo(
    () =>
      formatTrend(windowOrders.length, previousWindowOrders.length),
    [previousWindowOrders.length, windowOrders.length],
  );

  const revenueTrend = useMemo(
    () =>
      formatTrend(
        windowOrders.reduce((total, order) => total + toNumber(order.total_amount), 0),
        previousWindowOrders.reduce((total, order) => total + toNumber(order.total_amount), 0),
      ),
    [previousWindowOrders, windowOrders],
  );

  const aiTrend = useMemo(
    () =>
      formatTrend(
        aiStats.uniqueSessionsWindow,
        aiStats.uniqueSessionsPrevious,
      ),
    [aiStats.uniqueSessionsPrevious, aiStats.uniqueSessionsWindow],
  );

  const topItemColumns: Array<
    TableColumn<{
      id: string;
      name: string;
      quantity: number;
      revenue: number;
      category?: string;
      description?: string | null;
    }>
  > = [
    {
      id: "item",
      header: "Item",
      render: (item) => (
        <>
          <strong>{item.name}</strong>
          <span>{item.description ?? "Popular choice"}</span>
        </>
      ),
      hideOnMobile: true,
    },
    {
      id: "category",
      header: "Category",
      render: (item) => item.category ?? "Uncategorized",
      mobileLabel: "Category",
    },
    {
      id: "units",
      header: "Units sold",
      render: (item) => String(item.quantity),
      mobileLabel: "Units sold",
      align: "right",
    },
    {
      id: "revenue",
      header: "Revenue",
      render: (item) => formatCurrency(item.revenue),
      mobileLabel: "Revenue",
      align: "right",
    },
  ];

  if (isAdmin) {
    return (
      <div className="page-stack">
        <DashboardHeader
          lastUpdatedAt={lastUpdatedAt}
          loading={loading}
          onChangeWindow={setTimeWindow}
          onRefresh={() => {
            void loadDashboard();
          }}
          timeWindow={timeWindow}
        />

        <section className="dashboard-admin-metrics">
          <DashboardMetricCard
            accentClass="dashboard-admin-metric--orders"
            description="Platform-wide order volume from the current backend snapshot."
            icon={<ShoppingBag size={18} />}
            label="Total platform orders"
            trend={ordersTrend}
            value={String(stats?.total_orders ?? 0)}
          />
          <DashboardMetricCard
            accentClass="dashboard-admin-metric--revenue"
            description="Gross paid order value captured across accessible restaurants."
            icon={<IndianRupee size={18} />}
            label="Revenue"
            trend={revenueTrend}
            value={formatCurrency(stats?.total_revenue ?? 0)}
          />
          <DashboardMetricCard
            accentClass="dashboard-admin-metric--approvals"
            description="Restaurants still waiting for review and launch approval."
            icon={<Store size={18} />}
            label="Pending approvals"
            trend={`${pendingRestaurants.length} restaurants awaiting action`}
            value={String(pendingRestaurants.length)}
          />
          <DashboardMetricCard
            accentClass="dashboard-admin-metric--ai"
            description="Unique AI chat sessions recorded from current assistant activity."
            icon={<Bot size={18} />}
            label="AI chat sessions"
            trend={aiTrend}
            value={String(aiStats.uniqueSessions)}
          />
        </section>

        <section className="dashboard-admin-grid">
          <div className="dashboard-admin-grid__main">
            <DashboardAreaChart
              data={ordersByDay}
              subtitle={`Order volume over the selected ${timeWindow === "30d" ? "30-day" : "7-day"} window`}
              title="Orders trend"
            />

            <DashboardBarsChart
              data={revenueByDay}
              subtitle={`Revenue performance across the selected ${timeWindow === "30d" ? "30-day" : "7-day"} window`}
              title="Revenue trend"
            />

            <section className="admin-surface dashboard-admin-panel dashboard-admin-panel--empty">
              <div className="admin-surface__header">
                <div>
                  <span className="eyebrow">Pending restaurant approvals</span>
                  <h2>New restaurants awaiting review</h2>
                </div>
              </div>
              {pendingRestaurants.length > 0 ? (
                <div className="dashboard-admin-list">
                  {pendingRestaurants.map((restaurant) => (
                    <article className="dashboard-admin-list__row" key={restaurant.id}>
                      <div>
                        <strong>{restaurant.name}</strong>
                        <span>
                          {restaurant.city} • {restaurant.cuisine_type}
                        </span>
                      </div>
                      <div className="dashboard-admin-list__meta">
                        <StatusPill status={restaurant.is_open ? "OPEN" : "CLOSED"} />
                        <span>{formatDate(restaurant.created_at)}</span>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="dashboard-admin-empty-state">
                  <div className="dashboard-admin-empty-state__icon">
                    <ShieldCheck size={28} />
                  </div>
                  <strong>No approvals pending</strong>
                  <p>All restaurant applications have been reviewed.</p>
                </div>
              )}
            </section>
          </div>

          <aside className="dashboard-admin-grid__aside">
            <section className="admin-surface dashboard-admin-panel">
              <div className="admin-surface__header">
                <div>
                  <span className="eyebrow">Platform health</span>
                  <h2>RAG health</h2>
                </div>
                <ShieldCheck size={18} />
              </div>
              <div className="dashboard-admin-health__selector">Platform</div>
              <div className="dashboard-admin-health">
                <div className="dashboard-admin-health__row dashboard-admin-health__row--success">
                  <span>Status</span>
                  <StatusPill status={aiStats.total > 0 ? "ACTIVE" : "IDLE"} />
                </div>
                <div className="dashboard-admin-health__row dashboard-admin-health__row--warning">
                  <span>Alert level</span>
                  <StatusPill status={aiStats.failures > 0 ? "AMBER" : "CLEAR"} />
                </div>
                <div className="dashboard-admin-health__row">
                  <span>Avg response time</span>
                  <strong>{formatResponseTime(aiStats.avgResponse, { zeroLabel: 'No data' })}</strong>
                </div>
                <div className="dashboard-admin-health__row">
                  <span>Failures</span>
                  <strong>{aiStats.failures}</strong>
                </div>
              </div>
            </section>

            <section className="admin-surface dashboard-admin-panel">
              <div className="admin-surface__header">
                <div>
                  <span className="eyebrow">Recent activity</span>
                  <h2>Latest orders</h2>
                </div>
                <Activity size={18} />
              </div>
              {recentOrders.length > 0 ? (
                <div className="dashboard-admin-list">
                  {recentOrders.map((order) => (
                    <article className="dashboard-admin-list__row" key={order.id}>
                      <div>
                        <strong>{order.restaurant.name}</strong>
                        <span>
                          Cuisine: {order.restaurant.cuisine_type} •{" "}
                          {new Intl.DateTimeFormat("en-IN", {
                            hour: "2-digit",
                            minute: "2-digit",
                            hour12: false,
                          }).format(new Date(order.placed_at))}
                        </span>
                      </div>
                      <div className="dashboard-admin-list__meta">
                        <strong>{formatCurrency(order.total_amount)}</strong>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <EmptyPanel
                  description="Orders inside the selected dashboard window will appear here."
                  title="No recent orders"
                />
              )}
            </section>

            <section className="admin-surface dashboard-admin-panel">
              <div className="admin-surface__header">
                <div>
                  <span className="eyebrow">Revenue leaders</span>
                  <h2>Top restaurants</h2>
                </div>
                <Store size={18} />
              </div>
              {topRestaurants.length > 0 ? (
                <div className="dashboard-admin-list">
                  {topRestaurants.map((restaurant) => (
                    <article className="dashboard-admin-list__row" key={restaurant.name}>
                      <div>
                        <strong>{restaurant.name}</strong>
                        <span>{restaurant.cuisine}</span>
                      </div>
                      <div className="dashboard-admin-list__meta">
                        <span>{pluralize(restaurant.orders, 'order')}</span>
                        <strong>{formatCurrency(restaurant.revenue)}</strong>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <EmptyPanel
                  description="Revenue leaders will appear after orders land in the selected dashboard window."
                  title="No restaurant leaders yet"
                />
                )}
              </section>
          </aside>
        </section>

        <section className="dashboard-admin-tertiary-grid">
          <section className="admin-surface dashboard-admin-panel">
            <div className="admin-surface__header">
              <div>
                <span className="eyebrow">Recent restaurants</span>
                <h2>Newest onboarding activity</h2>
              </div>
            </div>
            {recentRestaurants.length > 0 ? (
              <div className="dashboard-admin-list">
                {recentRestaurants.map((restaurant) => (
                  <article className="dashboard-admin-list__row" key={restaurant.id}>
                    <div>
                      <strong>{restaurant.name}</strong>
                      <span>{restaurant.city}</span>
                    </div>
                    <div className="dashboard-admin-list__meta">
                      <StatusPill status={restaurant.is_approved ? "APPROVED" : "PENDING"} />
                      <span>{formatDate(restaurant.created_at)}</span>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyPanel
                description="Newly created restaurants will appear here."
                title="No restaurants yet"
              />
            )}
          </section>

          <section className="admin-surface dashboard-admin-panel">
            <div className="admin-surface__header">
              <div>
                <span className="eyebrow">Recent users</span>
                <h2>Latest account creation</h2>
              </div>
            </div>
            {recentUsers.length > 0 ? (
              <div className="dashboard-admin-list">
                {recentUsers.map((user) => (
                  <article className="dashboard-admin-list__row" key={user.id}>
                    <div>
                      <strong>{user.full_name}</strong>
                      <span>{user.email}</span>
                    </div>
                    <div className="dashboard-admin-list__meta">
                      <StatusPill status={user.is_active ? "ACTIVE" : "INACTIVE"} />
                      <span>{formatDate(user.created_at)}</span>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyPanel
                description="New customer, owner, and admin accounts will appear here."
                title="No recent users"
              />
            )}
          </section>

          <section className="admin-surface dashboard-admin-panel">
            <div className="admin-surface__header">
              <div>
                <span className="eyebrow">Recent AI activity</span>
                <h2>Latest assistant traces</h2>
              </div>
              <Flame size={18} />
            </div>
            {recentAiLogs.length > 0 ? (
              <div className="dashboard-admin-list">
                {recentAiLogs.map((log) => (
                  <article className="dashboard-admin-list__row" key={`${log.session_id}-${log.created_at}`}>
                    <div>
                      <strong>{log.restaurant_name ?? "Platform"}</strong>
                      <span>{log.query_text}</span>
                    </div>
                    <div className="dashboard-admin-list__meta">
                      <StatusPill status={log.success ? "SUCCESS" : "FAILURE"} />
                      <span>{formatDate(log.created_at)}</span>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyPanel
                description="Assistant traces will appear here once users start chatting."
                title="No recent AI activity"
              />
            )}
          </section>
        </section>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <section className="dashboard-admin-hero">
        <div className="dashboard-admin-hero__copy">
          <h1>
            {assignedRestaurant
              ? assignedRestaurant.name
              : "Restaurant operations at a glance"}
          </h1>
          <p>
            Today's orders, revenue, menu health, and top dishes for your
            restaurant in one focused view.
          </p>
        </div>
        <div className="dashboard-admin-hero__actions">
          {assignedRestaurant ? (
            <StatusPill status={assignedRestaurant.is_open ? "OPEN" : "CLOSED"} />
          ) : null}
          <div className="dashboard-admin-hero__status">{formatTimestamp(lastUpdatedAt)}</div>
          {assignedRestaurant ? (
            <button
              className="secondary-button"
              onClick={() =>
                onNavigate(`/admin/restaurants/${assignedRestaurant.id}/locations`)
              }
              type="button"
            >
              Open workspace
            </button>
          ) : null}
          <button
            className="secondary-button dashboard-admin-hero__refresh"
            disabled={loading}
            onClick={() => {
              void loadDashboard();
            }}
            type="button"
          >
            <RefreshCw className={loading ? "reports-spin" : undefined} size={16} />
            Refresh
          </button>
        </div>
      </section>

      <section className="dashboard-admin-metrics">
        <DashboardMetricCard
          accentClass="dashboard-admin-metric--orders"
          description="Orders placed today for your assigned restaurant."
          icon={<ShoppingBag size={18} />}
          label="Today's orders"
          trend="Live orders placed today"
          value={String(todaysOrders.length)}
        />
        <DashboardMetricCard
          accentClass="dashboard-admin-metric--revenue"
          description="Gross order value captured today."
          icon={<DollarSign size={18} />}
          label="Today's revenue"
          trend="Gross value for today"
          value={formatCurrency(todaysRevenue)}
        />
        <DashboardMetricCard
          accentClass="dashboard-admin-metric--approvals"
          description="Items currently visible and orderable by customers."
          icon={<UtensilsCrossed size={18} />}
          label="Active menu items"
          trend="Currently visible to customers"
          value={String(menuItems.filter((item) => item.is_available).length)}
        />
        <DashboardMetricCard
          accentClass="dashboard-admin-metric--ai"
          description="Best performing dish by recent sales."
          icon={<Flame size={18} />}
          label="Top seller"
          trend="Best performing dish"
          value={topItems[0]?.name ?? "No sales yet"}
        />
      </section>

      <section className="dashboard-admin-grid">
        <div className="dashboard-admin-grid__main">
          <DashboardAreaChart
            data={ordersByDay}
            subtitle="Order volume over the last 7 days"
            title="Orders trend"
          />
          <DashboardBarsChart
            data={revenueByDay}
            subtitle="Daily restaurant revenue"
            title="Revenue trend"
          />

          <section className="admin-surface">
            <div className="admin-surface__header">
              <div>
                <span className="eyebrow">Top items</span>
                <h2>Best performing dishes</h2>
              </div>
            </div>
            {topItems.length > 0 ? (
              <ResponsiveTable
                columns={topItemColumns}
                emptyDescription="Once orders arrive, your top items will surface here automatically."
                emptyTitle="No item sales yet"
                keyExtractor={(item) => item.id}
                mobileSubtitle={(item) => item.category ?? "Uncategorized"}
                mobileTitle={(item) => item.name}
                rows={topItems}
              />
            ) : (
              <EmptyPanel
                description="Once orders arrive, your top items will surface here automatically."
                title="No item sales yet"
              />
            )}
          </section>
        </div>

        <aside className="dashboard-admin-grid__aside">
          {assignedRestaurant ? (
            <section className="admin-surface">
              <div className="admin-surface__header">
                <div>
                  <span className="eyebrow">Assigned restaurant</span>
                  <h2>{assignedRestaurant.name}</h2>
                </div>
              </div>
              <p className="hint-text">
                Every dashboard metric on this page is automatically filtered to
                this restaurant only.
              </p>
            </section>
          ) : null}

          <section className="admin-surface">
            <div className="admin-surface__header">
              <div>
                <span className="eyebrow">Recent orders</span>
                <h2>Latest activity</h2>
              </div>
            </div>
            {recentOrders.length > 0 ? (
              <div className="insight-list">
                {recentOrders.map((order) => (
                  <article className="insight-row" key={order.id}>
                    <div>
                      <strong>{order.customer.full_name}</strong>
                      <span>{formatDate(order.placed_at)}</span>
                    </div>
                    <div className="insight-row__meta">
                      <StatusPill status={order.status} />
                      <span>{formatCurrency(order.total_amount)}</span>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyPanel
                description="Your first order will show up here once customers start checking out."
                title="No recent orders"
              />
            )}
          </section>
        </aside>
      </section>
    </div>
  );
}

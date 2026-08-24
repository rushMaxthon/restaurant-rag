import {
  ArrowUpRight,
  Bot,
  Clock3,
  Download,
  IndianRupee,
  RefreshCw,
  Repeat2,
  ShoppingBag,
  SlidersHorizontal,
  Store,
  Trophy,
  Users,
  Utensils,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AreaTrendChart,
  HorizontalBarsChart,
  VerticalBarsChart,
  type ChartDatum,
} from "../components/AnimatedCharts";
import { EmptyPanel } from "../components/EmptyPanel";
import { ResponsiveTable, type TableColumn } from "../components/ResponsiveTable";
import { StatusPill } from "../components/StatusPill";
import { ApiError, api, formatCurrency } from "../services/api";
import { humanizeEnum, pluralize } from "../services/format";
import { buildAdminRestaurantsCacheKeyPrefix } from "./AdminRestaurantsPage";
import {
  getPageSnapshot,
  hasPageSnapshot,
  setPageSnapshot,
  tokenScope,
} from "../services/pageCache";
import {
  ORDER_FILTER_STATUSES,
  type OrderStatus,
  type ReportComboPerformance,
  type ReportItemPerformance,
  type ReportRestaurantPerformance,
  type ReportsSnapshot,
  type Restaurant,
  type UserRole,
} from "../types/app";

interface ReportsPageProps {
  token: string;
  role: UserRole;
  restaurantId: string | null;
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

type DatePreset = "today" | "7d" | "30d" | "custom";
type ReportsTab = "analytics" | "items" | "chat";
type RankedRestaurantPerformance = ReportRestaurantPerformance & { rank: number };
type RankedItemPerformance = ReportItemPerformance & { rank: number };
type RankedComboPerformance = ReportComboPerformance & { rank: number };

const PRESET_LABELS: Record<DatePreset, string> = {
  today: "Today",
  "7d": "7 days",
  "30d": "30 days",
  custom: "Custom",
};

function toDateInputValue(value: Date): string {
  const year = value.getFullYear();
  const month = `${value.getMonth() + 1}`.padStart(2, "0");
  const day = `${value.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function getPresetRange(preset: Exclude<DatePreset, "custom">): {
  from: string;
  to: string;
} {
  const today = new Date();
  const end = toDateInputValue(today);
  const start = new Date(today);
  if (preset === "today") {
    return { from: end, to: end };
  }
  start.setDate(today.getDate() - (preset === "7d" ? 6 : 29));
  return { from: toDateInputValue(start), to: end };
}

function formatTimestamp(value: Date | null): string {
  if (!value) {
    return "Not refreshed yet";
  }
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(value);
}

function formatDateRange(dateFrom: string, dateTo: string): string {
  if (dateFrom && dateTo) {
    return `${dateFrom} → ${dateTo}`;
  }
  return "All time";
}

function formatCompactCurrency(value: number) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    notation: "compact",
    maximumFractionDigits: value >= 1000 ? 1 : 0,
  }).format(value);
}

function formatCompactNumber(value: number) {
  return new Intl.NumberFormat("en-IN", {
    notation: value >= 10000 ? "compact" : "standard",
    maximumFractionDigits: 1,
  }).format(value);
}

function StatTile({
  label,
  value,
  hint,
  icon: Icon,
  tone = "neutral",
  loading,
}: {
  label: string;
  value: string;
  hint: string;
  icon: LucideIcon;
  tone?: "accent" | "neutral";
  loading: boolean;
}) {
  return (
    <article className={`rpt-stat rpt-stat--${tone}`}>
      <div className="rpt-stat__head">
        <span className="rpt-stat__label">{label}</span>
        <span className="rpt-stat__icon">
          <Icon size={15} strokeWidth={2.1} />
        </span>
      </div>
      <strong className="rpt-stat__value">
        {loading ? <span className="rpt-skeleton rpt-skeleton--value" /> : value}
      </strong>
      <span className="rpt-stat__hint">{loading ? "Refreshing…" : hint}</span>
    </article>
  );
}

function ChartPanel({
  title,
  subtitle,
  children,
  loading,
  hasData,
  emptyTitle,
  emptyDescription,
  className,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
  loading: boolean;
  hasData: boolean;
  emptyTitle: string;
  emptyDescription: string;
  className?: string;
}) {
  return (
    <article className={className ? `rpt-panel ${className}` : "rpt-panel"}>
      <header className="rpt-panel__header">
        <h3>{title}</h3>
        <p>{subtitle}</p>
      </header>
      {loading ? (
        <div aria-hidden="true" className="rpt-chart-skeleton">
          <span />
          <span />
          <span />
          <span />
          <span />
        </div>
      ) : hasData ? (
        children
      ) : (
        <EmptyPanel description={emptyDescription} title={emptyTitle} />
      )}
    </article>
  );
}

function HighlightCard({
  icon: Icon,
  label,
  title,
  meta,
  aside,
}: {
  icon: LucideIcon;
  label: string;
  title: string;
  meta: string;
  aside?: ReactNode;
}) {
  return (
    <article className="rpt-highlight">
      <span className="rpt-highlight__icon">
        <Icon size={15} strokeWidth={2.1} />
      </span>
      <div className="rpt-highlight__copy">
        <span>{label}</span>
        <strong>{title}</strong>
        <em>{meta}</em>
      </div>
      {aside ? <div className="rpt-highlight__aside">{aside}</div> : null}
    </article>
  );
}

export function ReportsPage({
  token,
  role,
  restaurantId,
  onToast,
}: ReportsPageProps) {
  const isAdmin = role === "ADMIN";
  const defaultRange = useMemo(() => getPresetRange("30d"), []);
  const scope = tokenScope(token);
  // Admins fetch the same list AdminRestaurantsPage shows - share its exact
  // key so switching between the two pages costs one fetch instead of two.
  // An owner's restaurant list comes from a different endpoint, so it gets
  // its own key.
  const restaurantsKey = isAdmin
    ? buildAdminRestaurantsCacheKeyPrefix(scope)
    : `reports-owner-restaurants:${scope}`;

  // The initial-render key, built from the same literals every filter
  // useState below starts from - computed ahead of them so `reports` and
  // `loading` can seed from it in their own lazy initializers, exactly like
  // the key the mount effect will compute once those states exist.
  const initialReportsKey = [
    "reports",
    scope,
    defaultRange.from,
    defaultRange.to,
    // `restaurantFilter`'s own initial value is `restaurantId ?? ""` too, so
    // this matches the real key regardless of admin/owner.
    restaurantId ?? "",
    "",
    "",
    "",
  ].join(":");

  const [restaurants, setRestaurants] = useState<Restaurant[]>(
    () => getPageSnapshot<Restaurant[]>(restaurantsKey) ?? [],
  );
  const [reports, setReports] = useState<ReportsSnapshot | null>(
    () => getPageSnapshot<ReportsSnapshot>(initialReportsKey) ?? null,
  );
  // Only true when this exact filter combination has never been fetched this
  // session - not on every mount, so revisiting reports (with the same
  // defaults) keeps showing its data instead of a skeleton.
  const [loading, setLoading] = useState(() => !hasPageSnapshot(initialReportsKey));
  const [error, setError] = useState<string | null>(null);
  const [preset, setPreset] = useState<DatePreset>("30d");
  const [dateFrom, setDateFrom] = useState(defaultRange.from);
  const [dateTo, setDateTo] = useState(defaultRange.to);
  const [restaurantFilter, setRestaurantFilter] = useState<string>(restaurantId ?? "");
  const [cuisineFilter, setCuisineFilter] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<OrderStatus | "">("");
  const [activeTab, setActiveTab] = useState<ReportsTab>("analytics");
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);

  // Every filter that reaches the API belongs in this key - a filter change
  // is exactly the "required scope/filter change" that should hit the
  // network again, while returning to a combination already fetched this
  // session should not.
  const reportsKey = [
    "reports",
    scope,
    dateFrom,
    dateTo,
    isAdmin ? restaurantFilter : restaurantId ?? "",
    cuisineFilter,
    categoryFilter,
    statusFilter,
  ].join(":");

  // `force`: bypasses the cache. The Refresh button below always forces;
  // the mount/filter-change effects never do, which is what makes revisiting
  // this page (or a filter combination already seen) free.
  const loadRestaurants = useCallback(
    async (force = false) => {
      if (!force) {
        const cached = getPageSnapshot<Restaurant[]>(restaurantsKey);
        if (cached) {
          setRestaurants(cached);
          if (!isAdmin) {
            setRestaurantFilter((current) => current || restaurantId || cached[0]?.id || "");
          }
          return;
        }
      }

      try {
        const rows = isAdmin
          ? await api.getAdminRestaurants(token)
          : await api.getOwnerRestaurants(token);
        setRestaurants(rows);
        setPageSnapshot(restaurantsKey, rows);
        if (!isAdmin) {
          setRestaurantFilter((current) => current || restaurantId || rows[0]?.id || "");
        }
      } catch (loadError) {
        const message =
          loadError instanceof ApiError
            ? loadError.message
            : "Unable to load restaurant filters.";
        onToast("Filter options unavailable", message, "error");
      }
    },
    [isAdmin, onToast, restaurantId, restaurantsKey, token],
  );

  const loadReports = useCallback(
    async (force = false) => {
      if (!force) {
        const cached = getPageSnapshot<ReportsSnapshot>(reportsKey);
        if (cached) {
          setReports(cached);
          setLoading(false);
          return;
        }
      }

      setLoading(true);
      setError(null);
      try {
        const snapshot = await api.getReports(token, {
          dateFrom: dateFrom || null,
          dateTo: dateTo || null,
          restaurantId: isAdmin ? restaurantFilter || null : restaurantId,
          cuisineType: cuisineFilter || null,
          category: categoryFilter || null,
          orderStatus: statusFilter || null,
        });
        setReports(snapshot);
        setLastUpdatedAt(new Date());
        setPageSnapshot(reportsKey, snapshot);
      } catch (loadError) {
        const message =
          loadError instanceof ApiError
            ? loadError.message
            : "Unable to load analytics.";
        setError(message);
        onToast("Reports unavailable", message, "error");
      } finally {
        setLoading(false);
      }
    },
    [
      categoryFilter,
      cuisineFilter,
      dateFrom,
      dateTo,
      isAdmin,
      onToast,
      reportsKey,
      restaurantFilter,
      restaurantId,
      statusFilter,
      token,
    ],
  );

  useEffect(() => {
    void loadRestaurants();
  }, [loadRestaurants]);

  useEffect(() => {
    void loadReports();
  }, [loadReports]);

  const cuisineOptions = useMemo(() => {
    const values = new Set<string>();
    for (const restaurant of restaurants) {
      values.add(restaurant.cuisine_type);
    }
    for (const item of reports?.popular_cuisines ?? []) {
      values.add(item.label);
    }
    return Array.from(values).sort((left, right) => left.localeCompare(right));
  }, [reports?.popular_cuisines, restaurants]);

  const categoryOptions = useMemo(() => {
    const values = new Set<string>();
    for (const item of reports?.top_selling_items ?? []) {
      values.add(item.category);
    }
    for (const item of reports?.least_selling_items ?? []) {
      values.add(item.category);
    }
    for (const item of reports?.favorite_items ?? []) {
      values.add(item.category);
    }
    for (const item of reports?.popular_categories ?? []) {
      values.add(item.label);
    }
    return Array.from(values).sort((left, right) => left.localeCompare(right));
  }, [
    reports?.favorite_items,
    reports?.least_selling_items,
    reports?.popular_categories,
    reports?.top_selling_items,
  ]);

  const revenueTrendData = useMemo(
    () =>
      reports?.revenue_trend.map((point) => ({
        label: point.label,
        value: point.revenue,
        meta: `${point.orders} orders`,
      })) ?? [],
    [reports?.revenue_trend],
  );

  const orderStatusChartData = useMemo(
    () =>
      reports?.order_status_summary.map((item) => ({
        label: item.status.replaceAll("_", " "),
        value: item.count,
        meta: formatCurrency(item.revenue),
      })) ?? [],
    [reports?.order_status_summary],
  );

  const cuisineChartData = useMemo(
    () =>
      reports?.popular_cuisines.map((item) => ({
        label: item.label,
        value: item.orders,
        meta: formatCurrency(item.revenue),
      })) ?? [],
    [reports?.popular_cuisines],
  );

  const categoryChartData = useMemo(
    () =>
      reports?.popular_categories.map((item) => ({
        label: item.label,
        value: item.orders,
        meta: formatCurrency(item.revenue),
      })) ?? [],
    [reports?.popular_categories],
  );

  const rankedTopRestaurants = useMemo<RankedRestaurantPerformance[]>(
    () =>
      (reports?.top_restaurants ?? []).map((row, index) => ({
        ...row,
        rank: index + 1,
      })),
    [reports?.top_restaurants],
  );

  const rankedTopSellingItems = useMemo<RankedItemPerformance[]>(
    () =>
      (reports?.top_selling_items ?? []).map((row, index) => ({
        ...row,
        rank: index + 1,
      })),
    [reports?.top_selling_items],
  );

  const rankedLeastSellingItems = useMemo<RankedItemPerformance[]>(
    () =>
      (reports?.least_selling_items ?? []).map((row, index) => ({
        ...row,
        rank: index + 1,
      })),
    [reports?.least_selling_items],
  );

  const rankedFavoriteItems = useMemo<RankedItemPerformance[]>(
    () =>
      (reports?.favorite_items ?? []).map((row, index) => ({
        ...row,
        rank: index + 1,
      })),
    [reports?.favorite_items],
  );

  const rankedComboPerformance = useMemo<RankedComboPerformance[]>(
    () =>
      (reports?.generated_combo_performance ?? []).map((row, index) => ({
        ...row,
        rank: index + 1,
      })),
    [reports?.generated_combo_performance],
  );

  const averageOrdersPerRestaurant = useMemo(() => {
    const totalOrders = reports?.summary.total_orders ?? 0;
    const totalRestaurants = reports?.summary.total_restaurants ?? 0;
    if (!totalRestaurants) {
      return "0";
    }
    return (totalOrders / totalRestaurants).toFixed(1);
  }, [reports?.summary.total_orders, reports?.summary.total_restaurants]);

  const activeFiltersCount = useMemo(() => {
    let count = 0;
    if (dateFrom !== defaultRange.from || dateTo !== defaultRange.to) {
      count += 1;
    }
    if (restaurantFilter) {
      count += 1;
    }
    if (cuisineFilter) {
      count += 1;
    }
    if (categoryFilter) {
      count += 1;
    }
    if (statusFilter) {
      count += 1;
    }
    return count;
  }, [
    categoryFilter,
    cuisineFilter,
    dateFrom,
    dateTo,
    defaultRange.from,
    defaultRange.to,
    restaurantFilter,
    statusFilter,
  ]);

  const clearFilters = useCallback(() => {
    setPreset("30d");
    setDateFrom(defaultRange.from);
    setDateTo(defaultRange.to);
    setCuisineFilter("");
    setCategoryFilter("");
    setStatusFilter("");
    setRestaurantFilter(isAdmin ? "" : restaurantId ?? "");
  }, [defaultRange.from, defaultRange.to, isAdmin, restaurantId]);

  const exportSnapshot = useCallback(() => {
    if (!reports) {
      onToast("Nothing to export", "Load a report snapshot before exporting.", "info");
      return;
    }

    const payload = {
      exported_at: new Date().toISOString(),
      filters: reports.filters,
      snapshot: reports,
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = window.URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `reports-${dateFrom || "all"}-${dateTo || "all"}.json`;
    anchor.click();
    window.URL.revokeObjectURL(url);
  }, [dateFrom, dateTo, onToast, reports]);

  const exportCsv = useCallback(() => {
    if (!reports) {
      onToast("Nothing to export", "Load a report snapshot before exporting.", "info");
      return;
    }
    const esc = (value: unknown) => {
      const text = String(value ?? "");
      return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
    };
    const lines: string[] = [];
    lines.push("Summary");
    lines.push("Metric,Value");
    const s = reports.summary;
    lines.push(`Total orders,${esc(s.total_orders)}`);
    lines.push(`Total revenue,${esc(s.total_revenue)}`);
    lines.push(`Average order value,${esc(s.average_order_value)}`);
    lines.push(`Repeat customers,${esc(s.repeat_customer_count)}`);
    lines.push(`Unique customers,${esc(s.total_customers)}`);
    lines.push(`AI chat sessions,${esc(s.ai_chat_sessions)}`);
    lines.push("");
    lines.push("Top selling items");
    lines.push("Rank,Item,Restaurant,Category,Units sold,Revenue,Likes");
    rankedTopSellingItems.forEach((row) => {
      lines.push(
        [row.rank, esc(row.name), esc(row.restaurant_name), esc(row.category), row.quantity, row.revenue, row.favorite_count].join(","),
      );
    });
    if (isAdmin && rankedTopRestaurants.length > 0) {
      lines.push("");
      lines.push("Top restaurants");
      lines.push("Rank,Restaurant,Cuisine,Orders,Revenue,Average order value");
      rankedTopRestaurants.forEach((row) => {
        lines.push(
          [row.rank, esc(row.restaurant_name), esc(row.cuisine_type), row.orders, row.revenue, row.average_order_value].join(","),
        );
      });
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = window.URL.createObjectURL(blob);
    const anchorEl = document.createElement("a");
    anchorEl.href = url;
    anchorEl.download = `reports-${dateFrom || "all"}-${dateTo || "all"}.csv`;
    anchorEl.click();
    window.URL.revokeObjectURL(url);
  }, [dateFrom, dateTo, isAdmin, onToast, rankedTopRestaurants, rankedTopSellingItems, reports]);

  const hasNoOrderData = !loading && reports?.summary.total_orders === 0;

  const topRestaurantColumns: Array<TableColumn<RankedRestaurantPerformance>> = [
    {
      id: "restaurant",
      header: "Restaurant",
      render: (row) => (
        <div className="rpt-cell">
          <span className="rpt-cell__rank">{row.rank}</span>
          <div className="rpt-cell__copy">
            <strong>{row.restaurant_name}</strong>
            <span>{row.cuisine_type}</span>
          </div>
        </div>
      ),
    },
    {
      id: "orders",
      header: "Orders",
      render: (row) => String(row.orders),
      mobileLabel: "Orders",
      align: "right",
    },
    {
      id: "revenue",
      header: "Revenue",
      render: (row) => formatCurrency(row.revenue),
      mobileLabel: "Revenue",
      align: "right",
    },
    {
      id: "aov",
      header: "Avg order",
      render: (row) => formatCurrency(row.average_order_value),
      mobileLabel: "Avg order",
      align: "right",
    },
  ];

  const itemColumns: Array<TableColumn<RankedItemPerformance>> = [
    {
      id: "item",
      header: "Item",
      render: (row) => (
        <div className="rpt-cell">
          <span className="rpt-cell__rank">{row.rank}</span>
          <div className="rpt-cell__copy">
            <strong>{row.name}</strong>
            <span>{row.restaurant_name}</span>
          </div>
        </div>
      ),
    },
    {
      id: "category",
      header: "Category",
      render: (row) => <span className="rpt-chip">{row.category}</span>,
      mobileLabel: "Category",
    },
    {
      id: "units",
      header: "Units sold",
      render: (row) => String(row.quantity),
      mobileLabel: "Units",
      align: "right",
    },
    {
      id: "revenue",
      header: "Revenue",
      render: (row) => formatCurrency(row.revenue),
      mobileLabel: "Revenue",
      align: "right",
    },
    {
      id: "likes",
      header: "Likes",
      render: (row) => String(row.favorite_count),
      mobileLabel: "Likes",
      align: "right",
    },
  ];

  const comboColumns: Array<TableColumn<RankedComboPerformance>> = [
    {
      id: "combo",
      header: "Combo",
      render: (row) => (
        <div className="rpt-cell">
          <span className="rpt-cell__rank">{row.rank}</span>
          <div className="rpt-cell__copy">
            <strong>{row.combo_name}</strong>
            <span>{row.restaurant_name}</span>
          </div>
        </div>
      ),
    },
    {
      id: "orders",
      header: "Orders",
      render: (row) => String(row.order_count),
      mobileLabel: "Orders",
      align: "right",
    },
    {
      id: "users",
      header: "Unique users",
      render: (row) => String(row.unique_user_count),
      mobileLabel: "Users",
      align: "right",
    },
    {
      id: "confidence",
      header: "Confidence",
      render: (row) => (
        <div className="rpt-meter">
          <strong>{`${row.confidence_score.toFixed(2)}%`}</strong>
          <div className="rpt-meter__track">
            <div
              className="rpt-meter__bar"
              style={{ width: `${Math.max(Math.min(row.confidence_score, 100), 4)}%` }}
            />
          </div>
        </div>
      ),
      mobileLabel: "Confidence",
      align: "right",
    },
    {
      id: "status",
      header: "Status",
      render: (row) => <StatusPill status={row.is_active ? "ACTIVE" : "INACTIVE"} />,
      mobileLabel: "Status",
    },
  ];

  const chatMetrics = reports?.chat_usage;
  const bestPerformingRestaurant = rankedTopRestaurants[0] ?? null;
  const topRevenueGenerator = rankedTopSellingItems[0] ?? null;
  const peakWindow = reports?.peak_order_times?.[0] ?? null;
  const reportingScopeLabel =
    reports?.restaurant_scope?.name ?? (isAdmin ? "All restaurants" : "Assigned restaurant");
  const summary = reports?.summary;

  const revenueChart: ChartDatum[] = revenueTrendData;

  return (
    <div className="rpt">
      <header className="rpt-header">
        <div className="rpt-header__copy">
          <h1>{isAdmin ? "Platform reports" : "Restaurant reports"}</h1>
          <p>
            {isAdmin
              ? "Revenue, orders, engagement and AI activity across every restaurant."
              : "Revenue, order flow, menu momentum and AI activity for your restaurant."}
          </p>
        </div>
        <div className="rpt-header__actions">
          <span className="rpt-header__updated" title="Last refreshed">
            <Clock3 size={14} strokeWidth={2.1} />
            {formatTimestamp(lastUpdatedAt)}
          </span>
          <button className="rpt-btn" onClick={exportCsv} type="button">
            <Download size={15} strokeWidth={2.1} />
            CSV
          </button>
          <button className="rpt-btn" onClick={exportSnapshot} type="button">
            <Download size={15} strokeWidth={2.1} />
            JSON
          </button>
          <button
            className="rpt-btn rpt-btn--primary"
            disabled={loading}
            onClick={() => {
              void loadRestaurants(true);
              void loadReports(true);
            }}
            type="button"
          >
            <RefreshCw className={loading ? "reports-spin" : undefined} size={15} strokeWidth={2.1} />
            Refresh
          </button>
        </div>
      </header>

      <section className="rpt-card rpt-filters">
        <div className="rpt-filters__row">
          <div className="rpt-seg" role="group" aria-label="Date presets">
            {(["today", "7d", "30d", "custom"] as const).map((entry) => (
              <button
                aria-pressed={preset === entry}
                className={preset === entry ? "rpt-seg__btn rpt-seg__btn--active" : "rpt-seg__btn"}
                key={entry}
                onClick={() => {
                  setPreset(entry);
                  if (entry !== "custom") {
                    const nextRange = getPresetRange(entry);
                    setDateFrom(nextRange.from);
                    setDateTo(nextRange.to);
                  }
                }}
                type="button"
              >
                {PRESET_LABELS[entry]}
              </button>
            ))}
          </div>
          <div className="rpt-filters__meta">
            {activeFiltersCount > 0 ? (
              <span className="rpt-filters__count">
                <SlidersHorizontal size={13} strokeWidth={2.2} />
                {activeFiltersCount} active
              </span>
            ) : null}
            <button className="rpt-btn rpt-btn--ghost" onClick={clearFilters} type="button">
              Clear
            </button>
          </div>
        </div>

        <div className="rpt-filters__grid">
          <label className="rpt-field">
            <span>From</span>
            <input
              onChange={(event) => {
                setPreset("custom");
                setDateFrom(event.target.value);
              }}
              type="date"
              value={dateFrom}
            />
          </label>
          <label className="rpt-field">
            <span>To</span>
            <input
              onChange={(event) => {
                setPreset("custom");
                setDateTo(event.target.value);
              }}
              type="date"
              value={dateTo}
            />
          </label>
          {isAdmin ? (
            <label className="rpt-field">
              <span>Restaurant</span>
              <select onChange={(event) => setRestaurantFilter(event.target.value)} value={restaurantFilter}>
                <option value="">All restaurants</option>
                {restaurants.map((restaurant) => (
                  <option key={restaurant.id} value={restaurant.id}>
                    {restaurant.name}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label className="rpt-field">
            <span>Cuisine</span>
            <select onChange={(event) => setCuisineFilter(event.target.value)} value={cuisineFilter}>
              <option value="">All cuisines</option>
              {cuisineOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label className="rpt-field">
            <span>Category</span>
            <select onChange={(event) => setCategoryFilter(event.target.value)} value={categoryFilter}>
              <option value="">All categories</option>
              {categoryOptions.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
          <label className="rpt-field">
            <span>Order status</span>
            <select
              onChange={(event) => setStatusFilter(event.target.value as OrderStatus | "")}
              value={statusFilter}
            >
              <option value="">All statuses</option>
              {ORDER_FILTER_STATUSES.map((statusValue) => (
                <option key={statusValue} value={statusValue}>
                  {humanizeEnum(statusValue)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      <section className="rpt-stats" aria-label="Key metrics">
        <StatTile
          hint={`${summary?.peak_order_label ?? "No peak window"} is the busiest window`}
          icon={ShoppingBag}
          label="Total orders"
          loading={loading}
          tone="accent"
          value={formatCompactNumber(summary?.total_orders ?? 0)}
        />
        <StatTile
          hint={`${formatCurrency(summary?.average_order_value ?? 0)} average order value`}
          icon={IndianRupee}
          label="Revenue"
          loading={loading}
          tone="accent"
          value={formatCompactCurrency(summary?.total_revenue ?? 0)}
        />
        <StatTile
          hint={
            isAdmin
              ? "Average orders per restaurant in scope"
              : `${summary?.total_orders ?? 0} completed orders in range`
          }
          icon={ArrowUpRight}
          label={isAdmin ? "Avg orders / restaurant" : "Average order value"}
          loading={loading}
          value={
            isAdmin
              ? averageOrdersPerRestaurant
              : formatCurrency(summary?.average_order_value ?? 0)
          }
        />
        {isAdmin ? (
          <StatTile
            hint="Restaurants in the current reporting scope"
            icon={Store}
            label="Active restaurants"
            loading={loading}
            value={formatCompactNumber(summary?.total_restaurants ?? 0)}
          />
        ) : null}
        <StatTile
          hint="Returning customers in this date range"
          icon={Repeat2}
          label="Repeat customers"
          loading={loading}
          value={formatCompactNumber(summary?.repeat_customer_count ?? 0)}
        />
        <StatTile
          hint="Unique customers in this snapshot"
          icon={Users}
          label="Users reached"
          loading={loading}
          value={formatCompactNumber(summary?.total_customers ?? 0)}
        />
        <StatTile
          hint="Assistant sessions under the same filters"
          icon={Bot}
          label="AI chat sessions"
          loading={loading}
          value={formatCompactNumber(summary?.ai_chat_sessions ?? 0)}
        />
        <StatTile
          hint="High-demand order window in range"
          icon={Clock3}
          label="Peak order time"
          loading={loading}
          value={summary?.peak_order_label ?? "No data"}
        />
      </section>

      <div className="rpt-tabs" role="tablist" aria-label="Report sections">
        {(
          [
            ["analytics", "Analytics"],
            ["items", "Items performance"],
            ["chat", "Chat activity"],
          ] as const
        ).map(([tab, label]) => (
          <button
            aria-selected={activeTab === tab}
            className={activeTab === tab ? "rpt-tabs__btn rpt-tabs__btn--active" : "rpt-tabs__btn"}
            key={tab}
            onClick={() => setActiveTab(tab)}
            role="tab"
            type="button"
          >
            {label}
          </button>
        ))}
      </div>

      {error && !reports ? (
        <section className="rpt-card">
          <EmptyPanel description={error} title="We couldn’t load reports right now" />
        </section>
      ) : null}

      {!error ? (
        <>
          {activeTab === "analytics" ? (
            <>
              <div className="rpt-chart-grid">
                <ChartPanel
                  className="rpt-chart-grid__wide"
                  emptyDescription="Revenue points will appear after matching orders are captured."
                  emptyTitle="No revenue trend available"
                  hasData={revenueChart.length > 0}
                  loading={loading}
                  subtitle={`${pluralize(summary?.total_orders ?? 0, 'order')} in the selected range`}
                  title="Revenue trend"
                >
                  <AreaTrendChart
                    className="rpt-area"
                    data={revenueChart}
                    height={200}
                    seriesLabel="Revenue"
                    valueFormatter={formatCurrency}
                    width={560}
                    yTickFormatter={formatCompactCurrency}
                  />
                </ChartPanel>
                <ChartPanel
                  emptyDescription="Chart bars will appear once matching data exists."
                  emptyTitle="No status data yet"
                  hasData={orderStatusChartData.length > 0}
                  loading={loading}
                  subtitle="Orders grouped by lifecycle status"
                  title="Orders by status"
                >
                  <VerticalBarsChart className="rpt-vbars" data={orderStatusChartData} />
                </ChartPanel>
                <ChartPanel
                  emptyDescription="Top cuisines appear once the range has enough orders."
                  emptyTitle="No cuisine data yet"
                  hasData={cuisineChartData.length > 0}
                  loading={loading}
                  subtitle="Ranked by matching order volume"
                  title="Popular cuisines"
                >
                  <HorizontalBarsChart className="rpt-hbars" data={cuisineChartData} />
                </ChartPanel>
                <ChartPanel
                  emptyDescription="Category mix appears once matching orders exist."
                  emptyTitle="No category data yet"
                  hasData={categoryChartData.length > 0}
                  loading={loading}
                  subtitle="Most ordered menu categories"
                  title="Popular categories"
                >
                  <VerticalBarsChart className="rpt-vbars" data={categoryChartData} />
                </ChartPanel>
              </div>

              <section className="rpt-highlights" aria-label="Highlights">
                <HighlightCard
                  icon={SlidersHorizontal}
                  label="Current scope"
                  meta={`${formatDateRange(dateFrom, dateTo)} · ${activeFiltersCount} filters`}
                  title={reportingScopeLabel}
                />
                <HighlightCard
                  icon={Trophy}
                  label={isAdmin ? "Restaurant leader" : "Your restaurant"}
                  meta={
                    isAdmin
                      ? bestPerformingRestaurant
                        ? `${pluralize(bestPerformingRestaurant.orders, 'order')} · ${formatCurrency(bestPerformingRestaurant.revenue)}`
                        : "No performance data yet"
                      : `${pluralize(summary?.total_orders ?? 0, 'order')} · ${formatCurrency(summary?.total_revenue ?? 0)}`
                  }
                  title={
                    isAdmin
                      ? bestPerformingRestaurant?.restaurant_name ?? "—"
                      : reports?.restaurant_scope?.name ?? "Assigned restaurant"
                  }
                />
                <HighlightCard
                  icon={Utensils}
                  label="Best selling item"
                  meta={
                    topRevenueGenerator
                      ? `${pluralize(topRevenueGenerator.quantity, 'unit')} · ${formatCurrency(topRevenueGenerator.revenue)}`
                      : "Appears after matching orders arrive"
                  }
                  title={topRevenueGenerator?.name ?? "—"}
                />
                <HighlightCard
                  icon={Bot}
                  label="Chat health"
                  meta={
                    chatMetrics
                      ? `${pluralize(chatMetrics.assistant_messages, 'reply', 'replies')} · ${pluralize(chatMetrics.total_messages, 'message')}`
                      : "No chat activity in scope"
                  }
                  title={pluralize(chatMetrics?.total_sessions ?? 0, 'session')}
                  aside={peakWindow ? <StatusPill status={pluralize(peakWindow.orders, 'order')} /> : null}
                />
              </section>

              {isAdmin ? (
                <section className="rpt-panel">
                  <header className="rpt-panel__header">
                    <h3>Top restaurants</h3>
                    <p>Highest performing restaurants under the current filters.</p>
                  </header>
                  <ResponsiveTable
                    columns={topRestaurantColumns}
                    emptyDescription="No restaurant-level performance data for the selected filters."
                    emptyTitle="No restaurant performance yet"
                    keyExtractor={(row) => row.restaurant_id}
                    loading={loading}
                    mobileStatus={(row) => <strong>{formatCurrency(row.revenue)}</strong>}
                    mobileSubtitle={(row) => row.cuisine_type}
                    mobileTitle={(row) => row.restaurant_name}
                    rows={rankedTopRestaurants}
                  />
                </section>
              ) : null}
            </>
          ) : null}

          {activeTab === "items" ? (
            <div className="rpt-stack">
              <section className="rpt-panel">
                <header className="rpt-panel__header">
                  <h3>Top selling items</h3>
                  <p>Revenue, units sold and velocity for the best movers.</p>
                </header>
                <ResponsiveTable
                  columns={itemColumns}
                  emptyDescription="No item sales are available for the selected filters yet."
                  emptyTitle="No item performance yet"
                  keyExtractor={(row) => row.menu_item_id}
                  loading={loading}
                  mobileStatus={(row) => <strong>{formatCurrency(row.revenue)}</strong>}
                  mobileSubtitle={(row) => row.restaurant_name}
                  mobileTitle={(row) => row.name}
                  rows={rankedTopSellingItems}
                />
              </section>

              {!isAdmin ? (
                <section className="rpt-panel">
                  <header className="rpt-panel__header">
                    <h3>Least selling items</h3>
                    <p>Useful for pricing, bundling or pruning underperformers.</p>
                  </header>
                  <ResponsiveTable
                    columns={itemColumns}
                    emptyDescription="No low-volume items are available yet."
                    emptyTitle="No least-selling items yet"
                    keyExtractor={(row) => row.menu_item_id}
                    loading={loading}
                    mobileStatus={(row) => <strong>{formatCurrency(row.revenue)}</strong>}
                    mobileSubtitle={(row) => row.restaurant_name}
                    mobileTitle={(row) => row.name}
                    rows={rankedLeastSellingItems}
                  />
                </section>
              ) : null}

              <section className="rpt-panel">
                <header className="rpt-panel__header">
                  <h3>Generated combos</h3>
                  <p>Order strength, reach, confidence and live state together.</p>
                </header>
                <ResponsiveTable
                  columns={comboColumns}
                  emptyDescription="No generated combo performance for the current scope."
                  emptyTitle="No combo analytics yet"
                  keyExtractor={(row) => row.combo_id}
                  loading={loading}
                  mobileStatus={(row) => <StatusPill status={row.is_active ? "ACTIVE" : "INACTIVE"} />}
                  mobileSubtitle={(row) => row.restaurant_name}
                  mobileTitle={(row) => row.combo_name}
                  rows={rankedComboPerformance}
                />
              </section>

              <section className="rpt-panel">
                <header className="rpt-panel__header">
                  <h3>Most liked items</h3>
                  <p>Dishes customers save most often, beyond completed purchases.</p>
                </header>
                <ResponsiveTable
                  columns={itemColumns}
                  emptyDescription="No favorite activity is available yet for the selected filters."
                  emptyTitle="No favorite signals yet"
                  keyExtractor={(row) => row.menu_item_id}
                  loading={loading}
                  mobileStatus={(row) => <strong>{row.favorite_count} likes</strong>}
                  mobileSubtitle={(row) => row.restaurant_name}
                  mobileTitle={(row) => row.name}
                  rows={rankedFavoriteItems}
                />
              </section>
            </div>
          ) : null}

          {activeTab === "chat" ? (
            <div className="rpt-stack">
              <section className="rpt-stats" aria-label="Chat metrics">
                <StatTile
                  hint="AI chat sessions inside the reporting window"
                  icon={Bot}
                  label="Total sessions"
                  loading={loading}
                  tone="accent"
                  value={formatCompactNumber(chatMetrics?.total_sessions ?? 0)}
                />
                <StatTile
                  hint="Messages exchanged across tracked sessions"
                  icon={Users}
                  label="Messages"
                  loading={loading}
                  value={formatCompactNumber(chatMetrics?.total_messages ?? 0)}
                />
                <StatTile
                  hint="User-originated prompts in scope"
                  icon={ArrowUpRight}
                  label="Queries"
                  loading={loading}
                  value={formatCompactNumber(chatMetrics?.user_messages ?? 0)}
                />
                <StatTile
                  hint="Assistant responses in the same session set"
                  icon={Bot}
                  label="Assistant replies"
                  loading={loading}
                  value={formatCompactNumber(chatMetrics?.assistant_messages ?? 0)}
                />
              </section>

              <div className="rpt-chart-grid rpt-chart-grid--two">
                <section className="rpt-panel">
                  <header className="rpt-panel__header">
                    <h3>Peak order windows</h3>
                    <p>Align staffing and prompt timing with demand.</p>
                  </header>
                  <div className="rpt-peaks">
                    {(reports?.peak_order_times ?? []).map((entry) => (
                      <div className="rpt-peaks__row" key={`${entry.hour}-${entry.label}`}>
                        <span className="rpt-peaks__icon">
                          <Clock3 size={14} strokeWidth={2.1} />
                        </span>
                        <div className="rpt-peaks__copy">
                          <strong>{entry.label}</strong>
                          <span>Window #{entry.hour}</span>
                        </div>
                        <StatusPill status={pluralize(entry.orders, 'order')} />
                      </div>
                    ))}
                    {!loading && (reports?.peak_order_times.length ?? 0) === 0 ? (
                      <EmptyPanel
                        description="Order timing trends will appear after the first matching orders arrive."
                        title="No peak windows yet"
                      />
                    ) : null}
                  </div>
                </section>

                <section className="rpt-panel">
                  <header className="rpt-panel__header">
                    <h3>Scope summary</h3>
                    <p>The backend filters driving this dashboard.</p>
                  </header>
                  <dl className="rpt-scope">
                    <div>
                      <dt>Role scope</dt>
                      <dd>{isAdmin ? "ADMIN" : "OWNER"}</dd>
                    </div>
                    <div>
                      <dt>Restaurant</dt>
                      <dd>{reportingScopeLabel}</dd>
                    </div>
                    <div>
                      <dt>Date range</dt>
                      <dd>{formatDateRange(dateFrom, dateTo)}</dd>
                    </div>
                    <div>
                      <dt>Category</dt>
                      <dd>{categoryFilter || "All categories"}</dd>
                    </div>
                    <div>
                      <dt>Cuisine</dt>
                      <dd>{cuisineFilter || "All cuisines"}</dd>
                    </div>
                    <div>
                      <dt>Status</dt>
                      <dd>{statusFilter || "All statuses"}</dd>
                    </div>
                  </dl>
                </section>
              </div>

              {!chatMetrics && !loading ? (
                <section className="rpt-card">
                  <EmptyPanel
                    description="AI usage analytics are not available for the current filter combination."
                    title="AI usage unavailable"
                  />
                </section>
              ) : null}
            </div>
          ) : null}

          {hasNoOrderData ? (
            <section className="rpt-card">
              <EmptyPanel
                description="Try broadening the date range or removing one of the active filters."
                title="No order data for the current filters"
              />
            </section>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

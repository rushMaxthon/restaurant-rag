import { CircleAlert, Clock, Download, Landmark, PauseCircle, RotateCcw, Send, Store } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DashboardPeriodPicker } from "../components/DashboardPeriodPicker";
import { EmptyPanel } from "../components/EmptyPanel";
import { PageIntro } from "../components/PageIntro";
import { PayoutAccountPanel } from "../components/PayoutAccountPanel";
import { ResponsiveTable, type TableColumn } from "../components/ResponsiveTable";
import { StatTiles, type StatTileItem } from "../components/StatTiles";
import { resolveStatusPillTone } from "../components/statusPillUtils";
import { useMarketingScope } from "../hooks/useMarketingScope";
import { useMoney } from "../hooks/useMoney";
import { ApiError, api } from "../services/api";
import { DEFAULT_PERIOD, parsePeriod, resolvePeriod, type DashboardPeriod } from "../services/dashboardPeriod";
import { pluralize } from "../services/format";
import { PAYOUT_STATUS_META, payoutsCsv, periodQuery } from "../services/payouts";
import type { PayoutList, PayoutRow, ToastMessage } from "../types/app";

interface PayoutsPageProps {
  token: string;
  onToast: (title: string, description: string, tone?: ToastMessage["tone"]) => void;
}

const PERIOD_KEY = "restaurant-rag-payouts-period";

function readPeriod(): DashboardPeriod {
  try {
    return parsePeriod(window.localStorage.getItem(PERIOD_KEY)) ?? DEFAULT_PERIOD;
  } catch {
    return DEFAULT_PERIOD;
  }
}

/** Payouts reach back to when Route went live; nothing before 2026 can be on it. */
const YEARS = Array.from({ length: new Date().getFullYear() - 2026 + 1 }, (_, index) => new Date().getFullYear() - index);

/**
 * What each restaurant is owed from the payments the platform collected, and
 * where that money is: held until the food is delivered, on its way, or in
 * the restaurant's bank.
 *
 * One screen for both roles. An admin sees every restaurant and both halves
 * of each order; an owner sees their own share only - the platform's half,
 * beside their share and the total, would give the commission away. The
 * server enforces both; this page only follows it.
 */
export function PayoutsPage({ token, onToast }: PayoutsPageProps) {
  const money = useMoney();
  const scope = useMarketingScope();
  const isAdmin = scope.isAdmin;
  const restaurantId = isAdmin ? scope.selectedRestaurantId : "";

  const [period, setPeriod] = useState<DashboardPeriod>(readPeriod);
  const [list, setList] = useState<PayoutList | null>(null);
  // What the list on screen was asked for, so a slower answer for a filter
  // somebody has moved on from is not mistaken for the current one.
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const query = useMemo(
    () => ({ ...periodQuery(resolvePeriod(period)), restaurant_id: restaurantId || undefined }),
    [period, restaurantId],
  );
  const requestKey = `${JSON.stringify(query)}#${attempt}`;

  useEffect(() => {
    let current = true;
    api
      .getPayouts(token, query)
      .then((next) => {
        if (!current) return;
        setList(next);
        setFailed(null);
        setLoadedFor(requestKey);
      })
      .catch((error: unknown) => {
        if (!current) return;
        const message = error instanceof ApiError ? error.message : "Please try again.";
        setFailed(message);
        setLoadedFor(requestKey);
        onToast("Could not load payouts", message, "error");
      });
    return () => {
      current = false;
    };
  }, [onToast, query, requestKey, token]);

  const loading = loadedFor !== requestKey;
  const reload = useCallback(() => setAttempt((count) => count + 1), []);

  const choosePeriod = (next: DashboardPeriod) => {
    setPeriod(next);
    try {
      window.localStorage.setItem(PERIOD_KEY, JSON.stringify(next));
    } catch {
      // Remembering the choice is a convenience; the page works without it.
    }
  };

  const rows = list?.rows ?? [];
  const summary = list?.summary;
  const tile = (bucket: keyof PayoutList["summary"]) => ({
    value: summary ? money.format(summary[bucket].amount, restaurantId || null) : "-",
    hint: summary ? pluralize(summary[bucket].count, "order") : "",
  });

  const tiles: Array<StatTileItem<string>> = [
    { key: "held", label: isAdmin ? "Held" : "Held until delivered", icon: PauseCircle, ...tile("held"), isStatic: true },
    { key: "released", label: "On its way", icon: Send, ...tile("released"), isStatic: true },
    { key: "settled", label: "In the bank", icon: Landmark, ...tile("settled"), isStatic: true },
    { key: "waiting", label: "Waiting", icon: Clock, ...tile("waiting"), isStatic: true },
    { key: "problems", label: isAdmin ? "Problems" : "Being looked into", icon: CircleAlert, ...tile("problems"), isStatic: true },
  ];

  const statusCell = (row: PayoutRow) => (
    <span className={`status-pill status-pill--${resolveStatusPillTone(row.status)}`}>
      {isAdmin ? PAYOUT_STATUS_META[row.status].label : PAYOUT_STATUS_META[row.status].ownerLabel}
    </span>
  );

  const columns: Array<TableColumn<PayoutRow>> = [
    {
      id: "placed",
      header: "Order placed",
      render: (row) => (row.order_placed_at ? new Date(row.order_placed_at).toLocaleString() : "-"),
      mobileLabel: "Placed",
    },
    ...(isAdmin
      ? [{ id: "restaurant", header: "Restaurant", render: (row: PayoutRow) => row.restaurant_name, mobileLabel: "Restaurant" }]
      : []),
    {
      id: "share",
      header: isAdmin ? "Restaurant's share" : "Your share",
      render: (row) => <strong>{money.format(row.restaurant_share, row.restaurant_id)}</strong>,
      mobileLabel: "Share",
      align: "right",
    },
    ...(isAdmin
      ? [
          {
            id: "keeps",
            header: "Platform keeps",
            render: (row: PayoutRow) => (row.platform_keeps === null ? "-" : money.format(row.platform_keeps, row.restaurant_id)),
            mobileLabel: "Platform keeps",
            align: "right" as const,
          },
        ]
      : []),
    { id: "status", header: "Where it is", render: statusCell, mobileLabel: "Status" },
    {
      id: "note",
      header: "Note",
      render: (row) => (row.last_error ? <small>{row.last_error}</small> : null),
      hideOnMobile: true,
    },
  ];

  const retry = async (row: PayoutRow) => {
    try {
      const result = await api.retryPayout(token, row.id);
      onToast("Retry queued", result.last_error ?? `Now ${PAYOUT_STATUS_META[result.status as PayoutRow["status"]]?.label ?? result.status}.`, "success");
      reload();
    } catch (error) {
      onToast("Could not retry", error instanceof ApiError ? error.message : "Please try again.", "error");
    }
  };

  const exportCsv = () => {
    const blob = new Blob([payoutsCsv(rows, isAdmin)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "payouts.csv";
    link.click();
    URL.revokeObjectURL(url);
  };

  const restaurantPicker = isAdmin ? (
    <label className="period-picker__field">
      <Store aria-hidden="true" size={15} />
      <select
        aria-label="Restaurant"
        onChange={(event) => scope.setSelectedRestaurantId(event.target.value)}
        value={scope.selectedRestaurantId}
      >
        <option value="">All restaurants</option>
        {scope.restaurants.map((restaurant) => (
          <option key={restaurant.id} value={restaurant.id}>
            {restaurant.name}
          </option>
        ))}
      </select>
    </label>
  ) : null;

  return (
    <div className="page-stack">
      <PageIntro
        actions={
          <div className="period-picker">
            {restaurantPicker}
            <DashboardPeriodPicker onChange={choosePeriod} period={period} years={YEARS} />
            <button
              className="secondary-button"
              disabled={rows.length === 0}
              onClick={exportCsv}
              title={rows.length === 0 ? "Nothing to export for this period" : "Download these rows as a CSV file"}
              type="button"
            >
              <Download size={15} /> Export CSV
            </button>
          </div>
        }
        description={
          isAdmin
            ? "Each restaurant's share of the payments the platform collected, and where that money is."
            : "Your share of each order paid online, and where that money is."
        }
        eyebrow={isAdmin ? "Platform" : "Orders"}
        title="Payouts"
      />

      {list && !list.payouts_enabled ? (
        <p className="hint-text" role="status">
          Payouts are switched off. These are the amounts that would be paid; nothing has been sent to Razorpay.
        </p>
      ) : null}

      <StatTiles ariaLabel="Payouts in this period" loading={loading} tiles={tiles} />

      <section className="admin-surface">
        {failed && !loading ? (
          <EmptyPanel
            action={
              <button className="primary-button" onClick={reload} type="button">
                Try again
              </button>
            }
            description={failed}
            title="Payouts didn't load"
          />
        ) : (
          <ResponsiveTable
            actions={
              isAdmin
                ? [
                    {
                      id: "retry",
                      label: "Retry",
                      icon: RotateCcw,
                      onClick: (row) => void retry(row),
                      hidden: (row) => row.status !== "FAILED" && row.status !== "BLOCKED",
                    },
                  ]
                : undefined
            }
            columns={columns}
            emptyDescription="An order paid online appears here as soon as the payment is confirmed."
            emptyTitle="No payouts in this period"
            keyExtractor={(row) => row.id}
            loading={loading}
            mobileStatus={statusCell}
            mobileSubtitle={(row) => (row.order_placed_at ? new Date(row.order_placed_at).toLocaleString() : "")}
            mobileTitle={(row) => money.format(row.restaurant_share, row.restaurant_id)}
            rows={loading ? [] : rows}
          />
        )}
      </section>

      {isAdmin && !restaurantId ? (
        <p className="hint-text">Pick a restaurant above to see or set up its bank account for payouts.</p>
      ) : (
        <PayoutAccountPanel isAdmin={isAdmin} onToast={onToast} restaurantId={restaurantId} token={token} />
      )}
    </div>
  );
}

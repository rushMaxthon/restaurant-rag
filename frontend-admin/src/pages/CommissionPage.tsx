import { BadgeIndianRupee, ReceiptText, ShoppingBag, Store } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { EmptyPanel } from "../components/EmptyPanel";
import { PageIntro } from "../components/PageIntro";
import { ResponsiveTable, type TableColumn } from "../components/ResponsiveTable";
import { StatTiles, type StatTileItem } from "../components/StatTiles";
import { useMoney } from "../hooks/useMoney";
import { ApiError, api } from "../services/api";
import {
  COMMISSION_PERIODS,
  commissionTotals,
  coverageNote,
  shareOfCommission,
} from "../services/commissionReport";
import { pluralize } from "../services/format";
import type { CommissionReport, CommissionRow, ToastMessage } from "../types/app";

interface CommissionPageProps {
  token: string;
  onNavigate: (path: string) => void;
  onToast: (title: string, description: string, tone?: ToastMessage["tone"]) => void;
}

/**
 * What the platform earned from each restaurant.
 *
 * The commission is inside every menu price and, since migration 0079, on
 * every order. This is the first screen that adds it up: until it existed the
 * rate could be set per branch and nothing said what it had brought in.
 *
 * Admin only, like the rate itself. The route is not offered to an owner and
 * the endpoint refuses one.
 */
export function CommissionPage({ token, onNavigate, onToast }: CommissionPageProps) {
  const money = useMoney();
  const [days, setDays] = useState<number>(30);
  const [report, setReport] = useState<CommissionReport | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  // Bumped by "Try again", so the same period can be asked for twice.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // State is only set from the answer, never on the way in: `loading` below
    // is worked out from what has arrived, so there is nothing to set first.
    let current = true;
    api
      .getCommissionReport(token, days)
      .then((next) => {
        if (!current) return;
        setReport(next);
        setFailed(null);
      })
      .catch((error: unknown) => {
        if (!current) return;
        const message = error instanceof ApiError ? error.message : "Please try again.";
        setFailed(message);
        onToast("Could not load the commission report", message, "error");
      });
    // A slower answer for a period somebody has already clicked away from
    // must not land on top of the one they are looking at.
    return () => {
      current = false;
    };
  }, [attempt, days, onToast, token]);

  // The report on screen is for another period, and nothing has failed:
  // the one that was asked for is still on its way.
  const loading = failed === null && report?.days !== days;
  const retry = () => {
    setFailed(null);
    setAttempt((count) => count + 1);
  };

  const totals = useMemo(() => commissionTotals(report), [report]);
  const note = coverageNote(report);
  // One currency for the totals: the first restaurant's. Right while every
  // restaurant on the platform charges in the same one, which the money hook
  // already assumes for any figure that is not about a single restaurant.
  const anyRestaurant = report?.restaurants[0]?.restaurant_id;

  const tiles: Array<StatTileItem<string>> = [
    {
      key: "commission",
      label: "Commission earned",
      icon: BadgeIndianRupee,
      value: money.format(totals.commission, anyRestaurant),
      hint:
        totals.effectiveRate === null
          ? "Nothing sold in this period"
          : `${totals.effectiveRate.toFixed(1)}% of what customers paid for food`,
      isStatic: true,
    },
    {
      key: "sales",
      label: "Food sales",
      icon: ReceiptText,
      value: money.format(totals.sales, anyRestaurant),
      hint: "Menu prices, before fees and tax",
      isStatic: true,
    },
    {
      key: "orders",
      label: "Orders",
      icon: ShoppingBag,
      value: totals.orders,
      hint: "Paid for, not cancelled",
      isStatic: true,
    },
    {
      key: "restaurants",
      label: "Restaurants",
      icon: Store,
      value: totals.restaurants,
      hint: "With at least one counted order",
      isStatic: true,
    },
  ];

  const columns: Array<TableColumn<CommissionRow>> = [
    {
      id: "restaurant",
      header: "Restaurant",
      render: (row) => <strong>{row.restaurant_name}</strong>,
    },
    {
      id: "orders",
      header: "Orders",
      render: (row) => row.orders,
      mobileLabel: "Orders",
      align: "right",
    },
    {
      id: "sales",
      header: "Food sales",
      render: (row) => money.format(Number(row.sales), row.restaurant_id),
      mobileLabel: "Food sales",
      align: "right",
    },
    {
      id: "commission",
      header: "Commission",
      render: (row) => <strong>{money.format(Number(row.commission), row.restaurant_id)}</strong>,
      mobileLabel: "Commission",
      align: "right",
    },
    {
      id: "share",
      header: "Share",
      render: (row) => `${shareOfCommission(row, totals)}%`,
      mobileLabel: "Share of commission",
      align: "right",
    },
  ];

  return (
    <div className="page-stack">
      <PageIntro
        actions={
          <div aria-label="Period" className="live-segment" role="group">
            {COMMISSION_PERIODS.map((period) => (
              <button
                aria-pressed={days === period.days}
                className={`live-segment__item${
                  days === period.days ? " live-segment__item--active" : ""
                }`}
                key={period.days}
                onClick={() => {
                  setFailed(null);
                  setDays(period.days);
                }}
                type="button"
              >
                {period.label}
              </button>
            ))}
          </div>
        }
        description="What the platform earned from each restaurant, from the commission inside menu prices."
        eyebrow="Platform"
        help="commission"
        title="Commission"
      />

      <StatTiles ariaLabel="Commission in this period" loading={loading} tiles={tiles} />

      <section className="admin-surface">
        {failed && !loading ? (
          <EmptyPanel
            action={
              <button className="primary-button" onClick={retry} type="button">
                Try again
              </button>
            }
            description={failed}
            title="The commission report didn't load"
          />
        ) : (
          <ResponsiveTable
            actions={[
              {
                id: "open",
                label: "Open restaurant",
                icon: Store,
                onClick: (row) => onNavigate(`/admin/restaurants/${row.restaurant_id}`),
              },
            ]}
            columns={columns}
            emptyDescription="Orders that are paid for and not cancelled are counted here as soon as they are placed."
            emptyTitle={`No commission recorded in the last ${pluralize(days, "day")}`}
            keyExtractor={(row) => row.restaurant_id}
            loading={loading}
            mobileTitle={(row) => row.restaurant_name}
            rows={loading ? [] : (report?.restaurants ?? [])}
          />
        )}
        {note ? <small className="hint-text">{note}</small> : null}
      </section>
    </div>
  );
}

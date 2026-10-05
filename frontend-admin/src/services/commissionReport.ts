/**
 * The sums behind the Commission page, kept apart from the page so they can
 * be checked without rendering one.
 *
 * The server sends one row per restaurant. Everything here is what the page
 * adds on top: the totals, and each restaurant's share of what was earned.
 */
import type { CommissionReport, CommissionRow } from "../types/app";

/** The windows the page offers. Days, because that is what the server takes. */
export const COMMISSION_PERIODS = [
  { days: 1, label: "24 hours" },
  { days: 7, label: "7 days" },
  { days: 30, label: "30 days" },
  { days: 90, label: "90 days" },
] as const;

export interface CommissionTotals {
  restaurants: number;
  orders: number;
  sales: number;
  commission: number;
  /** Commission as a percentage of sales, or null with no sales to divide by. */
  effectiveRate: number | null;
}

export function commissionTotals(report: CommissionReport | null): CommissionTotals {
  const rows = report?.restaurants ?? [];
  const orders = rows.reduce((sum, row) => sum + row.orders, 0);
  const sales = rows.reduce((sum, row) => sum + Number(row.sales), 0);
  const commission = rows.reduce((sum, row) => sum + Number(row.commission), 0);
  return {
    restaurants: rows.length,
    orders,
    sales,
    commission,
    // Of the SALES figure, which already contains the commission: 10 inside
    // 110 is 9.1%, not 10%. It is what the platform kept of what was charged,
    // and labelled as that on the page so it is not read as the rate.
    effectiveRate: sales > 0 ? (commission / sales) * 100 : null,
  };
}

/** This restaurant's part of everything earned, as a whole percentage. */
export function shareOfCommission(row: CommissionRow, totals: CommissionTotals): number {
  if (totals.commission <= 0) return 0;
  return Math.round((Number(row.commission) / totals.commission) * 100);
}

/**
 * The sentence under the table saying what the report cannot see.
 *
 * Orders placed before commission was recorded carry no figure, so they are
 * not in any total. Said plainly: a report that silently starts on a Tuesday
 * reads as a bad month.
 */
export function coverageNote(report: CommissionReport | null): string | null {
  if (!report) return null;
  if (!report.counted_from) {
    return "No order has recorded a commission yet. Orders placed from now on are counted here.";
  }
  const countedFrom = new Date(report.counted_from);
  if (countedFrom.getTime() <= new Date(report.since).getTime()) return null;
  const day = countedFrom.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  return `Commission has been recorded on each order since ${day}. Orders placed before that are not counted.`;
}

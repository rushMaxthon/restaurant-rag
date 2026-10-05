import { describe, expect, it } from "vitest";

import type { CommissionReport } from "../types/app";
import { commissionTotals, coverageNote, shareOfCommission } from "./commissionReport";

const row = (name: string, orders: number, sales: string, commission: string) => ({
  restaurant_id: name,
  restaurant_name: name,
  orders,
  sales,
  commission,
  currency: "INR",
});

const report = (over: Partial<CommissionReport> = {}): CommissionReport => ({
  days: 30,
  since: "2026-09-05T00:00:00Z",
  counted_from: "2026-09-01T00:00:00Z",
  restaurants: [row("Bhagwati", 3, "330.00", "30.00"), row("Radhe", 1, "110.00", "10.00")],
  ...over,
});

describe("commissionTotals", () => {
  it("adds up every restaurant", () => {
    const totals = commissionTotals(report());
    expect(totals.restaurants).toBe(2);
    expect(totals.orders).toBe(4);
    expect(totals.sales).toBe(440);
    expect(totals.commission).toBe(40);
  });

  it("gives what was kept of what was charged, which is less than the rate", () => {
    // 10 inside 110 is 9.09%, not 10%.
    expect(commissionTotals(report()).effectiveRate).toBeCloseTo(9.09, 2);
  });

  it("is all zeros, with no rate to show, when nothing was sold", () => {
    const totals = commissionTotals(report({ restaurants: [] }));
    expect(totals).toMatchObject({ restaurants: 0, orders: 0, sales: 0, commission: 0 });
    expect(totals.effectiveRate).toBeNull();
    expect(commissionTotals(null).effectiveRate).toBeNull();
  });
});

describe("shareOfCommission", () => {
  it("is each restaurant's part of everything earned", () => {
    const data = report();
    const totals = commissionTotals(data);
    expect(shareOfCommission(data.restaurants[0]!, totals)).toBe(75);
    expect(shareOfCommission(data.restaurants[1]!, totals)).toBe(25);
  });

  it("is zero rather than a division by nothing", () => {
    const data = report({ restaurants: [row("Free", 2, "200.00", "0.00")] });
    expect(shareOfCommission(data.restaurants[0]!, commissionTotals(data))).toBe(0);
  });
});

describe("coverageNote", () => {
  it("says nothing when the whole window is covered", () => {
    expect(coverageNote(report())).toBeNull();
  });

  it("says when counting started, if that is inside the window", () => {
    const note = coverageNote(report({ counted_from: "2026-10-05T08:00:00Z" }));
    expect(note).toMatch(/since/);
    expect(note).toMatch(/2026/);
  });

  it("says so when no order has recorded a commission at all", () => {
    expect(coverageNote(report({ counted_from: null, restaurants: [] }))).toMatch(/No order/);
  });

  it("says nothing before the report has loaded", () => {
    expect(coverageNote(null)).toBeNull();
  });
});

import { describe, expect, it } from "vitest";

import { isSale, parsePeriod, periodBuckets, periodFor, resolvePeriod } from "./dashboardPeriod";

// Tuesday 5 Oct 2026, 18:30 local time.
const NOW = new Date(2026, 9, 5, 18, 30);
const day = (y: number, m: number, d: number, h = 0, min = 0) => new Date(y, m - 1, d, h, min);

describe("resolvePeriod", () => {
  it("today runs from midnight to now, against the same hours of yesterday", () => {
    const range = resolvePeriod({ kind: "today" }, NOW);
    expect(range.start).toEqual(day(2026, 10, 5));
    expect(range.end).toEqual(NOW);
    expect(range.previousStart).toEqual(day(2026, 10, 4));
    expect(range.previousEnd).toEqual(day(2026, 10, 4, 18, 30));
    expect(range.label).toBe("Today");
    expect(range.bucket).toBe("hour");
  });

  it("yesterday is the whole of yesterday, against the day before", () => {
    const range = resolvePeriod({ kind: "yesterday" }, NOW);
    expect(range.start).toEqual(day(2026, 10, 4));
    expect(range.end).toEqual(day(2026, 10, 5));
    expect(range.previousStart).toEqual(day(2026, 10, 3));
    expect(range.previousEnd).toEqual(day(2026, 10, 4));
    expect(range.comparison).toBe("vs the day before");
  });

  it("last 7 days includes today", () => {
    const range = resolvePeriod({ kind: "last7" }, NOW);
    expect(range.start).toEqual(day(2026, 9, 29));
    expect(range.previousStart).toEqual(day(2026, 9, 22));
    expect(range.bucket).toBe("day");
  });

  it("this month so far is compared with the same days of last month", () => {
    const range = resolvePeriod({ kind: "thisMonth" }, NOW);
    expect(range.start).toEqual(day(2026, 10, 1));
    expect(range.end).toEqual(NOW);
    expect(range.previousStart).toEqual(day(2026, 9, 1));
    expect(range.previousEnd).toEqual(day(2026, 9, 5, 18, 30));
    expect(range.label).toBe("October 2026");
  });

  it("last month is the whole month, against the one before", () => {
    const range = resolvePeriod({ kind: "lastMonth" }, NOW);
    expect(range.start).toEqual(day(2026, 9, 1));
    expect(range.end).toEqual(day(2026, 10, 1));
    expect(range.previousStart).toEqual(day(2026, 8, 1));
    expect(range.previousEnd).toEqual(day(2026, 9, 1));
    expect(range.label).toBe("September 2026");
  });

  it("a chosen month is that calendar month", () => {
    const range = resolvePeriod({ kind: "month", month: "2026-02" }, NOW);
    expect(range.start).toEqual(day(2026, 2, 1));
    expect(range.end).toEqual(day(2026, 3, 1));
    expect(range.comparison).toBe("vs January 2026");
  });

  it("a chosen year is months, against the year before", () => {
    const range = resolvePeriod({ kind: "year", year: 2025 }, NOW);
    expect(range.start).toEqual(day(2025, 1, 1));
    expect(range.end).toEqual(day(2026, 1, 1));
    expect(range.previousStart).toEqual(day(2024, 1, 1));
    expect(range.bucket).toBe("month");
    expect(range.label).toBe("2025");
  });

  it("the current year stops at now", () => {
    const range = resolvePeriod({ kind: "year", year: 2026 }, NOW);
    expect(range.end).toEqual(NOW);
    expect(range.previousEnd).toEqual(day(2025, 10, 5, 18, 30));
  });

  it("a custom range includes both days and compares with the same length before", () => {
    const range = resolvePeriod({ kind: "custom", from: "2026-09-10", to: "2026-09-12" }, NOW);
    expect(range.start).toEqual(day(2026, 9, 10));
    expect(range.end).toEqual(day(2026, 9, 13));
    expect(range.previousStart).toEqual(day(2026, 9, 7));
    expect(range.previousEnd).toEqual(day(2026, 9, 10));
    expect(range.label).toBe("10 Sept 2026 – 12 Sept 2026");
  });

  it("a custom range typed backwards is read the right way round", () => {
    const range = resolvePeriod({ kind: "custom", from: "2026-09-12", to: "2026-09-10" }, NOW);
    expect(range.start).toEqual(day(2026, 9, 10));
    expect(range.end).toEqual(day(2026, 9, 13));
  });

  it("an incomplete choice falls back to the last 7 days rather than to nothing", () => {
    expect(resolvePeriod({ kind: "month" }, NOW).start).toEqual(day(2026, 9, 29));
    expect(resolvePeriod({ kind: "custom", from: "2026-09-10" }, NOW).start).toEqual(day(2026, 9, 29));
  });
});

describe("periodBuckets", () => {
  it("cuts a day into 24 hours", () => {
    const buckets = periodBuckets(resolvePeriod({ kind: "yesterday" }, NOW));
    expect(buckets).toHaveLength(24);
    expect(buckets[0].start).toEqual(day(2026, 10, 4, 0));
    expect(buckets[23].end).toEqual(day(2026, 10, 5, 0));
  });

  it("cuts this month into the days so far", () => {
    const buckets = periodBuckets(resolvePeriod({ kind: "thisMonth" }, NOW));
    expect(buckets).toHaveLength(5);
  });

  it("cuts a past month into all of its days", () => {
    expect(periodBuckets(resolvePeriod({ kind: "month", month: "2026-02" }, NOW))).toHaveLength(28);
  });

  it("cuts a year into months, and the current year into the months so far", () => {
    expect(periodBuckets(resolvePeriod({ kind: "year", year: 2025 }, NOW))).toHaveLength(12);
    expect(periodBuckets(resolvePeriod({ kind: "year", year: 2026 }, NOW))).toHaveLength(10);
  });
});

describe("isSale", () => {
  it("counts what was sold, not an abandoned checkout or a cancelled order", () => {
    expect(isSale({ status: "DELIVERED" })).toBe(true);
    expect(isSale({ status: "PLACED" })).toBe(true);
    expect(isSale({ status: "CANCELLED" })).toBe(false);
    expect(isSale({ status: "PAYMENT_PENDING" })).toBe(false);
  });
});

describe("parsePeriod", () => {
  it("reads back what was saved, and refuses what was not a period", () => {
    expect(parsePeriod('{"kind":"month","month":"2026-02"}')).toEqual({ kind: "month", month: "2026-02" });
    expect(parsePeriod('{"kind":"forever"}')).toBeNull();
    expect(parsePeriod("not json")).toBeNull();
    expect(parsePeriod(null)).toBeNull();
  });
});

describe("periodFor", () => {
  it("opens a newly picked kind on something already chosen", () => {
    expect(periodFor("month", NOW)).toEqual({ kind: "month", month: "2026-09" });
    expect(periodFor("year", NOW)).toEqual({ kind: "year", year: 2026 });
    expect(periodFor("custom", NOW)).toEqual({ kind: "custom", from: "2026-09-29", to: "2026-10-05" });
    expect(periodFor("yesterday", NOW)).toEqual({ kind: "yesterday" });
  });

  it("picks December of last year in January", () => {
    expect(periodFor("month", new Date(2027, 0, 10))).toEqual({ kind: "month", month: "2026-12" });
  });
});

import { describe, expect, it } from "vitest";

import {
  MISLEADING_PERCENT_CHANGE,
  PERIOD_OPTIONS,
  overlapsPeriod,
  percentIsMisleading,
} from "./insightFormat";

describe("percentIsMisleading", () => {
  it("suppresses a percentage measured against nothing", () => {
    // A zero previous period cannot produce a meaningful percentage.
    expect(percentIsMisleading(0, 100)).toBe(true);
  });

  it("suppresses the real case that reached the screen", () => {
    // ₹44 one week, ₹1,304 the next, rendered on a KPI tile as "+2859.6%".
    expect(percentIsMisleading(44.07, 2859.6)).toBe(true);
  });

  it("keeps an ordinary movement", () => {
    expect(percentIsMisleading(1368, 95.2)).toBe(false);
    expect(percentIsMisleading(1000, -28.6)).toBe(false);
  });

  it("treats a missing percentage as nothing to suppress", () => {
    expect(percentIsMisleading(100, null)).toBe(false);
  });

  it("uses the same threshold the backend does", () => {
    // Mirrors insights_misleading_percent_change. If these drift, one screen
    // describes the same movement two different ways.
    expect(MISLEADING_PERCENT_CHANGE).toBe(300);
  });
});

describe("overlapsPeriod", () => {
  it("keeps a finding whose window overlaps the one on screen", () => {
    expect(overlapsPeriod("2026-07-15", "2026-08-13", "2026-08-11", "2026-08-17")).toBe(true);
  });

  it("separates a finding from an entirely different window", () => {
    // These used to be interleaved into one list, so the feed silently spanned
    // two different analyses.
    expect(overlapsPeriod("2026-04-01", "2026-04-30", "2026-08-11", "2026-08-17")).toBe(false);
  });

  it("counts a single shared day as overlap", () => {
    expect(overlapsPeriod("2026-08-01", "2026-08-11", "2026-08-11", "2026-08-17")).toBe(true);
  });
});

describe("period options", () => {
  it("offers windows the backend accepts", () => {
    // Tool windows are an allowlist (7/14/30/60/90); every option must be one.
    expect(PERIOD_OPTIONS.map((option) => option.days)).toEqual([7, 30, 90]);
  });

  it("gives every option words for a sentence", () => {
    for (const option of PERIOD_OPTIONS) {
      expect(option.phrase.length).toBeGreaterThan(0);
    }
  });
});

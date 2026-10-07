import { describe, expect, it } from "vitest";

import { busiestHours, dailyChart, hourChart, hourLabel, percentText, versusYesterday } from "./traffic";

describe("hours", () => {
  it("names an hour the way a person says it", () => {
    expect(hourLabel(0)).toBe("12 AM");
    expect(hourLabel(9)).toBe("9 AM");
    expect(hourLabel(12)).toBe("12 PM");
    expect(hourLabel(21)).toBe("9 PM");
  });

  it("the busiest hours are the top three with anyone in them, busiest first", () => {
    const hours = Array.from({ length: 24 }, () => 0);
    hours[13] = 9;
    hours[20] = 14;
    hours[21] = 9;
    hours[11] = 2;
    expect(busiestHours(hours)).toBe("8–9 PM, 1–2 PM, 9–10 PM");
  });

  it("says nothing when nobody came", () => {
    expect(busiestHours(Array.from({ length: 24 }, () => 0))).toBeNull();
  });

  it("charts all 24 hours", () => {
    const chart = hourChart(Array.from({ length: 24 }, (_, hour) => hour));
    expect(chart).toHaveLength(24);
    expect(chart[20]).toEqual({ label: "8 PM", value: 20, meta: "20 visitors, 8–9 PM" });
  });
});

describe("days", () => {
  it("labels each day and says who ordered", () => {
    const chart = dailyChart([
      { day: "2026-10-06", visitors: 1, ordered: 0 },
      { day: "2026-10-07", visitors: 12, ordered: 3 },
    ]);
    expect(chart[1]).toEqual({ label: "7 Oct", value: 12, meta: "7 Oct: 12 visitors, 3 ordered" });
    expect(chart[0].meta).toBe("6 Oct: 1 visitor, 0 ordered");
  });
});

describe("comparisons", () => {
  it("against yesterday", () => {
    expect(versusYesterday(12, 10)).toBe("+20% vs yesterday");
    expect(versusYesterday(5, 10)).toBe("−50% vs yesterday");
    expect(versusYesterday(10, 10)).toBe("Same as yesterday");
    expect(versusYesterday(4, 0)).toBe("None yesterday");
    expect(versusYesterday(0, 0)).toBeNull();
  });

  it("a percentage, or a dash when there is nothing to divide", () => {
    expect(percentText(7.5)).toBe("7.5%");
    expect(percentText(null)).toBe("—");
  });
});

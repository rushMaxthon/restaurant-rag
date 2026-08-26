import { describe, expect, it } from "vitest";
import { discountLabel, needsDecimals, rupees } from "./suggestionFormat";

const pricing = (original: number | null, offered: number | null, saving: number | null) => ({
  original,
  offered,
  saving,
});

describe("needsDecimals", () => {
  it("keeps whole rupees whole", () => {
    expect(needsDecimals(pricing(320, 290, 30))).toBe(false);
  });

  it("switches the whole triple to decimals when any part is fractional", () => {
    // The real regression: 31.57 / 29.36 / 2.21 rendered as 32 / 29 / 2.
    expect(needsDecimals(pricing(31.57, 29.36, 2.21))).toBe(true);
  });

  it("is true when only the saving is fractional", () => {
    expect(needsDecimals(pricing(30, 28, 2.5))).toBe(true);
  });

  it("handles a card with no pricing at all", () => {
    expect(needsDecimals(null)).toBe(false);
  });

  it("ignores nulls inside the triple", () => {
    expect(needsDecimals(pricing(null, 290, null))).toBe(false);
  });
});

describe("rupees", () => {
  it("rounds to whole rupees by default", () => {
    expect(rupees(31.57)).toBe("₹32");
  });

  it("shows exactly two decimals when asked", () => {
    expect(rupees(31.5, true)).toBe("₹31.50");
  });

  it("groups thousands the Indian way", () => {
    expect(rupees(125000)).toBe("₹1,25,000");
  });

  it("renders the displayed figures so they subtract correctly", () => {
    const p = pricing(31.57, 29.36, 2.21);
    const d = needsDecimals(p);
    expect(rupees(p.original!, d)).toBe("₹31.57");
    expect(rupees(p.offered!, d)).toBe("₹29.36");
    expect(rupees(p.saving!, d)).toBe("₹2.21");
  });
});

describe("discountLabel", () => {
  it("renders a whole percentage without decimals", () => {
    expect(discountLabel({ type: "PERCENTAGE", value: 20 })).toBe("20% off");
  });

  it("keeps one decimal on a fractional percentage", () => {
    expect(discountLabel({ type: "PERCENTAGE", value: 12.5 })).toBe("12.5% off");
  });

  it("drops a trailing .0 rather than writing 9.0%", () => {
    // The generator emits values like 9.03; toFixed(1) rendered "9.0% off".
    expect(discountLabel({ type: "PERCENTAGE", value: 9.03 })).toBe("9% off");
  });

  it("rounds to one decimal rather than showing every place", () => {
    expect(discountLabel({ type: "PERCENTAGE", value: 9.06 })).toBe("9.1% off");
  });

  it("renders a flat discount as money", () => {
    expect(discountLabel({ type: "FLAT", value: 150 })).toBe("₹150 off");
  });

  it("names free delivery", () => {
    expect(discountLabel({ type: "FREE_DELIVERY", value: 0 })).toBe("Free delivery");
  });

  it("says nothing for no discount or an unknown type", () => {
    expect(discountLabel(null)).toBeNull();
    expect(discountLabel({ type: "MYSTERY", value: 5 })).toBeNull();
  });
});

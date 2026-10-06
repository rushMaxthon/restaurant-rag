import { describe, expect, it } from "vitest";

import { DEFAULT_CURRENCY, formatCurrency } from "./api";

describe("formatCurrency", () => {
  it("writes whole rupees without paise", () => {
    expect(formatCurrency(120, "INR")).toBe("₹120");
  });

  it("writes paise as two digits, never one", () => {
    // The platform revenue tile read "₹8,412.5".
    expect(formatCurrency(8412.5, "INR")).toBe("₹8,412.50");
  });

  it("groups rupees the Indian way", () => {
    expect(formatCurrency(123456, "INR")).toBe("₹1,23,456");
  });

  it("falls back to rupees when nothing names a currency", () => {
    expect(DEFAULT_CURRENCY).toBe("INR");
    expect(formatCurrency(50)).toBe("₹50");
  });
});

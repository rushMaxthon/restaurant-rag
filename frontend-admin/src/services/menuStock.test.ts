import { describe, expect, it } from "vitest";

import { parseStock, stockChange } from "./menuStock";

describe("parseStock", () => {
  it("reads an empty box as not counted, never as sold out", () => {
    expect(parseStock("")).toBeNull();
    expect(parseStock("   ")).toBeNull();
  });

  it("reads zero as zero, which is sold out", () => {
    expect(parseStock("0")).toBe(0);
  });

  it("reads a whole number", () => {
    expect(parseStock(" 40 ")).toBe(40);
  });

  it("refuses anything that is not a whole number of dishes", () => {
    for (const typed of ["-3", "12.5", "ten", "4 loaves"]) {
      expect(() => parseStock(typed), typed).toThrow(/whole number/);
    }
  });
});

describe("stockChange", () => {
  it("sends nothing when the owner did not touch the box", () => {
    // Opened at 10; three sold while the editor was open. Saving a new name
    // must not write 10 back.
    expect(stockChange("10", "10")).toEqual({});
    expect(stockChange("", "")).toEqual({});
  });

  it("sends the new count when it was changed", () => {
    expect(stockChange("25", "10")).toEqual({ stock_quantity: 25 });
  });

  it("sends null when the box was cleared, which stops the count", () => {
    expect(stockChange("", "10")).toEqual({ stock_quantity: null });
  });

  it("sends zero when zero was typed over nothing", () => {
    expect(stockChange("0", "")).toEqual({ stock_quantity: 0 });
  });

  it("always sends what was typed for a dish that is being created", () => {
    expect(stockChange("40", null)).toEqual({ stock_quantity: 40 });
    expect(stockChange("", null)).toEqual({ stock_quantity: null });
  });

  it("still refuses nonsense in a box nobody touched", () => {
    expect(() => stockChange("ten", "ten")).toThrow(/whole number/);
  });
});

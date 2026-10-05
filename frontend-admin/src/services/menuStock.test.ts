import { describe, expect, it } from "vitest";

import { countChange, countText, parseStock, stockChange, stockState } from "./menuStock";

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

describe("countChange", () => {
  it("names the field it was asked about", () => {
    expect(countChange("stock_daily_quantity", "40", "")).toEqual({ stock_daily_quantity: 40 });
  });

  it("sends nothing for a box nobody touched", () => {
    expect(countChange("stock_daily_quantity", "40", "40")).toEqual({});
  });

  it("sends null when a box that held a number was cleared", () => {
    expect(countChange("stock_quantity", "", "12")).toEqual({ stock_quantity: null });
  });

  it("always sends for something new", () => {
    expect(countChange("stock_quantity", "", null)).toEqual({ stock_quantity: null });
  });
});

describe("countText", () => {
  it("is an empty box for a count nobody keeps", () => {
    expect(countText(null)).toBe("");
    expect(countText(undefined)).toBe("");
  });

  it("keeps zero as zero", () => {
    expect(countText(0)).toBe("0");
  });
});

describe("stockState", () => {
  it("is out when marked by hand, whatever the count says", () => {
    expect(stockState({ out_of_stock: true, stock_quantity: 40 })).toBe("out");
    expect(stockState({ out_of_stock: true, stock_quantity: null })).toBe("out");
  });

  it("is out when counted down to zero", () => {
    expect(stockState({ out_of_stock: false, stock_quantity: 0 })).toBe("out");
  });

  it("tells a counted dish from one nobody counts", () => {
    expect(stockState({ stock_quantity: 7 })).toBe("counted");
    expect(stockState({ stock_quantity: null })).toBe("uncounted");
    expect(stockState({})).toBe("uncounted");
  });
});

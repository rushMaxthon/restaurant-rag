import { describe, expect, it } from "vitest";

import { menuListPrice } from "./menuPrice";

describe("menuListPrice", () => {
  const dish = { price: "55.00", base_price: "50.00" };

  it("shows an owner the price they typed", () => {
    expect(menuListPrice(dish, "OWNER")).toBe("50.00");
  });

  it("shows the platform admin what the customer pays", () => {
    expect(menuListPrice(dish, "ADMIN")).toBe("55.00");
  });

  it("falls back to the listed price where no typed figure was kept", () => {
    expect(menuListPrice({ price: "40.00", base_price: null }, "OWNER")).toBe("40.00");
    expect(menuListPrice({ price: "40.00" }, "OWNER")).toBe("40.00");
  });

  it("keeps a typed price of zero rather than treating it as missing", () => {
    expect(menuListPrice({ price: "0.00", base_price: 0 }, "OWNER")).toBe(0);
  });
});

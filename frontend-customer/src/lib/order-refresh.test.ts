import { describe, expect, it } from "vitest";

import { orderQueriesToRefresh } from "./order-refresh";
import { queryKeys } from "./queries";

describe("what an order:updated push refreshes on the storefront", () => {
  it("refreshes the order, its payment and its delivery card for each id", () => {
    const keys = orderQueriesToRefresh(["o1"]);
    expect(keys).toContainEqual(queryKeys.order("o1"));
    expect(keys).toContainEqual(["payment-status", "o1"]);
    // The rider's name, "at your door", the ETA and the code live here: a
    // rider step that does not move the order status only shows up through it.
    expect(keys).toContainEqual(queryKeys.orderDelivery("o1"));
  });

  it("always refreshes the order list", () => {
    expect(orderQueriesToRefresh(["o1"])).toContainEqual(queryKeys.orders);
    expect(orderQueriesToRefresh(null)).toContainEqual(queryKeys.orders);
  });

  it("after a reconnect refreshes every order, payment and delivery", () => {
    const keys = orderQueriesToRefresh(null);
    expect(keys).toContainEqual(["order"]);
    expect(keys).toContainEqual(["payment-status"]);
    expect(keys).toContainEqual(["order-delivery"]);
  });
});

import { describe, expect, it } from "vitest";

import { courierEta, courierNow } from "./courier";

const step = (status: string) => ({ status, at: "2026-10-05T11:30:00Z", remark: "" });

describe("courierNow", () => {
  it("says the courier's latest step in the customer's terms", () => {
    expect(courierNow({ state: "ASSIGNED", timeline: [step("CREATED"), step("REACHED_PICKUP")] })).toBe(
      "Your rider is at the restaurant",
    );
    expect(courierNow({ state: "IN_TRANSIT", timeline: [step("REACHED_DELIVERY")] })).toBe(
      "Your rider is at your door",
    );
  });

  it("explains a failed delivery instead of showing a courier word", () => {
    expect(courierNow({ state: "FAILED", timeline: [step("UNDELIVERED")] })).toMatch(/restaurant will be in touch/);
  });

  it("says nothing with no news, or for a rider called off", () => {
    expect(courierNow({ state: "PENDING", timeline: [] })).toBeNull();
    expect(courierNow({ state: "CANCELLED", timeline: [step("CANCELLED")] })).toBeNull();
    expect(courierNow(null)).toBeNull();
  });
});

describe("courierEta", () => {
  const fmt = () => "8:16 pm";
  const eta = { pickup_eta: "2026-10-05T14:30:00Z", drop_eta: "2026-10-05T14:46:00Z" };

  it("is the door once the rider has the food", () => {
    expect(courierEta({ state: "IN_TRANSIT", ...eta }, fmt)).toBe("Arriving by 8:16 pm");
  });

  it("is the restaurant before that", () => {
    expect(courierEta({ state: "ASSIGNED", ...eta }, fmt)).toBe("Rider reaches the restaurant by 8:16 pm");
  });

  it("is nothing once it has arrived, or when the courier gave no time", () => {
    expect(courierEta({ state: "DELIVERED", ...eta }, fmt)).toBeNull();
    expect(courierEta({ state: "IN_TRANSIT", pickup_eta: null, drop_eta: null }, fmt)).toBeNull();
  });
});

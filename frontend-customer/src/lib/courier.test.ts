import { describe, expect, it } from "vitest";

import {
  courierEta,
  courierNow,
  deliveryCode,
  isOwnFleet,
  riderMapLink,
  riderSeen,
} from "./courier";

const step = (status: string) => ({ status, at: "2026-10-05T11:30:00Z", remark: "" });

describe("courierNow", () => {
  it("says the courier's latest step in the customer's terms", () => {
    expect(
      courierNow({ state: "ASSIGNED", timeline: [step("CREATED"), step("REACHED_PICKUP")] }),
    ).toBe("Your rider is at the restaurant");
    expect(courierNow({ state: "IN_TRANSIT", timeline: [step("REACHED_DELIVERY")] })).toBe(
      "Your rider is at your door",
    );
  });

  it("explains a failed delivery instead of showing a courier word", () => {
    expect(courierNow({ state: "FAILED", timeline: [step("UNDELIVERED")] })).toMatch(
      /restaurant will be in touch/,
    );
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
    expect(courierEta({ state: "ASSIGNED", ...eta }, fmt)).toBe(
      "Rider reaches the restaurant by 8:16 pm",
    );
  });

  it("is nothing once it has arrived, or when the courier gave no time", () => {
    expect(courierEta({ state: "DELIVERED", ...eta }, fmt)).toBeNull();
    expect(courierEta({ state: "IN_TRANSIT", pickup_eta: null, drop_eta: null }, fmt)).toBeNull();
  });
});

// --- the platform's own riders (2026-10-08) ---

const fleet = (state: string, timeline: string[] = [], extra = {}) => ({
  provider: "own_fleet",
  state: state as never,
  timeline: timeline.map((status) => ({ status, at: null, remark: "" })),
  ...extra,
});

describe("our own riders, in the customer's words", () => {
  it("is finding a rider while nobody has accepted", () => {
    expect(courierNow(fleet("PENDING", ["OFFERED", "OFFER_EXPIRED"]))).toBe(
      "Finding you a rider nearby",
    );
  });

  it("follows the rider to the restaurant and then to the door", () => {
    expect(courierNow(fleet("ASSIGNED", ["OFFERED", "ASSIGNED"]))).toBe(
      "Your rider is on the way to the restaurant",
    );
    expect(courierNow(fleet("ASSIGNED", ["ASSIGNED", "ARRIVED_PICKUP"]))).toBe(
      "Your rider is at the restaurant",
    );
    // The fleet's timeline stops at the restaurant; the state carries on.
    expect(courierNow(fleet("PICKED_UP", ["ASSIGNED", "ARRIVED_PICKUP"]))).toBe(
      "Your rider has your food and is on the way",
    );
    expect(courierNow(fleet("IN_TRANSIT", ["ARRIVED_PICKUP"]))).toBe("Your rider is at your door");
  });

  it("leaves the courier's own wording alone", () => {
    expect(
      courierNow({
        state: "ASSIGNED",
        timeline: [{ status: "REACHED_PICKUP", at: null, remark: "" }],
      }),
    ).toBe("Your rider is at the restaurant");
  });
});

describe("the delivery code", () => {
  it("is shown only while our rider is on the way", () => {
    expect(deliveryCode(fleet("ASSIGNED", [], { delivery_otp: "1295" }))).toBe("1295");
    expect(deliveryCode(fleet("DELIVERED", [], { delivery_otp: "1295" }))).toBeNull();
    expect(
      deliveryCode({ ...fleet("ASSIGNED"), provider: "pidge", delivery_otp: "1295" }),
    ).toBeNull();
    expect(deliveryCode(fleet("ASSIGNED"))).toBeNull();
  });
});

describe("where the rider is", () => {
  it("links to the rider's last position on the map", () => {
    expect(
      riderMapLink(fleet("PICKED_UP", [], { rider_latitude: 21.2, rider_longitude: 72.8 })),
    ).toBe("https://www.google.com/maps/search/?api=1&query=21.2,72.8");
    expect(riderMapLink(fleet("PICKED_UP"))).toBeNull();
  });

  it("says how fresh the position is", () => {
    const now = new Date("2026-10-08T12:00:00Z");
    expect(riderSeen("2026-10-08T11:59:50Z", now)).toBe("updated just now");
    expect(riderSeen("2026-10-08T11:57:00Z", now)).toBe("updated 3 min ago");
    expect(riderSeen(null, now)).toBeNull();
  });

  it("knows which deliveries are ours", () => {
    expect(isOwnFleet(fleet("PENDING"))).toBe(true);
    expect(isOwnFleet({ provider: "pidge" })).toBe(false);
    expect(isOwnFleet(null)).toBe(false);
  });
});

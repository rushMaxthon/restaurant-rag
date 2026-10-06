import { describe, expect, it } from "vitest";

import { canCancelRider, isBadStep, nextEta, riderMapUrl, stepLabel } from "./courier";

describe("stepLabel", () => {
  it("says the courier's statuses in words", () => {
    expect(stepLabel("REACHED_PICKUP")).toBe("Rider at the restaurant");
    expect(stepLabel("out_for_delivery")).toBe("On the way to the customer");
  });

  it("still shows a status nobody has seen, rather than dropping it", () => {
    expect(stepLabel("REACHED_GATE")).toBe("Reached gate");
  });
});

describe("isBadStep", () => {
  it("marks the steps where a trip went wrong", () => {
    expect(isBadStep("UNDELIVERED")).toBe(true);
    expect(isBadStep("RTO_DELIVERED")).toBe(true);
    expect(isBadStep("PICKED_UP")).toBe(false);
  });
});

describe("nextEta", () => {
  const eta = { pickup_eta: "2026-10-05T11:30:00Z", drop_eta: "2026-10-05T11:45:00Z" };

  it("is the restaurant while a rider is coming for the food", () => {
    expect(nextEta({ state: "ASSIGNED", ...eta })?.at).toBe(eta.pickup_eta);
  });

  it("is the door once the food is on its way", () => {
    expect(nextEta({ state: "IN_TRANSIT", ...eta })?.at).toBe(eta.drop_eta);
    // The network sends its delivery DEADLINE here (wefast: about 70
    // minutes after booking), not an arrival estimate, so it says "by".
    expect(nextEta({ state: "PICKED_UP", ...eta })?.label).toBe("Rider must deliver by");
  });

  it("is nothing once the trip is over, or when the courier gave none", () => {
    expect(nextEta({ state: "DELIVERED", ...eta })).toBeNull();
    expect(nextEta({ state: "IN_TRANSIT", pickup_eta: null, drop_eta: null })).toBeNull();
  });
});

describe("riderMapUrl and canCancelRider", () => {
  it("links to the rider's last point, and to nothing without one", () => {
    expect(riderMapUrl({ rider_latitude: 21.2, rider_longitude: 72.8 })).toBe("https://www.google.com/maps?q=21.2,72.8");
    expect(riderMapUrl({ rider_latitude: null, rider_longitude: 72.8 })).toBeNull();
  });

  it("offers calling the rider off only when the server says it may", () => {
    expect(canCancelRider({ can_cancel: true })).toBe(true);
    expect(canCancelRider({ can_cancel: false })).toBe(false);
    // An older API that does not send the field offers nothing.
    expect(canCancelRider({})).toBe(false);
  });
});

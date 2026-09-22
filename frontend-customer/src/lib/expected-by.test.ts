/**
 * When an order is expected, on the page somebody refreshes while waiting.
 *
 * The tracking page walked a customer through Placed → Accepted → Preparing
 * and never said when the food would arrive. The cart promises a time before
 * the order exists; the moment it was placed, the promise vanished.
 *
 * The time is derived from the branch's own estimate and the moment the order
 * was placed — nothing is invented here, which is what the null cases below
 * are protecting. A wrong time on this page is worse than no time: it is the
 * one number the customer will hold the restaurant to.
 */

import { describe, expect, it } from "vitest";

import { expectedBy, type Order } from "./bangkok-data";

type Subject = Pick<
  Order,
  "schedule_type" | "placed_at" | "fulfillment_type" | "restaurant_location"
>;

const PLACED = "2026-09-20T14:10:00.000Z";

function order(over: Partial<Subject> = {}): Subject {
  return {
    schedule_type: over.schedule_type ?? "ASAP",
    placed_at: over.placed_at ?? PLACED,
    fulfillment_type: over.fulfillment_type ?? "DELIVERY",
    restaurant_location: over.restaurant_location ?? {
      id: "b1",
      branch_name: "Rushtampura",
      estimated_delivery_time: 35,
      estimated_pickup_time: 15,
    },
  };
}

/** Five minutes after the order was placed: it is still being made. */
const SOON = new Date("2026-09-20T14:15:00.000Z");

describe("expectedBy", () => {
  it("adds the branch's delivery estimate to when the order was placed", () => {
    // 14:10 + 35 minutes.
    expect(expectedBy(order(), SOON)).toBe(
      new Intl.DateTimeFormat("en-CA", { hour: "numeric", minute: "2-digit", hour12: true }).format(
        new Date("2026-09-20T14:45:00.000Z"),
      ),
    );
  });

  it("uses the pickup estimate for a pickup order", () => {
    const delivery = expectedBy(order(), SOON);
    const pickup = expectedBy(order({ fulfillment_type: "PICKUP" }), SOON);
    expect(pickup).not.toBe(delivery);
  });

  it("says nothing for an order booked for later", () => {
    // `scheduledFor` answers that one, with the time the customer chose
    // rather than an estimate from when they happened to press the button.
    expect(expectedBy(order({ schedule_type: "SCHEDULED" }), SOON)).toBeNull();
  });

  it("says nothing when the branch publishes no estimate", () => {
    expect(
      expectedBy(
        order({
          restaurant_location: {
            id: "b1",
            branch_name: "Rushtampura",
            estimated_delivery_time: 0,
            estimated_pickup_time: 0,
          },
        }),
        SOON,
      ),
    ).toBeNull();
  });

  it("says nothing when the branch is missing entirely", () => {
    // Built without the key rather than with an undefined one:
    // `exactOptionalPropertyTypes` is on, and "absent" is the shape the API
    // actually produces for an order whose branch was not expanded.
    const { restaurant_location: _omitted, ...withoutBranch } = order();
    expect(expectedBy(withoutBranch, SOON)).toBeNull();
  });

  it("stops promising a time once that time has passed", () => {
    // The whole point of the null. A late order insisting it "arrives by
    // 2:45 p.m." at three o'clock is the app calling the restaurant a liar;
    // the steps still say where the food is.
    const late = new Date("2026-09-20T15:00:00.000Z");
    expect(expectedBy(order(), late)).toBeNull();
  });

  it("says nothing rather than throwing on an unusable timestamp", () => {
    expect(expectedBy(order({ placed_at: "not a date" }), SOON)).toBeNull();
  });
});

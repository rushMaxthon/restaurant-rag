import { describe, expect, it } from "vitest";
import {
  availabilityNow,
  bookableTimes,
  dayFromDate,
  formatSlotTime,
  nextOpening,
  weeklySlots,
} from "./branch-hours";
import type { FulfillmentSlot, RestaurantLocation } from "./bangkok-data";

/**
 * Opening-hours logic, which is the most bug-prone code in the app.
 *
 * It decides whether an order can be placed at all. Before any of this existed,
 * the customer app ignored the availability the API had always sent — so at
 * 11pm, when every branch is outside its schedule, you could fill a cart, reach
 * checkout, and only then be told the branch was shut.
 *
 * Dates are pinned rather than taken from the clock: a test that passes at
 * 2pm and fails at midnight is worse than no test.
 */

function slot(
  day: FulfillmentSlot["day_of_week"],
  type: FulfillmentSlot["fulfillment_type"],
  start: string,
  end: string,
  isActive = true,
): FulfillmentSlot {
  return {
    id: `${day}-${type}-${start}`,
    day_of_week: day,
    fulfillment_type: type,
    start_time: start,
    end_time: end,
    is_active: isActive,
  };
}

function branch(overrides: Partial<RestaurantLocation> = {}): RestaurantLocation {
  return {
    id: "loc-1",
    branch_name: "Test Branch",
    address_line_1: "1 Test Street",
    city: "Ahmedabad",
    delivery_fee: "2.79",
    minimum_order_amount: "16.00",
    estimated_delivery_time: 29,
    estimated_pickup_time: 15,
    delivery_enabled: true,
    pickup_enabled: true,
    is_open: true,
    is_active: true,
    slot_interval_minutes: 30,
    preparation_time_minutes: 20,
    fulfillment_slots: [
      slot("MONDAY", "DELIVERY", "11:00:00", "21:30:00"),
      slot("MONDAY", "PICKUP", "10:30:00", "22:00:00"),
      slot("SUNDAY", "DELIVERY", "10:30:00", "21:00:00"),
      // Inactive: an operator turned this window off, so it must not count.
      slot("TUESDAY", "DELIVERY", "11:00:00", "20:00:00", false),
    ],
    ...overrides,
  };
}

// Sunday 13 September 2026, 23:12 local — the exact moment the gap was found,
// with every branch outside its schedule.
const SUNDAY_LATE = new Date(2026, 8, 13, 23, 12);
const SUNDAY_MIDDAY = new Date(2026, 8, 13, 12, 30);

describe("dayFromDate", () => {
  it("maps JS's Sunday-first week onto the Monday-first slot enum", () => {
    // Off-by-one here silently reads the wrong day's hours all week.
    expect(dayFromDate(SUNDAY_LATE)).toBe("SUNDAY");
    expect(dayFromDate(new Date(2026, 8, 14, 9, 0))).toBe("MONDAY");
    expect(dayFromDate(new Date(2026, 8, 19, 9, 0))).toBe("SATURDAY");
  });
});

describe("formatSlotTime", () => {
  it("reads the way a person says it, not the way the column stores it", () => {
    expect(formatSlotTime("09:00:00")).toBe("9 am");
    expect(formatSlotTime("21:30:00")).toBe("9:30 pm");
    expect(formatSlotTime("12:00:00")).toBe("12 pm");
    expect(formatSlotTime("00:00:00")).toBe("12 am");
  });
});

describe("availabilityNow", () => {
  it("prefers the server's answer over anything derived here", () => {
    // The server knows about temporary closures the slot table does not, and
    // it is the one that will accept or reject the order.
    const closed = branch({
      delivery_available_now: false,
      delivery_unavailable_reason: "Kitchen closed for maintenance.",
    });
    expect(availabilityNow(closed, "DELIVERY", SUNDAY_MIDDAY)).toEqual({
      available: false,
      reason: "Kitchen closed for maintenance.",
    });
  });

  it("falls back to the slots when the server did not say", () => {
    expect(availabilityNow(branch(), "DELIVERY", SUNDAY_MIDDAY).available).toBe(true);
    expect(availabilityNow(branch(), "DELIVERY", SUNDAY_LATE).available).toBe(false);
  });

  it("treats an unknown branch as unavailable rather than assuming open", () => {
    expect(availabilityNow(undefined, "DELIVERY", SUNDAY_MIDDAY).available).toBe(false);
  });
});

describe("nextOpening", () => {
  it("rolls into next week rather than reporting nothing", () => {
    // Sunday 23:12: today's window has closed, so the answer is Monday. Getting
    // this wrong is what "no upcoming slots" on a perfectly normal branch means.
    const next = nextOpening(branch(), "DELIVERY", SUNDAY_LATE);
    expect(next?.day).toBe("MONDAY");
    expect(next?.slot.start_time).toBe("11:00:00");
    expect(next?.isToday).toBe(false);
  });

  it("finds a later window on the same day", () => {
    const early = new Date(2026, 8, 13, 8, 0);
    const next = nextOpening(branch(), "DELIVERY", early);
    expect(next?.isToday).toBe(true);
    expect(next?.slot.start_time).toBe("10:30:00");
  });

  it("returns nothing when the branch has no windows for that type", () => {
    expect(nextOpening(branch({ fulfillment_slots: [] }), "DELIVERY", SUNDAY_LATE)).toBeNull();
  });
});

describe("weeklySlots", () => {
  it("covers all seven days, Monday first, closed days included", () => {
    const week = weeklySlots(branch(), "DELIVERY");
    expect(week).toHaveLength(7);
    expect(week[0]?.day).toBe("MONDAY");
    expect(week[6]?.day).toBe("SUNDAY");
    // Wednesday has no window; the row still exists so the table reads "Closed".
    expect(week[2]?.slots).toHaveLength(0);
  });

  it("leaves out windows an operator disabled", () => {
    const tuesday = weeklySlots(branch(), "DELIVERY").find((d) => d.day === "TUESDAY");
    expect(tuesday?.slots).toHaveLength(0);
  });

  it("keeps delivery and pickup apart", () => {
    // They genuinely differ: the kitchen opens for collection before it starts
    // sending riders out.
    const delivery = weeklySlots(branch(), "DELIVERY").find((d) => d.day === "MONDAY");
    const pickup = weeklySlots(branch(), "PICKUP").find((d) => d.day === "MONDAY");
    expect(delivery?.slots[0]?.start_time).toBe("11:00:00");
    expect(pickup?.slots[0]?.start_time).toBe("10:30:00");
  });
});

describe("bookableTimes", () => {
  const monday = new Date(2026, 8, 14, 0, 0);

  it("steps by the branch's own interval", () => {
    const times = bookableTimes(branch(), "DELIVERY", "MONDAY", monday, SUNDAY_LATE);
    expect(times[0]?.getHours()).toBe(11);
    expect(times[0]?.getMinutes()).toBe(0);
    expect(times[1]?.getMinutes()).toBe(30);
  });

  it("never offers a time the kitchen cannot cook in", () => {
    // Preparation time is 20 minutes, so 11:00 is gone by 10:50.
    const nearOpening = new Date(2026, 8, 14, 10, 50);
    const times = bookableTimes(branch(), "DELIVERY", "MONDAY", monday, nearOpening);
    expect(times[0]?.getHours()).toBe(11);
    expect(times[0]?.getMinutes()).toBe(30);
  });

  it("stays inside the window", () => {
    const times = bookableTimes(branch(), "DELIVERY", "MONDAY", monday, SUNDAY_LATE);
    const last = times[times.length - 1];
    expect(last!.getHours() * 60 + last!.getMinutes()).toBeLessThanOrEqual(21 * 60 + 30);
  });

  it("offers nothing for a day the branch is shut", () => {
    const wednesday = new Date(2026, 8, 16, 0, 0);
    expect(bookableTimes(branch(), "DELIVERY", "WEDNESDAY", wednesday, SUNDAY_LATE)).toHaveLength(
      0,
    );
  });
});

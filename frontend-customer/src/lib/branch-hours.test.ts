import { describe, expect, it } from "vitest";
import {
  availabilityNow,
  bookableDays,
  bookableTimes,
  dayChipLabel,
  dateInputValue,
  dayFromInputValue,
  groupByPartOfDay,
  isBookableTime,
  nextBookableTime,
  snapToInterval,
  lastBookableDay,
  leadMinutes,
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
    future_order_enabled: true,
    max_future_days: 7,
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

  it("leaves the kitchen time to cook before it shuts", () => {
    // The window closes at 21:30 and the delivery ETA is 29 minutes, so the
    // last honest slot is the grid point at or before 21:01, i.e. 21:00.
    // Offering 21:30 meant booking food nobody could have made — the server
    // rejects it, and the customer finds out after filling in the whole form.
    const times = bookableTimes(branch(), "DELIVERY", "MONDAY", monday, SUNDAY_LATE);
    const last = times[times.length - 1]!;
    expect(last.getHours()).toBe(21);
    expect(last.getMinutes()).toBe(0);
  });

  it("offers nothing when the window is shorter than the prep time", () => {
    const tiny = branch({
      fulfillment_slots: [slot("MONDAY", "DELIVERY", "11:00:00", "11:10:00")],
    });
    expect(bookableTimes(tiny, "DELIVERY", "MONDAY", monday, SUNDAY_LATE)).toHaveLength(0);
  });

  it("offers nothing for a day the branch is shut", () => {
    const wednesday = new Date(2026, 8, 16, 0, 0);
    expect(bookableTimes(branch(), "DELIVERY", "WEDNESDAY", wednesday, SUNDAY_LATE)).toHaveLength(
      0,
    );
  });
});


describe("leadMinutes", () => {
  it("uses the larger of preparation time and the ETA, as the server does", () => {
    // The server's buffer is max(preparation_time_minutes, ETA). Using prep
    // alone offered 11:00 when the branch could not have it there until 11:19,
    // and the order was then rejected for being too soon.
    expect(leadMinutes(branch(), "DELIVERY")).toBe(29);
    expect(leadMinutes(branch(), "PICKUP")).toBe(20);
  });
});

describe("bookableDays", () => {
  it("offers today plus the branch's own horizon, today first", () => {
    const days = bookableDays(branch(), "DELIVERY", SUNDAY_LATE);
    expect(days.length).toBeGreaterThan(0);
    expect(days[0]!.getTime()).toBeLessThan(days[days.length - 1]!.getTime());
  });

  it("leaves out days with nothing left on them", () => {
    // Wednesday has no delivery window at all; a chip for it would be a dead
    // end the customer discovers by tapping.
    const days = bookableDays(branch(), "DELIVERY", SUNDAY_LATE);
    expect(days.some((d) => d.getDay() === 3)).toBe(false);
  });

  it("drops today once its last window has passed", () => {
    // Sunday 23:12 — the 10:30-21:00 window is over.
    const days = bookableDays(branch(), "DELIVERY", SUNDAY_LATE);
    expect(days.some((d) => isSameDayAs(d, SUNDAY_LATE))).toBe(false);
  });

  it("offers nothing when the branch does not take future orders", () => {
    expect(bookableDays(branch({ future_order_enabled: false }), "DELIVERY", SUNDAY_LATE)).toEqual([]);
  });

  it("stays within max_future_days", () => {
    const days = bookableDays(branch({ max_future_days: 2 }), "DELIVERY", SUNDAY_LATE);
    const last = days[days.length - 1]!;
    const limit = new Date(SUNDAY_LATE);
    limit.setDate(limit.getDate() + 2);
    expect(last.getTime()).toBeLessThanOrEqual(limit.getTime());
  });
});

describe("slot alignment", () => {
  it("puts times on the interval grid, not on the window's start", () => {
    // The server rejects any minute that is not a multiple of the interval, so
    // a window opening at 10:45 with a 30-minute interval must offer 11:00.
    const odd = branch({
      fulfillment_slots: [
        {
          id: "odd",
          day_of_week: "MONDAY",
          fulfillment_type: "DELIVERY",
          start_time: "10:45:00",
          end_time: "14:00:00",
          is_active: true,
        },
      ],
    });
    const monday = new Date(2026, 8, 14, 0, 0);
    const times = bookableTimes(odd, "DELIVERY", "MONDAY", monday, SUNDAY_LATE);
    expect(times[0]?.getMinutes()).toBe(0);
    expect(times[0]?.getHours()).toBe(11);
    for (const time of times) expect(time.getMinutes() % 30).toBe(0);
  });
});

describe("dayChipLabel", () => {
  it("says Today and Tomorrow before it resorts to a date", () => {
    const tomorrow = new Date(SUNDAY_LATE);
    tomorrow.setDate(tomorrow.getDate() + 1);
    const later = new Date(SUNDAY_LATE);
    later.setDate(later.getDate() + 3);
    expect(dayChipLabel(SUNDAY_LATE, SUNDAY_LATE)).toBe("Today");
    expect(dayChipLabel(tomorrow, SUNDAY_LATE)).toBe("Tomorrow");
    expect(dayChipLabel(later, SUNDAY_LATE)).toMatch(/\w{3}/);
  });
});

function isSameDayAs(a: Date, b: Date): boolean {
  return a.toDateString() === b.toDateString();
}

describe("dateInputValue", () => {
  /**
   * The obvious implementation is `date.toISOString().slice(0, 10)`, and it is
   * wrong for half the planet. `toISOString` converts to UTC first, so any
   * local time whose UTC equivalent falls on another date comes back as the
   * wrong day — and the customer books dinner for Tuesday and is handed
   * Monday. Pinned to the two edges where that actually bites.
   */
  it("keeps the local calendar day just before midnight", () => {
    expect(dateInputValue(new Date(2026, 8, 17, 23, 30))).toBe("2026-09-17");
  });

  it("keeps the local calendar day just after midnight", () => {
    expect(dateInputValue(new Date(2026, 8, 17, 0, 15))).toBe("2026-09-17");
  });

  it("pads single-digit months and days", () => {
    expect(dateInputValue(new Date(2026, 0, 5, 12, 0))).toBe("2026-01-05");
  });
});

describe("dayFromInputValue", () => {
  /**
   * `new Date("2026-09-17")` parses as UTC midnight, which in any negative
   * offset is the 16th locally. The round trip has to survive, or the date
   * input silently moves the order a day earlier every time.
   */
  it("round-trips with dateInputValue", () => {
    const original = new Date(2026, 8, 17, 19, 45);
    const back = dayFromInputValue(dateInputValue(original));
    expect(back).not.toBeNull();
    expect(back!.getFullYear()).toBe(2026);
    expect(back!.getMonth()).toBe(8);
    expect(back!.getDate()).toBe(17);
  });

  it("returns local midnight, not UTC midnight", () => {
    const day = dayFromInputValue("2026-09-17")!;
    expect(day.getHours()).toBe(0);
    expect(day.getDate()).toBe(17);
  });

  it("rejects a blank or malformed value rather than returning Invalid Date", () => {
    expect(dayFromInputValue("")).toBeNull();
    expect(dayFromInputValue("not-a-date")).toBeNull();
  });
});

describe("lastBookableDay", () => {
  it("is today plus the branch horizon", () => {
    const now = new Date(2026, 8, 14, 12, 0);
    const last = lastBookableDay(branch({ max_future_days: 3 }), now);
    expect(dateInputValue(last)).toBe("2026-09-17");
  });

  // The read schema always sends max_future_days, but the TS type marks it
  // optional, so the missing case is undefined rather than null.
  it("falls back to the default horizon when the branch does not say", () => {
    const now = new Date(2026, 8, 14, 12, 0);
    // The key is omitted, not set to undefined: exactOptionalPropertyTypes
    // makes those two different things, and absent is the one that can happen.
    const { max_future_days: _horizon, ...noHorizon } = branch();
    expect(dateInputValue(lastBookableDay(noHorizon, now))).toBe("2026-09-21");
  });
});

describe("groupByPartOfDay", () => {
  const at = (h: number, m = 0) => new Date(2026, 8, 17, h, m);

  it("splits a long list into morning, afternoon and evening", () => {
    const groups = groupByPartOfDay([at(9), at(11, 30), at(13), at(17), at(19, 30)]);
    expect(groups.map((g) => g.label)).toEqual(["Morning", "Afternoon", "Evening"]);
    expect(groups[0]!.times).toHaveLength(2); // 9:00, 11:30
    expect(groups[1]!.times).toHaveLength(1); // 13:00
    expect(groups[2]!.times).toHaveLength(2); // 17:00, 19:30
  });

  it("leaves out a part of the day with nothing in it", () => {
    const groups = groupByPartOfDay([at(19), at(20)]);
    expect(groups.map((g) => g.label)).toEqual(["Evening"]);
  });

  it("puts noon in the afternoon and 5pm in the evening", () => {
    expect(groupByPartOfDay([at(12)])[0]!.label).toBe("Afternoon");
    expect(groupByPartOfDay([at(17)])[0]!.label).toBe("Evening");
  });

  it("has nothing to group when there are no times", () => {
    expect(groupByPartOfDay([])).toEqual([]);
  });
});

describe("nextBookableTime", () => {
  /**
   * The soonest time this branch can actually have food ready.
   *
   * This is what the picker leads with, so it has to be a time the server
   * would accept — not merely the next opening. A window that opens at 11:00
   * cannot take an 11:00 order at 10:50 if the kitchen needs 20 minutes.
   */
  it("is the first slot on the first day that has one", () => {
    const soon = nextBookableTime(branch(), "DELIVERY", SUNDAY_LATE);
    expect(soon).not.toBeNull();
    expect(soon!.getHours()).toBe(11);
    expect(soon!.getMinutes()).toBe(0);
  });

  it("skips past today once today has nothing left", () => {
    // Monday 21:20 — the window shuts at 21:30 and delivery needs 29 minutes,
    // so nothing remains today and the answer must come from a later day.
    const lateMonday = new Date(2026, 8, 14, 21, 20);
    const soon = nextBookableTime(branch(), "DELIVERY", lateMonday);
    expect(soon).not.toBeNull();
    expect(soon!.getDate()).not.toBe(14);
  });

  it("is null when the branch has no bookable window at all", () => {
    expect(nextBookableTime(branch({ fulfillment_slots: [] }), "DELIVERY", SUNDAY_LATE)).toBeNull();
  });
});

describe("snapToInterval", () => {
  /**
   * A custom time has to land on the branch's grid, because the server rejects
   * anything whose minute is not a multiple of the interval. Rounding UP, not
   * to nearest: rounding down can land before the prep buffer.
   */
  it("rounds up to the next grid point", () => {
    const snapped = snapToInterval(new Date(2026, 8, 14, 18, 7), 30);
    expect(snapped.getHours()).toBe(18);
    expect(snapped.getMinutes()).toBe(30);
  });

  it("leaves a time already on the grid alone", () => {
    const snapped = snapToInterval(new Date(2026, 8, 14, 18, 30), 30);
    expect(snapped.getMinutes()).toBe(30);
  });

  it("rolls into the next hour", () => {
    const snapped = snapToInterval(new Date(2026, 8, 14, 18, 45), 30);
    expect(snapped.getHours()).toBe(19);
    expect(snapped.getMinutes()).toBe(0);
  });
});

describe("isBookableTime", () => {
  /**
   * Guards the free-text time picker. Someone can type 11:59 pm into a time
   * input; the picker must say no before the server does.
   */
  const monday = new Date(2026, 8, 14, 9, 0);

  it("accepts a time inside the window with room to cook", () => {
    expect(isBookableTime(branch(), "DELIVERY", new Date(2026, 8, 14, 19, 0), monday)).toBe(true);
  });

  it("refuses the closing minute", () => {
    expect(isBookableTime(branch(), "DELIVERY", new Date(2026, 8, 14, 21, 30), monday)).toBe(false);
  });

  it("refuses a time before the branch opens", () => {
    expect(isBookableTime(branch(), "DELIVERY", new Date(2026, 8, 14, 9, 30), monday)).toBe(false);
  });

  it("refuses a time off the interval grid", () => {
    expect(isBookableTime(branch(), "DELIVERY", new Date(2026, 8, 14, 19, 7), monday)).toBe(false);
  });

  it("refuses a day the branch is shut", () => {
    expect(isBookableTime(branch(), "DELIVERY", new Date(2026, 8, 16, 19, 0), monday)).toBe(false);
  });
});

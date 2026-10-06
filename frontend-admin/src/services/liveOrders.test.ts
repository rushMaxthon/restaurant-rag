/**
 * The live orders board, without the board.
 *
 * What is pinned is what an operator would be misled by: a column that looks
 * complete and is not, an order that looks late and is not due, a backlog
 * that buries tonight's work, a tooltip that names a different threshold from
 * the one the card uses, and a link that should never have been one.
 */
import { describe, expect, it } from "vitest";

import type { LiveOrder, LiveOrdersBoard, OrderStatus } from "../types/app";
import {
  CARD_HELP,
  LIVE_COLUMNS,
  NO_FILTER,
  STATIC_HELP,
  buildColumns,
  columnHelp,
  deliveryLine,
  formatDuration,
  itemsSummary,
  orderClock,
  restaurantBreakdown,
  safeTrackingUrl,
  startOfToday,
  summarise,
  etaText,
  nextAction,
} from "./liveOrders";

const NOW = new Date("2026-10-05T12:00:00Z");
const minutesAgo = (minutes: number) => new Date(NOW.getTime() - minutes * 60000).toISOString();
const DAY = 24 * 60;

let seq = 0;
function order(status: OrderStatus, over: Partial<LiveOrder> = {}): LiveOrder {
  seq += 1;
  return {
    id: `order-${seq}`,
    restaurant_id: "r1",
    restaurant: { id: "r1", name: "Bhagwati Bakery", city: "Surat" },
    restaurant_location: { id: "l1", branch_name: "Main Branch" },
    customer: { id: "c1", full_name: "Asha Patel", email: "asha@example.com" },
    contact_name: null,
    status,
    fulfillment_type: "DELIVERY",
    payment_status: "PAID",
    schedule_type: "ASAP",
    scheduled_at: minutesAgo(10),
    placed_at: minutesAgo(10),
    updated_at: minutesAgo(1),
    completed_at: null,
    items: [],
    delivery: null,
    ...over,
  } as unknown as LiveOrder;
}

type StageSpec = [OrderStatus, LiveOrder[], number?, number?];

function board(stages: StageSpec[]): LiveOrdersBoard {
  return {
    generated_at: NOW.toISOString(),
    completed_from: NOW.toISOString(),
    stage_limit: 100,
    stale_after_minutes: DAY,
    restaurants: [],
    stages: stages.map(([status, orders, total, stale]) => ({
      status,
      orders,
      total: total ?? orders.length,
      stale_total: stale ?? 0,
    })),
  };
}

const column = (key: string) => LIVE_COLUMNS.find((meta) => meta.key === key)!;

describe("buildColumns", () => {
  it("puts accepted and preparing in one kitchen column, oldest first", () => {
    const older = order("PREPARING", { placed_at: minutesAgo(50) });
    const newer = order("ACCEPTED", { placed_at: minutesAgo(5) });
    const columns = buildColumns(
      board([
        ["PLACED", []],
        ["ACCEPTED", [newer]],
        ["PREPARING", [older]],
        ["OUT_FOR_DELIVERY", []],
        ["DELIVERED", []],
      ]),
      NO_FILTER,
      NOW,
    );
    expect(columns.map((c) => c.key)).toEqual(["new", "kitchen", "road", "done"]);
    expect(columns[1].orders.map((o) => o.id)).toEqual([older.id, newer.id]);
    expect(columns[1].total).toBe(2);
  });

  it("re-sorts what the server sent newest-first into longest-wait-first", () => {
    const fresh = order("PLACED", { placed_at: minutesAgo(1) });
    const waiting = order("PLACED", { placed_at: minutesAgo(8) });
    const columns = buildColumns(board([["PLACED", [fresh, waiting]]]), NO_FILTER, NOW);
    expect(columns[0].orders.map((o) => o.id)).toEqual([waiting.id, fresh.id]);
  });

  it("keeps orders open for more than a day out of tonight's list", () => {
    // 213 at PLACED on the server: 5 from tonight, 208 nobody will ever cook.
    const tonight = order("PLACED", { placed_at: minutesAgo(3) });
    const lastWeek = order("PLACED", { placed_at: minutesAgo(7 * DAY) });
    const lastMonth = order("PLACED", { placed_at: minutesAgo(30 * DAY) });
    const columns = buildColumns(
      board([["PLACED", [tonight, lastWeek, lastMonth], 213, 208]]),
      NO_FILTER,
      NOW,
    );
    expect(columns[0].orders.map((o) => o.id)).toEqual([tonight.id]);
    // The headline is tonight's work; the backlog is its own number.
    expect(columns[0].total).toBe(5);
    expect(columns[0].staleTotal).toBe(208);
    // Newest of the old first: the one most likely to still matter.
    expect(columns[0].stale.map((o) => o.id)).toEqual([lastWeek.id, lastMonth.id]);
    expect(columns[0].truncated).toBe(true);
  });

  it("does not call a scheduled order backlog because it was placed long ago", () => {
    const booked = order("PLACED", {
      schedule_type: "SCHEDULED",
      placed_at: minutesAgo(6 * DAY),
      scheduled_at: minutesAgo(-90),
    });
    const columns = buildColumns(board([["PLACED", [booked]]]), NO_FILTER, NOW);
    expect(columns[0].orders).toHaveLength(1);
    expect(columns[0].staleTotal).toBe(0);
  });

  it("never treats a finished order as backlog", () => {
    const done = order("DELIVERED", { placed_at: minutesAgo(3 * DAY) });
    const columns = buildColumns(board([["DELIVERED", [done]]]), NO_FILTER, NOW);
    expect(columns[3].orders).toHaveLength(1);
    expect(columns[3].staleTotal).toBe(0);
  });

  it("counts only what matches once somebody is filtering", () => {
    const delivery = order("PLACED");
    const pickup = order("PLACED", { fulfillment_type: "PICKUP" });
    const columns = buildColumns(
      board([["PLACED", [delivery, pickup], 240]]),
      { ...NO_FILTER, fulfillment: "PICKUP" },
      NOW,
    );
    expect(columns[0].orders.map((o) => o.id)).toEqual([pickup.id]);
    expect(columns[0].total).toBe(1);
  });

  it("finds an order by what somebody typed", () => {
    const mine = order("PLACED");
    const theirs = order("PLACED", {
      restaurant_id: "r2",
      restaurant: { id: "r2", name: "Luigi's", city: "Surat" },
    } as Partial<LiveOrder>);
    const columns = buildColumns(
      board([["PLACED", [mine, theirs]]]),
      { ...NO_FILTER, query: "  LUIGI " },
      NOW,
    );
    expect(columns[0].orders.map((o) => o.id)).toEqual([theirs.id]);
  });

  it("is four empty columns before anything has loaded", () => {
    const columns = buildColumns(null, NO_FILTER, NOW);
    expect(columns).toHaveLength(4);
    expect(columns.every((c) => c.total === 0 && c.orders.length === 0)).toBe(true);
  });
});

describe("summarise", () => {
  it("adds up what is open and what share of the day is done", () => {
    const columns = buildColumns(
      board([
        ["PLACED", [order("PLACED")]],
        ["ACCEPTED", [order("ACCEPTED")]],
        ["PREPARING", [order("PREPARING")]],
        ["OUT_FOR_DELIVERY", [order("OUT_FOR_DELIVERY")]],
        ["DELIVERED", [order("DELIVERED")], 12],
      ]),
      NO_FILTER,
      NOW,
    );
    expect(summarise(columns)).toEqual({
      new: 1,
      kitchen: 2,
      road: 1,
      done: 12,
      open: 4,
      stale: 0,
      progress: 75,
    });
  });

  it("leaves the backlog out of what is still to finish", () => {
    const columns = buildColumns(
      board([["PLACED", [order("PLACED")], 213, 208]]),
      NO_FILTER,
      NOW,
    );
    expect(summarise(columns)).toMatchObject({ new: 5, open: 5, stale: 208 });
  });

  it("is zero percent on a day with no orders, not a division by zero", () => {
    expect(summarise(buildColumns(null, NO_FILTER, NOW)).progress).toBe(0);
  });
});

describe("restaurantBreakdown", () => {
  it("uses the server's counts, not the cards, and lists the busiest first", () => {
    // One card was sent; the restaurant has 213 new orders.
    const data = board([["PLACED", [order("PLACED")], 213]]);
    data.restaurants = [
      { restaurant_id: "r2", name: "Quiet", city: "Surat", counts: { PREPARING: 1, DELIVERED: 1 } },
      {
        restaurant_id: "r1",
        name: "Bhagwati Bakery",
        city: "Surat",
        counts: { PLACED: 213, ACCEPTED: 2, PREPARING: 3, OUT_FOR_DELIVERY: 1 },
      },
    ];
    const rows = restaurantBreakdown(data);
    expect(rows.map((r) => r.name)).toEqual(["Bhagwati Bakery", "Quiet"]);
    expect(rows[0]).toMatchObject({ new: 213, kitchen: 5, road: 1, done: 0, open: 219 });
    expect(rows[1]).toMatchObject({ new: 0, kitchen: 1, road: 0, done: 1, open: 1 });
  });

  it("takes the backlog out of each figure and reports it once", () => {
    const data = board([]);
    data.restaurants = [
      {
        restaurant_id: "r1",
        name: "Bangkok Bowl",
        city: "Bangkok",
        counts: { PLACED: 208, PREPARING: 7 },
        stale: { PLACED: 208, PREPARING: 6 },
      },
      { restaurant_id: "r2", name: "Bhagwati Bakery", city: "Surat", counts: { PLACED: 2 } },
    ];
    const rows = restaurantBreakdown(data);
    // Two live orders outrank a backlog of 214 with one live order.
    expect(rows.map((r) => r.name)).toEqual(["Bhagwati Bakery", "Bangkok Bowl"]);
    expect(rows[1]).toMatchObject({ new: 0, kitchen: 1, open: 1, stale: 214 });
  });

  it("is empty before anything has loaded", () => {
    expect(restaurantBreakdown(null)).toEqual([]);
  });
});

describe("orderClock", () => {
  it("counts from when the order was placed", () => {
    const clock = orderClock(order("PLACED", { placed_at: minutesAgo(3) }), column("new"), NOW);
    expect(clock).toMatchObject({ label: "3 min", late: false });
  });

  it("marks a new order nobody has accepted as late", () => {
    const clock = orderClock(order("PLACED", { placed_at: minutesAgo(9) }), column("new"), NOW);
    expect(clock.late).toBe(true);
  });

  it("does not call a scheduled order late before its slot", () => {
    // Placed four days ago for a slot two hours from now.
    const scheduled = order("PLACED", {
      schedule_type: "SCHEDULED",
      placed_at: minutesAgo(4 * DAY),
      scheduled_at: minutesAgo(-120),
    });
    expect(orderClock(scheduled, column("new"), NOW)).toMatchObject({
      label: "Due in 2 h",
      late: false,
    });
  });

  it("counts a scheduled order from its slot once that has passed", () => {
    const scheduled = order("PREPARING", {
      schedule_type: "SCHEDULED",
      placed_at: minutesAgo(4 * DAY),
      scheduled_at: minutesAgo(15),
    });
    const clock = orderClock(scheduled, column("kitchen"), NOW);
    expect(clock).toMatchObject({ label: "15 min", late: false });
    expect(clock.help).toContain("time slot");
  });

  it("says how long ago a finished order went out, and is never late", () => {
    const done = order("DELIVERED", { completed_at: minutesAgo(65), placed_at: minutesAgo(300) });
    expect(orderClock(done, column("done"), NOW)).toMatchObject({
      label: "1 h 5 min ago",
      late: false,
    });
  });

  it("explains itself with the threshold it actually used", () => {
    for (const meta of LIVE_COLUMNS) {
      if (meta.lateAfterMinutes === null) continue;
      const waited = order(meta.statuses[0], { placed_at: minutesAgo(meta.lateAfterMinutes + 1) });
      const clock = orderClock(waited, meta, NOW);
      expect(clock.late).toBe(true);
      expect(clock.help).toContain(`${meta.lateAfterMinutes} minutes`);
    }
  });
});

describe("formatDuration", () => {
  it("reads like a person would say it", () => {
    expect(formatDuration(0.4)).toBe("just now");
    expect(formatDuration(59)).toBe("59 min");
    expect(formatDuration(120)).toBe("2 h");
    expect(formatDuration(125)).toBe("2 h 5 min");
    expect(formatDuration(3 * DAY + 5)).toBe("3 d");
  });
});

describe("itemsSummary", () => {
  it("names the first two lines and counts the rest", () => {
    const items = [
      { quantity: 2, item_name_snapshot: "Chocolate Doughnut", size_name_snapshot: null },
      { quantity: 1, item_name_snapshot: "Pizza", size_name_snapshot: "Large" },
      { quantity: 1, item_name_snapshot: "Brown Bread", size_name_snapshot: null },
    ];
    expect(itemsSummary(order("PLACED", { items } as unknown as Partial<LiveOrder>))).toBe(
      "2 × Chocolate Doughnut, 1 × Pizza (Large) +1 more",
    );
  });
});

describe("deliveryLine", () => {
  const rider = {
    state: "IN_TRANSIT",
    rider_name: "Ramesh",
    rider_mobile: "9000000000",
    tracking_url: "https://track.example/abc",
  };

  it("carries the rider and the tracking link for a delivery under way", () => {
    const line = deliveryLine(
      order("OUT_FOR_DELIVERY", { delivery: rider } as unknown as Partial<LiveOrder>),
    );
    expect(line).toMatchObject({
      label: "On the way to the customer",
      tone: "busy",
      riderName: "Ramesh",
      riderPhone: "9000000000",
      trackingUrl: "https://track.example/abc",
    });
  });

  it("says so when no rider has been booked", () => {
    expect(deliveryLine(order("ACCEPTED")).label).toBe("No rider booked yet");
  });

  it("does not talk about riders for a pickup order", () => {
    const line = deliveryLine(order("PREPARING", { fulfillment_type: "PICKUP" }));
    expect(line.label).toBe("Customer collects");
    expect(line.trackingUrl).toBeNull();
  });

  it("warns when a delivery came back, and says what to do", () => {
    const line = deliveryLine(
      order("OUT_FOR_DELIVERY", {
        delivery: { ...rider, state: "FAILED" },
      } as unknown as Partial<LiveOrder>),
    );
    expect(line).toMatchObject({ label: "Could not be delivered", tone: "warn" });
    expect(line.help).toContain("contact the customer");
  });

  it("shows a state nobody has seen before rather than hiding it", () => {
    const line = deliveryLine(
      order("OUT_FOR_DELIVERY", {
        delivery: { ...rider, state: "REROUTED" },
      } as unknown as Partial<LiveOrder>),
    );
    expect(line.label).toBe("REROUTED");
    expect(line.help.length).toBeGreaterThan(0);
  });

  it("explains every state it can show", () => {
    const states = ["PENDING", "ASSIGNED", "PICKED_UP", "IN_TRANSIT", "DELIVERED", "CANCELLED", "FAILED"];
    for (const state of states) {
      const line = deliveryLine(
        order("OUT_FOR_DELIVERY", {
          delivery: { ...rider, state },
        } as unknown as Partial<LiveOrder>),
      );
      expect(line.label).not.toBe(state);
      expect(line.help.length).toBeGreaterThan(20);
    }
  });
});

describe("safeTrackingUrl", () => {
  it("lets a web address through", () => {
    expect(safeTrackingUrl("https://track.example/abc")).toBe("https://track.example/abc");
  });

  it("refuses anything a browser would run or cannot open", () => {
    expect(safeTrackingUrl("javascript:alert(1)")).toBeNull();
    expect(safeTrackingUrl("data:text/html,x")).toBeNull();
    expect(safeTrackingUrl("PIDGE-12345")).toBeNull();
    expect(safeTrackingUrl("")).toBeNull();
    expect(safeTrackingUrl(null)).toBeNull();
  });
});

describe("startOfToday", () => {
  it("is the viewer's own midnight", () => {
    const start = startOfToday(new Date(2026, 9, 5, 18, 30));
    expect([start.getFullYear(), start.getMonth(), start.getDate()]).toEqual([2026, 9, 5]);
    expect([start.getHours(), start.getMinutes()]).toEqual([0, 0]);
  });
});

describe("the words on the board", () => {
  it("answers what, who and what-to-do for every column, for both roles", () => {
    for (const meta of LIVE_COLUMNS) {
      for (const role of ["ADMIN", "OWNER"] as const) {
        const help = columnHelp(meta.key, role);
        expect(help.what.length).toBeGreaterThan(20);
        expect(help.who.length).toBeGreaterThan(5);
        expect(help.action.length).toBeGreaterThan(20);
      }
    }
  });

  it("quotes the same late threshold the cards use", () => {
    for (const meta of LIVE_COLUMNS) {
      if (meta.lateAfterMinutes === null) continue;
      for (const role of ["ADMIN", "OWNER"] as const) {
        expect(columnHelp(meta.key, role).action).toContain(`${meta.lateAfterMinutes} minutes`);
      }
    }
  });

  it("does not tell an admin to press a button an admin does not have", () => {
    // The panel gives an admin no way to accept an order; their move is a call.
    expect(columnHelp("new", "ADMIN").action).not.toMatch(/accept it/i);
    expect(columnHelp("new", "ADMIN").action).toMatch(/call the restaurant/i);
    expect(columnHelp("new", "OWNER").action).toMatch(/accept it/i);
  });

  it("speaks to an owner about their own kitchen", () => {
    expect(columnHelp("kitchen", "OWNER").who).toBe("Your kitchen.");
    expect(columnHelp("kitchen", "ADMIN").who).toBe("The restaurant's kitchen.");
  });

  it("has an explanation for every part of a card and every fixed tip", () => {
    expect(CARD_HELP.length).toBeGreaterThanOrEqual(5);
    for (const entry of CARD_HELP) {
      expect(entry.term.length).toBeGreaterThan(0);
      expect(entry.meaning.length).toBeGreaterThan(20);
    }
    for (const entry of Object.values(STATIC_HELP)) {
      expect(entry.what.length).toBeGreaterThan(20);
      expect(entry.action.length).toBeGreaterThan(20);
    }
  });
});

describe("nextAction", () => {
  it("offers the one step an order can take next", () => {
    expect(nextAction(order("PLACED"))?.to).toBe("ACCEPTED");
    expect(nextAction(order("ACCEPTED"))?.to).toBe("PREPARING");
    expect(nextAction(order("PREPARING"))?.to).toBe("OUT_FOR_DELIVERY");
    expect(nextAction(order("OUT_FOR_DELIVERY"))?.to).toBe("DELIVERED");
  });

  it("offers nothing for an order that is finished", () => {
    expect(nextAction(order("DELIVERED"))).toBeNull();
    expect(nextAction(order("CANCELLED"))).toBeNull();
  });

  it("offers nothing until the money is committed", () => {
    // The server refuses to advance an unpaid order. A button that can only
    // answer with an error is worse than no button.
    expect(nextAction(order("PLACED", { payment_status: "PENDING" }))).toBeNull();
    expect(nextAction(order("PLACED", { payment_status: "COD" }))?.to).toBe("ACCEPTED");
  });

  it("says a rider will be booked before somebody accepts a delivery", () => {
    const delivery = nextAction(order("PLACED", { fulfillment_type: "DELIVERY" }));
    const pickup = nextAction(order("PLACED", { fulfillment_type: "PICKUP" }));
    expect(delivery?.help).toMatch(/rider/i);
    expect(pickup?.help).not.toMatch(/rider/i);
  });

  it("uses the counter's words for a pickup and the rider's for a delivery", () => {
    expect(nextAction(order("PREPARING", { fulfillment_type: "DELIVERY" }))?.label).toMatch(/rider/i);
    expect(nextAction(order("PREPARING", { fulfillment_type: "PICKUP" }))?.label).toMatch(/collect/i);
  });
});

describe("etaText", () => {
  const base = { pickup_eta: "2026-10-05T11:30:00Z", drop_eta: "2026-10-05T11:45:00Z" };
  const delivery = (state: string) => ({ ...base, state }) as unknown as Parameters<typeof etaText>[0];

  it("points at the restaurant until the food is collected, then at the door", () => {
    expect(etaText(delivery("ASSIGNED"))).toMatch(/^Rider due /);
    expect(etaText(delivery("IN_TRANSIT"))).toMatch(/^Deliver by /);
  });

  it("says nothing once the trip is over", () => {
    expect(etaText(delivery("DELIVERED"))).toBe("");
  });
});

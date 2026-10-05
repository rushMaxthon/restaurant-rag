/**
 * The rules behind the live orders board, kept out of the page so they can be
 * tested without rendering one.
 *
 * The server sends five stages, one per order status. A person running a
 * restaurant thinks in four: it is new, it is in the kitchen, it is on the
 * road, it is done. ACCEPTED and PREPARING are both "in the kitchen" — the
 * difference is a tap on the kitchen tablet, not a place the food is.
 *
 * The words that explain the board live here too (`columnHelp`, `CARD_HELP`,
 * `deliveryHelp`). They are rules as much as the thresholds are: a tooltip
 * that says "late after 5 minutes" has to be reading the same 5 the card is.
 */
import type {
  LiveOrder,
  LiveOrdersBoard,
  OrderFulfillmentType,
  OrderStatus,
  UserRole,
} from "../types/app";

export type LiveColumnKey = "new" | "kitchen" | "road" | "done";

export interface LiveColumnMeta {
  key: LiveColumnKey;
  title: string;
  hint: string;
  statuses: OrderStatus[];
  /** Minutes an order may sit here before the card says it is late. */
  lateAfterMinutes: number | null;
}

/**
 * The four columns, in the order food moves through them.
 *
 * The late thresholds are deliberately generous. A board that marks half its
 * cards red on an ordinary evening teaches people to ignore red.
 */
export const LIVE_COLUMNS: LiveColumnMeta[] = [
  {
    key: "new",
    title: "New",
    hint: "Waiting to be accepted",
    statuses: ["PLACED"],
    lateAfterMinutes: 5,
  },
  {
    key: "kitchen",
    title: "In the kitchen",
    hint: "Accepted and being prepared",
    statuses: ["ACCEPTED", "PREPARING"],
    lateAfterMinutes: 40,
  },
  {
    key: "road",
    title: "On the way",
    hint: "Out for delivery or ready to collect",
    statuses: ["OUT_FOR_DELIVERY"],
    lateAfterMinutes: 60,
  },
  {
    key: "done",
    title: "Done today",
    hint: "Delivered or collected",
    statuses: ["DELIVERED"],
    lateAfterMinutes: null,
  },
];

/** Used only until the server has said where it drew the line. */
const DEFAULT_STALE_AFTER_MINUTES = 24 * 60;

export interface LiveFilter {
  fulfillment: "ALL" | OrderFulfillmentType;
  query: string;
}

export const NO_FILTER: LiveFilter = { fulfillment: "ALL", query: "" };

export function isFiltering(filter: LiveFilter): boolean {
  return filter.fulfillment !== "ALL" || filter.query.trim() !== "";
}

export function matchesFilter(order: LiveOrder, filter: LiveFilter): boolean {
  if (filter.fulfillment !== "ALL" && order.fulfillment_type !== filter.fulfillment) {
    return false;
  }
  const needle = filter.query.trim().toLowerCase();
  if (!needle) {
    return true;
  }
  return [
    order.id,
    order.customer.full_name,
    order.contact_name ?? "",
    order.restaurant.name,
    order.restaurant_location.branch_name,
    order.delivery?.rider_name ?? "",
  ].some((value) => value.toLowerCase().includes(needle));
}

/**
 * When this order started needing attention.
 *
 * For an order wanted now, that is when it was placed. For a scheduled one it
 * is the slot the customer chose: an order placed on Monday for Friday night
 * has not been waiting four days.
 */
export function waitingSince(order: LiveOrder): Date {
  return new Date(order.schedule_type === "SCHEDULED" ? order.scheduled_at : order.placed_at);
}

function waitedMinutes(order: LiveOrder, now: Date): number {
  return (now.getTime() - waitingSince(order).getTime()) / 60000;
}

export interface LiveColumn extends LiveColumnMeta {
  /** Tonight's work, the one that has waited longest first. */
  orders: LiveOrder[];
  /** How many orders that is. */
  total: number;
  /**
   * Open orders that have waited longer than a day. Still open, and almost
   * certainly never going to move: kept out of `orders` so they cannot bury
   * the ones somebody is waiting for.
   */
  stale: LiveOrder[];
  staleTotal: number;
  /**
   * True when the server holds more orders in this column than it sent. The
   * counts are still right; the lists are the newest hundred.
   */
  truncated: boolean;
}

/**
 * The board as four columns.
 *
 * Unfiltered, the counts are the server's — true even when the lists were
 * capped. Filtered, they are the number of cards that match, because that is
 * the only thing a client can count.
 */
export function buildColumns(
  board: LiveOrdersBoard | null,
  filter: LiveFilter,
  now: Date,
): LiveColumn[] {
  const filtering = isFiltering(filter);
  const staleAfter = board?.stale_after_minutes ?? DEFAULT_STALE_AFTER_MINUTES;
  return LIVE_COLUMNS.map((meta) => {
    const stages = (board?.stages ?? []).filter((stage) => meta.statuses.includes(stage.status));
    const all = stages.flatMap((stage) => stage.orders);
    const serverTotal = stages.reduce((sum, stage) => sum + stage.total, 0);
    const serverStale = stages.reduce((sum, stage) => sum + (stage.stale_total ?? 0), 0);
    const matching = filtering ? all.filter((order) => matchesFilter(order, filter)) : all;

    if (meta.key === "done") {
      return {
        ...meta,
        orders: matching,
        total: filtering ? matching.length : serverTotal,
        stale: [],
        staleTotal: 0,
        truncated: serverTotal > all.length,
      };
    }

    const orders: LiveOrder[] = [];
    const stale: LiveOrder[] = [];
    for (const order of matching) {
      (waitedMinutes(order, now) >= staleAfter ? stale : orders).push(order);
    }
    // Two statuses share the kitchen column and each arrives newest-first.
    // Tonight's work reads oldest-first: the longest wait is the one to see.
    orders.sort((a, b) => waitingSince(a).getTime() - waitingSince(b).getTime());
    stale.sort((a, b) => waitingSince(b).getTime() - waitingSince(a).getTime());
    return {
      ...meta,
      orders,
      total: filtering ? orders.length : Math.max(serverTotal - serverStale, orders.length),
      stale,
      staleTotal: filtering ? stale.length : Math.max(serverStale, stale.length),
      truncated: serverTotal > all.length,
    };
  });
}

export interface LiveSummary {
  new: number;
  kitchen: number;
  road: number;
  done: number;
  /** Everything not finished yet, backlog aside. */
  open: number;
  /** Open for more than a day, across every column. */
  stale: number;
  /** Done as a share of everything seen today, 0-100. */
  progress: number;
}

export function summarise(columns: LiveColumn[]): LiveSummary {
  const count = (key: LiveColumnKey) => columns.find((column) => column.key === key)?.total ?? 0;
  const summary = {
    new: count("new"),
    kitchen: count("kitchen"),
    road: count("road"),
    done: count("done"),
  };
  const open = summary.new + summary.kitchen + summary.road;
  const all = open + summary.done;
  return {
    ...summary,
    open,
    stale: columns.reduce((sum, column) => sum + column.staleTotal, 0),
    progress: all === 0 ? 0 : Math.round((summary.done / all) * 100),
  };
}

export interface RestaurantLoad {
  restaurantId: string;
  name: string;
  city: string;
  new: number;
  kitchen: number;
  road: number;
  done: number;
  /** Not finished yet, backlog aside. */
  open: number;
  /** Open for more than a day. */
  stale: number;
}

/**
 * Who has what, for an admin looking at every restaurant at once.
 *
 * The server counts these, because the cards are capped: a restaurant with
 * 213 new orders read as 99 when the figure was added up from the hundred
 * cards that were sent. Backlog is taken out of each figure and shown as its
 * own number, the same way the columns do it. Busiest first — most open
 * orders, then most waiting to be accepted, because an unaccepted order is
 * the one a customer is watching.
 */
export function restaurantBreakdown(board: LiveOrdersBoard | null): RestaurantLoad[] {
  const loads = (board?.restaurants ?? []).map((entry) => {
    const load: RestaurantLoad = {
      restaurantId: entry.restaurant_id,
      name: entry.name,
      city: entry.city,
      new: 0,
      kitchen: 0,
      road: 0,
      done: 0,
      open: 0,
      stale: 0,
    };
    for (const column of LIVE_COLUMNS) {
      for (const status of column.statuses) {
        const stale = column.key === "done" ? 0 : (entry.stale?.[status] ?? 0);
        load[column.key] += Math.max((entry.counts[status] ?? 0) - stale, 0);
        load.stale += stale;
      }
    }
    load.open = load.new + load.kitchen + load.road;
    return load;
  });
  return loads.sort(
    (a, b) =>
      b.open - a.open ||
      b.new - a.new ||
      b.done - a.done ||
      b.stale - a.stale ||
      a.name.localeCompare(b.name),
  );
}

export interface OrderClock {
  /** What the card shows: "12 min", "Due in 2 h", "Done 5 min ago". */
  label: string;
  late: boolean;
  /** The sentence behind the badge, for a tooltip. */
  help: string;
}

export function formatDuration(minutes: number): string {
  const whole = Math.max(0, Math.floor(minutes));
  if (whole < 1) return "just now";
  if (whole < 60) return `${whole} min`;
  const hours = Math.floor(whole / 60);
  if (hours < 24) {
    const rest = whole % 60;
    return rest === 0 ? `${hours} h` : `${hours} h ${rest} min`;
  }
  const days = Math.floor(hours / 24);
  return `${days} d`;
}

export function orderClock(order: LiveOrder, column: LiveColumnMeta, now: Date): OrderClock {
  if (column.key === "done") {
    const finished = new Date(order.completed_at ?? order.updated_at);
    const minutes = (now.getTime() - finished.getTime()) / 60000;
    return {
      label: minutes < 1 ? "Just now" : `${formatDuration(minutes)} ago`,
      late: false,
      help: "How long ago this order was delivered or collected.",
    };
  }
  const scheduled = order.schedule_type === "SCHEDULED";
  const minutes = waitedMinutes(order, now);
  if (minutes < 0) {
    // A scheduled order whose slot has not come. Nothing is late yet.
    return {
      label: `Due in ${formatDuration(-minutes)}`,
      late: false,
      help: "The customer booked a time slot. This is how long until it is due, so it is not late.",
    };
  }
  const since = scheduled ? "the time slot the customer booked" : "the order was placed";
  const limit = column.lateAfterMinutes;
  const late = limit !== null && minutes >= limit;
  return {
    label: minutes < 1 ? "Just now" : formatDuration(minutes),
    late,
    help:
      limit === null
        ? `Time since ${since}.`
        : late
          ? `Time since ${since}. Late: orders in "${column.title}" should move on within ${limit} minutes.`
          : `Time since ${since}. It turns red if it is still in "${column.title}" after ${limit} minutes.`,
  };
}

/** "2 × Chocolate Doughnut, 1 × Brown Bread +1 more". */
export function itemsSummary(order: LiveOrder, max = 2): string {
  const shown = order.items.slice(0, max).map((item) => {
    const size = item.size_name_snapshot ? ` (${item.size_name_snapshot})` : "";
    return `${item.quantity} × ${item.item_name_snapshot}${size}`;
  });
  const rest = order.items.length - shown.length;
  return rest > 0 ? `${shown.join(", ")} +${rest} more` : shown.join(", ");
}

export type DeliveryTone = "ok" | "busy" | "warn" | "idle";

export interface DeliveryLine {
  label: string;
  tone: DeliveryTone;
  /** What that state means and what, if anything, to do about it. */
  help: string;
  riderName: string;
  riderPhone: string;
  /** Null unless it is a link a browser should open. */
  trackingUrl: string | null;
}

const DELIVERY_STATES: Record<string, { label: string; tone: DeliveryTone; help: string }> = {
  PENDING: {
    label: "Finding a rider",
    tone: "busy",
    help: "The delivery partner has the request and is assigning a rider. Nothing to do yet.",
  },
  ASSIGNED: {
    label: "Rider heading to the kitchen",
    tone: "busy",
    help: "A rider is on the way to collect the food. Have the order packed and ready.",
  },
  PICKED_UP: {
    label: "Rider has the food",
    tone: "busy",
    help: "The rider collected the order from the restaurant.",
  },
  IN_TRANSIT: {
    label: "On the way to the customer",
    tone: "busy",
    help: "The rider is travelling to the customer. Use Track to see where they are.",
  },
  DELIVERED: {
    label: "Delivered",
    tone: "ok",
    help: "The rider handed the order to the customer.",
  },
  CANCELLED: {
    label: "Delivery called off",
    tone: "warn",
    help: "The delivery was cancelled before the food was collected. Open the order to see why and arrange another rider.",
  },
  FAILED: {
    label: "Could not be delivered",
    tone: "warn",
    help: "The rider could not hand the order over, for example nobody was home. Open the order and contact the customer.",
  },
};

/**
 * A tracking link is the courier's string, stored as it arrived. Only an
 * http(s) address is ever put in an `href`; anything else — empty, a bare
 * id, a `javascript:` URL — is not a link.
 */
export interface NextAction {
  /** The status the order moves to. */
  to: OrderStatus;
  /** The button, in the words a kitchen uses. */
  label: string;
  /** What pressing it sets off, for the tooltip and the confirm step. */
  help: string;
}

/**
 * The one step this order can take next, or null when there is none to offer.
 *
 * The board could only watch: to accept an order somebody had to open it,
 * press the button there and come back, once per order, on the screen whose
 * whole job is the queue. This is the same step, on the card.
 *
 * Null for an order whose payment is not committed. The server refuses to
 * advance one, so the button could only ever answer with an error.
 *
 * The backend is the rule - `PATCH /orders/{id}/status` re-checks the scope,
 * the payment and the order of the steps. This decides what to OFFER.
 */
export function nextAction(order: LiveOrder): NextAction | null {
  const settled = order.payment_status === "PAID" || order.payment_status === "COD";
  if (!settled) return null;
  const isDelivery = order.fulfillment_type === "DELIVERY";
  switch (order.status) {
    case "PLACED":
      return {
        to: "ACCEPTED",
        label: "Accept order",
        help: isDelivery
          ? "Confirms the order to the customer and books a rider straight away."
          : "Confirms the order to the customer and sends it to the kitchen.",
      };
    case "ACCEPTED":
      return {
        to: "PREPARING",
        label: "Start preparing",
        help: "Tells the customer the kitchen has started on their order.",
      };
    case "PREPARING":
      return {
        to: "OUT_FOR_DELIVERY",
        label: isDelivery ? "Hand to the rider" : "Ready to collect",
        help: isDelivery
          ? "Tells the customer their order has left the kitchen."
          : "Tells the customer their order is ready at the counter.",
      };
    case "OUT_FOR_DELIVERY":
      return {
        to: "DELIVERED",
        label: "Mark delivered",
        help: "Closes the order. It moves to Done today.",
      };
    default:
      return null;
  }
}

export function safeTrackingUrl(value: string | null | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

/** What the card says about getting the food to the customer. */
export function deliveryLine(order: LiveOrder): DeliveryLine {
  const none = { riderName: "", riderPhone: "", trackingUrl: null };
  if (order.fulfillment_type !== "DELIVERY") {
    return order.status === "DELIVERED"
      ? {
          label: "Collected by the customer",
          tone: "idle",
          help: "A pickup order. The customer collected it from the restaurant.",
          ...none,
        }
      : {
          label: "Customer collects",
          tone: "idle",
          help: "A pickup order. No rider is involved: the customer comes to the restaurant for it.",
          ...none,
        };
  }
  const delivery = order.delivery;
  if (!delivery) {
    return order.status === "DELIVERED"
      ? { label: "Delivered", tone: "ok", help: "This order reached the customer.", ...none }
      : {
          label: "No rider booked yet",
          tone: "idle",
          help: "A delivery order with no rider requested yet. A rider is booked once the restaurant accepts and prepares the order.",
          ...none,
        };
  }
  const state = DELIVERY_STATES[delivery.state] ?? {
    label: delivery.state,
    tone: "busy" as const,
    help: "The delivery partner reported a status this screen has no description for. Open the order for details.",
  };
  return {
    label: state.label,
    tone: state.tone,
    help: state.help,
    riderName: delivery.rider_name,
    riderPhone: delivery.rider_mobile,
    trackingUrl: safeTrackingUrl(delivery.tracking_url),
  };
}

/** The operator's own midnight, which is what "today" means on the board. */
export function startOfToday(now: Date): Date {
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

/* -------------------------------------------------------------------------
 * The words. Three questions for every part of the board, because those are
 * the three a new person asks: what is this, whose job is it, what do I do.
 * ---------------------------------------------------------------------- */

export interface HelpEntry {
  /** What this is. */
  what: string;
  /** Who is responsible for moving it on. */
  who: string;
  /** What the person reading should do. */
  action: string;
}

/**
 * A column, explained to the person looking at it.
 *
 * An owner works their own orders. The platform's admin watches other
 * people's kitchens: this panel gives an admin no accept button (see
 * `OrdersPage`), so telling one to "accept it" would be telling them to press
 * something they do not have. Their action is a phone call.
 */
export function columnHelp(key: LiveColumnKey, role: UserRole): HelpEntry {
  const owner = role !== "ADMIN";
  const late = LIVE_COLUMNS.find((column) => column.key === key)?.lateAfterMinutes;
  switch (key) {
    case "new":
      return {
        what: "Orders the customer has paid for that the restaurant has not accepted yet.",
        who: owner ? "Your kitchen." : "The restaurant's kitchen.",
        action: owner
          ? `Open the order and accept it, or accept it on the kitchen board. A card turns red after ${late} minutes.`
          : `The restaurant accepts its own orders. If a card turns red (after ${late} minutes), call the restaurant.`,
      };
    case "kitchen":
      return {
        what: "Orders the restaurant accepted and is cooking or packing.",
        who: owner ? "Your kitchen." : "The restaurant's kitchen.",
        action: owner
          ? `Nothing while it is on time. A card turns red after ${late} minutes: check with the kitchen.`
          : `Nothing while it is on time. If a card turns red (after ${late} minutes), check with the restaurant.`,
      };
    case "road":
      return {
        what: "Food that has left the kitchen: with a rider, or packed and waiting for the customer to collect.",
        who: "The rider, or the customer for a pickup order.",
        action: `Press Track to see where the rider is, or the phone button to call them. A card turns red after ${late} minutes.`,
      };
    case "done":
      return {
        what: "Orders delivered or collected since midnight today.",
        who: "Nobody. These are finished.",
        action: "Nothing to do. Open one to see its bill and history.",
      };
  }
}

/** The small parts of a card, in the order they appear on it. */
export const CARD_HELP: Array<{ term: string; meaning: string }> = [
  {
    term: "Time badge",
    meaning:
      "How long the order has been waiting. Red with the word late means it has been in its column too long.",
  },
  {
    term: "Paid / Cash on delivery",
    meaning:
      "Green Paid means the money is already collected online. Amber means the customer pays in cash when the order arrives.",
  },
  {
    term: "Delivery / Pickup",
    meaning: "Delivery goes out with a rider. Pickup is collected by the customer at the restaurant.",
  },
  {
    term: "Day and time tag",
    meaning: "The customer booked this order for a later time slot instead of right away.",
  },
  {
    term: "Rider strip",
    meaning:
      "The bottom of each card shows what the rider is doing and their name. It turns red if the delivery failed or was called off.",
  },
  {
    term: "Track and phone buttons",
    meaning:
      "Track opens the delivery partner's live map in a new tab. The phone button calls the rider.",
  },
];

export const STATIC_HELP = {
  progress: {
    what: "How much of today's work is finished: orders done, out of done plus still open.",
    who: "Everyone with an order in the first three columns.",
    action: "Watch the Still to finish number go down. It only reaches zero when every order is delivered or collected.",
  },
  restaurants: {
    what: "Each restaurant with orders right now, busiest first, with how many are new, cooking and on the way.",
    who: "This row is only shown to the platform admin.",
    action: "Click a restaurant to see only its orders. Click it again, or All restaurants, to go back.",
  },
  stale: {
    what: "Orders that have been open for more than a day. They were never accepted, finished or cancelled.",
    who: "The restaurant that received them.",
    action: "They are kept apart so they do not hide today's orders. Open one to see what happened to it.",
  },
} satisfies Record<string, HelpEntry>;

import type {
  FulfillmentType,
  KitchenOrder,
  LiveStatus,
  OrderLine,
  OrderStatus,
} from '@/types/app';

// The linear flow, ORDER_STATUS_FLOW in backend/app/services/orders.py. The
// server refuses anything but the single legal next step; this only lets the
// button name that step before it is pressed.
const FLOW: Partial<Record<OrderStatus, OrderStatus>> = {
  PLACED: 'ACCEPTED',
  ACCEPTED: 'PREPARING',
  PREPARING: 'OUT_FOR_DELIVERY',
  OUT_FOR_DELIVERY: 'DELIVERED',
};

export const nextStatus = (status: OrderStatus): OrderStatus | null => FLOW[status] ?? null;

export const isLiveStatus = (status: OrderStatus): status is LiveStatus =>
  status === 'PLACED' ||
  status === 'ACCEPTED' ||
  status === 'PREPARING' ||
  status === 'OUT_FOR_DELIVERY';

// The button's verb, for the person pressing it. Pickup orders also pass
// through OUT_FOR_DELIVERY (one flow for both), so naming the status would
// tell a cook bagging a collection order that it is "out for delivery".
export const advanceLabel = (
  order: Pick<KitchenOrder, 'status' | 'fulfillment_type'>,
): string | null => {
  const isDelivery = order.fulfillment_type === 'DELIVERY';
  switch (order.status) {
    case 'PLACED':
      return 'Accept';
    case 'ACCEPTED':
      return 'Start cooking';
    case 'PREPARING':
      return isDelivery ? 'Hand to rider' : 'Ready for pickup';
    case 'OUT_FOR_DELIVERY':
      return isDelivery ? 'Delivered' : 'Collected';
    default:
      return null;
  }
};

// What an order's stage is called on this board, per fulfillment type.
export const stageLabel = (status: OrderStatus, fulfillment: FulfillmentType): string => {
  switch (status) {
    case 'PAYMENT_PENDING':
      return 'Awaiting payment';
    case 'PLACED':
      return 'New';
    case 'ACCEPTED':
      return 'Accepted';
    case 'PREPARING':
      return 'Cooking';
    case 'OUT_FOR_DELIVERY':
      return fulfillment === 'DELIVERY' ? 'With rider' : 'Ready for pickup';
    case 'DELIVERED':
      return fulfillment === 'DELIVERY' ? 'Delivered' : 'Collected';
    case 'CANCELLED':
      return 'Cancelled';
  }
};

// How far back the live queue reaches, by when an order is DUE. Without a
// bound the board grows forever — a branch once carried 206 "New" tickets,
// 178 over a week old, and orders past the page limit never appeared. 24h
// covers an overnight pass and a late ticket without carrying yesterday's
// abandoned work onto today's board. Nothing outside it is changed; it is
// just not this service's work.
export const LIVE_WINDOW_HOURS = 24;

export const liveWindowStart = (now: Date = new Date()): string =>
  new Date(now.getTime() - LIVE_WINDOW_HOURS * 3600000).toISOString();

// The page arrives newest-first (so the limit drops the oldest); a kitchen
// works oldest-first, FIFO at the pass.
export const inServiceOrder = <T>(rows: readonly T[]): T[] => [...rows].reverse();

// Tickets matching a column that did not fit in the page — shown, never
// swallowed.
export const hiddenCount = (total: number, shown: number): number => Math.max(0, total - shown);

// Whole minutes this ticket has been waiting. A SCHEDULED order starts
// waiting at its booked time: counting from when it was placed would show a
// lunch order booked at 9am as two hours late before anyone should touch it.
export const waitingMinutes = (
  order: Pick<KitchenOrder, 'schedule_type' | 'scheduled_at' | 'placed_at'>,
  now: Date = new Date(),
): number => {
  const from =
    order.schedule_type === 'SCHEDULED' && order.scheduled_at
      ? new Date(order.scheduled_at)
      : new Date(order.placed_at);
  if (Number.isNaN(from.getTime())) {
    return 0;
  }
  const elapsed = Math.floor((now.getTime() - from.getTime()) / 60000);
  // Due later is "not yet", never "-38m".
  return elapsed > 0 ? elapsed : 0;
};

// Minutes until a scheduled order is due, or 0 once it is (or for ASAP).
export const minutesUntilDue = (
  order: Pick<KitchenOrder, 'schedule_type' | 'scheduled_at'>,
  now: Date = new Date(),
): number => {
  if (order.schedule_type !== 'SCHEDULED' || !order.scheduled_at) {
    return 0;
  }
  const due = new Date(order.scheduled_at);
  if (Number.isNaN(due.getTime())) {
    return 0;
  }
  return Math.max(0, Math.ceil((due.getTime() - now.getTime()) / 60000));
};

// A wait as a kitchen says it. Minutes under an hour — the range a cook works
// in — and never a five-figure minute count: a forgotten order once read
// "132388m", which is unreadable and somehow less alarming than "92d".
export const formatWait = (minutes: number): string => {
  if (minutes <= 0) {
    return 'now';
  }
  if (minutes < 60) {
    return `${minutes}m`;
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    const rest = minutes % 60;
    return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`;
  }
  const days = Math.floor(hours / 24);
  return days < 7 ? `${days}d ${hours % 24}h` : `${days}d`;
};

// Minutes before a ticket in each stage counts as late. Later stages get
// less patience.
const LATE_AFTER: Record<LiveStatus, number> = {
  PLACED: 5,
  ACCEPTED: 10,
  PREPARING: 25,
  OUT_FOR_DELIVERY: 45,
};

// Three states, not a boolean: a board where everything is white or red has
// no way to say "this one next", which is what a cook glances up to learn.
export type Urgency = 'calm' | 'due' | 'late';

export const urgencyOf = (order: KitchenOrder, now: Date = new Date()): Urgency => {
  if (!isLiveStatus(order.status)) {
    return 'calm';
  }
  const limit = LATE_AFTER[order.status];
  const waited = waitingMinutes(order, now);
  if (waited >= limit) {
    return 'late';
  }
  return waited >= limit * 0.6 ? 'due' : 'calm';
};

// Which tickets appeared since the previous load. Returned, not acted on, so
// the caller can stay silent on the very first load — when every ticket is
// "new" and nobody wants a fanfare for a board they just opened.
export const newlyArrived = (
  previousIds: ReadonlySet<string>,
  current: readonly KitchenOrder[],
): string[] => current.filter(order => !previousIds.has(order.id)).map(order => order.id);

// The code a kitchen calls an order by: the same first eight characters the
// customer's receipt prints, so a number read down the phone matches.
export const orderCode = (order: Pick<KitchenOrder, 'id'>): string =>
  `#${order.id.slice(0, 8).toUpperCase()}`;

// A time of day in the device's locale, or '' for a missing one.
export const clockTime = (iso: string | null | undefined): string => {
  if (!iso) {
    return '';
  }
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) {
    return '';
  }
  return at.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
};

// The name the customer gave at checkout, else their account's.
export const customerName = (order: KitchenOrder): string | null =>
  order.contact_name?.trim() || order.customer?.full_name?.trim() || null;

export const isScheduled = (order: KitchenOrder): boolean =>
  order.schedule_type === 'SCHEDULED' && Boolean(order.scheduled_at);

// The one payment fact a kitchen acts on at handover: whether cash is owed.
export type PayKind = 'COD' | 'PAID' | 'UNPAID';

export const payKind = (status: string): PayKind => {
  const upper = status.toUpperCase();
  if (upper === 'COD') {
    return 'COD';
  }
  return upper === 'PAID' || upper === 'REFUNDED' ? 'PAID' : 'UNPAID';
};

export const payLabel = (status: string): string => {
  switch (status.toUpperCase()) {
    case 'COD':
      return 'Collect cash';
    case 'PAID':
      return 'Paid';
    case 'REFUNDED':
      return 'Refunded';
    default:
      return 'Unpaid';
  }
};

export type Half = 'LEFT' | 'RIGHT';

export interface ModifierRow {
  label: string | null;
  half: Half | null;
  text: string;
}

// How a dish differs from the menu default, one row per group, in the order
// the customer built it: "Crust: Thin", "Toppings: Olives · Cheese ×2".
//
// A half-and-half group gets a row PER HALF — "Pepperoni (left)" buried
// mid-sentence is how the wrong side gets topped. Should a group ever carry
// whole AND half options, every row prints: checkout enforces the rule, and
// this screen's job is to show what was ordered, never to drop part of it.
// Nothing is dropped for a missing key either; an unlabelled option prints.
export const lineModifiers = (
  line: Pick<OrderLine, 'size_name_snapshot' | 'selected_options_snapshot'>,
): ModifierRow[] => {
  const rows: ModifierRow[] = [];
  const size = line.size_name_snapshot?.trim();
  if (size) {
    rows.push({ label: 'Size', half: null, text: size });
  }

  const groups = new Map<
    string,
    { title: string | null; whole: string[]; LEFT: string[]; RIGHT: string[] }
  >();
  for (const option of line.selected_options_snapshot ?? []) {
    const title = option.group_title?.trim() || null;
    const key = option.group_id || title || '';
    let group = groups.get(key);
    if (!group) {
      group = { title, whole: [], LEFT: [], RIGHT: [] };
      groups.set(key, group);
    }
    const count = option.quantity && option.quantity > 1 ? ` ×${option.quantity}` : '';
    const name = `${option.option_name?.trim() || 'Option'}${count}`;
    const portion = option.portion?.toUpperCase();
    if (portion === 'LEFT' || portion === 'RIGHT') {
      group[portion].push(name);
    } else {
      group.whole.push(name);
    }
  }

  for (const group of groups.values()) {
    if (group.whole.length) {
      rows.push({ label: group.title, half: null, text: group.whole.join(' · ') });
    }
    for (const half of ['LEFT', 'RIGHT'] as const) {
      if (group[half].length) {
        rows.push({ label: group.title, half, text: group[half].join(' · ') });
      }
    }
  }
  return rows;
};

// "3 items", counted by quantity — that is what was cooked.
export const itemCount = (items: readonly { quantity: number }[]): string => {
  const count = items.reduce((sum, line) => sum + line.quantity, 0);
  return `${count} ${count === 1 ? 'item' : 'items'}`;
};

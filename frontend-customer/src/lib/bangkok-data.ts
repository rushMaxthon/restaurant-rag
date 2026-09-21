export type Money = string;
export type MenuSize = {
  id: string;
  name: string;
  price: Money;
  is_active: boolean;
  /** Groups that exist only for this size. See lib/customization.ts. */
  customization_groups?: CustomizationGroup[];
};
export type CustomizationOption = {
  id: string;
  name: string;
  extra_price: Money;
  is_countable: boolean;
  /**
   * The API has always sent this; the type simply omitted it, so an option the
   * owner had switched off was still rendered and still selectable.
   */
  is_active: boolean;
};
export type CustomizationGroup = {
  id: string;
  /**
   * Set when the group belongs to ONE size rather than the whole item.
   *
   * Also omitted from this type before, so every size-scoped group was shown
   * against every size — which is what made groups look duplicated.
   */
  menu_item_size_id?: string | null;
  title: string;
  selection_type: "SINGLE" | "MULTI";
  is_required: boolean;
  min_selection: number;
  max_selection: number;
  /**
   * Whether the kitchen can put these options on half the item.
   *
   * Half-and-half pizza: pepperoni one side, mushroom the other. Off for
   * almost every group — a spice level or a crust has no halves — so the
   * portion control only appears where the owner said it can.
   */
  supports_halves?: boolean;
  is_active: boolean;
  options: CustomizationOption[];
};
export type MenuItem = {
  id: string;
  restaurant_id: string;
  restaurant_location_id: string;
  name: string;
  category: string;
  cuisine_type: string;
  /**
   * Null far more often than not — 720 of one restaurant's 816 rows — and the
   * column has always been nullable. This said `string`, so
   * `description.toLowerCase()` in the menu search typechecked, shipped, and
   * threw on the first dish without one: the whole grid came down and the
   * customer got the error boundary's empty page for typing a letter.
   */
  description: string | null;
  price: Money;
  is_veg: boolean;
  is_available: boolean;
  is_bestseller: boolean;
  image_url: string | null;
  rating: Money | null;
  rating_count: number;
  is_new: boolean;
  is_favorite: boolean;
  has_sizes: boolean;
  has_customizations: boolean;
  sizes: MenuSize[];
  customization_groups: CustomizationGroup[];
};
export type LocationDayOfWeek =
  "MONDAY" | "TUESDAY" | "WEDNESDAY" | "THURSDAY" | "FRIDAY" | "SATURDAY" | "SUNDAY";

/** One opening window, e.g. Monday delivery 11:00-21:30. Times are "HH:MM:SS". */
export type FulfillmentSlot = {
  id: string;
  day_of_week: LocationDayOfWeek;
  fulfillment_type: "DELIVERY" | "PICKUP";
  start_time: string;
  end_time: string;
  is_active: boolean;
};

// The API has been returning all of this per location from the start — live
// availability, the reason when it is closed, and the whole weekly schedule.
// The customer app read none of it, so it happily let someone fill a cart at
// 11pm and only failed at checkout with "This branch is unavailable".
export type RestaurantLocation = {
  id: string;
  branch_name: string;
  address_line_1: string;
  city: string;
  delivery_fee: Money;
  minimum_order_amount: Money;
  estimated_delivery_time: string | number;
  estimated_pickup_time: string | number;
  delivery_enabled: boolean;
  pickup_enabled: boolean;
  is_open: boolean;
  is_active: boolean;
  delivery_available_now?: boolean;
  pickup_available_now?: boolean;
  delivery_unavailable_reason?: string | null;
  pickup_unavailable_reason?: string | null;
  temporary_closed_reason?: string | null;
  fulfillment_slots?: FulfillmentSlot[];
  // Nullable on the server, and null on most stored rows — five of eight.
  preparation_time_minutes?: number | null;
  slot_interval_minutes?: number;
  future_order_enabled?: boolean;
  max_future_days?: number;
};
export type Restaurant = {
  id: string;
  name: string;
  slug: string;
  /** Nullable in the database, like a dish's. */
  description: string | null;
  cuisine_type: string;
  city: string;
  minimum_order_amount: Money;
  delivery_fee: Money;
  logo_image_url: string | null;
  cover_image_url: string | null;
  is_open: boolean;
  locations?: RestaurantLocation[];
};
export type Order = {
  id: string;
  status: string;
  payment_status: string;
  /**
   * How it was paid, which is not the same question as whether it was paid.
   * The API has always sent this; nothing here declared it, so the order page
   * told everyone they had "Paid by card" — including customers who paid by
   * UPI on a Razorpay link, which is most of them in India.
   */
  payment_method?: string;
  fulfillment_type: string;
  subtotal: Money;
  delivery_fee: Money;
  tax_amount: Money;
  discount_amount: Money;
  total_amount: Money;
  placed_at: string;
  /**
   * Set when the customer booked a time instead of ordering for now.
   *
   * The API has always returned both; the type simply omitted them, so
   * somebody who booked "Tomorrow at 7:00 p.m." was never shown it again
   * anywhere after checkout.
   */
  schedule_type?: string | null;
  scheduled_at?: string | null;
  delivery_address: string | null;
  restaurant?: { id: string; name: string };
  /**
   * The branch, and how long it says it takes. Sent by the API all along; the
   * type omitted it, which is why a customer watching "preparing" was never
   * told when to expect the food.
   */
  restaurant_location?: {
    id: string;
    branch_name: string;
    estimated_delivery_time: number;
    estimated_pickup_time: number;
  };
  items: {
    id: string;
    menu_item_id: string;
    item_name_snapshot: string;
    quantity: number;
    unit_price: Money;
    total_price: Money;
    /**
     * What the customer actually chose, frozen at order time.
     *
     * The API has always sent both; the type omitted them, so a past order
     * showed "Pad Thai" with no hint of the Large or the extra prawns that
     * made up its price — and someone checking why an order cost what it did
     * had nothing to look at.
     */
    size_name_snapshot?: string | null;
    selected_options_snapshot?: {
      group_title: string;
      option_name: string;
      extra_price: Money;
      quantity: number;
      is_countable: boolean;
    }[];
  }[];
};
/** Orders have no human-readable number from the API — build a short display code from the id. */
export const orderCode = (order: Pick<Order, "id">) => `#${order.id.slice(0, 8).toUpperCase()}`;

/** Every price the customer sees goes through here — one place to change the currency. */
/**
 * What a restaurant charges in, as `/app-config` sends it.
 *
 * `locale` carries the GROUPING rule, not the symbol — which matters more
 * than it looks: Indian grouping is 2-2-3, so formatting ₹1234567 with an
 * `en-US` locale writes ₹1,234,567 where the customer reads ₹12,34,567.
 */
export type CurrencyFormat = {
  code: string;
  locale: string;
  min_fraction_digits: number;
  max_fraction_digits: number;
};

/**
 * The currency a storefront falls back to before `/app-config` has answered.
 *
 * Every price on the page comes from that same response, so in practice
 * nothing is rendered with this — it exists so the formatter has an answer
 * rather than a crash if a price ever reaches it first.
 */
export const FALLBACK_CURRENCY: CurrencyFormat = {
  code: "USD",
  locale: "en-US",
  min_fraction_digits: 2,
  max_fraction_digits: 2,
};

/**
 * A price, written the way the restaurant charging it writes prices.
 *
 * `currency` is a parameter rather than a constant because one deployment
 * serves every tenant: a Surat kitchen's menu was rendering as "$35.00",
 * which is the right number under the wrong symbol — worse than either being
 * wrong alone, because it reads as a price a customer could agree to.
 *
 * Components should reach for `useMoney()` instead, which binds this to the
 * tenant the page resolved. This stays exported for the handful of callers
 * outside React, which are handed a formatter by their caller.
 */
export const formatMoney = (
  value: Money | number,
  currency: CurrencyFormat = FALLBACK_CURRENCY,
) => {
  const amount = Number(value);
  // Zero decimals or two, never one.
  //
  // Rupees are configured with `min_fraction_digits: 0`, deliberately: ₹145 is
  // how a menu price is written, not ₹145.00. But `Intl` reads min 0 / max 2
  // as "between none and two", so a cart whose tax came to 0.6 printed
  // "Tax ₹0.6" and totalled "₹32.6" — an amount of money with one decimal
  // place, which exists in no currency and reads as a rounding bug.
  //
  // So the minimum is raised to two only when there IS a fractional part,
  // and never above what the currency itself allows.
  const hasFraction = Number.isFinite(amount) && Math.round(amount * 100) % 100 !== 0;
  const minimumFractionDigits = hasFraction
    ? Math.min(2, currency.max_fraction_digits)
    : currency.min_fraction_digits;

  return new Intl.NumberFormat(currency.locale, {
    style: "currency",
    currency: currency.code,
    minimumFractionDigits,
    maximumFractionDigits: currency.max_fraction_digits,
  }).format(amount);
};

/**
 * The same money, to the nearest whole unit, for prose.
 *
 * "A light lunch under $20" is how a person says it; "$20.00" is how a
 * ledger says it, and a craving chip is a sentence. Mirrors
 * `format_rounded_amount` in the backend's `services/currency.py`, and is
 * separate from `formatMoney` for the reason given there: a flag on the price
 * formatter would let a price list quietly lose its cents.
 *
 * Grouping still comes from the currency's locale, so a rounded rupee figure
 * is still written the Indian way.
 */
export const formatRoundedMoney = (
  value: Money | number,
  currency: CurrencyFormat = FALLBACK_CURRENCY,
) =>
  new Intl.NumberFormat(currency.locale, {
    style: "currency",
    currency: currency.code,
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(Math.round(Math.abs(Number(value))));

/** Derives the "All" + unique category list from a live menu-items response. */
export const deriveCategories = (items: MenuItem[]) => [
  "All",
  ...Array.from(new Set(items.map((item) => item.category))),
];

/**
 * "Tomorrow at 7:00 p.m." for an order the customer booked ahead.
 *
 * Returns null for an ASAP order, so callers can render nothing rather than a
 * misleading "scheduled for" line on something that is being made right now.
 * en-CA throughout, matching every other time in the app.
 */
/**
 * "2:45 p.m." — when an ASAP order is expected, or null.
 *
 * The tracking page showed a customer which step their food was on and never
 * once said when it would arrive, which is the thing somebody refreshing that
 * page actually wants. The cart promises a time before the order is placed;
 * after it, the promise disappeared.
 *
 * Derived, not invented: the branch's own estimate added to the moment the
 * order was placed. Three cases return null instead of a time, because a
 * wrong time here is worse than none —
 *
 *   - a SCHEDULED order, which `scheduledFor` already answers properly;
 *   - a branch that publishes no estimate;
 *   - an estimate that has already passed. A late order must not keep
 *     insisting it arrived twenty minutes ago; the steps still say where it
 *     is, and silence is the honest state until it moves.
 */
export function expectedBy(
  order: Pick<Order, "schedule_type" | "placed_at" | "fulfillment_type" | "restaurant_location">,
  now: Date = new Date(),
): string | null {
  if (order.schedule_type === "SCHEDULED") return null;

  const branch = order.restaurant_location;
  const minutes =
    order.fulfillment_type === "PICKUP"
      ? branch?.estimated_pickup_time
      : branch?.estimated_delivery_time;
  if (!minutes || minutes <= 0) return null;

  const placed = new Date(order.placed_at);
  if (Number.isNaN(placed.getTime())) return null;

  const due = new Date(placed.getTime() + minutes * 60_000);
  if (due.getTime() <= now.getTime()) return null;

  return new Intl.DateTimeFormat("en-CA", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(due);
}

export function scheduledFor(order: Pick<Order, "schedule_type" | "scheduled_at">): string | null {
  if (order.schedule_type !== "SCHEDULED" || !order.scheduled_at) return null;
  const at = new Date(order.scheduled_at);
  if (Number.isNaN(at.getTime())) return null;

  const now = new Date();
  const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);

  const time = new Intl.DateTimeFormat("en-CA", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  }).format(at);

  if (sameDay(at, now)) return `Today at ${time}`;
  if (sameDay(at, tomorrow)) return `Tomorrow at ${time}`;
  const day = new Intl.DateTimeFormat("en-CA", {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(at);
  return `${day} at ${time}`;
}

/**
 * "Large · Extra prawns, No peanuts" for one order line, or null.
 *
 * Reads the snapshot rather than today's menu on purpose: the point of a past
 * order is what was bought then, and the dish may have been re-priced or its
 * options renamed since.
 */
export function lineSelections(line: Order["items"][number]): string | null {
  const parts: string[] = [];
  if (line.size_name_snapshot) parts.push(line.size_name_snapshot);
  for (const option of line.selected_options_snapshot ?? []) {
    parts.push(
      option.is_countable && option.quantity > 1
        ? `${option.option_name} ×${option.quantity}`
        : option.option_name,
    );
  }
  return parts.length ? parts.join(" · ") : null;
}

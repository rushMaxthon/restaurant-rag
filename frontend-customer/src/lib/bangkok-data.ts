export type Money = string;
export type MenuSize = { id: string; name: string; price: Money; is_active: boolean };
export type CustomizationOption = {
  id: string;
  name: string;
  extra_price: Money;
  is_countable: boolean;
};
export type CustomizationGroup = {
  id: string;
  title: string;
  selection_type: "SINGLE" | "MULTI";
  is_required: boolean;
  min_selection: number;
  max_selection: number;
  options: CustomizationOption[];
};
export type MenuItem = {
  id: string;
  restaurant_id: string;
  restaurant_location_id: string;
  name: string;
  category: string;
  cuisine_type: string;
  description: string;
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
  preparation_time_minutes?: number;
  slot_interval_minutes?: number;
  future_order_enabled?: boolean;
  max_future_days?: number;
};
export type Restaurant = {
  id: string;
  name: string;
  slug: string;
  description: string;
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
  fulfillment_type: string;
  subtotal: Money;
  delivery_fee: Money;
  tax_amount: Money;
  discount_amount: Money;
  total_amount: Money;
  placed_at: string;
  delivery_address: string | null;
  restaurant?: { id: string; name: string };
  items: {
    id: string;
    menu_item_id: string;
    item_name_snapshot: string;
    quantity: number;
    unit_price: Money;
    total_price: Money;
  }[];
};
/** Orders have no human-readable number from the API — build a short display code from the id. */
export const orderCode = (order: Pick<Order, "id">) => `#${order.id.slice(0, 8).toUpperCase()}`;

/** Every price the customer sees goes through here — one place to change the currency. */
export const formatMoney = (value: Money | number) =>
  new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));

/** Derives the "All" + unique category list from a live menu-items response. */
export const deriveCategories = (items: MenuItem[]) => [
  "All",
  ...Array.from(new Set(items.map((item) => item.category))),
];

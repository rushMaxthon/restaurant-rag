// Mirrors backend/app/models/enums.py. The backend owns these values; the
// board only ever displays them, so a new status is added there first.
export type UserRole = 'ADMIN' | 'OWNER' | 'KITCHEN' | 'CUSTOMER';

// The roles allowed to run a board — ORDER_BOARD_ROLES on the API.
export type BoardRole = Exclude<UserRole, 'CUSTOMER'>;

export type OrderStatus =
  | 'PAYMENT_PENDING'
  | 'PLACED'
  | 'ACCEPTED'
  | 'PREPARING'
  | 'OUT_FOR_DELIVERY'
  | 'DELIVERED'
  | 'CANCELLED';

// The four statuses a kitchen works in, New through Ready.
export type LiveStatus = 'PLACED' | 'ACCEPTED' | 'PREPARING' | 'OUT_FOR_DELIVERY';

export type FulfillmentType = 'DELIVERY' | 'PICKUP';

// POST /auth/login, as backend/app/schemas/auth.py AuthResponse returns it.
export interface AuthResponse {
  access_token: string;
  token_type: string;
  role: UserRole;
  restaurant_id: string | null;
  restaurant_location_id: string | null;
  user: {
    id: string;
    full_name: string;
    email: string;
    role: UserRole;
  };
}

export interface KitchenUser {
  id: string;
  fullName: string;
  email: string;
  role: BoardRole;
}

export interface KitchenSession {
  token: string;
  user: KitchenUser;
  // The restaurant an OWNER owns or a KITCHEN account is assigned to; null
  // for an ADMIN, who has none.
  restaurantId: string | null;
  // The one branch a KITCHEN account is pinned to. Null means the account can
  // see every branch — which is the only thing that decides whether a branch
  // picker is offered at all.
  restaurantLocationId: string | null;
}

// One chosen option, as the checkout snapshot froze it. Every field is
// optional: the column is JSON written per order, and rows from before
// `portion` or `group_title` existed still come back.
export interface SelectedOptionSnapshot {
  group_id?: string | null;
  group_title?: string | null;
  option_id?: string | null;
  option_name?: string | null;
  quantity?: number | null;
  // WHOLE, or LEFT / RIGHT for a group the owner marked supports_halves.
  portion?: string | null;
}

export interface OrderLine {
  id: string;
  menu_item_id: string;
  item_name_snapshot: string;
  quantity: number;
  unit_price: string;
  total_price: string;
  size_name_snapshot?: string | null;
  selected_options_snapshot?: SelectedOptionSnapshot[] | null;
}

// OrderResponse, narrowed to what a kitchen reads.
export interface KitchenOrder {
  id: string;
  status: OrderStatus;
  payment_status: string;
  fulfillment_type: FulfillmentType;
  schedule_type: 'ASAP' | 'SCHEDULED';
  scheduled_at: string | null;
  placed_at: string;
  total_amount: string;
  currency: string;
  special_instructions: string | null;
  contact_name: string | null;
  contact_phone: string | null;
  delivery_address: string | null;
  restaurant_id: string;
  restaurant_location_id: string;
  restaurant_location: { id: string; branch_name: string } | null;
  customer: { full_name: string; phone_number: string | null } | null;
  items: OrderLine[];
  // Bumped by the server on every change; lets a poll keep an unchanged order
  // as the same object, so nothing on screen re-renders for it.
  updated_at?: string;
  // When it was delivered, from the status-event log. Only the LIST endpoint
  // fills it, and only on DELIVERED rows; GET /orders/{id} leaves it null.
  completed_at?: string | null;
}

export interface RestaurantLocationSummary {
  id: string;
  branch_name: string;
  is_open: boolean;
}

export interface RestaurantInfo {
  id: string;
  name: string;
  locations: RestaurantLocationSummary[];
}

// A page of results plus how many match in total (X-Total-Count).
export interface Page<T> {
  rows: T[];
  total: number;
}

// Which restaurant and branch the board is looking at. The server re-resolves
// it on every request (resolve_order_board_scope); this is only the request.
export interface BoardScope {
  restaurantId: string | null;
  locationId: string | null;
}

// `disabled` means the server has realtime switched off.
export type RealtimeStatus = 'connecting' | 'live' | 'offline' | 'disabled';

// GET /kitchen/menu — a dish as the kitchen sees it: stock, never prices.
export interface KitchenMenuSize {
  id: string;
  name: string;
  // null: this size draws on the dish's count (or nobody counts it).
  stock_quantity: number | null;
  stock_daily_quantity: number | null;
}

export interface KitchenMenuItem {
  id: string;
  name: string;
  category: string;
  is_veg: boolean;
  restaurant_location_id: string;
  branch_name: string;
  // The owner's switch. Read-only here: the kitchen cannot show a dish.
  is_available: boolean;
  out_of_stock: boolean;
  // null is "not counted" (unlimited) — a different fact from 0 (sold out).
  stock_quantity: number | null;
  stock_daily_quantity: number | null;
  is_on_sale: boolean;
  sizes: KitchenMenuSize[];
  updated_at: string;
}

// Only what is sent changes; null on a count means "stop counting".
export interface DishStockChange {
  out_of_stock?: boolean;
  stock_quantity?: number | null;
  stock_daily_quantity?: number | null;
}

export interface SizeStockChange {
  stock_quantity?: number | null;
  stock_daily_quantity?: number | null;
}

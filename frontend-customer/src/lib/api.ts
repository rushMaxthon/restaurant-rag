import type {
  Restaurant,
  RestaurantLocation,
  MenuItem,
  Order,
  Money,
} from "@/lib/bangkok-data";

export const API_BASE_URL =
  (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? "http://localhost:8000/api";

export const BUNDLE_ID = "com.quickbite.bangkokbowl";

const TOKEN_KEY = "bangkok-bowl-token";
const USER_KEY = "bangkok-bowl-user";

export type AuthUser = {
  id: string;
  full_name: string;
  email: string;
  phone_number: string | null;
  default_address: string | null;
  role: string;
  is_active: boolean;
  is_verified: boolean;
};

export type AuthResponse = {
  access_token: string;
  token_type: string;
  role: string;
  restaurant_id: string | null;
  app_client_id: string | null;
  app_key: string | null;
  user: AuthUser;
};

export type AppConfig = {
  app_client_id: string;
  app_key: string;
  app_mode: string;
  restaurant_id: string;
  display_name: string;
  branding: { primary_color: string; theme_preset: string };
  order_prefix: string;
  minimum_supported_version: string;
  bundle_id: string;
};

export type ChatSuggestion = {
  id: string;
  restaurant_id: string;
  restaurant_location_id: string;
  restaurant_name: string;
  restaurant_location_name: string;
  name: string;
  category: string;
  cuisine_type: string | null;
  description: string | null;
  price: Money;
  is_veg: boolean;
  is_available: boolean;
  is_bestseller?: boolean;
  is_featured?: boolean;
  image_url: string | null;
  is_new?: boolean;
  is_favorite?: boolean;
  similarity_score: number;
};

export type ChatResponse = {
  reply: string;
  session_id: string;
  suggestions: ChatSuggestion[];
};

export type OrderCreateItem = {
  menu_item_id: string;
  menu_item_size_id?: string | null;
  selected_options?: { option_id: string; quantity?: number }[];
  quantity: number;
};

export type OrderCreateRequest = {
  restaurant_id: string;
  restaurant_location_id?: string | null;
  fulfillment_type: "DELIVERY" | "PICKUP";
  items: OrderCreateItem[];
  delivery_address: string;
  special_instructions?: string | null;
  payment_method?: string;
};

export type OrderValidationResponse = {
  valid: boolean;
  restaurant_id: string;
  restaurant_location_id: string;
  fulfillment_type: string;
  schedule_type: string;
  scheduled_at: string;
  subtotal: Money;
  delivery_fee: Money;
  tax_amount: Money;
  discount_amount: Money;
  total_amount: Money;
  currency: string;
  item_count: number;
};

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setSession(token: string, user: AuthUser) {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    // ignore storage failures (private mode, etc.)
  }
}

export function getStoredUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as AuthUser) : null;
  } catch {
    return null;
  }
}

export function clearSession() {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  } catch {
    // ignore
  }
}

const DEFAULT_TIMEOUT_MS = 12000;

function extractErrorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => (entry && typeof entry === "object" && "msg" in entry ? String((entry as { msg: unknown }).msg) : null))
      .filter((m): m is string => Boolean(m));
    if (messages.length) return messages.join(" ");
  }
  return fallback;
}

type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  auth?: boolean;
  timeoutMs?: number;
  query?: Record<string, string | number | boolean | undefined | null>;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, auth = false, timeoutMs = DEFAULT_TIMEOUT_MS, query } = options;

  let url = `${API_BASE_URL}${path}`;
  if (query) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null) params.set(key, String(value));
    }
    const qs = params.toString();
    if (qs) url += `?${qs}`;
  }

  // Deliberately NOT sending X-App-Bundle-Id here. On this backend that header
  // does double duty: as a query param (used only in getAppConfig below) it
  // just scopes which restaurant's data is visible, but as a request HEADER it
  // also drives resolve_identity_app_client_id, which decides which app client
  // a customer account belongs to. Customer identity is scoped per app client
  // (partial unique index on (app_client_id, lower(email))), and the seeded
  // customers belong to the "marketplace" app client, not Bangkok Bowl's. Send
  // the header here and every login 401s even with correct credentials.
  const headers: Record<string, string> = {
    Accept: "application/json",
  };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const init: RequestInit = { method, headers, signal: controller.signal };
  if (body !== undefined) init.body = JSON.stringify(body);

  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (error) {
    clearTimeout(timer);
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("The request timed out. Please try again.", 0);
    }
    throw new ApiError("Could not reach the server. Check your connection and try again.", 0);
  }
  clearTimeout(timer);

  let payload: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    throw new ApiError(extractErrorMessage(payload, `Request failed (${response.status}).`), response.status);
  }

  return payload as T;
}

export const api = {
  getAppConfig: () => request<AppConfig>("/app-config", { query: { bundle_id: BUNDLE_ID } }),

  getRestaurant: (restaurantId: string) =>
    request<Restaurant & { locations: RestaurantLocation[] }>(`/restaurants/${restaurantId}`),

  getMenuItems: (restaurantId: string, locationId?: string | null) =>
    request<MenuItem[]>("/menu-items", {
      query: { restaurant_id: restaurantId, location_id: locationId ?? undefined },
    }),

  getMenuItem: (menuItemId: string) => request<MenuItem>(`/menu-items/${menuItemId}`),

  login: (email: string, password: string) =>
    request<AuthResponse>("/auth/login", { method: "POST", body: { email, password } }),

  register: (payload: { full_name: string; email: string; password: string; phone_number?: string | null }) =>
    request<AuthResponse>("/auth/register", { method: "POST", body: payload }),

  getOrders: () => request<Order[]>("/orders", { auth: true }),

  getOrder: (orderId: string) => request<Order>(`/orders/${orderId}`, { auth: true }),

  validateOrder: (payload: OrderCreateRequest) =>
    request<OrderValidationResponse>("/orders/validate", { method: "POST", body: payload, auth: true }),

  createOrder: (payload: OrderCreateRequest) =>
    request<Order>("/orders", { method: "POST", body: payload, auth: true }),

  sendChatMessage: (payload: { message: string; session_id?: string | null; restaurant_id?: string | null; restaurant_location_id?: string | null }) =>
    request<ChatResponse>("/chat/message", { method: "POST", body: payload, auth: true }),

  getGeneratedCombos: (limit = 12) => request<unknown[]>("/generated-combos", { query: { limit } }),

  getPersonalizedOffers: () => request<unknown[]>("/personalized-offers", { auth: true }),
};

import type { Restaurant, RestaurantLocation, MenuItem, Order, Money } from "@/lib/bangkok-data";
import type { GuestPreferences } from "@/lib/guest-preferences";
import type { CartLineRequest, SellSuggestion } from "@/lib/suggestions";

export const API_BASE_URL =
  (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? "http://localhost:8000/api";

/**
 * Which restaurant this storefront is.
 *
 * It used to be `BUNDLE_ID = "com.quickbite.bangkokbowl"`, a constant sent on
 * every request — so one deployment served six tenants and all six of them
 * were Bangkok Bowl. `dragon-wok.localhost` rendered Bangkok Bowl's name,
 * logo, hero copy and menu.
 *
 * A mobile build can carry a constant: the app store fixed its bundle id at
 * release, and one build is one restaurant. A web build cannot. One
 * deployment answers every tenant's address, so the address IS the identity,
 * and it has to be read per request rather than compiled in.
 *
 * Sent as a header on every call, not just `/app-config`, because identifying
 * the brand and restricting the data are two different jobs. The backend
 * resolves this host to an app client and narrows every query to that
 * restaurant — see `get_app_scope`. A storefront asking for another
 * restaurant's menu is refused server-side; picking is the client's job,
 * refusing is the server's.
 *
 * Empty during server rendering, where there is no `window`. The only thing
 * fetched before hydration is the page shell, and every data query runs on
 * the client.
 */
function storefrontHost(): string {
  if (typeof window === "undefined") return "";
  return window.location.host;
}

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

/**
 * An address the customer has saved, as `/profile/addresses` returns it.
 *
 * The backend has had these since before this web app existed — the mobile
 * app writes them — and the parts line up one for one with what checkout
 * asks for. Nothing here is new server-side.
 */
export type SavedAddress = {
  id: string;
  label: "HOME" | "WORK" | "OTHER";
  address_line_1: string;
  address_line_2: string | null;
  landmark: string | null;
  city: string;
  state: string;
  postal_code: string;
  phone_number: string | null;
  is_default: boolean;
  formatted_address: string;
};

export type SavedAddressCreate = {
  label?: "HOME" | "WORK" | "OTHER";
  address_line_1: string;
  address_line_2?: string | null;
  landmark?: string | null;
  city: string;
  state: string;
  postal_code: string;
  phone_number?: string | null;
  is_default?: boolean;
};

/** A dish someone favourited, as the favourites list returns it. */
export type FavoriteItem = {
  id: string;
  name: string;
  price: Money;
  image_url?: string | null;
  category?: string | null;
  is_veg?: boolean;
  is_available?: boolean;
  has_sizes?: boolean;
  has_customizations?: boolean;
};

/**
 * Two or more dishes people actually ordered together.
 *
 * Not a marketing bundle: `generated_from_orders` says it was derived from
 * real orders, and `unique_user_count` is how many different people did it.
 * That provenance is the interesting part of this feature and the reason the
 * UI leads with it rather than with the discount.
 */
export type GeneratedCombo = {
  id: string;
  combo_name: string;
  description: string | null;
  restaurant_name: string;
  items: { menu_item_id: string; name: string; price: Money; image_url?: string | null }[];
  order_count: number;
  unique_user_count: number;
  original_total_price: Money;
  suggested_combo_price: Money;
  savings_amount: Money;
  image_url: string | null;
  generated_from_orders: boolean;
};

export type ProfileStats = {
  total_orders: number;
  delivered_orders: number;
  saved_places: number;
  favorites_count: number;
};

/**
 * Everything the account knows about someone, in one request.
 *
 * `/profile/me` has always returned all of this; the type named only the two
 * fields checkout happened to need, so the profile screen would have made
 * three more calls for data already in its hand.
 */
export type ProfileSummary = {
  user: AuthUser;
  stats: ProfileStats;
  saved_addresses: SavedAddress[];
  recent_orders: Order[];
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
  /**
   * The clock the restaurant's hours, slots and cutoffs are written in.
   *
   * Sent because the device cannot guess it. Optional on the type so an older
   * backend degrades to the device's zone rather than crashing the app.
   */
  business_timezone?: string;
  /**
   * The dialling code the server prepends to a bare local number. Read rather
   * than assumed: the checkout used to print "+1" from a literal in its own
   * source while the server prepended something else, so the number shown to
   * the customer and the number stored could differ silently.
   */
  phone_country_code?: string;
  /**
   * Optional features this restaurant has, already combined with the
   * deployment's own flags — the client is told the answer, never the rule.
   *
   * Optional on the type so an older backend degrades to "everything on"
   * rather than hiding features that are in fact available: a missing field
   * is an old server, not a revoked capability.
   */
  capabilities?: Record<string, boolean>;
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
  /** Whether the dish needs a size or options chosen before it can be ordered. */
  has_sizes?: boolean;
  has_customizations?: boolean;
  similarity_score: number;
};

export type ChatResponse = {
  reply: string;
  session_id: string;
  suggestions: ChatSuggestion[];
};

/**
 * One cart edit the ordering agent decided on for this turn.
 *
 * Identifiers only — no name or price arrives, by the same rule as
 * `ChatSuggestion`: the client renders from the menu it already loaded, so
 * the reply can never disagree with the menu page about what something is
 * called or costs. `status` is the gate: only "applied" may change the cart,
 * and a missing/null value (a drifted response shape) must read as NOT
 * applied. See `lib/cart-actions.ts` for how these are turned into cart
 * lines.
 */
export type CartAction = {
  kind: "add" | "remove" | "set_quantity" | "clear" | "checkout";
  status: "applied" | "proposed";
  reason: "named" | "ambiguous" | "destructive";
  menu_item_id: string | null;
  menu_item_size_id: string | null;
  selected_option_ids: string[];
  quantity: number | null;
};

export type ChatStreamMeta = {
  session_id: string;
  suggestions: ChatSuggestion[];
  combo_suggestions: unknown[];
  offer_suggestions: unknown[];
  // Empty for a signed-in customer: their traits already live in a row, and
  // echoing them to a client that may not assert them would invite exactly the
  // round-trip the backend's trust boundary refuses.
  inferred_preferences?: GuestPreferences;
  // Present only when the server's ordering-agent flag is on. Absent under
  // the old contract, so every reader must treat it as optional.
  turn_id?: string;
};

export type ChatStreamDone = ChatStreamMeta & {
  /** True when the agent asked the customer to choose or refused a dish for their diet. */
  agent_asks?: boolean;
  /** Set only on the turn that placed an order. The link is a field, not
   *  text in the reply: a model repeating a long URL is a customer who
   *  cannot pay. */
  /** True when everything an order needs is gathered and only a confirmation is left. */
  order_ready?: boolean;
  placed_order?: {
    order_id: string | null;
    total: string | null;
    currency: string | null;
    payment_url: string | null;
  } | null;
  reply: string;
  // Same flag-gated pair as `turn_id` above: both arrive together or not at
  // all.
  agent_reply?: string | null;
  cart_actions?: CartAction[];
};

export type ChatHistoryItem = {
  id: string;
  session_id: string;
  restaurant_id: string | null;
  restaurant_location_id: string | null;
  role: "USER" | "ASSISTANT";
  message: string;
  created_at: string;
};

/**
 * The conversation the backend has been keeping all along.
 *
 * Every turn was already written to `chat_history` and every request already
 * sent the last few back as model context — the screen was the only party that
 * forgot. Auth-only: a guest's turns are keyed to an ephemeral session id that
 * does not survive a reload, so there is nothing to fetch for one.
 */
export async function getChatHistory(sessionId?: string | null): Promise<ChatHistoryItem[]> {
  return request<ChatHistoryItem[]>("/chat/history", {
    auth: true,
    query: sessionId ? { session_id: sessionId, limit: 50 } : { limit: 50 },
  });
}

export type UserPreferencesResponse = {
  cuisines: string[];
  diet: string | null;
  spice_level: string | null;
  budget: string | null;
  favorite_items: string[];
};

export async function getMyPreferences(): Promise<UserPreferencesResponse | null> {
  try {
    return await request<UserPreferencesResponse>("/preferences/me", { auth: true });
  } catch {
    // A customer with no preferences row is the case this feature exists for,
    // and it is indistinguishable from a transport failure at this layer. Both
    // answers are "do not promote", which is the safe direction: the worst
    // outcome is the guest's traits waiting for the next login.
    return null;
  }
}

export type UserPreferencesPayload = {
  cuisines: string[];
  diet: string | null;
  spice_level: string | null;
  budget: string | null;
  favorite_items: string[];
};

/**
 * Replaces the whole profile, so every field must be sent.
 *
 * `upsert_user_preferences` assigns each column from the payload rather than
 * patching, so omitting `cuisines` clears them. The screen therefore sends what
 * it loaded, edited — never a partial.
 */
export async function putMyPreferences(payload: Partial<UserPreferencesPayload>): Promise<void> {
  await request("/preferences/me", { method: "PUT", auth: true, body: payload });
}

export type PersonalizedOffer = {
  id: string;
  offer_id: string;
  badge: string;
  title: string;
  subtitle: string;
  cta_label: string;
  target_type: string;
  restaurant_id: string;
  restaurant_name: string;
  restaurant_location_id: string | null;
  restaurant_location_name: string | null;
  menu_item_id: string | null;
  menu_item_name: string | null;
  generated_combo_id: string | null;
  generated_combo_name: string | null;
  discount_label: string | null;
  terms_label: string | null;
  expires_at: string | null;
};

export type OrderCreateItem = {
  menu_item_id: string;
  menu_item_size_id?: string | null;
  selected_options?: {
    option_id: string;
    quantity?: number;
    /** Which half this option goes on; omitted means the whole item. */
    portion?: "WHOLE" | "LEFT" | "RIGHT";
  }[];
  quantity: number;
};

/** Mirrors PaymentConfigResponse. `stripe_enabled` is false until a key is set. */
export type PaymentConfig = {
  publishable_key: string;
  stripe_enabled: boolean;
  currency: string;
  /** What this restaurant can actually settle right now. */
  supported_methods: string[];
  /**
   * The PUBLIC key of each gateway, by gateway name — Razorpay Checkout
   * cannot open without its `key_id`, and the browser has no other source
   * for it.
   *
   * Public by design: every one of these is in the page source of the
   * checkout that uses it. The matching secrets never leave the server.
   */
  gateway_keys?: Record<string, string>;
};

export type PaymentIntent = {
  order_id: string;
  payment_intent_id: string;
  client_secret: string;
  amount: string;
  currency: string;
  publishable_key: string;
};

export type PaymentStatus = {
  order_id: string;
  payment_status: string;
  order_status: string;
};

export type OrderCreateRequest = {
  restaurant_id: string;
  restaurant_location_id?: string | null;
  fulfillment_type: "DELIVERY" | "PICKUP";
  items: OrderCreateItem[];
  delivery_address: string;
  contact_name?: string;
  contact_phone?: string;
  special_instructions?: string | null;
  payment_method?: string;
  // The server has accepted these since the beginning and validates
  // `scheduled_at` against the branch's slot rows. Omitted for an ASAP order,
  // which is what the API defaults to.
  schedule_type?: "ASAP" | "SCHEDULED";
  scheduled_at?: string | undefined;
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

export function extractErrorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) =>
        entry && typeof entry === "object" && "msg" in entry
          ? String((entry as { msg: unknown }).msg)
          : null,
      )
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
  // In production a proxy writes this. In development the browser talks to
  // the API directly, so the page sends its own address — `Host` would name
  // the API on a cross-origin call, not the storefront.
  const host = storefrontHost();
  if (host) headers["X-Forwarded-Host"] = host;
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
    throw new ApiError(
      extractErrorMessage(payload, `Request failed (${response.status}).`),
      response.status,
    );
  }

  return payload as T;
}

export const api = {
  getAppConfig: () => request<AppConfig>("/app-config", { query: { host: storefrontHost() } }),

  getRestaurant: (restaurantId: string) =>
    request<Restaurant & { locations: RestaurantLocation[] }>(`/restaurants/${restaurantId}`),

  getMenuItems: (restaurantId: string, locationId?: string | null) =>
    request<MenuItem[]>("/menu-items", {
      query: { restaurant_id: restaurantId, location_id: locationId ?? undefined },
    }),

  getMenuItem: (menuItemId: string) => request<MenuItem>(`/menu-items/${menuItemId}`),

  login: (email: string, password: string) =>
    request<AuthResponse>("/auth/login", { method: "POST", body: { email, password } }),

  register: (payload: {
    full_name: string;
    email: string;
    password: string;
    phone_number?: string | null;
  }) => request<AuthResponse>("/auth/register", { method: "POST", body: payload }),

  // The stored user is whatever login returned, which goes stale the moment
  // the customer edits their details anywhere else. This is the live copy,
  // and it carries the saved addresses in the same response.
  getProfile: () => request<ProfileSummary>("/profile/me", { auth: true }),

  updateProfile: (payload: { full_name: string; phone_number?: string | null }) =>
    request<AuthUser>("/profile/me", { method: "PATCH", body: payload, auth: true }),

  deleteSavedAddress: (addressId: string) =>
    request<void>(`/profile/addresses/${addressId}`, { method: "DELETE", auth: true }),

  makeSavedAddressDefault: (addressId: string) =>
    request<SavedAddress>(`/profile/addresses/${addressId}/default`, {
      method: "POST",
      auth: true,
    }),

  createSavedAddress: (payload: SavedAddressCreate) =>
    request<SavedAddress>("/profile/addresses", { method: "POST", body: payload, auth: true }),

  getOrders: () => request<Order[]>("/orders", { auth: true }),

  getOrder: (orderId: string) => request<Order>(`/orders/${orderId}`, { auth: true }),

  // Authenticated: the endpoint requires a token, because the publishable key
  // is not handed to anonymous callers even though it is not secret. Calling it
  // without one 401s, the query fails, and the app concludes card is off — the
  // checkout then refused every order with "card payments aren't switched on".
  getPaymentConfig: () => request<PaymentConfig>("/payments/config", { auth: true }),

  createPaymentIntent: (orderId: string) =>
    request<PaymentIntent>(`/orders/${orderId}/payment-intent`, { method: "POST", auth: true }),

  /**
   * Hand back what Razorpay Checkout gave the browser.
   *
   * Worth nothing until the server checks it: the signature is an HMAC of the
   * order and payment ids with the restaurant's own API secret, and without
   * that check a customer could post a made-up payment id and have their
   * order marked paid.
   */
  confirmRazorpayPayment: (
    orderId: string,
    payload: {
      razorpay_order_id: string;
      razorpay_payment_id: string;
      razorpay_signature: string;
    },
  ) =>
    request<{ status: string; order_id: string }>(
      `/payments/razorpay/confirm/${orderId}`,
      { method: "POST", auth: true, body: payload },
    ),

  getPaymentStatus: (orderId: string) =>
    request<PaymentStatus>(`/orders/${orderId}/payment-status`, { auth: true }),

  cancelPayment: (orderId: string) =>
    request<PaymentStatus>(`/orders/${orderId}/payment-cancel`, { method: "POST", auth: true }),

  validateOrder: (payload: OrderCreateRequest) =>
    request<OrderValidationResponse>("/orders/validate", {
      method: "POST",
      body: payload,
      auth: true,
    }),

  createOrder: (payload: OrderCreateRequest) =>
    request<Order>("/orders", { method: "POST", body: payload, auth: true }),

  // Chat replies are LLM-generated (Ollama), which routinely takes 15-25s —
  // well past the default timeout, so this gets a longer budget of its own.
  sendChatMessage: (payload: {
    message: string;
    session_id?: string | null;
    restaurant_id?: string | null;
    restaurant_location_id?: string | null;
  }) =>
    request<ChatResponse>("/chat/message", {
      method: "POST",
      body: payload,
      auth: true,
      timeoutMs: 45000,
    }),

  /**
   * The dishes this customer keeps coming back to, as ids only.
   *
   * Ids rather than whole items: every dish card on the menu needs to know
   * whether it is a favourite, and that is a set membership test, not 40 menu
   * items fetched a second time.
   */
  getFavoriteIds: () => request<string[]>("/favorites/ids", { auth: true }),

  getFavorites: () => request<FavoriteItem[]>("/favorites", { auth: true }),

  addFavorite: (menuItemId: string) =>
    request<{ is_favorite: boolean }>(`/favorites/${menuItemId}`, { method: "POST", auth: true }),

  removeFavorite: (menuItemId: string) =>
    request<{ is_favorite: boolean }>(`/favorites/${menuItemId}`, { method: "DELETE", auth: true }),

  /**
   * Pairings for one restaurant.
   *
   * The unscoped `/generated-combos` answers for the whole marketplace, which
   * on a restaurant's own menu offered a burger and a milkshake from somewhere
   * else entirely — dishes that cannot go in this cart at all, since a cart
   * belongs to one restaurant and one branch.
   */
  getGeneratedCombos: (restaurantId: string, limit = 12) =>
    request<GeneratedCombo[]>(`/restaurants/${restaurantId}/generated-combos`, {
      query: { limit },
    }),

  // NOTE: the real route is /offers/personalized (see backend app/api/personalized_offers.py) —
  // there is no top-level /personalized-offers path on this API.
  getPersonalizedOffers: () => request<PersonalizedOffer[]>("/offers/personalized", { auth: true }),

  getMyPreferences,
  putMyPreferences,

  getSuggestion: (params: {
    restaurantLocationId: string;
    sessionId: string;
    cart: CartLineRequest[];
  }) =>
    // auth: true so a signed-in customer's diet reaches `_is_offerable` —
    // without it every call is anonymous, `get_current_user_optional` returns
    // None, and a VEG customer's non-negotiable filter never runs. Degrades
    // to no header for a guest (see `request`), so this still works signed out.
    request<{ suggestion: SellSuggestion | null }>("/suggestions", {
      query: {
        restaurant_location_id: params.restaurantLocationId,
        session_id: params.sessionId,
        cart: JSON.stringify(params.cart),
      },
      auth: true,
    }).then((envelope) => envelope.suggestion),

  declineSuggestion: (sessionId: string, menuItemId: string) =>
    request("/suggestions/decline", {
      method: "POST",
      body: { session_id: sessionId, menu_item_id: menuItemId },
      // Same identity as getSuggestion — a decline must land under the same
      // principal (real user id, not the guest uuid5) or the memory it writes
      // suppresses nothing the next authenticated call reads.
      auth: true,
    }),
};

type ChatStreamPayload = {
  message: string;
  session_id?: string | null;
  restaurant_id?: string | null | undefined;
  restaurant_location_id?: string | null | undefined;
  guest_preferences?: GuestPreferences | undefined;
  // The cart as it stands when the message is sent, so the ordering agent can
  // resolve "make it two" or "remove that" against what is actually in it.
  // Identifiers only — see `cartLinesForRequest`.
  cart?: CartLineRequest[];
  /** The assistant line the customer last saw, so "yes" can be read against it. */
  previous_reply?: string | undefined;
  /** The tail of the thread as shown, newest last, so answers are read against their questions. */
  recent_history?: { role: "customer" | "assistant"; text: string }[] | undefined;
};

type ChatStreamHandlers = {
  onMeta?: (meta: ChatStreamMeta) => void;
  onToken?: (text: string) => void;
  onDone?: (done: ChatStreamDone) => void;
};

/**
 * Streams a concierge reply over Server-Sent Events. Uses fetch + a manual
 * ReadableStream reader rather than EventSource because EventSource cannot
 * send an Authorization header, and this endpoint requires the Bearer token.
 *
 * Frames are separated by a blank line, each with an `event:` and `data:`
 * line: `meta` arrives first (already carrying the full suggestions array),
 * then a stream of `token` frames with partial reply text, then `done` with
 * the full reply.
 */
/**
 * Place the order this conversation built.
 *
 * The contact details are not sent: they were collected and validated turn
 * by turn and live server-side against this session. All this carries is
 * which conversation, which branch, and the cart.
 */
export async function placeOrderFromChat(params: {
  restaurant_id: string;
  restaurant_location_id: string;
  session_id: string;
  cart: CartLineRequest[];
}): Promise<{
  outcome: string;
  order_id: string | null;
  total: string | null;
  currency: string | null;
  payment_url: string | null;
  missing: string[];
  reason: string | null;
}> {
  return request("/chat/place-order", { method: "POST", body: JSON.stringify(params), auth: true });
}

export async function streamChatMessage(
  payload: ChatStreamPayload,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let response: Response;
  try {
    const init: RequestInit = { method: "POST", headers, body: JSON.stringify(payload) };
    if (signal) init.signal = signal;
    response = await fetch(`${API_BASE_URL}/chat/message/stream`, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("Could not reach the server. Check your connection and try again.", 0);
  }

  if (!response.ok || !response.body) {
    let message = `Request failed (${response.status}).`;
    try {
      const text = await response.text();
      if (text) message = extractErrorMessage(JSON.parse(text), message);
    } catch {
      // keep fallback message
    }
    throw new ApiError(message, response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  function handleFrame(frame: string) {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    if (!dataLines.length) return;
    let data: unknown;
    try {
      data = JSON.parse(dataLines.join("\n"));
    } catch {
      return;
    }
    if (event === "meta") handlers.onMeta?.(data as ChatStreamMeta);
    else if (event === "token") handlers.onToken?.((data as { text: string }).text);
    else if (event === "done") handlers.onDone?.(data as ChatStreamDone);
  }

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sepIndex: number;
    while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, sepIndex);
      buffer = buffer.slice(sepIndex + 2);
      if (frame.trim()) handleFrame(frame);
    }
  }
  if (buffer.trim()) handleFrame(buffer);
}

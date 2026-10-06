/**
 * Everything this app asks the backend for, which is deliberately very little.
 *
 * A kitchen board reads orders and advances them by one step. It does not
 * browse a menu, take payment or edit anything, and the token it holds is a
 * KITCHEN account's — pinned server-side to one restaurant and usually one
 * branch, so the scoping below is a convenience for the UI and never the rule.
 * `resolve_order_board_scope` on the backend is the rule.
 */

/** `vite dev` / `vitest`. The backend on the developer's own machine. */
const DEV_API_BASE_URL = 'http://localhost:8000/api'

/**
 * `vite build`. The Render web service.
 *
 * This used to be absent, and the fallback below was `localhost` for every
 * build — so a deployment with `VITE_API_BASE_URL` missing or misspelled
 * shipped a board that talks to nobody, while building and deploying
 * perfectly green. `frontend-admin/src/config/api.ts` has carried this
 * argument for a while; the kitchen board and the storefront had not adopted
 * it, which is the kind of gap that only shows up on a wall-mounted tablet in
 * a kitchen during service.
 *
 * Render mints a new random suffix each time the API service is recreated, so
 * re-check this value when that happens.
 */
const PROD_API_BASE_URL = 'https://restaurant-rag-api-oj8p.onrender.com/api'

/**
 * `VITE_API_BASE_URL` still wins when set — a preview build against a staging
 * backend, or a tablet pointed at a LAN dev server, both need it. Vite inlines
 * it at BUILD time, so changing it requires a rebuild.
 */
export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ??
  (import.meta.env.PROD ? PROD_API_BASE_URL : DEV_API_BASE_URL)

const TOKEN_KEY = 'kitchen-token'
const SESSION_KEY = 'kitchen-session'

/** The roles allowed to run a board. Mirrors `ORDER_BOARD_ROLES` on the API. */
export type BoardRole = 'ADMIN' | 'OWNER' | 'KITCHEN'

export type OrderStatus =
  | 'PAYMENT_PENDING'
  | 'PLACED'
  | 'ACCEPTED'
  | 'PREPARING'
  | 'OUT_FOR_DELIVERY'
  | 'DELIVERED'
  | 'CANCELLED'

export type KitchenSession = {
  token: string
  role: BoardRole
  fullName: string
  /** The restaurant an OWNER owns or a KITCHEN account is assigned to. */
  restaurantId: string | null
  /**
   * The branch a KITCHEN account is pinned to, and null for everyone else.
   *
   * Null is the difference between "this screen is one kitchen's" and "this
   * screen can be pointed at any of them", which is the only thing that
   * decides whether a branch picker is offered at all.
   */
  restaurantLocationId: string | null
}

/**
 * One chosen option, exactly as `ResolvedCustomizationOption.to_snapshot()`
 * writes it at checkout.
 *
 * Every field is optional because this is a JSON column frozen per order:
 * rows written before `portion` or `group_title` existed still come back, and
 * a ticket that drops an option because a key is missing is worse than one
 * that prints it plainly.
 */
export type SelectedOptionSnapshot = {
  group_id?: string | null
  group_title?: string | null
  option_id?: string | null
  option_name?: string | null
  /** How many of this option — "Extra cheese ×2". */
  quantity?: number | null
  /** WHOLE, or LEFT / RIGHT for a group the owner marked `supports_halves`. */
  portion?: string | null
}

/**
 * Mirrors `OrderItemResponse`.
 *
 * The size and options used to be read as `selected_size_name` and
 * `selected_options` — names the API has never sent — so every ticket printed
 * the bare dish: "1× Pizza" for "Large · Pepperoni (left) · Mushroom (right)".
 * There is no per-line note either; the only free text is the order's own
 * `special_instructions`.
 */
export type OrderLine = {
  id: string
  menu_item_id: string
  item_name_snapshot: string
  quantity: number
  unit_price: string
  total_price: string
  size_name_snapshot?: string | null
  selected_options_snapshot?: SelectedOptionSnapshot[] | null
}

export type KitchenOrder = {
  id: string
  status: OrderStatus
  payment_status: string
  fulfillment_type: 'DELIVERY' | 'PICKUP'
  schedule_type: 'ASAP' | 'SCHEDULED'
  scheduled_at: string | null
  placed_at: string
  total_amount: string
  currency: string
  special_instructions: string | null
  contact_name: string | null
  contact_phone: string | null
  delivery_address: string | null
  restaurant_id: string
  restaurant_location_id: string
  restaurant_location: { id: string; branch_name: string } | null
  customer: { full_name: string; phone_number: string | null } | null
  items: OrderLine[]
  /**
   * When it was delivered, from the status-event log. Set on DELIVERED rows
   * only, and null for one delivered before event tracking began.
   */
  completed_at?: string | null
}

export type RestaurantLocationSummary = { id: string; branch_name: string; is_open: boolean }

/**
 * The brand and its branches, for the header.
 *
 * `/restaurants/{id}` already carries both, so the name beside the branch in
 * the header is the restaurant's own rather than something this app was
 * configured with — the same rule the customer storefront follows, and for
 * the same reason: one deployment serves every tenant.
 */
export type RestaurantInfo = {
  id: string
  name: string
  locations: RestaurantLocationSummary[]
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function readSession(): KitchenSession | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY)
    return raw ? (JSON.parse(raw) as KitchenSession) : null
  } catch {
    return null
  }
}

export function storeSession(session: KitchenSession) {
  try {
    localStorage.setItem(TOKEN_KEY, session.token)
    localStorage.setItem(SESSION_KEY, JSON.stringify(session))
  } catch {
    // A locked-down browser still runs the board for as long as the tab lives.
  }
}

export function clearSession() {
  try {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(SESSION_KEY)
  } catch {
    // Nothing to do; the in-memory state is cleared by the caller either way.
  }
}

/**
 * Who to tell when the server stops accepting this screen's token.
 *
 * Clearing localStorage alone was not enough: `AuthProvider` reads the session
 * once, at mount, so a 401 wiped the stored copy while React kept the old one
 * and went on rendering the board — every request failing, the header saying
 * "Not updating", and no way back to sign-in short of a reload. That is what
 * an expired token or a cook deactivated by their owner (which bumps
 * `token_version`) looked like on the wall. The socket's `auth` refusal covered
 * it only with `enable_realtime` on, and that defaults off.
 */
const sessionExpiredListeners = new Set<() => void>()

export function onSessionExpired(listener: () => void): () => void {
  sessionExpiredListeners.add(listener)
  return () => {
    sessionExpiredListeners.delete(listener)
  }
}

function notifySessionExpired() {
  for (const listener of sessionExpiredListeners) listener()
}

function messageFrom(payload: unknown, fallback: string): string {
  if (typeof payload === 'string') return payload
  if (payload && typeof payload === 'object' && 'detail' in payload) {
    const detail = (payload as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      const parts = detail
        .map((entry) =>
          entry && typeof entry === 'object' && 'msg' in entry
            ? String((entry as { msg: unknown }).msg)
            : null,
        )
        .filter((m): m is string => Boolean(m))
      if (parts.length) return parts.join(' ')
    }
  }
  return fallback
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH'
  body?: unknown
  auth?: boolean
  query?: Record<string, string | number | undefined | null>
  /** Handed the raw response, for the callers that need a header off it. */
  onResponse?: (response: Response) => void
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, auth = true, query, onResponse } = options

  let url = `${API_BASE_URL}${path}`
  if (query) {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
    }
    const qs = params.toString()
    if (qs) url += `?${qs}`
  }

  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  let sentToken: string | null = null
  if (auth) {
    sentToken = getToken()
    if (sentToken) headers.Authorization = `Bearer ${sentToken}`
  }

  let response: Response
  try {
    response = await fetch(url, {
      method,
      headers,
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    })
  } catch {
    // A kitchen loses its wifi more often than an office does, and the board
    // must say so rather than silently showing a stale screen forever.
    throw new ApiError('Could not reach the server.', 0)
  }

  onResponse?.(response)

  const text = await response.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }

  if (!response.ok) {
    // Only when the rejected token is still the stored one: a slow request
    // from a previous login must not sign out the account that replaced it.
    if (response.status === 401 && sentToken && sentToken === getToken()) {
      clearSession()
      notifySessionExpired()
    }
    throw new ApiError(messageFrom(payload, `Request failed (${response.status}).`), response.status)
  }
  return payload as T
}

/** A page of results, plus how many exist in total behind it. */
export interface Page<T> {
  rows: T[]
  /** `X-Total-Count`: matches the query, ignores the limit. */
  total: number
}

/**
 * Like `request`, but keeps the count the server sent alongside the page.
 *
 * `request` throws the `Response` away, which is how the board came to show
 * the oldest 100 of 206 tickets and report it as the whole queue — the number
 * that would have exposed it was in a header nothing read. Anything that
 * paginates a live queue needs this instead, so it can say when it is not
 * showing everything.
 */
async function requestPage<T>(path: string, options: RequestOptions = {}): Promise<Page<T>> {
  let total: number | null = null
  const rows = await request<T[]>(path, {
    ...options,
    onResponse: (response) => {
      const header = response.headers.get('X-Total-Count')
      const parsed = header === null ? Number.NaN : Number(header)
      total = Number.isFinite(parsed) ? parsed : null
    },
  })
  // Falling back to the page length rather than to 0: an absent or unparseable
  // header should read as "no overflow known", not as "there are none".
  return { rows, total: total ?? rows.length }
}

type AuthPayload = {
  access_token: string
  role: string
  restaurant_id: string | null
  restaurant_location_id: string | null
  user: { full_name: string }
}

const BOARD_ROLES: BoardRole[] = ['ADMIN', 'OWNER', 'KITCHEN']

export async function login(email: string, password: string): Promise<KitchenSession> {
  const payload = await request<AuthPayload>('/auth/login', {
    method: 'POST',
    body: { email, password },
    auth: false,
  })

  // Refused here as well as by every endpoint, so a customer typing their own
  // details into a kitchen tablet gets one clear sentence instead of a board
  // that loads empty and 403s on the first tap.
  if (!BOARD_ROLES.includes(payload.role as BoardRole)) {
    throw new ApiError('This screen is for kitchen staff. Ask your manager for an account.', 403)
  }

  return {
    token: payload.access_token,
    role: payload.role as BoardRole,
    fullName: payload.user.full_name,
    restaurantId: payload.restaurant_id,
    restaurantLocationId: payload.restaurant_location_id,
  }
}

export const api = {
  /**
   * The board, newest first.
   *
   * One call per status rather than one call filtered client-side: the API
   * takes `order_status`, and a busy restaurant's DELIVERED history is far
   * larger than its live queue — fetching it all to throw most of it away
   * would grow without bound over a service.
   */
  ordersByStatus: (
    status: OrderStatus,
    scope: { restaurantId?: string | null; locationId?: string | null },
    dueFrom: string,
  ) =>
    requestPage<KitchenOrder>('/orders', {
      query: {
        order_status: status,
        restaurant_id: scope.restaurantId ?? undefined,
        restaurant_location_id: scope.locationId ?? undefined,
        // Only this service's work — see `LIVE_WINDOW_HOURS`. Without it the
        // page below is a page of all history, oldest first, and a new order
        // is behind every abandoned one ever placed.
        due_from: dueFrom,
        // The API's ceiling, not a guess. Inside the window a branch is not
        // expected to come near it; `hiddenCount` reports it if one does.
        limit: 200,
        // Newest-first on the wire, oldest-first on the rail — `inServiceOrder`
        // puts it back. This is about which end the limit cuts, not about what
        // a cook sees; the reasoning is on that function.
        sort: 'placed_at:desc',
      },
    }),

  /**
   * Finished orders, most recently completed first — the history view.
   *
   * Scoped exactly like the board: the same `restaurant_id` and
   * `restaurant_location_id`, run through the same `resolve_order_board_scope`
   * on the server, so a pinned cook's history is their branch's and nothing
   * else. `completedFrom` bounds it by when an order was DELIVERED (not when
   * it was due); leave it out to search all history.
   */
  completedOrders: ({
    scope,
    completedFrom,
    search,
    limit,
    offset,
  }: {
    scope: { restaurantId?: string | null; locationId?: string | null }
    completedFrom?: string
    search?: string
    limit: number
    offset: number
  }) =>
    requestPage<KitchenOrder>('/orders', {
      query: {
        order_status: 'DELIVERED',
        restaurant_id: scope.restaurantId ?? undefined,
        restaurant_location_id: scope.locationId ?? undefined,
        completed_from: completedFrom,
        search,
        sort: 'completed_at:desc',
        limit,
        offset,
      },
    }),

  advance: (orderId: string, nextStatus: OrderStatus, restaurantId?: string | null) =>
    request<KitchenOrder>(`/orders/${orderId}/status`, {
      method: 'PATCH',
      body: { status: nextStatus },
      // Only an ADMIN needs this; an OWNER or KITCHEN account is scoped by its
      // own row and the server refuses a value that disagrees.
      query: { restaurant_id: restaurantId ?? undefined },
    }),

  restaurant: (restaurantId: string) =>
    request<RestaurantInfo>(`/restaurants/${restaurantId}`, { auth: false }).then((info) => ({
      ...info,
      locations: info.locations ?? [],
    })),
}

/**
 * GET /kitchen/menu — a dish as the kitchen sees it: stock, never prices.
 *
 * `is_available` is the owner's switch and read-only here; the kitchen
 * manages `out_of_stock` and the counts. A count of null is "not counted"
 * (unlimited) — a different fact from 0, which is sold out.
 */
export type KitchenMenuSize = {
  id: string
  name: string
  /** null: this size draws on the dish's count (or nobody counts it). */
  stock_quantity: number | null
  stock_daily_quantity: number | null
}

export type KitchenMenuItem = {
  id: string
  name: string
  category: string
  is_veg: boolean
  restaurant_location_id: string
  branch_name: string
  is_available: boolean
  out_of_stock: boolean
  stock_quantity: number | null
  stock_daily_quantity: number | null
  is_on_sale: boolean
  sizes: KitchenMenuSize[]
  updated_at: string
}

/** Only what is sent changes; null on a count stops counting. */
export type DishStockChange = {
  out_of_stock?: boolean
  stock_quantity?: number | null
  stock_daily_quantity?: number | null
}

export type SizeStockChange = {
  stock_quantity?: number | null
  stock_daily_quantity?: number | null
}

export const menuApi = {
  /** Scoped on the server by the board's own rule; a pinned cook gets one branch. */
  list: (scope: { restaurantId?: string | null; locationId?: string | null }) =>
    request<KitchenMenuItem[]>('/kitchen/menu', {
      query: {
        restaurant_id: scope.restaurantId ?? undefined,
        location_id: scope.locationId ?? undefined,
      },
    }),

  updateDish: (menuItemId: string, change: DishStockChange, restaurantId?: string | null) =>
    request<KitchenMenuItem>(`/kitchen/menu/${menuItemId}/stock`, {
      method: 'PATCH',
      body: change,
      query: { restaurant_id: restaurantId ?? undefined },
    }),

  updateSize: (
    menuItemId: string,
    sizeId: string,
    change: SizeStockChange,
    restaurantId?: string | null,
  ) =>
    request<KitchenMenuItem>(`/kitchen/menu/${menuItemId}/sizes/${sizeId}/stock`, {
      method: 'PATCH',
      body: change,
      query: { restaurant_id: restaurantId ?? undefined },
    }),
}

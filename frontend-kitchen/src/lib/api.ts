/**
 * Everything this app asks the backend for, which is deliberately very little.
 *
 * A kitchen board reads orders and advances them by one step. It does not
 * browse a menu, take payment or edit anything, and the token it holds is a
 * KITCHEN account's — pinned server-side to one restaurant and usually one
 * branch, so the scoping below is a convenience for the UI and never the rule.
 * `resolve_order_board_scope` on the backend is the rule.
 */

export const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://localhost:8000/api'

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

export type OrderLine = {
  id: string
  menu_item_id: string
  item_name_snapshot: string
  quantity: number
  unit_price: string
  total_price: string
  selected_size_name?: string | null
  selected_options?: { option_name: string; portion?: string | null }[] | null
  special_instructions?: string | null
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
    if (response.status === 401 && sentToken) clearSession()
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

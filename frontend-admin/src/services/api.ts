import type {
  AdminAILog,
  AdminAIOfferGenerationStatusResponse,
  AdminAIOfferGenerationTriggerResponse,
  AdminCreateRestaurantPayload,
  AdminCreateRestaurantResult,
  AdminDashboardStats,
  AppClient,
  AppClientUpsertPayload,
  ReportsSnapshot,
  GeneratedCombo,
  AdminMenuItem,
  AuthResponse,
  GeneratedOfferUserMatch,
  ManagedPersonalizedOffer,
  MenuItem,
  MenuItemBulkCreateResult,
  MenuItemUpsertPayload,
  Order,
  OrderStatus,
  RestaurantDetail,
  LocationFulfillmentSlot,
  RestaurantLocation,
  Restaurant,
  SendNotificationPayload,
  SendNotificationResponse,
  NotificationHistoryItem,
  User,
  DiagnosticsSnapshot,
  OfferPerformanceSnapshot,
  OwnerActionApproval,
  OwnerActionProposal,
  OwnerBriefing,
  OwnerChatAnswer,
  OwnerChatClearResult,
  OwnerChatHistoryItem,
  OwnerInsight,
  OwnerInsightStatus,
  ActionOutcome,
} from '../types/app';

// Imported for the fetch calls below AND re-exported, because
// services/aiManagerStream.ts already imports API_BASE_URL from this module:
// the public surface stays exactly as it was, while the value itself now comes
// from the single config module.
import { API_BASE_URL } from '../config/api';

export { API_BASE_URL };

export const AUTH_INVALID_EVENT = 'restaurant-rag-admin-auth-invalid';

export class ApiError extends Error {
  status: number;
  detail?: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  token?: string | null;
  body?: unknown;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers();
  if (options.body !== undefined) {
    headers.set('Content-Type', 'application/json');
  }
  if (options.token) {
    headers.set('Authorization', `Bearer ${options.token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    // Expired/invalid sessions redirect to login instead of dead-ending in
    // repeated error toasts. Login failures (/auth/*) keep their own message.
    if (response.status === 401 && !path.startsWith('/auth/')) {
      window.dispatchEvent(new CustomEvent(AUTH_INVALID_EVENT));
      throw new ApiError('Your session has expired. Please sign in again.', 401);
    }
    const rawDetail: unknown = payload.detail;
    const detailMessage =
      typeof rawDetail === 'string'
        ? rawDetail
        : rawDetail !== null &&
            typeof rawDetail === 'object' &&
            typeof (rawDetail as { message?: unknown }).message === 'string'
          ? (rawDetail as { message: string }).message
          : typeof payload.message === 'string'
            ? payload.message
            : 'Something went wrong';
    throw new ApiError(detailMessage, response.status, rawDetail);
  }

  return payload as T;
}

function scopeQuery(restaurantId?: string | null): string {
  return restaurantId ? `?restaurant_id=${encodeURIComponent(restaurantId)}` : '';
}

export const api = {
  login(input: { email: string; password: string }): Promise<AuthResponse> {
    return request<AuthResponse>('/auth/login', { method: 'POST', body: input });
  },
  getAdminDashboard(token: string): Promise<AdminDashboardStats> {
    return request<AdminDashboardStats>('/admin/dashboard', { token });
  },
  getReports(
    token: string,
    filters: {
      dateFrom?: string | null;
      dateTo?: string | null;
      restaurantId?: string | null;
      cuisineType?: string | null;
      category?: string | null;
      orderStatus?: OrderStatus | null;
    },
  ): Promise<ReportsSnapshot> {
    const params = new URLSearchParams();
    if (filters.dateFrom) {
      params.set('date_from', filters.dateFrom);
    }
    if (filters.dateTo) {
      params.set('date_to', filters.dateTo);
    }
    if (filters.restaurantId) {
      params.set('restaurant_id', filters.restaurantId);
    }
    if (filters.cuisineType) {
      params.set('cuisine_type', filters.cuisineType);
    }
    if (filters.category) {
      params.set('category', filters.category);
    }
    if (filters.orderStatus) {
      params.set('order_status', filters.orderStatus);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<ReportsSnapshot>(`/reports${suffix}`, { token });
  },
  getAdminRestaurants(token: string): Promise<Restaurant[]> {
    return request<Restaurant[]>('/admin/restaurants', { token });
  },
  getAdminMenuItems(token: string): Promise<AdminMenuItem[]> {
    return request<AdminMenuItem[]>('/admin/menu-items', { token });
  },
  getAdminAILogs(token: string): Promise<AdminAILog[]> {
    return request<AdminAILog[]>('/admin/ai-logs', { token });
  },
  triggerAdminAIOfferGeneration(
    token: string,
    payload: {
      user_limit?: number | null;
      batch_size?: number | null;
      force_refresh?: boolean;
    } = {},
  ): Promise<AdminAIOfferGenerationTriggerResponse> {
    return request<AdminAIOfferGenerationTriggerResponse>('/admin/offers/generate-ai', {
      method: 'POST',
      token,
      body: payload,
    });
  },
  getAdminAIOfferGenerationStatus(
    token: string,
    taskId: string,
  ): Promise<AdminAIOfferGenerationStatusResponse> {
    return request<AdminAIOfferGenerationStatusResponse>(`/admin/offers/generate-ai/${taskId}`, { token });
  },
  getManagedGeneratedCombos(token: string, restaurantId?: string, locationId?: string | null): Promise<GeneratedCombo[]> {
    const params = new URLSearchParams();
    if (restaurantId) {
      params.set('restaurant_id', restaurantId);
    }
    if (locationId) {
      params.set('location_id', locationId);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<GeneratedCombo[]>(`/admin/generated-combos${suffix}`, { token });
  },
  getRestaurantLocations(token: string, restaurantId: string): Promise<RestaurantLocation[]> {
    return request<RestaurantLocation[]>(`/restaurants/${restaurantId}/locations`, {token});
  },
  getRestaurantMenuItems(
    token: string,
    restaurantId: string,
    locationId?: string | null,
  ): Promise<MenuItem[]> {
    const params = new URLSearchParams({
      restaurant_id: restaurantId,
      include_unavailable: 'true',
    });
    if (locationId) {
      params.set('location_id', locationId);
    }
    return request<MenuItem[]>(`/menu-items?${params.toString()}`, { token });
  },
  getRestaurantOffers(token: string, restaurantId: string): Promise<ManagedPersonalizedOffer[]> {
    return request<ManagedPersonalizedOffer[]>(`/restaurants/${restaurantId}/offers`, { token });
  },
  createRestaurantOffer(
    token: string,
    restaurantId: string,
    payload: {
      name: string;
      offer_type: string;
      state: string;
      restaurant_location_id?: string | null;
      applicable_item_id?: string | null;
      applicable_category?: string | null;
      applicable_cuisine?: string | null;
      discount_type: string;
      discount_value: number;
      max_discount_amount?: number | null;
      minimum_order_amount: number;
      inactivity_days: number;
      cooldown_hours: number;
      valid_for_days: number;
      cta_label?: string | null;
      business_rules?: Record<string, unknown>;
      notes?: string | null;
      starts_at?: string | null;
      expires_at?: string | null;
    },
  ): Promise<ManagedPersonalizedOffer> {
    return request<ManagedPersonalizedOffer>(`/restaurants/${restaurantId}/offers`, {
      method: 'POST',
      token,
      body: payload,
    });
  },
  updateRestaurantOffer(
    token: string,
    restaurantId: string,
    offerId: string,
    payload: {
      name: string;
      offer_type: string;
      state: string;
      restaurant_location_id?: string | null;
      applicable_item_id?: string | null;
      applicable_category?: string | null;
      applicable_cuisine?: string | null;
      discount_type: string;
      discount_value: number;
      max_discount_amount?: number | null;
      minimum_order_amount: number;
      inactivity_days: number;
      cooldown_hours: number;
      valid_for_days: number;
      cta_label?: string | null;
      business_rules?: Record<string, unknown>;
      notes?: string | null;
      starts_at?: string | null;
      expires_at?: string | null;
    },
  ): Promise<ManagedPersonalizedOffer> {
    return request<ManagedPersonalizedOffer>(`/restaurants/${restaurantId}/offers/${offerId}`, {
      method: 'PATCH',
      token,
      body: payload,
    });
  },
  deleteRestaurantOffer(
    token: string,
    restaurantId: string,
    offerId: string,
  ): Promise<void> {
    return request<void>(`/restaurants/${restaurantId}/offers/${offerId}`, {
      method: 'DELETE',
      token,
    });
  },
  getGeneratedOfferMatches(
    token: string,
    restaurantId: string,
    generatedOfferId: string,
  ): Promise<GeneratedOfferUserMatch[]> {
    return request<GeneratedOfferUserMatch[]>(
      `/restaurants/${restaurantId}/generated-offers/${generatedOfferId}/matches`,
      { token },
    );
  },
  updateGeneratedOfferState(
    token: string,
    restaurantId: string,
    generatedOfferId: string,
    payload: {
      state?: string | null;
      title?: string | null;
      subtitle?: string | null;
      badge?: string | null;
      cta_label?: string | null;
      starts_at?: string | null;
      expires_at?: string | null;
    },
  ): Promise<ManagedPersonalizedOffer> {
    return request<ManagedPersonalizedOffer>(
      `/restaurants/${restaurantId}/generated-offers/${generatedOfferId}`,
      {
        method: 'PATCH',
        token,
        body: payload,
      },
    );
  },
  deleteGeneratedOffer(
    token: string,
    restaurantId: string,
    generatedOfferId: string,
  ): Promise<void> {
    return request<void>(`/restaurants/${restaurantId}/generated-offers/${generatedOfferId}`, {
      method: 'DELETE',
      token,
    });
  },
  createRestaurantLocation(
    token: string,
    restaurantId: string,
    payload: {
      branch_name: string;
      address_line_1: string;
      address_line_2?: string | null;
      city: string;
      state: string;
      postal_code: string;
      latitude?: number | null;
      longitude?: number | null;
      phone_number?: string | null;
      delivery_fee: number;
      minimum_order_amount: number;
      estimated_delivery_time: number;
      estimated_pickup_time?: number;
      delivery_enabled?: boolean;
      pickup_enabled?: boolean;
      is_open: boolean;
      is_active: boolean;
      temporary_closed_reason?: string | null;
      preparation_time_minutes?: number | null;
      service_radius_km?: number | null;
      opening_time?: string | null;
      closing_time?: string | null;
    },
  ): Promise<RestaurantLocation> {
    return request<RestaurantLocation>(`/restaurants/${restaurantId}/locations`, {
      method: 'POST',
      token,
      body: payload,
    });
  },
  updateRestaurantLocation(
    token: string,
    restaurantId: string,
    locationId: string,
    payload: Record<string, unknown>,
  ): Promise<RestaurantLocation> {
    return request<RestaurantLocation>(`/restaurants/${restaurantId}/locations/${locationId}`, {
      method: 'PATCH',
      token,
      body: payload,
    });
  },
  getRestaurantLocationGeneralSettings(
    token: string,
    restaurantId: string,
    locationId: string,
  ): Promise<RestaurantLocation> {
    return request<RestaurantLocation>(
      `/restaurants/${restaurantId}/locations/${locationId}/general-settings`,
      { token },
    );
  },
  updateRestaurantLocationGeneralSettings(
    token: string,
    restaurantId: string,
    locationId: string,
    payload: Record<string, unknown>,
  ): Promise<RestaurantLocation> {
    return request<RestaurantLocation>(
      `/restaurants/${restaurantId}/locations/${locationId}/general-settings`,
      {
        method: 'PATCH',
        token,
        body: payload,
      },
    );
  },
  getRestaurantLocationSlots(
    token: string,
    restaurantId: string,
    locationId: string,
  ): Promise<LocationFulfillmentSlot[]> {
    return request<LocationFulfillmentSlot[]>(
      `/restaurants/${restaurantId}/locations/${locationId}/slots`,
      { token },
    );
  },
  createRestaurantLocationSlot(
    token: string,
    restaurantId: string,
    locationId: string,
    payload: {
      day_of_week: string;
      fulfillment_type: 'DELIVERY' | 'PICKUP';
      start_time: string;
      end_time: string;
      is_active?: boolean;
    },
  ): Promise<LocationFulfillmentSlot> {
    return request<LocationFulfillmentSlot>(
      `/restaurants/${restaurantId}/locations/${locationId}/slots`,
      {
        method: 'POST',
        token,
        body: payload,
      },
    );
  },
  updateRestaurantLocationSlot(
    token: string,
    restaurantId: string,
    locationId: string,
    slotId: string,
    payload: Record<string, unknown>,
  ): Promise<LocationFulfillmentSlot> {
    return request<LocationFulfillmentSlot>(
      `/restaurants/${restaurantId}/locations/${locationId}/slots/${slotId}`,
      {
        method: 'PATCH',
        token,
        body: payload,
      },
    );
  },
  deleteRestaurantLocationSlot(
    token: string,
    restaurantId: string,
    locationId: string,
    slotId: string,
  ): Promise<LocationFulfillmentSlot> {
    return request<LocationFulfillmentSlot>(
      `/restaurants/${restaurantId}/locations/${locationId}/slots/${slotId}`,
      {
        method: 'DELETE',
        token,
      },
    );
  },
  deactivateRestaurantLocation(
    token: string,
    restaurantId: string,
    locationId: string,
  ): Promise<RestaurantLocation> {
    return request<RestaurantLocation>(`/restaurants/${restaurantId}/locations/${locationId}`, {
      method: 'DELETE',
      token,
    });
  },
  rebuildAdminGeneratedCombos(
    token: string,
    lookbackDays?: number,
  ): Promise<{
    created_count: number;
    updated_count: number;
    deactivated_count: number;
    scanned_order_count: number;
    eligible_pattern_count: number;
  }> {
    const suffix = lookbackDays ? `?lookback_days=${lookbackDays}` : '';
    return request(`/admin/generated-combos/rebuild${suffix}`, {
      method: 'POST',
      token,
    });
  },
  updateGeneratedComboStatus(
    token: string,
    comboId: string,
    status: 'DRAFT' | 'LIVE' | 'ARCHIVED',
  ): Promise<GeneratedCombo> {
    return request<GeneratedCombo>(`/admin/generated-combos/${comboId}/status`, {
      method: 'PATCH',
      token,
      body: { status },
    });
  },
  getAdminRestaurant(token: string, restaurantId: string): Promise<RestaurantDetail> {
    return request<RestaurantDetail>(`/admin/restaurants/${restaurantId}`, { token });
  },
  getRestaurant(token: string, restaurantId: string): Promise<RestaurantDetail> {
    return request<RestaurantDetail>(`/restaurants/${restaurantId}`, { token });
  },
  updateRestaurantSettings(
    token: string,
    restaurantId: string,
    payload: {
      name?: string;
      description?: string | null;
      cuisine_type?: string;
      address_line_1?: string;
      address_line_2?: string | null;
      city?: string;
      state?: string;
      country?: string;
      postal_code?: string;
      phone_number?: string | null;
      logo_image_url?: string | null;
      cover_image_url?: string | null;
      is_open?: boolean;
      is_active?: boolean;
    },
  ): Promise<RestaurantDetail> {
    return request<RestaurantDetail>(`/restaurants/${restaurantId}/settings`, {
      method: 'PATCH',
      token,
      body: payload,
    });
  },
  updateRestaurantApproval(token: string, restaurantId: string, isApproved: boolean): Promise<Restaurant> {
    return request<Restaurant>(`/admin/restaurants/${restaurantId}/approval`, {
      method: 'PATCH',
      token,
      body: { is_approved: isApproved },
    });
  },
  updateRestaurant(
    token: string,
    restaurantId: string,
    payload: {
      name: string;
      description?: string | null;
      cuisine_type: string;
      address_line_1: string;
      address_line_2?: string | null;
      city: string;
      state: string;
      country: string;
      postal_code: string;
      phone_number?: string | null;
      minimum_order_amount: number;
      delivery_fee: number;
      logo_image_url?: string | null;
      cover_image_url?: string | null;
      is_open: boolean;
    },
  ): Promise<Restaurant> {
    return request<Restaurant>(`/admin/restaurants/${restaurantId}`, {
      method: 'PATCH',
      token,
      body: payload,
    });
  },
  deleteRestaurant(token: string, restaurantId: string): Promise<void> {
    return request<void>(`/admin/restaurants/${restaurantId}`, { method: 'DELETE', token });
  },
  getAdminUsers(token: string): Promise<User[]> {
    return request<User[]>('/admin/users', { token });
  },
  getAdminUser(token: string, userId: string): Promise<User> {
    return request<User>(`/admin/users/${userId}`, { token });
  },
  updateAdminUserDetails(
    token: string,
    userId: string,
    payload: { full_name: string; phone_number: string | null; default_address: string | null },
  ): Promise<User> {
    return request<User>(`/admin/users/${userId}/details`, {
      method: 'PATCH',
      token,
      body: payload,
    });
  },
  updateUserStatus(token: string, userId: string, isActive: boolean): Promise<User> {
    return request<User>(`/admin/users/${userId}`, {
      method: 'PATCH',
      token,
      body: { is_active: isActive },
    });
  },
  sendNotification(
    token: string,
    payload: SendNotificationPayload,
  ): Promise<SendNotificationResponse> {
    return request<SendNotificationResponse>('/admin/notifications/send', {
      method: 'POST',
      token,
      body: payload,
    });
  },
  getNotificationHistory(token: string): Promise<NotificationHistoryItem[]> {
    return request<NotificationHistoryItem[]>('/admin/notifications/history', {
      token,
    });
  },
  getOwnerRestaurants(token: string): Promise<Restaurant[]> {
    return request<Restaurant[]>('/restaurants/mine', { token });
  },
  createRestaurant(
    token: string,
    payload: AdminCreateRestaurantPayload,
  ): Promise<AdminCreateRestaurantResult> {
    return request<AdminCreateRestaurantResult>('/restaurants', { method: 'POST', token, body: payload });
  },
  /** Resolves to null when the restaurant has no app client yet. */
  async getRestaurantAppClient(token: string, restaurantId: string): Promise<AppClient | null> {
    try {
      return await request<AppClient>(`/restaurants/${restaurantId}/app-client`, { token });
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 404) {
        return null;
      }
      throw error;
    }
  },
  saveRestaurantAppClient(
    token: string,
    restaurantId: string,
    payload: AppClientUpsertPayload,
  ): Promise<AppClient> {
    return request<AppClient>(`/restaurants/${restaurantId}/app-client`, {
      method: 'PUT',
      token,
      body: payload,
    });
  },
  getMenuItems(token: string, restaurantId: string, locationId?: string | null): Promise<MenuItem[]> {
    const params = new URLSearchParams({
      restaurant_id: restaurantId,
      include_unavailable: 'true',
    });
    if (locationId) {
      params.set('location_id', locationId);
    }
    return request<MenuItem[]>(`/menu-items?${params.toString()}`, { token });
  },
  createMenuItem(
    token: string,
    payload: MenuItemUpsertPayload & {
      restaurant_id: string;
      restaurant_location_id?: string | null;
    },
  ): Promise<MenuItem> {
    return request<MenuItem>('/menu-items', { method: 'POST', token, body: payload });
  },
  createMenuItemsBulk(
    token: string,
    payload: MenuItemUpsertPayload & {
      restaurant_id: string;
      restaurant_location_ids: string[];
      skip_duplicates?: boolean;
    },
  ): Promise<MenuItemBulkCreateResult> {
    return request<MenuItemBulkCreateResult>('/menu-items/bulk', {
      method: 'POST',
      token,
      body: payload,
    });
  },
  updateMenuItem(
    token: string,
    menuItemId: string,
    payload: MenuItemUpsertPayload & {
      restaurant_location_id?: string | null;
    },
  ): Promise<MenuItem> {
    return request<MenuItem>(`/menu-items/${menuItemId}`, { method: 'PUT', token, body: payload });
  },
  updateMenuItemAvailability(token: string, menuItemId: string, isAvailable: boolean): Promise<MenuItem> {
    return request<MenuItem>(`/menu-items/${menuItemId}/availability`, {
      method: 'PATCH',
      token,
      body: { is_available: isAvailable },
    });
  },
  deleteMenuItem(token: string, menuItemId: string): Promise<void> {
    return request<void>(`/menu-items/${menuItemId}`, { method: 'DELETE', token });
  },
  getOrders(token: string, restaurantId?: string, locationId?: string | null): Promise<Order[]> {
    const params = new URLSearchParams();
    if (restaurantId) {
      params.set('restaurant_id', restaurantId);
    }
    if (locationId) {
      params.set('restaurant_location_id', locationId);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<Order[]>(`/orders${suffix}`, { token });
  },
  async getOrdersPage(
    token: string,
    opts: {
      page: number;
      pageSize: number;
      search?: string;
      status?: OrderStatus | null;
      sort?: { id: string; direction: 'asc' | 'desc' } | null;
    },
  ): Promise<{ rows: Order[]; total: number }> {
    const params = new URLSearchParams({
      limit: String(opts.pageSize),
      offset: String((opts.page - 1) * opts.pageSize),
    });
    if (opts.search) {
      params.set('search', opts.search);
    }
    if (opts.status) {
      params.set('order_status', opts.status);
    }
    if (opts.sort) {
      params.set('sort', `${opts.sort.id}:${opts.sort.direction}`);
    }
    const headers = new Headers({ Authorization: `Bearer ${token}` });
    const response = await fetch(`${API_BASE_URL}/orders?${params.toString()}`, { headers });
    if (response.status === 401) {
      window.dispatchEvent(new CustomEvent(AUTH_INVALID_EVENT));
      throw new ApiError('Your session has expired. Please sign in again.', 401);
    }
    const payload = await response.json().catch(() => []);
    if (!response.ok) {
      const detail = typeof payload.detail === 'string' ? payload.detail : 'Unable to load orders.';
      throw new ApiError(detail, response.status);
    }
    const total = Number(response.headers.get('X-Total-Count') ?? payload.length);
    return { rows: payload as Order[], total };
  },
  async getOrdersCount(
    token: string,
    opts: { search?: string; status?: OrderStatus | null } = {},
  ): Promise<number> {
    const params = new URLSearchParams({ limit: '1', offset: '0' });
    if (opts.search) {
      params.set('search', opts.search);
    }
    if (opts.status) {
      params.set('order_status', opts.status);
    }
    const headers = new Headers({ Authorization: `Bearer ${token}` });
    const response = await fetch(`${API_BASE_URL}/orders?${params.toString()}`, { headers });
    if (!response.ok) {
      return 0;
    }
    await response.json().catch(() => null);
    return Number(response.headers.get('X-Total-Count') ?? 0);
  },
  getOrder(token: string, orderId: string): Promise<Order> {
    return request<Order>(`/orders/${orderId}`, { token });
  },
  updateOrderStatus(token: string, orderId: string, status: OrderStatus): Promise<Order> {
    return request<Order>(`/orders/${orderId}/status`, {
      method: 'PATCH',
      token,
      body: { status },
    });
  },
  // --- AI Restaurant Manager ------------------------------------------------
  // `restaurantId` is required for ADMIN and ignored for OWNER: the backend
  // pins an owner to their own restaurant and rejects any other value.

  getOwnerBriefing(
    token: string,
    restaurantId?: string | null,
    // Naming a period returns a briefing for exactly that period, computed on
    // the spot. Without one the stored nightly briefing comes back, which may
    // describe a different window than the rest of the screen.
    options: { windowDays?: number | null } = {},
  ): Promise<OwnerBriefing> {
    const params = new URLSearchParams();
    if (restaurantId) {
      params.set('restaurant_id', restaurantId);
    }
    if (options.windowDays) {
      params.set('window_days', String(options.windowDays));
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<OwnerBriefing>(`/owner/insights/briefing${suffix}`, { token });
  },
  getOwnerDiagnostics(
    token: string,
    options: {
      restaurantId?: string | null;
      windowDays?: number | null;
      // Used to align the KPI row with the briefing's own period. Without it the
      // two halves of the card can describe different windows.
      dateFrom?: string | null;
      dateTo?: string | null;
    } = {},
  ): Promise<DiagnosticsSnapshot> {
    const params = new URLSearchParams();
    if (options.restaurantId) {
      params.set('restaurant_id', options.restaurantId);
    }
    if (options.windowDays) {
      params.set('window_days', String(options.windowDays));
    }
    if (options.dateFrom) {
      params.set('date_from', options.dateFrom);
    }
    if (options.dateTo) {
      params.set('date_to', options.dateTo);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<DiagnosticsSnapshot>(`/owner/insights/diagnostics${suffix}`, { token });
  },
  getOwnerInsightFeed(
    token: string,
    // The period makes this and the briefing read from one analysis. Without
    // it the feed lists stored rows from whatever window the nightly run chose,
    // which is how a briefing could narrate findings the feed said did not exist.
    options: { restaurantId?: string | null; limit?: number; windowDays?: number | null } = {},
  ): Promise<OwnerInsight[]> {
    const params = new URLSearchParams();
    if (options.restaurantId) {
      params.set('restaurant_id', options.restaurantId);
    }
    if (options.windowDays) {
      params.set('window_days', String(options.windowDays));
    }
    if (options.limit) {
      params.set('limit', String(options.limit));
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<OwnerInsight[]>(`/owner/insights/feed${suffix}`, { token });
  },
  updateOwnerInsightStatus(
    token: string,
    insightId: string,
    status: OwnerInsightStatus,
    restaurantId?: string | null,
  ): Promise<OwnerInsight> {
    return request<OwnerInsight>(
      `/owner/insights/feed/${insightId}${scopeQuery(restaurantId)}`,
      { method: 'PATCH', token, body: { status } },
    );
  },
  getOwnerRecommendations(
    token: string,
    options: { restaurantId?: string | null; statuses?: string[] } = {},
  ): Promise<OwnerActionProposal[]> {
    const params = new URLSearchParams();
    if (options.restaurantId) {
      params.set('restaurant_id', options.restaurantId);
    }
    for (const status of options.statuses ?? []) {
      params.append('action_status', status);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<OwnerActionProposal[]>(`/owner/insights/recommendations${suffix}`, {
      token,
    });
  },
  approveOwnerRecommendation(
    token: string,
    proposalId: string,
    restaurantId?: string | null,
  ): Promise<OwnerActionApproval> {
    return request<OwnerActionApproval>(
      `/owner/insights/recommendations/${proposalId}/approve${scopeQuery(restaurantId)}`,
      { method: 'POST', token },
    );
  },
  rejectOwnerRecommendation(
    token: string,
    proposalId: string,
    restaurantId?: string | null,
  ): Promise<OwnerActionProposal> {
    return request<OwnerActionProposal>(
      `/owner/insights/recommendations/${proposalId}/reject${scopeQuery(restaurantId)}`,
      { method: 'POST', token },
    );
  },
  getOwnerOfferPerformance(
    token: string,
    options: { restaurantId?: string | null; windowDays?: number | null } = {},
  ): Promise<OfferPerformanceSnapshot> {
    const params = new URLSearchParams();
    if (options.restaurantId) {
      params.set('restaurant_id', options.restaurantId);
    }
    if (options.windowDays) {
      params.set('window_days', String(options.windowDays));
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<OfferPerformanceSnapshot>(
      `/owner/insights/offer-performance${suffix}`,
      { token },
    );
  },
  getOwnerActionOutcomes(
    token: string,
    options: { restaurantId?: string | null; limit?: number } = {},
  ): Promise<ActionOutcome[]> {
    const params = new URLSearchParams();
    if (options.restaurantId) {
      params.set('restaurant_id', options.restaurantId);
    }
    if (options.limit) {
      params.set('limit', String(options.limit));
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<ActionOutcome[]>(`/owner/insights/outcomes${suffix}`, { token });
  },
  sendOwnerChatMessage(
    token: string,
    input: { message: string; sessionId?: string | null; restaurantId?: string | null },
  ): Promise<OwnerChatAnswer> {
    return request<OwnerChatAnswer>('/owner/insights/chat/message', {
      method: 'POST',
      token,
      body: {
        message: input.message,
        session_id: input.sessionId ?? null,
        restaurant_id: input.restaurantId ?? null,
      },
    });
  },
  getOwnerChatHistory(
    token: string,
    options: { restaurantId?: string | null; sessionId?: string | null } = {},
  ): Promise<OwnerChatHistoryItem[]> {
    const params = new URLSearchParams();
    if (options.restaurantId) {
      params.set('restaurant_id', options.restaurantId);
    }
    if (options.sessionId) {
      params.set('session_id', options.sessionId);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<OwnerChatHistoryItem[]>(`/owner/insights/chat/history${suffix}`, {
      token,
    });
  },
  clearOwnerChatHistory(
    token: string,
    options: { restaurantId?: string | null; sessionId?: string | null } = {},
  ): Promise<OwnerChatClearResult> {
    const params = new URLSearchParams();
    if (options.restaurantId) {
      params.set('restaurant_id', options.restaurantId);
    }
    if (options.sessionId) {
      params.set('session_id', options.sessionId);
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request<OwnerChatClearResult>(`/owner/insights/chat/history${suffix}`, {
      method: 'DELETE',
      token,
    });
  },
};


export function toNumber(value: number | string): number {
  return typeof value === 'number' ? value : Number(value);
}

export function formatCurrency(value: number | string): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
  }).format(toNumber(value));
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

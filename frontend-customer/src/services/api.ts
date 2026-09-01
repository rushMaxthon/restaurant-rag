import type {
  AppConfig,
  AuthResponse,
  BudgetTier,
  ChatHistoryItem,
  ChatMessageRequest,
  ChatMessageResponse,
  ChatSuggestionItem,
  ComboUpsellSuggestion,
  DecimalValue,
  DietPreference,
  FavoriteItem,
  GeneratedCombo,
  MenuItem,
  Order,
  PersonalizedOfferCard,
  PersonalizedOfferItemAvailability,
  PersonalizedOfferPreview,
  ProfileSummary,
  ProfileUpdatePayload,
  RecommendationItem,
  Restaurant,
  RestaurantLocation,
  SpiceLevel,
  UserPreferences,
} from '../types/app';

// Single source of truth for which backend this app talks to. Stays
// module-private, exactly as before — nothing outside this file used it.
import { API_BASE_URL, APP_BUNDLE_ID } from '../config/api';
export const AUTH_INVALID_EVENT = 'restaurant-rag-auth-invalid';

class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function hasMeaningfulPreferences(preferences?: UserPreferences | null): boolean {
  return Boolean(
    preferences &&
      (preferences.cuisines.length > 0 ||
        preferences.favorite_items.length > 0 ||
        preferences.diet ||
        preferences.spice_level ||
        preferences.budget),
  );
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  token?: string | null;
  signal?: AbortSignal;
  timeoutMs?: number;
};

type StreamMetaPayload = {
  session_id: string;
  suggestions: ChatSuggestionItem[];
  combo_suggestions: GeneratedCombo[];
  offer_suggestions: PersonalizedOfferCard[];
};

type ChatStreamHandlers = {
  onMeta?: (payload: StreamMetaPayload) => void;
  onToken?: (text: string) => void;
  onDone?: (payload: ChatMessageResponse) => void;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers();
  if (options.body !== undefined) {
    headers.set('Content-Type', 'application/json');
  }
  if (options.token) {
    headers.set('Authorization', `Bearer ${options.token}`);
  }

  const timeoutMs = options.timeoutMs ?? 15000;
  const controller = new AbortController();
  let timedOut = false;
  const handleExternalAbort = () => controller.abort(options.signal?.reason);
  if (options.signal) {
    if (options.signal.aborted) {
      controller.abort(options.signal.reason);
    } else {
      options.signal.addEventListener('abort', handleExternalAbort, { once: true });
    }
  }
  const timeoutId = window.setTimeout(() => {
    timedOut = true;
    controller.abort(new DOMException('Request timed out', 'AbortError'));
  }, timeoutMs);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: options.method ?? 'GET',
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });
  } catch (error) {
    if (timedOut) {
      throw new ApiError('The request took too long. Please try again.', 408);
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
    if (options.signal) {
      options.signal.removeEventListener('abort', handleExternalAbort);
    }
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail =
      typeof payload.detail === 'string'
        ? payload.detail
        : typeof payload.message === 'string'
          ? payload.message
          : 'Something went wrong';
    if (response.status === 401 && options.token && typeof window !== 'undefined') {
      window.dispatchEvent(
        new CustomEvent(AUTH_INVALID_EVENT, {
          detail: {
            path,
            status: response.status,
          },
        }),
      );
    }
    throw new ApiError(detail, response.status);
  }

  return payload as T;
}

export const api = {
  async register(input: {
    full_name: string;
    email: string;
    password: string;
    phone_number?: string | null;
    default_address?: string | null;
  }): Promise<AuthResponse> {
    return request<AuthResponse>('/auth/register', {
      method: 'POST',
      body: { ...input, role: 'CUSTOMER' },
    });
  },
  async login(input: { email: string; password: string }): Promise<AuthResponse> {
    return request<AuthResponse>('/auth/login', {
      method: 'POST',
      body: input,
    });
  },
  /**
   * This build's app configuration.
   *
   * Public and unauthenticated on purpose - it is what tells the app which
   * restaurant it is before anyone has logged in. Sent as a query parameter
   * rather than the `X-App-Bundle-Id` header; see `config/api.ts` for why that
   * distinction is load-bearing for existing accounts.
   */
  async getAppConfig(signal?: AbortSignal): Promise<AppConfig> {
    return request<AppConfig>(
      `/app-config?bundle_id=${encodeURIComponent(APP_BUNDLE_ID)}`,
      { signal },
    );
  },
  async getRestaurants(): Promise<Restaurant[]> {
    return request<Restaurant[]>('/restaurants');
  },
  async getRestaurant(restaurantId: string, signal?: AbortSignal): Promise<Restaurant> {
    return request<Restaurant>(`/restaurants/${encodeURIComponent(restaurantId)}`, {
      signal,
      timeoutMs: 10000,
    });
  },
  async getRestaurantLocations(
    restaurantId: string,
    token?: string | null,
    signal?: AbortSignal,
  ): Promise<RestaurantLocation[]> {
    try {
      return await request<RestaurantLocation[]>(
        `/restaurants/${encodeURIComponent(restaurantId)}/locations`,
        {
          token,
          signal,
          timeoutMs: 10000,
        },
      );
    } catch (error) {
      if (token && error instanceof ApiError && error.status === 401) {
        return request<RestaurantLocation[]>(
          `/restaurants/${encodeURIComponent(restaurantId)}/locations`,
          {
            signal,
            timeoutMs: 10000,
          },
        );
      }
      throw error;
    }
  },
  async getMenuItems(
    restaurantId: string,
    token?: string | null,
    signal?: AbortSignal,
    locationId?: string | null,
  ): Promise<MenuItem[]> {
    const query = new URLSearchParams({ restaurant_id: restaurantId });
    if (locationId) {
      query.set('location_id', locationId);
    }
    try {
      return await request<MenuItem[]>(`/menu-items?${query.toString()}`, {
        token,
        signal,
        timeoutMs: 10000,
      });
    } catch (error) {
      if (token && error instanceof ApiError && error.status === 401) {
        return request<MenuItem[]>(`/menu-items?${query.toString()}`, {
          signal,
          timeoutMs: 10000,
        });
      }
      throw error;
    }
  },
  async getMenuItem(menuItemId: string, token?: string | null, signal?: AbortSignal): Promise<MenuItem> {
    try {
      return await request<MenuItem>(`/menu-items/${encodeURIComponent(menuItemId)}`, {
        token,
        signal,
        timeoutMs: 10000,
      });
    } catch (error) {
      if (token && error instanceof ApiError && error.status === 401) {
        return request<MenuItem>(`/menu-items/${encodeURIComponent(menuItemId)}`, {
          signal,
          timeoutMs: 10000,
        });
      }
      throw error;
    }
  },
  async getRecommendations(token: string): Promise<RecommendationItem[]> {
    return request<RecommendationItem[]>('/recommendations', { token });
  },
  async getFavorites(token: string): Promise<FavoriteItem[]> {
    return request<FavoriteItem[]>('/favorites', { token });
  },
  async getFavoriteIds(token: string): Promise<string[]> {
    return request<string[]>('/favorites/ids', { token });
  },
  async addFavorite(token: string, menuItemId: string): Promise<{ menu_item_id: string; is_favorite: boolean }> {
    return request<{ menu_item_id: string; is_favorite: boolean }>(`/favorites/${encodeURIComponent(menuItemId)}`, {
      method: 'POST',
      token,
    });
  },
  async removeFavorite(token: string, menuItemId: string): Promise<{ menu_item_id: string; is_favorite: boolean }> {
    return request<{ menu_item_id: string; is_favorite: boolean }>(`/favorites/${encodeURIComponent(menuItemId)}`, {
      method: 'DELETE',
      token,
    });
  },
  async getGeneratedCombos(limit = 12): Promise<GeneratedCombo[]> {
    return request<GeneratedCombo[]>(`/generated-combos?limit=${limit}`);
  },
  async getRestaurantGeneratedCombos(
    restaurantId: string,
    limit = 12,
    locationId?: string | null,
  ): Promise<GeneratedCombo[]> {
    const query = new URLSearchParams({ limit: String(limit) });
    if (locationId) {
      query.set('location_id', locationId);
    }
    return request<GeneratedCombo[]>(
      `/restaurants/${encodeURIComponent(restaurantId)}/generated-combos?${query.toString()}`,
    );
  },
  async getCartUpsellSuggestions(options: {
    restaurantId: string;
    locationId?: string | null;
    itemId: string;
    cartItemIds?: string[];
    limit?: number;
  }): Promise<ComboUpsellSuggestion[]> {
    const params = new URLSearchParams({
      restaurant_id: options.restaurantId,
      item_id: options.itemId,
      limit: String(options.limit ?? 3),
    });
    if (options.locationId) {
      params.set('location_id', options.locationId);
    }
    for (const cartItemId of options.cartItemIds ?? []) {
      params.append('cart_item_ids', cartItemId);
    }
    return request<ComboUpsellSuggestion[]>(`/cart/upsell-suggestions?${params.toString()}`);
  },
  async getRecommendationsForContext(options: {
    token?: string | null;
    preferences?: UserPreferences | null;
    dedupeMultiLocation?: boolean;
  }): Promise<RecommendationItem[]> {
    const payload = {
      preferences: options.preferences
        ? normalizePreferencesPayload(options.preferences)
        : null,
      dedupe_multi_location: options.dedupeMultiLocation ?? false,
      location_context: null,
    };

    if (
      options.token &&
      (hasMeaningfulPreferences(options.preferences) ||
        options.dedupeMultiLocation)
    ) {
      try {
        const rows = await request<RecommendationItem[]>('/recommendations/query', {
          method: 'POST',
          token: options.token,
          body: payload,
        });
        if (rows.length > 0) {
          return rows;
        }
      } catch {
        // Fall through to authenticated endpoint and public fallback recommendation paths.
      }
    }

    if (options.token) {
      try {
        const recommendationPath = options.dedupeMultiLocation
          ? '/recommendations?dedupe_multi_location=true'
          : '/recommendations';
        const rows = await request<RecommendationItem[]>(recommendationPath, {
          token: options.token,
        });
        if (rows.length > 0) {
          return rows;
        }
      } catch {
        // Fall through to query-based and public fallback recommendation paths.
      }

      try {
        const rows = await request<RecommendationItem[]>('/recommendations/query', {
          method: 'POST',
          token: options.token,
          body: payload,
        });
        if (rows.length > 0) {
          return rows;
        }
      } catch {
        // Fall through to public fallback recommendation paths.
      }
    }

    if (hasMeaningfulPreferences(options.preferences)) {
      try {
        const rows = await request<RecommendationItem[]>('/recommendations/query', {
          method: 'POST',
          body: payload,
        });
        if (rows.length > 0) {
          return rows;
        }
      } catch {
        // Fall through to generic public picks.
      }
    }

    return request<RecommendationItem[]>('/recommendations/query', {
      method: 'POST',
      body: {
        preferences: null,
        dedupe_multi_location: options.dedupeMultiLocation ?? false,
        location_context: null,
      },
    });
  },
  async getPersonalizedOffers(token: string, limit = 4): Promise<PersonalizedOfferCard[]> {
    return request<PersonalizedOfferCard[]>(`/offers/personalized?limit=${limit}`, { token });
  },
  async trackPersonalizedOfferEvents(
    token: string,
    events: Array<{
      offer_id: string;
      generated_offer_id?: string | null;
      generated_offer_user_match_id?: string | null;
      event_type: 'VIEWED' | 'CLICKED';
      target_type?: string | null;
      target_id?: string | null;
    }>,
  ): Promise<{ recorded_count: number }> {
    return request<{ recorded_count: number }>('/offers/personalized/events', {
      method: 'POST',
      token,
      body: { events },
    });
  },
  async previewPersonalizedOffer(
    token: string,
    payload: {
      offer_id: string;
      generated_offer_id?: string | null;
      generated_offer_user_match_id?: string | null;
      restaurant_id: string;
      restaurant_location_id?: string | null;
      fulfillment_type?: 'DELIVERY' | 'PICKUP';
      items: Array<{
        menu_item_id: string;
        menu_item_size_id?: string | null;
        selected_options?: Array<{ option_id: string; quantity: number }>;
        quantity: number;
      }>;
    },
    ): Promise<PersonalizedOfferPreview> {
    return request<PersonalizedOfferPreview>('/offers/personalized/preview', {
      method: 'POST',
      token,
      body: payload,
    });
  },
  async getPersonalizedOffersForContext(
    token: string,
    payload: {
      restaurant_id: string;
      restaurant_location_id?: string | null;
      menu_item_id: string;
    },
  ): Promise<PersonalizedOfferCard[]> {
    return request<PersonalizedOfferCard[]>('/offers/personalized/context', {
      method: 'POST',
      token,
      body: payload,
    });
  },
  async getPersonalizedOfferAvailabilityForItems(
    token: string,
    payload: {
      restaurant_id: string;
      restaurant_location_id?: string | null;
      menu_item_ids: string[];
    },
  ): Promise<PersonalizedOfferItemAvailability[]> {
    return request<PersonalizedOfferItemAvailability[]>('/offers/personalized/context/items', {
      method: 'POST',
      token,
      body: payload,
    });
  },
  async getUserPreferences(token: string): Promise<UserPreferences> {
    return request<UserPreferences>('/preferences/me', { token });
  },
  async getProfileSummary(token: string): Promise<ProfileSummary> {
    return request<ProfileSummary>('/profile/me', { token });
  },
  async updateProfile(token: string, payload: ProfileUpdatePayload): Promise<AuthResponse['user']> {
    return request<AuthResponse['user']>('/profile/me', {
      method: 'PATCH',
      token,
      body: payload,
    });
  },
  async updateUserPreferences(
    token: string,
    preferences: UserPreferences,
  ): Promise<UserPreferences> {
    return request<UserPreferences>('/preferences/me', {
      method: 'PUT',
      token,
      body: normalizePreferencesPayload(preferences),
    });
  },
  async sendChatMessage(
    payload: ChatMessageRequest,
    token: string,
    signal?: AbortSignal,
  ): Promise<ChatMessageResponse> {
    return request<ChatMessageResponse>('/chat/message', {
      method: 'POST',
      token,
      body: payload,
      signal,
      timeoutMs: 45000,
    });
  },
  async streamChatMessage(
    payload: ChatMessageRequest,
    token: string,
    handlers: ChatStreamHandlers,
    signal?: AbortSignal,
  ): Promise<void> {
    const headers = new Headers({
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    });
    const controller = new AbortController();
    let timedOut = false;
    const handleExternalAbort = () => controller.abort(signal?.reason);
    if (signal) {
      if (signal.aborted) {
        controller.abort(signal.reason);
      } else {
        signal.addEventListener('abort', handleExternalAbort, { once: true });
      }
    }
    const timeoutId = window.setTimeout(() => {
      timedOut = true;
      controller.abort(new DOMException('Request timed out', 'AbortError'));
    }, 45000);

    let response: Response;
    try {
      response = await fetch(`${API_BASE_URL}/chat/message/stream`, {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
    } catch (error) {
      if (timedOut) {
        throw new ApiError('The request took too long. Please try again.', 408);
      }
      throw error;
    } finally {
      window.clearTimeout(timeoutId);
      if (signal) {
        signal.removeEventListener('abort', handleExternalAbort);
      }
    }

    if (!response.ok) {
      const payloadBody = await response.json().catch(() => ({}));
      const detail =
        typeof payloadBody.detail === 'string'
          ? payloadBody.detail
          : typeof payloadBody.message === 'string'
            ? payloadBody.message
            : 'Something went wrong';
      if (response.status === 401 && typeof window !== 'undefined') {
        window.dispatchEvent(
          new CustomEvent(AUTH_INVALID_EVENT, {
            detail: {
              path: '/chat/message/stream',
              status: response.status,
            },
          }),
        );
      }
      throw new ApiError(detail, response.status);
    }

    if (!response.body) {
      throw new ApiError('Streaming is unavailable right now.', 502);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    const dispatchEventBlock = (block: string) => {
      const lines = block
        .split('\n')
        .map((line) => line.trimEnd())
        .filter(Boolean);
      if (lines.length === 0) {
        return;
      }

      let eventName = 'message';
      const dataLines: string[] = [];
      for (const line of lines) {
        if (line.startsWith('event:')) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trim());
        }
      }

      if (dataLines.length === 0) {
        return;
      }

      const payloadText = dataLines.join('\n');
      let parsed: unknown;
      try {
        parsed = JSON.parse(payloadText);
      } catch {
        return;
      }

      if (eventName === 'meta') {
        handlers.onMeta?.(parsed as StreamMetaPayload);
      } else if (eventName === 'token') {
        const tokenText =
          typeof (parsed as { text?: unknown }).text === 'string'
            ? (parsed as { text: string }).text
            : '';
        if (tokenText) {
          handlers.onToken?.(tokenText);
        }
      } else if (eventName === 'done') {
        handlers.onDone?.(parsed as ChatMessageResponse);
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

      let boundaryIndex = buffer.indexOf('\n\n');
      while (boundaryIndex >= 0) {
        const block = buffer.slice(0, boundaryIndex);
        buffer = buffer.slice(boundaryIndex + 2);
        dispatchEventBlock(block);
        boundaryIndex = buffer.indexOf('\n\n');
      }

      if (done) {
        if (buffer.trim()) {
          dispatchEventBlock(buffer);
        }
        break;
      }
    }
  },
  async getChatHistory(token: string, sessionId?: string | null): Promise<ChatHistoryItem[]> {
    const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
    return request<ChatHistoryItem[]>(`/chat/history${query}`, { token });
  },
  async clearChatHistory(
    token: string,
    sessionId?: string | null,
  ): Promise<{ deleted_count: number; cleared_session_id: string | null }> {
    const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : '';
    return request<{ deleted_count: number; cleared_session_id: string | null }>(
      `/chat/history${query}`,
      {
        method: 'DELETE',
        token,
      },
    );
  },
  async placeOrder(
    token: string,
    payload: {
      restaurant_id: string;
      restaurant_location_id?: string | null;
      personalized_offer_id?: string | null;
      generated_offer_id?: string | null;
      generated_offer_user_match_id?: string | null;
      fulfillment_type?: 'DELIVERY' | 'PICKUP';
      items: Array<{
        menu_item_id: string;
        menu_item_size_id?: string | null;
        selected_options?: Array<{ option_id: string; quantity: number }>;
        quantity: number;
      }>;
      delivery_address: string;
      special_instructions?: string | null;
      payment_provider: string;
    },
  ): Promise<Order> {
    return request<Order>('/orders', {
      method: 'POST',
      token,
      body: payload,
    });
  },
  async getOrders(token: string): Promise<Order[]> {
    return request<Order[]>('/orders', { token });
  },
  async getOrder(token: string, orderId: string): Promise<Order> {
    return request<Order>(`/orders/${encodeURIComponent(orderId)}`, { token });
  },
};

export function toNumber(value: DecimalValue): number {
  return typeof value === 'number' ? value : Number(value);
}

export function formatCurrency(value: DecimalValue): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
  }).format(toNumber(value));
}

export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value));
}

/**
 * Stand-in art for a dish with no photo.
 *
 * Was a `placehold.co` URL: a 200x200 remote PNG of two letters, stretched to
 * fill a card several times that size, which is why a missing photo rendered as
 * enormous pixelated initials — and why every such card cost a third-party
 * request that fails offline and leaks the page to another host.
 *
 * Now an inline SVG, so it costs nothing, cannot fail, and is drawn in the
 * restaurant's own colours: the tokens are read from the live theme, which
 * means it follows a rebrand and both light and dark mode for free.
 */
export function createPlaceholderImage(seed: string): string {
  const initials = seed.trim().slice(0, 2).toUpperCase() || 'FD';
  const style = typeof document === 'undefined' ? null : getComputedStyle(document.documentElement);
  const ink = style?.getPropertyValue('--primary').trim() || '#FF5200';
  const ground = style?.getPropertyValue('--primary-soft').trim() || '#FFF0E8';

  // Wide rather than square, and lettered small: these are painted into card
  // media boxes with `object-fit: cover`, so a square source gets cropped and
  // scaled up — which is what made the old placeholder's initials fill a card.
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 260">
<rect width="420" height="260" fill="${ground}"/>
<circle cx="210" cy="130" r="46" fill="${ink}" opacity="0.10"/>
<text x="210" y="130" fill="${ink}" font-family="system-ui, sans-serif" font-size="30" font-weight="800" letter-spacing="1" text-anchor="middle" dominant-baseline="central">${initials}</text>
</svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function normalizePreferencesPayload(preferences: UserPreferences): {
  cuisines: string[];
  diet: DietPreference | null;
  spice_level: SpiceLevel | null;
  budget: BudgetTier | null;
  favorite_items: string[];
} {
  return {
    cuisines: preferences.cuisines,
    diet: preferences.diet,
    spice_level: preferences.spice_level,
    budget: preferences.budget,
    favorite_items: preferences.favorite_items,
  };
}

export { ApiError };

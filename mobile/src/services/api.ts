import axios from 'axios';
import type { AppIdentity } from '@services/appInfo';
import {
  cachedRequest,
  invalidateRequestCache,
  tokenScope,
} from '@services/requestCache';
import type {
  AppConfig,
  AuthResponse,
  BudgetTier,
  ChatHistoryItem,
  ChatMessageResponse,
  ChatSuggestionItem,
  ComboUpsellSuggestion,
  DecimalValue,
  DietPreference,
  FavoriteItem,
  GeneratedCombo,
  LocationScheduleOptionsResponse,
  MenuItem,
  Order,
  OrderValidationResult,
  OrderFulfillmentType,
  PaymentConfig,
  PaymentIntentResponse,
  PaymentMethod,
  PaymentStatusResponse,
  OrderScheduleType,
  PersonalizedRecommendationContext,
  PersonalizedOfferCard,
  PersonalizedOfferItemAvailability,
  PersonalizedOfferPreview,
  ProfileSummary,
  ProfileUpdatePayload,
  SavedAddress,
  SavedAddressPayload,
  SelectedLocation,
  RecommendationItem,
  Restaurant,
  RestaurantLocation,
  SpiceLevel,
  UserPreferences,
} from '@/types/app';

const API_BASE_URL = 'http://192.168.29.236:8000/api';

/**
 * How long a settled response may be reused.
 *
 * Deliberately short: these windows only collapse the duplicate calls several
 * screens make within the same interaction, never hide a real update. `NONE`
 * means dedupe-in-flight only - the value is dropped as soon as it settles.
 */
const TTL = {
  /** Dedupe concurrent callers only; never reuse a settled value. */
  NONE: 0,
  /** Order history, schedule slots - freshness matters most. */
  SHORT: 10_000,
  /** Single restaurant, menus, offers - matches existing screen throttles. */
  MEDIUM: 15_000,
  /** Restaurant lists, recommendations, combos - stable between screens. */
  LONG: 30_000,
} as const;

/** Re-exported so the store can clear everything when the session changes. */
export { invalidateRequestCache } from '@services/requestCache';

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

const client = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000,
});

function withToken(token?: string | null) {
  return token ? { Authorization: `Bearer ${token}` } : undefined;
}

function hasMeaningfulPreferences(
  preferences?: UserPreferences | null,
): boolean {
  return Boolean(
    preferences &&
      (preferences.cuisines.length > 0 ||
        preferences.favorite_items.length > 0 ||
        preferences.diet ||
        preferences.spice_level ||
        preferences.budget),
  );
}

function buildRecommendationQueryPayload(
  preferences?: UserPreferences | null,
): {
  preferences: ReturnType<typeof normalizePreferencesPayload> | null;
} {
  return {
    preferences: preferences ? normalizePreferencesPayload(preferences) : null,
  };
}

function mapError(error: unknown): never {
  if (axios.isAxiosError(error)) {
    const responseData = error.response?.data as
      | { detail?: string; message?: string }
      | undefined;
    const message =
      typeof responseData?.detail === 'string'
        ? responseData.detail
        : error.message;
    throw new ApiError(message, error.response?.status ?? 500);
  }

  throw new ApiError('Something went wrong', 500);
}

/** Startup config resolution must not hold the splash screen for long. */
const APP_CONFIG_TIMEOUT_MS = 8000;

export const APP_BUNDLE_ID_HEADER = 'X-App-Bundle-Id';
export const APP_PLATFORM_HEADER = 'X-App-Platform';

/**
 * Identifies this build on every subsequent request.
 *
 * The backend resolves these headers to an app client and scopes the response
 * server-side, so the app never has to filter another restaurant's data out.
 * Set once at startup, before any data call.
 */
export function setAppIdentityHeaders(identity: AppIdentity): void {
  client.defaults.headers.common[APP_BUNDLE_ID_HEADER] = identity.bundleId;
  client.defaults.headers.common[APP_PLATFORM_HEADER] = identity.platform;
  console.log(
    `[BundleId] Request headers set -> ${APP_BUNDLE_ID_HEADER}: ${identity.bundleId} | ${APP_PLATFORM_HEADER}: ${identity.platform}`,
  );
}

export const api = {
  /**
   * Resolves this build's bundle ID to its app configuration.
   *
   * Public endpoint: the app calls it before any login, so no token is sent.
   */
  async getAppConfig(): Promise<AppConfig> {
    console.log(`[BundleId] Request: GET ${API_BASE_URL}/app-config`);
    try {
      // Identity travels on the shared client defaults, so this request is
      // resolved from exactly the same headers as every other call.
      const response = await client.get<AppConfig>('/app-config', {
        timeout: APP_CONFIG_TIMEOUT_MS,
      });
      console.log(
        `[BundleId] Backend matched bundle_id: ${response.data.bundle_id} -> app_key=${response.data.app_key}`,
      );
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async login(payload: {
    email?: string | null;
    phone_number?: string | null;
    password: string;
  }): Promise<AuthResponse> {
    try {
      const response = await client.post<AuthResponse>('/auth/login', payload);
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async register(payload: {
    full_name: string;
    email: string;
    phone_number?: string | null;
    default_address?: string | null;
    password: string;
  }): Promise<AuthResponse> {
    try {
      const response = await client.post<AuthResponse>('/auth/register', {
        ...payload,
        role: 'CUSTOMER',
      });
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  /**
   * Invalidates every token issued to this account, including the one used
   * here. Only this app's account is affected.
   */
  async logoutAll(token: string): Promise<void> {
    try {
      await client.post('/auth/logout-all', undefined, {
        headers: withToken(token),
      });
    } catch (error) {
      return mapError(error);
    }
  },
  async registerDeviceToken(
    token: string,
    payload: {
      installation_id: string;
      fcm_token: string;
      platform: 'ANDROID' | 'IOS';
    },
  ): Promise<void> {
    try {
      await client.post('/notifications/device-tokens', payload, {
        headers: withToken(token),
      });
    } catch (error) {
      return mapError(error);
    }
  },
  async getRestaurants(token?: string | null): Promise<Restaurant[]> {
    return cachedRequest(
      `restaurants:list:${tokenScope(token)}`,
      TTL.LONG,
      async () => {
        try {
          const response = await client.get<Restaurant[]>('/restaurants', {
            headers: withToken(token),
          });
          return response.data;
        } catch (error) {
          if (
            token &&
            axios.isAxiosError(error) &&
            error.response?.status === 401
          ) {
            try {
              const fallbackResponse = await client.get<Restaurant[]>(
                '/restaurants',
              );
              return fallbackResponse.data;
            } catch (fallbackError) {
              return mapError(fallbackError);
            }
          }
          return mapError(error);
        }
      },
    );
  },
  async getRestaurant(
    restaurantId: string,
    token?: string | null,
  ): Promise<Restaurant> {
    return cachedRequest(
      `restaurants:detail:${restaurantId}:${tokenScope(token)}`,
      TTL.MEDIUM,
      async () => {
        try {
          const response = await client.get<Restaurant>(
            `/restaurants/${encodeURIComponent(restaurantId)}`,
            {
              headers: withToken(token),
            },
          );
          return response.data;
        } catch (error) {
          if (
            token &&
            axios.isAxiosError(error) &&
            error.response?.status === 401
          ) {
            try {
              const fallbackResponse = await client.get<Restaurant>(
                `/restaurants/${encodeURIComponent(restaurantId)}`,
              );
              return fallbackResponse.data;
            } catch (fallbackError) {
              return mapError(fallbackError);
            }
          }
          return mapError(error);
        }
      },
    );
  },
  async getRestaurantLocations(
    restaurantId: string,
    token?: string | null,
  ): Promise<RestaurantLocation[]> {
    try {
      const response = await client.get<RestaurantLocation[]>(
        `/restaurants/${encodeURIComponent(restaurantId)}/locations`,
        {
          headers: withToken(token),
        },
      );
      return response.data;
    } catch (error) {
      if (
        token &&
        axios.isAxiosError(error) &&
        error.response?.status === 401
      ) {
        try {
          const fallbackResponse = await client.get<RestaurantLocation[]>(
            `/restaurants/${encodeURIComponent(restaurantId)}/locations`,
          );
          return fallbackResponse.data;
        } catch (fallbackError) {
          return mapError(fallbackError);
        }
      }
      return mapError(error);
    }
  },
  async getRestaurantLocationScheduleOptions(
    restaurantId: string,
    locationId: string,
    fulfillmentType: OrderFulfillmentType,
    token?: string | null,
  ): Promise<LocationScheduleOptionsResponse> {
    return cachedRequest(
      `schedule-options:${restaurantId}:${locationId}:${fulfillmentType}:${tokenScope(
        token,
      )}`,
      TTL.SHORT,
      async () => {
        try {
          const response = await client.get<LocationScheduleOptionsResponse>(
            `/restaurants/${encodeURIComponent(
              restaurantId,
            )}/locations/${encodeURIComponent(locationId)}/schedule-options`,
            {
              params: {
                fulfillment_type: fulfillmentType,
              },
              headers: withToken(token),
            },
          );
          return response.data;
        } catch (error) {
          if (
            token &&
            axios.isAxiosError(error) &&
            error.response?.status === 401
          ) {
            try {
              const fallbackResponse =
                await client.get<LocationScheduleOptionsResponse>(
                  `/restaurants/${encodeURIComponent(
                    restaurantId,
                  )}/locations/${encodeURIComponent(
                    locationId,
                  )}/schedule-options`,
                  {
                    params: {
                      fulfillment_type: fulfillmentType,
                    },
                  },
                );
              return fallbackResponse.data;
            } catch (fallbackError) {
              return mapError(fallbackError);
            }
          }
          return mapError(error);
        }
      },
    );
  },
  async getMenuItems(
    restaurantId: string,
    token?: string | null,
    locationId?: string | null,
  ): Promise<MenuItem[]> {
    return cachedRequest(
      `menu-items:list:${restaurantId}:${locationId ?? 'all'}:${tokenScope(
        token,
      )}`,
      TTL.MEDIUM,
      async () => {
        try {
          const response = await client.get<MenuItem[]>('/menu-items', {
            params: {
              restaurant_id: restaurantId,
              location_id: locationId ?? undefined,
            },
            headers: withToken(token),
          });
          return response.data;
        } catch (error) {
          if (
            token &&
            axios.isAxiosError(error) &&
            error.response?.status === 401
          ) {
            try {
              const fallbackResponse = await client.get<MenuItem[]>(
                '/menu-items',
                {
                  params: {
                    restaurant_id: restaurantId,
                    location_id: locationId ?? undefined,
                  },
                },
              );
              return fallbackResponse.data;
            } catch (fallbackError) {
              return mapError(fallbackError);
            }
          }
          return mapError(error);
        }
      },
    );
  },
  async getMenuItem(
    menuItemId: string,
    token?: string | null,
  ): Promise<MenuItem> {
    return cachedRequest(
      `menu-items:detail:${menuItemId}:${tokenScope(token)}`,
      TTL.MEDIUM,
      async () => {
        try {
          const response = await client.get<MenuItem>(
            `/menu-items/${encodeURIComponent(menuItemId)}`,
            {
              headers: withToken(token),
            },
          );
          return response.data;
        } catch (error) {
          if (
            token &&
            axios.isAxiosError(error) &&
            error.response?.status === 401
          ) {
            try {
              const fallbackResponse = await client.get<MenuItem>(
                `/menu-items/${encodeURIComponent(menuItemId)}`,
              );
              return fallbackResponse.data;
            } catch (fallbackError) {
              return mapError(fallbackError);
            }
          }
          return mapError(error);
        }
      },
    );
  },
  async getRecommendations(token: string): Promise<RecommendationItem[]> {
    try {
      const response = await client.get<RecommendationItem[]>(
        '/recommendations',
        {
          headers: withToken(token),
        },
      );
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async getGeneratedCombos(limit = 12): Promise<GeneratedCombo[]> {
    return cachedRequest(
      `generated-combos:list:${limit}`,
      TTL.LONG,
      async () => {
        try {
          const response = await client.get<GeneratedCombo[]>(
            '/generated-combos',
            {
              params: { limit },
            },
          );
          return response.data;
        } catch (error) {
          return mapError(error);
        }
      },
    );
  },
  // Favorites are dedupe-only: concurrent callers share one request, but a
  // settled value is never reused, so a toggle is always read back fresh.
  async getFavorites(token: string): Promise<FavoriteItem[]> {
    return cachedRequest(
      `favorites:items:${tokenScope(token)}`,
      TTL.NONE,
      async () => {
        try {
          const response = await client.get<FavoriteItem[]>('/favorites', {
            headers: withToken(token),
          });
          return response.data;
        } catch (error) {
          return mapError(error);
        }
      },
    );
  },
  async getFavoriteIds(token: string): Promise<string[]> {
    return cachedRequest(
      `favorites:ids:${tokenScope(token)}`,
      TTL.NONE,
      async () => {
        try {
          const response = await client.get<string[]>('/favorites/ids', {
            headers: withToken(token),
          });
          return response.data;
        } catch (error) {
          return mapError(error);
        }
      },
    );
  },
  async addFavorite(
    token: string,
    menuItemId: string,
  ): Promise<{ menu_item_id: string; is_favorite: boolean }> {
    try {
      const response = await client.post<{
        menu_item_id: string;
        is_favorite: boolean;
      }>(`/favorites/${encodeURIComponent(menuItemId)}`, undefined, {
        headers: withToken(token),
      });
      invalidateRequestCache('favorites:');
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async removeFavorite(
    token: string,
    menuItemId: string,
  ): Promise<{ menu_item_id: string; is_favorite: boolean }> {
    try {
      const response = await client.delete<{
        menu_item_id: string;
        is_favorite: boolean;
      }>(`/favorites/${encodeURIComponent(menuItemId)}`, {
        headers: withToken(token),
      });
      invalidateRequestCache('favorites:');
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async getRestaurantGeneratedCombos(
    restaurantId: string,
    limit = 12,
    locationId?: string | null,
  ): Promise<GeneratedCombo[]> {
    return cachedRequest(
      `generated-combos:restaurant:${restaurantId}:${
        locationId ?? 'all'
      }:${limit}`,
      TTL.LONG,
      async () => {
        try {
          const response = await client.get<GeneratedCombo[]>(
            `/restaurants/${encodeURIComponent(restaurantId)}/generated-combos`,
            {
              params: { limit, location_id: locationId ?? undefined },
            },
          );
          return response.data;
        } catch (error) {
          return mapError(error);
        }
      },
    );
  },
  async getCartUpsellSuggestions(options: {
    restaurantId: string;
    locationId?: string | null;
    itemId: string;
    cartItemIds?: string[];
    limit?: number;
  }): Promise<ComboUpsellSuggestion[]> {
    const cacheKey = [
      'cart-upsell',
      options.restaurantId,
      options.locationId ?? 'all',
      options.itemId,
      (options.cartItemIds ?? []).join(','),
      options.limit ?? 3,
    ].join(':');
    return cachedRequest(cacheKey, TTL.MEDIUM, async () => {
      try {
        const response = await client.get<ComboUpsellSuggestion[]>(
          '/cart/upsell-suggestions',
          {
            params: {
              restaurant_id: options.restaurantId,
              location_id: options.locationId ?? undefined,
              item_id: options.itemId,
              cart_item_ids: options.cartItemIds ?? [],
              limit: options.limit ?? 3,
            },
            paramsSerializer: params => {
              const searchParams = new URLSearchParams();
              searchParams.set('restaurant_id', String(params.restaurant_id));
              if (params.location_id) {
                searchParams.set('location_id', String(params.location_id));
              }
              searchParams.set('item_id', String(params.item_id));
              searchParams.set('limit', String(params.limit));
              for (const cartItemId of params.cart_item_ids as string[]) {
                searchParams.append('cart_item_ids', cartItemId);
              }
              return searchParams.toString();
            },
          },
        );
        return response.data;
      } catch (error) {
        return mapError(error);
      }
    });
  },
  async getRecommendationsForContext(options: {
    token?: string | null;
    preferences?: UserPreferences | null;
    dedupeMultiLocation?: boolean;
    selectedLocation?: SelectedLocation | null;
  }): Promise<RecommendationItem[]> {
    const payload = {
      ...buildRecommendationQueryPayload(options.preferences),
      dedupe_multi_location: options.dedupeMultiLocation ?? false,
      location_context: options.selectedLocation
        ? {
            city: options.selectedLocation.city ?? null,
            latitude: options.selectedLocation.latitude ?? null,
            longitude: options.selectedLocation.longitude ?? null,
          }
        : null,
    };

    // Keyed on the request's content, not on the caller's object identity, so
    // the four screens that ask for the same context share one round trip.
    const cacheKey = [
      'recommendations:context',
      tokenScope(options.token),
      JSON.stringify(payload.preferences),
      String(payload.dedupe_multi_location),
      JSON.stringify(payload.location_context),
    ].join(':');

    return cachedRequest(cacheKey, TTL.LONG, async () => {
      if (options.token) {
        try {
          const response = await client.get<RecommendationItem[]>(
            '/recommendations',
            {
              params: {
                dedupe_multi_location: options.dedupeMultiLocation || undefined,
                location_city: options.selectedLocation?.city ?? undefined,
                latitude: options.selectedLocation?.latitude ?? undefined,
                longitude: options.selectedLocation?.longitude ?? undefined,
              },
              headers: withToken(options.token),
            },
          );
          if (response.data.length > 0) {
            return response.data;
          }
        } catch {
          // Fall through to query-based and public fallback recommendation paths.
        }

        try {
          const response = await client.post<RecommendationItem[]>(
            '/recommendations/query',
            payload,
            {
              headers: withToken(options.token),
            },
          );
          if (response.data.length > 0) {
            return response.data;
          }
        } catch {
          // Fall through to public fallback recommendation paths.
        }
      }

      if (hasMeaningfulPreferences(options.preferences)) {
        try {
          const response = await client.post<RecommendationItem[]>(
            '/recommendations/query',
            payload,
          );
          if (response.data.length > 0) {
            return response.data;
          }
        } catch {
          // Fall through to generic public picks.
        }
      }

      try {
        const response = await client.post<RecommendationItem[]>(
          '/recommendations/query',
          {
            preferences: null,
            dedupe_multi_location: options.dedupeMultiLocation ?? false,
            location_context: payload.location_context,
          },
        );
        return response.data;
      } catch (error) {
        return mapError(error);
      }
    });
  },
  async getPersonalizedRecommendationContext(
    token: string,
  ): Promise<PersonalizedRecommendationContext> {
    return cachedRequest(
      `recommendations:personalized-context:${tokenScope(token)}`,
      TTL.LONG,
      async () => {
        try {
          const response = await client.get<PersonalizedRecommendationContext>(
            '/recommendations/personalized-context',
            {
              headers: withToken(token),
            },
          );
          return response.data;
        } catch (error) {
          return mapError(error);
        }
      },
    );
  },
  async getPersonalizedOffers(
    token: string,
    limit = 4,
  ): Promise<PersonalizedOfferCard[]> {
    return cachedRequest(
      `offers:personalized:${limit}:${tokenScope(token)}`,
      TTL.MEDIUM,
      async () => {
        try {
          const response = await client.get<PersonalizedOfferCard[]>(
            '/offers/personalized',
            {
              params: { limit },
              headers: withToken(token),
            },
          );
          return response.data;
        } catch (error) {
          return mapError(error);
        }
      },
    );
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
    try {
      const response = await client.post<{ recorded_count: number }>(
        '/offers/personalized/events',
        { events },
        {
          headers: withToken(token),
        },
      );
      return response.data;
    } catch (error) {
      return mapError(error);
    }
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
    // Dedupe-only: eligibility must reflect the cart as it stands, but the
    // cart screen previews every offer against the same payload at once.
    return cachedRequest(
      `offers:preview:${tokenScope(token)}:${JSON.stringify(payload)}`,
      TTL.NONE,
      async () => {
        try {
          const response = await client.post<PersonalizedOfferPreview>(
            '/offers/personalized/preview',
            payload,
            {
              headers: withToken(token),
            },
          );
          return response.data;
        } catch (error) {
          return mapError(error);
        }
      },
    );
  },
  async getPersonalizedOffersForContext(
    token: string,
    payload: {
      restaurant_id: string;
      restaurant_location_id?: string | null;
      menu_item_id: string;
    },
  ): Promise<PersonalizedOfferCard[]> {
    try {
      const response = await client.post<PersonalizedOfferCard[]>(
        '/offers/personalized/context',
        payload,
        {
          headers: withToken(token),
        },
      );
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async getPersonalizedOffersForRestaurant(
    token: string,
    payload: {
      restaurant_id: string;
      restaurant_location_id?: string | null;
      limit?: number;
    },
  ): Promise<PersonalizedOfferCard[]> {
    try {
      const response = await client.post<PersonalizedOfferCard[]>(
        '/offers/personalized/restaurant',
        payload,
        {
          headers: withToken(token),
        },
      );
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async getPersonalizedOfferAvailabilityForItems(
    token: string,
    payload: {
      restaurant_id: string;
      restaurant_location_id?: string | null;
      menu_item_ids: string[];
    },
  ): Promise<PersonalizedOfferItemAvailability[]> {
    const cacheKey = [
      'offers:availability',
      tokenScope(token),
      payload.restaurant_id,
      payload.restaurant_location_id ?? 'all',
      [...payload.menu_item_ids].sort().join(','),
    ].join(':');
    return cachedRequest(cacheKey, TTL.MEDIUM, async () => {
      try {
        const response = await client.post<PersonalizedOfferItemAvailability[]>(
          '/offers/personalized/context/items',
          payload,
          {
            headers: withToken(token),
          },
        );
        return response.data;
      } catch (error) {
        return mapError(error);
      }
    });
  },
  async getChatHistory(
    token: string,
    sessionId?: string | null,
  ): Promise<ChatHistoryItem[]> {
    try {
      const response = await client.get<ChatHistoryItem[]>('/chat/history', {
        params: sessionId ? { session_id: sessionId } : undefined,
        headers: withToken(token),
      });
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async clearChatHistory(
    token: string,
    sessionId?: string | null,
  ): Promise<{ deleted_count: number; cleared_session_id: string | null }> {
    try {
      const response = await client.delete<{
        deleted_count: number;
        cleared_session_id: string | null;
      }>('/chat/history', {
        params: sessionId ? { session_id: sessionId } : undefined,
        headers: withToken(token),
      });
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async sendChatMessage(
    token: string,
    payload: {
      message: string;
      restaurant_id?: string | null;
      session_id?: string | null;
    },
  ): Promise<ChatMessageResponse> {
    try {
      const response = await client.post<ChatMessageResponse>(
        '/chat/message',
        payload,
        {
          headers: withToken(token),
        },
      );
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  /**
   * Streams a chat turn over the SSE endpoint so reply tokens render as the
   * model produces them instead of after the full generation.
   *
   * Axios cannot stream response bodies in React Native, so this rides
   * XMLHttpRequest's incremental `responseText`. Identity headers are copied
   * from the shared axios client so server-side restaurant scoping behaves
   * exactly like the non-streaming call. Resolves with the final `done`
   * payload (same shape as `sendChatMessage`); rejects on any transport or
   * protocol failure so the caller can fall back to the non-streaming path.
   */
  streamChatMessage(
    token: string,
    payload: {
      message: string;
      restaurant_id?: string | null;
      session_id?: string | null;
    },
    handlers: {
      onMeta?: (meta: {
        session_id: string;
        suggestions: ChatSuggestionItem[];
        combo_suggestions: GeneratedCombo[];
        offer_suggestions: PersonalizedOfferCard[];
      }) => void;
      onToken?: (text: string) => void;
    } = {},
  ): Promise<ChatMessageResponse> {
    return new Promise<ChatMessageResponse>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      let parsedUpTo = 0;
      let settled = false;

      const fail = (message: string, status: number) => {
        if (settled) {
          return;
        }
        settled = true;
        xhr.abort();
        reject(new ApiError(message, status));
      };

      const handleFrame = (frame: string) => {
        let eventName: string | null = null;
        let dataText: string | null = null;
        for (const line of frame.split('\n')) {
          if (line.startsWith('event: ')) {
            eventName = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            dataText = line.slice(6);
          }
        }
        if (!eventName || dataText === null) {
          return;
        }
        let data: any;
        try {
          data = JSON.parse(dataText);
        } catch {
          fail('Chat stream sent an unreadable frame', 502);
          return;
        }
        if (eventName === 'meta') {
          handlers.onMeta?.(data);
        } else if (eventName === 'token') {
          if (typeof data.text === 'string' && data.text) {
            handlers.onToken?.(data.text);
          }
        } else if (eventName === 'done') {
          if (!settled) {
            settled = true;
            resolve(data as ChatMessageResponse);
          }
        }
      };

      const processBuffer = () => {
        if (settled || xhr.status !== 200) {
          return;
        }
        const text = xhr.responseText;
        let separatorIndex = text.indexOf('\n\n', parsedUpTo);
        while (separatorIndex !== -1 && !settled) {
          const frame = text.slice(parsedUpTo, separatorIndex);
          parsedUpTo = separatorIndex + 2;
          handleFrame(frame);
          separatorIndex = text.indexOf('\n\n', parsedUpTo);
        }
      };

      xhr.open('POST', `${API_BASE_URL}/chat/message/stream`);
      xhr.responseType = 'text';
      // Streaming keeps data flowing, so this bounds the whole turn rather
      // than an idle gap; sized above the backend's 90s LLM read timeout.
      xhr.timeout = 150000;
      xhr.setRequestHeader('Content-Type', 'application/json');
      xhr.setRequestHeader('Accept', 'text/event-stream');
      xhr.setRequestHeader('Authorization', `Bearer ${token}`);
      const commonHeaders = client.defaults.headers.common as Record<
        string,
        unknown
      >;
      for (const headerName of [APP_BUNDLE_ID_HEADER, APP_PLATFORM_HEADER]) {
        const headerValue = commonHeaders[headerName];
        if (typeof headerValue === 'string' && headerValue) {
          xhr.setRequestHeader(headerName, headerValue);
        }
      }

      xhr.onprogress = processBuffer;
      xhr.onreadystatechange = () => {
        if (xhr.readyState === XMLHttpRequest.LOADING) {
          processBuffer();
          return;
        }
        if (xhr.readyState !== XMLHttpRequest.DONE) {
          return;
        }
        if (xhr.status !== 200) {
          let detail = 'Unable to send chat message.';
          try {
            const body = JSON.parse(xhr.responseText) as { detail?: string };
            if (typeof body.detail === 'string') {
              detail = body.detail;
            }
          } catch {
            // Non-JSON error body; keep the generic message.
          }
          fail(detail, xhr.status || 500);
          return;
        }
        processBuffer();
        if (!settled) {
          fail('Chat stream ended before completing.', 502);
        }
      };
      xhr.onerror = () => fail('Chat stream connection failed.', 0);
      xhr.ontimeout = () => fail('Chat stream timed out.', 408);

      xhr.send(JSON.stringify(payload));
    });
  },
  async placeOrder(
    token: string,
    payload: {
      restaurant_id: string;
      restaurant_location_id?: string | null;
      personalized_offer_id?: string | null;
      generated_offer_id?: string | null;
      generated_offer_user_match_id?: string | null;
      fulfillment_type?: OrderFulfillmentType;
      schedule_type?: OrderScheduleType;
      scheduled_at?: string | null;
      items: Array<{
        menu_item_id: string;
        menu_item_size_id?: string | null;
        selected_options?: Array<{ option_id: string; quantity: number }>;
        quantity: number;
      }>;
      delivery_address: string;
      special_instructions?: string | null;
      payment_method: PaymentMethod;
    },
  ): Promise<Order> {
    try {
      const response = await client.post<Order>('/orders', payload, {
        headers: withToken(token),
      });
      // A placed order changes order history and unlocks new recommendations.
      invalidateRequestCache('orders:');
      invalidateRequestCache('recommendations:');
      invalidateRequestCache('profile:');
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  /** Publishable key and the payment methods this deployment can settle. */
  async getPaymentConfig(token: string): Promise<PaymentConfig> {
    try {
      const response = await client.get<PaymentConfig>('/payments/config', {
        headers: withToken(token),
      });
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  /**
   * Starts (or resumes) payment for a card order. The amount is decided by the
   * server from the stored order, so nothing about it is passed from here.
   */
  async createPaymentIntent(
    token: string,
    orderId: string,
  ): Promise<PaymentIntentResponse> {
    try {
      const response = await client.post<PaymentIntentResponse>(
        `/orders/${encodeURIComponent(orderId)}/payment-intent`,
        undefined,
        { headers: withToken(token) },
      );
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async cancelOrderPayment(
    token: string,
    orderId: string,
  ): Promise<PaymentStatusResponse> {
    try {
      const response = await client.post<PaymentStatusResponse>(
        `/orders/${encodeURIComponent(orderId)}/payment-cancel`,
        undefined,
        { headers: withToken(token) },
      );
      invalidateRequestCache('orders:');
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async getOrderPaymentStatus(
    token: string,
    orderId: string,
  ): Promise<PaymentStatusResponse> {
    try {
      const response = await client.get<PaymentStatusResponse>(
        `/orders/${encodeURIComponent(orderId)}/payment-status`,
        { headers: withToken(token) },
      );
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async validateOrder(
    token: string,
    payload: {
      restaurant_id: string;
      restaurant_location_id?: string | null;
      personalized_offer_id?: string | null;
      generated_offer_id?: string | null;
      generated_offer_user_match_id?: string | null;
      fulfillment_type?: OrderFulfillmentType;
      schedule_type?: OrderScheduleType;
      scheduled_at?: string | null;
      items: Array<{
        menu_item_id: string;
        menu_item_size_id?: string | null;
        selected_options?: Array<{ option_id: string; quantity: number }>;
        quantity: number;
      }>;
      delivery_address: string;
      special_instructions?: string | null;
      payment_method?: PaymentMethod;
    },
  ): Promise<OrderValidationResult> {
    try {
      const response = await client.post<OrderValidationResult>(
        '/orders/validate',
        payload,
        {
          headers: withToken(token),
        },
      );
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async getOrders(token: string): Promise<Order[]> {
    return cachedRequest(
      `orders:list:${tokenScope(token)}`,
      TTL.SHORT,
      async () => {
        try {
          const response = await client.get<Order[]>('/orders', {
            headers: withToken(token),
          });
          return response.data;
        } catch (error) {
          return mapError(error);
        }
      },
    );
  },
  async getOrder(token: string, orderId: string): Promise<Order> {
    try {
      const response = await client.get<Order>(
        `/orders/${encodeURIComponent(orderId)}`,
        {
          headers: withToken(token),
        },
      );
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async getProfileSummary(token: string): Promise<ProfileSummary> {
    // Dedupe-only: the profile screen must always read back a fresh summary.
    return cachedRequest(
      `profile:summary:${tokenScope(token)}`,
      TTL.NONE,
      async () => {
        try {
          const response = await client.get<ProfileSummary>('/profile/me', {
            headers: withToken(token),
          });
          return response.data;
        } catch (error) {
          return mapError(error);
        }
      },
    );
  },
  async updateProfile(
    token: string,
    payload: ProfileUpdatePayload,
  ): Promise<AuthResponse['user']> {
    try {
      const response = await client.patch<AuthResponse['user']>(
        '/profile/me',
        payload,
        {
          headers: withToken(token),
        },
      );
      invalidateRequestCache('profile:');
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async getSavedAddresses(token: string): Promise<SavedAddress[]> {
    try {
      const response = await client.get<SavedAddress[]>('/profile/addresses', {
        headers: withToken(token),
      });
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async createSavedAddress(
    token: string,
    payload: SavedAddressPayload,
  ): Promise<SavedAddress> {
    try {
      const response = await client.post<SavedAddress>(
        '/profile/addresses',
        payload,
        {
          headers: withToken(token),
        },
      );
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async updateSavedAddress(
    token: string,
    addressId: string,
    payload: Partial<SavedAddressPayload>,
  ): Promise<SavedAddress> {
    try {
      const response = await client.patch<SavedAddress>(
        `/profile/addresses/${encodeURIComponent(addressId)}`,
        payload,
        {
          headers: withToken(token),
        },
      );
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async deleteSavedAddress(token: string, addressId: string): Promise<void> {
    try {
      await client.delete(
        `/profile/addresses/${encodeURIComponent(addressId)}`,
        {
          headers: withToken(token),
        },
      );
    } catch (error) {
      return mapError(error);
    }
  },
  async setDefaultSavedAddress(
    token: string,
    addressId: string,
  ): Promise<SavedAddress> {
    try {
      const response = await client.post<SavedAddress>(
        `/profile/addresses/${encodeURIComponent(addressId)}/default`,
        undefined,
        {
          headers: withToken(token),
        },
      );
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async getUserPreferences(token: string): Promise<UserPreferences> {
    try {
      const response = await client.get<UserPreferences>('/preferences/me', {
        headers: withToken(token),
      });
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
  async updateUserPreferences(
    token: string,
    preferences: UserPreferences,
  ): Promise<UserPreferences> {
    try {
      const response = await client.put<UserPreferences>(
        '/preferences/me',
        normalizePreferencesPayload(preferences),
        {
          headers: withToken(token),
        },
      );
      // Recommendations are ranked from these preferences.
      invalidateRequestCache('recommendations:');
      return response.data;
    } catch (error) {
      return mapError(error);
    }
  },
};

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

export function placeholderImage(seed: string): string {
  const label = encodeURIComponent(seed.slice(0, 2).toUpperCase() || 'FD');
  return `https://placehold.co/240x240/FFF3E0/CB202D?text=${label}`;
}

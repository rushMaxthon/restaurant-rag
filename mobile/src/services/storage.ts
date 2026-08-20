import AsyncStorage from '@react-native-async-storage/async-storage';
import type { ThemePreference } from '@/theme';
import type {
  AppConfig,
  AppliedPersonalizedOffer,
  CartState,
  SelectedLocation,
  User,
  UserPreferences,
} from '@/types/app';

const AUTH_KEY = 'restaurant-rag-mobile-auth';
const CART_KEY = 'restaurant-rag-mobile-cart';
const CHAT_SESSION_KEY = 'restaurant-rag-mobile-chat-session';
const LOCATION_KEY = 'restaurant-rag-mobile-location';
const PREFERENCES_KEY = 'restaurant-rag-mobile-preferences';
const PREFERENCES_ONBOARDING_KEY =
  'restaurant-rag-mobile-preferences-onboarding';
const SELECTED_PERSONALIZED_OFFER_KEY =
  'restaurant-rag-mobile-personalized-offer';
const THEME_PREFERENCE_KEY = 'restaurant-rag-mobile-theme-preference';
const SEARCH_HISTORY_KEY = 'restaurant-rag-mobile-search-history';
const PUSH_INSTALLATION_ID_KEY = 'restaurant-rag-mobile-push-installation-id';
const APP_CONFIG_KEY = 'restaurant-rag-mobile-app-config';

interface StoredAuth {
  token: string;
  user: User;
  /**
   * App this session was issued for. Optional so sessions saved by older
   * builds still load; those are treated as unknown and re-verified against
   * the backend on the next request.
   */
  appClientId?: string | null;
  appKey?: string | null;
}

export const storage = {
  async readAuth(): Promise<StoredAuth | null> {
    const raw = await AsyncStorage.getItem(AUTH_KEY);
    if (!raw) {
      return null;
    }

    try {
      return JSON.parse(raw) as StoredAuth;
    } catch {
      await AsyncStorage.removeItem(AUTH_KEY);
      return null;
    }
  },
  async writeAuth(value: StoredAuth | null): Promise<void> {
    if (!value) {
      await AsyncStorage.removeItem(AUTH_KEY);
      return;
    }
    await AsyncStorage.setItem(AUTH_KEY, JSON.stringify(value));
  },
  async readCart(): Promise<CartState | null> {
    const raw = await AsyncStorage.getItem(CART_KEY);
    if (!raw) {
      return null;
    }

    try {
      return JSON.parse(raw) as CartState;
    } catch {
      await AsyncStorage.removeItem(CART_KEY);
      return null;
    }
  },
  async writeCart(value: CartState): Promise<void> {
    await AsyncStorage.setItem(CART_KEY, JSON.stringify(value));
  },
  async readChatSession(): Promise<string | null> {
    return AsyncStorage.getItem(CHAT_SESSION_KEY);
  },
  async writeChatSession(value: string | null): Promise<void> {
    if (!value) {
      await AsyncStorage.removeItem(CHAT_SESSION_KEY);
      return;
    }
    await AsyncStorage.setItem(CHAT_SESSION_KEY, value);
  },
  async readLocation(): Promise<SelectedLocation | null> {
    const raw = await AsyncStorage.getItem(LOCATION_KEY);
    if (!raw) {
      return null;
    }

    try {
      return JSON.parse(raw) as SelectedLocation;
    } catch {
      await AsyncStorage.removeItem(LOCATION_KEY);
      return null;
    }
  },
  async writeLocation(value: SelectedLocation | null): Promise<void> {
    if (!value) {
      await AsyncStorage.removeItem(LOCATION_KEY);
      return;
    }
    await AsyncStorage.setItem(LOCATION_KEY, JSON.stringify(value));
  },
  async readPreferences(): Promise<UserPreferences | null> {
    const raw = await AsyncStorage.getItem(PREFERENCES_KEY);
    if (!raw) {
      return null;
    }

    try {
      return JSON.parse(raw) as UserPreferences;
    } catch {
      await AsyncStorage.removeItem(PREFERENCES_KEY);
      return null;
    }
  },
  async writePreferences(value: UserPreferences | null): Promise<void> {
    if (!value) {
      await AsyncStorage.removeItem(PREFERENCES_KEY);
      return;
    }
    await AsyncStorage.setItem(PREFERENCES_KEY, JSON.stringify(value));
  },
  async readPreferencesOnboardingCompleted(): Promise<boolean> {
    const raw = await AsyncStorage.getItem(PREFERENCES_ONBOARDING_KEY);
    return raw === 'true';
  },
  async writePreferencesOnboardingCompleted(value: boolean): Promise<void> {
    await AsyncStorage.setItem(
      PREFERENCES_ONBOARDING_KEY,
      value ? 'true' : 'false',
    );
  },
  async readSelectedPersonalizedOffer(): Promise<AppliedPersonalizedOffer | null> {
    const raw = await AsyncStorage.getItem(SELECTED_PERSONALIZED_OFFER_KEY);
    if (!raw) {
      return null;
    }
    try {
      return JSON.parse(raw) as AppliedPersonalizedOffer;
    } catch {
      await AsyncStorage.removeItem(SELECTED_PERSONALIZED_OFFER_KEY);
      return null;
    }
  },
  async writeSelectedPersonalizedOffer(
    value: AppliedPersonalizedOffer | null,
  ): Promise<void> {
    if (!value) {
      await AsyncStorage.removeItem(SELECTED_PERSONALIZED_OFFER_KEY);
      return;
    }
    await AsyncStorage.setItem(
      SELECTED_PERSONALIZED_OFFER_KEY,
      JSON.stringify(value),
    );
  },
  async readThemePreference(): Promise<ThemePreference> {
    const raw = await AsyncStorage.getItem(THEME_PREFERENCE_KEY);
    if (raw === 'light' || raw === 'dark' || raw === 'system') {
      return raw;
    }
    if (raw) {
      await AsyncStorage.removeItem(THEME_PREFERENCE_KEY);
    }
    return 'system';
  },
  async writeThemePreference(value: ThemePreference): Promise<void> {
    await AsyncStorage.setItem(THEME_PREFERENCE_KEY, value);
  },
  async readSearchHistory(): Promise<string[]> {
    const raw = await AsyncStorage.getItem(SEARCH_HISTORY_KEY);
    if (!raw) {
      return [];
    }
    try {
      const parsed = JSON.parse(raw) as unknown;
      if (!Array.isArray(parsed)) {
        await AsyncStorage.removeItem(SEARCH_HISTORY_KEY);
        return [];
      }
      return parsed.filter(
        (value): value is string => typeof value === 'string',
      );
    } catch {
      await AsyncStorage.removeItem(SEARCH_HISTORY_KEY);
      return [];
    }
  },
  async writeSearchHistory(value: string[]): Promise<void> {
    await AsyncStorage.setItem(SEARCH_HISTORY_KEY, JSON.stringify(value));
  },
  /**
   * Last successfully resolved app config, kept so a cold start without
   * connectivity can still boot with a known identity.
   */
  async readAppConfig(): Promise<AppConfig | null> {
    const raw = await AsyncStorage.getItem(APP_CONFIG_KEY);
    if (!raw) {
      return null;
    }

    try {
      return JSON.parse(raw) as AppConfig;
    } catch {
      await AsyncStorage.removeItem(APP_CONFIG_KEY);
      return null;
    }
  },
  async writeAppConfig(value: AppConfig | null): Promise<void> {
    if (!value) {
      await AsyncStorage.removeItem(APP_CONFIG_KEY);
      return;
    }
    await AsyncStorage.setItem(APP_CONFIG_KEY, JSON.stringify(value));
  },
  async readPushInstallationId(): Promise<string | null> {
    return AsyncStorage.getItem(PUSH_INSTALLATION_ID_KEY);
  },
  async writePushInstallationId(value: string | null): Promise<void> {
    if (!value) {
      await AsyncStorage.removeItem(PUSH_INSTALLATION_ID_KEY);
      return;
    }
    await AsyncStorage.setItem(PUSH_INSTALLATION_ID_KEY, value);
  },
};

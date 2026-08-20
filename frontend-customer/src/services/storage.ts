import type { AppliedPersonalizedOffer, CartState, User, UserPreferences } from '../types/app';

const AUTH_KEY = 'restaurant-rag-customer-auth';
const CART_KEY = 'restaurant-rag-customer-cart';
const CHAT_SESSION_KEY = 'restaurant-rag-chat-session';
const PENDING_AUTH_REDIRECT_KEY = 'restaurant-rag-pending-auth-redirect';
const PREFERENCES_KEY = 'restaurant-rag-customer-preferences';
const PREFERENCES_ONBOARDING_KEY = 'restaurant-rag-customer-preferences-onboarding';
const SELECTED_PERSONALIZED_OFFER_KEY = 'restaurant-rag-customer-personalized-offer';

interface StoredAuth {
  token: string;
  user: User;
}

function isValidCustomerAuth(value: StoredAuth | null): value is StoredAuth {
  return Boolean(value?.token && value.user?.role === 'CUSTOMER');
}

export const storage = {
  readAuth(): StoredAuth | null {
    const raw = window.localStorage.getItem(AUTH_KEY);
    if (!raw) {
      return null;
    }

    try {
      const parsed = JSON.parse(raw) as StoredAuth;
      if (!isValidCustomerAuth(parsed)) {
        window.localStorage.removeItem(AUTH_KEY);
        return null;
      }
      return parsed;
    } catch {
      window.localStorage.removeItem(AUTH_KEY);
      return null;
    }
  },
  writeAuth(value: StoredAuth | null): void {
    if (!value) {
      window.localStorage.removeItem(AUTH_KEY);
      return;
    }

    window.localStorage.setItem(AUTH_KEY, JSON.stringify(value));
  },
  readCart(): CartState | null {
    const raw = window.localStorage.getItem(CART_KEY);
    if (!raw) {
      return null;
    }

    try {
      return JSON.parse(raw) as CartState;
    } catch {
      window.localStorage.removeItem(CART_KEY);
      return null;
    }
  },
  writeCart(value: CartState): void {
    window.localStorage.setItem(CART_KEY, JSON.stringify(value));
  },
  readChatSession(): string | null {
    return window.localStorage.getItem(CHAT_SESSION_KEY);
  },
  writeChatSession(value: string | null): void {
    if (!value) {
      window.localStorage.removeItem(CHAT_SESSION_KEY);
      return;
    }

    window.localStorage.setItem(CHAT_SESSION_KEY, value);
  },
  readPendingAuthRedirect(): string | null {
    return window.localStorage.getItem(PENDING_AUTH_REDIRECT_KEY);
  },
  writePendingAuthRedirect(value: string | null): void {
    if (!value) {
      window.localStorage.removeItem(PENDING_AUTH_REDIRECT_KEY);
      return;
    }

    window.localStorage.setItem(PENDING_AUTH_REDIRECT_KEY, value);
  },
  readPreferences(): UserPreferences | null {
    const raw = window.localStorage.getItem(PREFERENCES_KEY);
    if (!raw) {
      return null;
    }

    try {
      return JSON.parse(raw) as UserPreferences;
    } catch {
      window.localStorage.removeItem(PREFERENCES_KEY);
      return null;
    }
  },
  writePreferences(value: UserPreferences | null): void {
    if (!value) {
      window.localStorage.removeItem(PREFERENCES_KEY);
      return;
    }

    window.localStorage.setItem(PREFERENCES_KEY, JSON.stringify(value));
  },
  readPreferencesOnboardingCompleted(): boolean {
    return window.localStorage.getItem(PREFERENCES_ONBOARDING_KEY) === 'true';
  },
  writePreferencesOnboardingCompleted(value: boolean): void {
    window.localStorage.setItem(PREFERENCES_ONBOARDING_KEY, value ? 'true' : 'false');
  },
  readSelectedPersonalizedOffer(): AppliedPersonalizedOffer | null {
    const raw = window.localStorage.getItem(SELECTED_PERSONALIZED_OFFER_KEY);
    if (!raw) {
      return null;
    }
    try {
      return JSON.parse(raw) as AppliedPersonalizedOffer;
    } catch {
      window.localStorage.removeItem(SELECTED_PERSONALIZED_OFFER_KEY);
      return null;
    }
  },
  writeSelectedPersonalizedOffer(value: AppliedPersonalizedOffer | null): void {
    if (!value) {
      window.localStorage.removeItem(SELECTED_PERSONALIZED_OFFER_KEY);
      return;
    }
    window.localStorage.setItem(SELECTED_PERSONALIZED_OFFER_KEY, JSON.stringify(value));
  },
};

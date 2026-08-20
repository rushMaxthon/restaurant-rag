import { createContext } from 'react';
import type {
  AppliedPersonalizedOffer,
  CartFulfillmentType,
  CartSelectedOption,
  CartSelectedSize,
  CartReplacementPrompt,
  CartState,
  FavoriteItem,
  MenuItem,
  PendingOfferPrompt,
  ToastMessage,
  User,
  UserPreferences,
} from '../types/app';

export type AddToCartInput = {
  menuItem: MenuItem;
  restaurantId: string;
  restaurantName: string;
  restaurantLocationId?: string | null;
  restaurantLocationName?: string | null;
  quantity?: number;
  silent?: boolean;
  selectedSize?: CartSelectedSize | null;
  selectedOptions?: CartSelectedOption[];
  unitPrice?: number;
};

export interface AppStoreValue {
  token: string | null;
  user: User | null;
  cart: CartState;
  selectedPersonalizedOffer: AppliedPersonalizedOffer | null;
  chatSessionId: string | null;
  pendingCartReplacement: CartReplacementPrompt | null;
  pendingOfferPrompt: PendingOfferPrompt | null;
  pendingAuthRedirectPath: string | null;
  preferences: UserPreferences | null;
  favoriteIds: string[];
  favoritesHydrated: boolean;
  favoritePendingIds: string[];
  favoriteVersion: number;
  preferencesOnboardingCompleted: boolean;
  toasts: ToastMessage[];
  isAuthenticated: boolean;
  setSession: (token: string, user: User) => Promise<void>;
  updateUser: (nextUser: User) => void;
  savePreferences: (
    preferences: UserPreferences | null,
    options?: {
      sync?: boolean;
      markOnboardingCompleted?: boolean;
    },
  ) => Promise<void>;
  skipPreferencesOnboarding: () => void;
  refreshFavoriteIds: () => Promise<void>;
  toggleFavorite: (input: {
    menuItemId: string;
    shouldFavorite?: boolean;
  }) => Promise<boolean>;
  isFavorite: (menuItemId: string) => boolean;
  isFavoritePending: (menuItemId: string) => boolean;
  getFavoriteItem: (menuItemId: string) => Promise<FavoriteItem | null>;
  logout: () => void;
  setSelectedPersonalizedOffer: (offer: AppliedPersonalizedOffer | null) => void;
  addToCart: (input: AddToCartInput) => void;
  requestAddToCart: (input: AddToCartInput) => Promise<void>;
  setCartFulfillmentType: (value: CartFulfillmentType) => void;
  updateCartQuantity: (cartItemId: string, nextQuantity: number) => void;
  clearCart: () => void;
  confirmCartReplacement: () => void;
  dismissCartReplacement: () => void;
  applyPendingOfferPrompt: (offerId: string) => void;
  continuePendingOfferPrompt: () => void;
  dismissPendingOfferPrompt: () => void;
  setChatSessionId: (value: string | null) => void;
  setPendingAuthRedirectPath: (path: string | null) => void;
  consumePendingAuthRedirectPath: () => string | null;
  pushToast: (
    title: string,
    description: string,
    tone?: ToastMessage['tone'],
  ) => void;
  dismissToast: (id: number) => void;
}

export const AppStoreContext = createContext<AppStoreValue | null>(null);

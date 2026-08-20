import { useContext, useMemo } from 'react';
import {
  AppStoreActionsContext,
  CartContext,
  ChatSessionContext,
  FavoritesContext,
  PreferencesContext,
  PromptsContext,
  SelectedLocationContext,
  SelectedOfferContext,
  SessionContext,
  ThemePreferenceContext,
  ToastsContext,
  type AppStoreActions,
  type FavoritesValue,
  type PreferencesValue,
  type PromptsValue,
  type SessionValue,
} from '@store/AppStore';
import type {
  AppliedPersonalizedOffer,
  CartState,
  SelectedLocation,
  ToastMessage,
} from '@/types/app';
import type { ThemePreference } from '@/theme';

function useStoreSlice<T>(context: React.Context<T | null>, name: string): T {
  const value = useContext(context);
  if (value === null) {
    throw new Error(`${name} must be used inside AppStoreProvider`);
  }
  return value;
}

/**
 * Actions never change identity, so reading them subscribes a component to
 * nothing. Prefer this over the state hooks wherever a component only
 * dispatches.
 */
export function useAppActions(): AppStoreActions {
  return useStoreSlice(AppStoreActionsContext, 'useAppActions');
}

export function useSession(): SessionValue {
  return useStoreSlice(SessionContext, 'useSession');
}

export function usePreferences(): PreferencesValue {
  return useStoreSlice(PreferencesContext, 'usePreferences');
}

export function useCart(): CartState {
  return useStoreSlice(CartContext, 'useCart');
}

export function useFavoritesState(): FavoritesValue {
  return useStoreSlice(FavoritesContext, 'useFavoritesState');
}

export function usePrompts(): PromptsValue {
  return useStoreSlice(PromptsContext, 'usePrompts');
}

export function useToasts(): ToastMessage[] {
  return useStoreSlice(ToastsContext, 'useToasts');
}

export function useThemePreference(): ThemePreference {
  return useStoreSlice(ThemePreferenceContext, 'useThemePreference');
}

/** Nullable by nature: no location is selected until the user picks one. */
export function useSelectedLocation(): SelectedLocation | null {
  return useContext(SelectedLocationContext);
}

/** Nullable by nature: no offer is applied until the user chooses one. */
export function useSelectedOffer(): AppliedPersonalizedOffer | null {
  return useContext(SelectedOfferContext);
}

/** Nullable by nature: no chat session exists until the first message. */
export function useChatSession(): string | null {
  return useContext(ChatSessionContext);
}

/**
 * Reads every slice at once.
 *
 * Kept for components that genuinely span most of the store (the cart and menu
 * item screens). Anything else should use the narrow hooks above - this one
 * re-renders on every store change, which is what the split exists to avoid.
 */
export function useAppStore() {
  const actions = useAppActions();
  const session = useSession();
  const preferences = usePreferences();
  const cart = useCart();
  const favorites = useFavoritesState();
  const prompts = usePrompts();
  const toasts = useToasts();
  const themePreference = useThemePreference();
  const selectedLocation = useSelectedLocation();
  const selectedPersonalizedOffer = useSelectedOffer();
  const chatSessionId = useChatSession();

  return useMemo(
    () => ({
      ...actions,
      ...session,
      ...preferences,
      ...favorites,
      ...prompts,
      cart,
      toasts,
      themePreference,
      selectedLocation,
      selectedPersonalizedOffer,
      chatSessionId,
    }),
    [
      actions,
      cart,
      chatSessionId,
      favorites,
      preferences,
      prompts,
      selectedLocation,
      selectedPersonalizedOffer,
      session,
      themePreference,
      toasts,
    ],
  );
}

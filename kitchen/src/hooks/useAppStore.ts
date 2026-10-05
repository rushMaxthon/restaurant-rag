import { useContext, useMemo } from 'react';
import {
  AppStoreActionsContext,
  PreferencesContext,
  SessionContext,
  type AppStoreActions,
  type PreferencesValue,
  type SessionValue,
} from '@store/AppStore';
import type { BoardScope, KitchenSession } from '@/types/app';

export function useAppActions(): AppStoreActions {
  const actions = useContext(AppStoreActionsContext);
  if (!actions) {
    throw new Error('useAppActions must be used inside AppStoreProvider');
  }
  return actions;
}

export function useSessionState(): SessionValue {
  return useContext(SessionContext);
}

export function useSession(): KitchenSession | null {
  return useContext(SessionContext).session;
}

export function usePreferences(): PreferencesValue {
  return useContext(PreferencesContext);
}

// Which restaurant and branch the board shows. A pinned branch always wins —
// if the server says this account belongs to one branch, the board must not
// even ask about another. Otherwise the remembered choice, or every branch.
export function useBoardScope(): BoardScope & { canChooseBranch: boolean } {
  const session = useSession();
  const { branchId } = usePreferences();
  return useMemo(() => {
    const pinned = session?.restaurantLocationId ?? null;
    const canChooseBranch = Boolean(session?.restaurantId && !pinned);
    return {
      restaurantId: session?.restaurantId ?? null,
      locationId: pinned ?? (canChooseBranch ? branchId : null),
      canChooseBranch,
    };
  }, [session?.restaurantId, session?.restaurantLocationId, branchId]);
}

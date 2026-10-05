import React, { createContext, useEffect, useMemo, useRef, useState } from 'react';
import { onUnauthorized } from '@services/api';
import { storage } from '@services/storage';
import type { KitchenSession } from '@/types/app';

export interface AppStoreActions {
  signIn: (session: KitchenSession) => void;
  // `expired` marks a sign-out the server forced (401, revoked socket), so the
  // login screen can say why the cook is looking at it.
  signOut: (options?: { expired?: boolean }) => void;
  setSoundOn: (on: boolean) => void;
  setBranchId: (branchId: string | null) => void;
}

export interface SessionValue {
  // False until the saved session has been read. Until then the app shows a
  // splash rather than flashing the login screen at a signed-in tablet.
  hydrated: boolean;
  session: KitchenSession | null;
  expired: boolean;
}

export interface PreferencesValue {
  soundOn: boolean;
  // The branch an unpinned account chose to watch; null is "All branches".
  branchId: string | null;
}

export const AppStoreActionsContext = createContext<AppStoreActions | null>(null);
export const SessionContext = createContext<SessionValue>({
  hydrated: false,
  session: null,
  expired: false,
});
export const PreferencesContext = createContext<PreferencesValue>({
  soundOn: true,
  branchId: null,
});

export const AppStoreProvider = ({ children }: { children: React.ReactNode }) => {
  const [sessionValue, setSessionValue] = useState<SessionValue>({
    hydrated: false,
    session: null,
    expired: false,
  });
  const [preferences, setPreferences] = useState<PreferencesValue>({
    soundOn: true,
    branchId: null,
  });
  const tokenRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([storage.loadSession(), storage.loadSoundOn(), storage.loadBranchId()]).then(
      ([session, soundOn, branchId]) => {
        if (cancelled) {
          return;
        }
        tokenRef.current = session?.token ?? null;
        setSessionValue({ hydrated: true, session, expired: false });
        setPreferences({ soundOn, branchId });
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const actions = useMemo<AppStoreActions>(() => {
    const signOut: AppStoreActions['signOut'] = ({ expired = false } = {}) => {
      tokenRef.current = null;
      storage.saveSession(null);
      setSessionValue({ hydrated: true, session: null, expired });
    };
    return {
      signIn: session => {
        tokenRef.current = session.token;
        storage.saveSession(session);
        setSessionValue({ hydrated: true, session, expired: false });
      },
      signOut,
      setSoundOn: soundOn => {
        storage.saveSoundOn(soundOn);
        setPreferences(current => ({ ...current, soundOn }));
      },
      setBranchId: branchId => {
        storage.saveBranchId(branchId);
        setPreferences(current => ({ ...current, branchId }));
      },
    };
  }, []);

  // A 401 on the token this tablet is signed in with ends the session — an
  // expired token, or a cook deactivated by their owner (which bumps
  // token_version). Without this the board would keep rendering, every
  // request failing, with no way back to sign-in.
  useEffect(
    () =>
      onUnauthorized(token => {
        if (token === tokenRef.current) {
          actions.signOut({ expired: true });
        }
      }),
    [actions],
  );

  return (
    <AppStoreActionsContext.Provider value={actions}>
      <SessionContext.Provider value={sessionValue}>
        <PreferencesContext.Provider value={preferences}>{children}</PreferencesContext.Provider>
      </SessionContext.Provider>
    </AppStoreActionsContext.Provider>
  );
};

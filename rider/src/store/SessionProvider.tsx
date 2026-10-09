import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';

import { translate } from '@/i18n/translate';
import { identifyRider } from '@/services/crashReports';
import { ApiError, setUnauthorizedHandler } from '@/services/http';
import { login as apiLogin, riderApi, type RiderApi } from '@/services/rider';
import { rememberOnboarding } from '@/services/onboardingMemory';
import { clearSession, loadSession, saveSession } from '@/services/session';
import type { LoginResponse, SessionUser } from '@/types/api';

type SessionState =
  | { status: 'loading' }
  | { status: 'signedOut'; reason: string | null }
  | { status: 'signedIn'; token: string; user: SessionUser };

type SessionContextValue = {
  state: SessionState;
  signIn: (phone: string, password: string) => Promise<void>;
  /** A login answer from anywhere: /auth/login, or /rider/signup (same shape). */
  signInWithToken: (result: LoginResponse) => Promise<void>;
  signOut: (reason?: string | null) => Promise<void>;
};

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: 'loading' });
  const tokenRef = useRef<string | null>(null);

  const signOut = useCallback(async (reason: string | null = null) => {
    tokenRef.current = null;
    await clearSession();
    // The next person on this phone may be somebody else entirely.
    await rememberOnboarding(null);
    setState({ status: 'signedOut', reason });
  }, []);

  useEffect(() => {
    let alive = true;
    loadSession().then(saved => {
      if (!alive) return;
      if (saved) {
        tokenRef.current = saved.token;
        setState({ status: 'signedIn', token: saved.token, user: saved.user });
      } else {
        setState({ status: 'signedOut', reason: null });
      }
    });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    // Only the token in use right now can sign us out: a late 401 for a token
    // from an earlier sign-in must not end the new session.
    setUnauthorizedHandler(token => {
      if (token === tokenRef.current) {
        void signOut(translate('system.errAuth'));
      }
    });
    return () => setUnauthorizedHandler(null);
  }, [signOut]);

  const signInWithToken = useCallback(async (result: LoginResponse) => {
    if (String(result.role ?? result.user.role) !== 'RIDER') {
      throw new ApiError(403, 'This account is not a rider account. Ask your manager for rider access.', 'not_rider');
    }
    await saveSession({ token: result.access_token, user: result.user });
    tokenRef.current = result.access_token;
    setState({ status: 'signedIn', token: result.access_token, user: result.user });
  }, []);

  const signIn = useCallback(
    async (phone: string, password: string) => signInWithToken(await apiLogin(phone, password)),
    [signInWithToken],
  );

  const userId = state.status === 'signedIn' ? state.user.id : null;
  useEffect(() => identifyRider(userId), [userId]);

  const value = useMemo(
    () => ({ state, signIn, signInWithToken, signOut }),
    [state, signIn, signInWithToken, signOut],
  );
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error('useSession outside SessionProvider');
  return ctx;
}

/** The API bound to the signed-in token. Only call inside signed-in screens. */
export function useApi(): RiderApi {
  const { state } = useSession();
  const token = state.status === 'signedIn' ? state.token : '';
  return useMemo(() => riderApi(token), [token]);
}

export function useSignedInUser(): SessionUser | null {
  const { state } = useSession();
  return state.status === 'signedIn' ? state.user : null;
}

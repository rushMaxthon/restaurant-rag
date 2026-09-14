import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  api,
  ApiError,
  clearSession,
  getStoredUser,
  getToken,
  setSession,
  type AuthUser,
} from "@/lib/api";
import { clearGuestPreferences, readGuestPreferences } from "@/lib/guest-preferences";

type AuthState = {
  user: AuthUser | null;
  token: string | null;
};

type AuthContextValue = AuthState & {
  isAuthenticated: boolean;
  /**
   * False until the stored session has been read on the client.
   *
   * Callers that would do something irreversible on "not signed in" — like
   * redirecting to /login — must wait for this. During SSR and the first
   * client render nobody is signed in yet, and acting on that would throw a
   * signed-in customer out of checkout.
   */
  ready: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (payload: {
    full_name: string;
    email: string;
    password: string;
    phone_number?: string | null;
  }) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const ROLE_REJECTION_MESSAGE =
  "This app is for customers only. Staff and admin accounts can't sign in here.";

/**
 * useLayoutEffect on the client, useEffect on the server.
 *
 * The restore below has to land BEFORE the browser paints, or a signed-in
 * customer sees a frame of the signed-out header. useLayoutEffect alone warns
 * during SSR, where it is a no-op anyway.
 */
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

/**
 * Move what this browser learned about a guest onto the account they just
 * signed into — but only if that account has nothing of its own.
 *
 * The ACCOUNT WINS. A browser's inference must never overwrite something a
 * person deliberately set: one session on a borrowed laptop would otherwise
 * silently rewrite a long-standing profile, and they would never see it happen.
 * So promotion only ever fires on the visit where an account first has no
 * preferences, which is the new-signup case.
 *
 * Never throws, never awaited in a way that can block. A customer who cannot
 * sign in because a preference promotion failed is a far worse outcome than one
 * whose remembered diet takes another visit to stick — the local copy is left
 * in place and the next login tries again.
 *
 * Goes through PUT /preferences/me rather than writing anything directly, so
 * the server-side cache invalidation and recommendation refresh that endpoint
 * performs come along with it.
 */
async function promoteGuestPreferences(): Promise<void> {
  try {
    const stored = readGuestPreferences();
    if (Object.keys(stored).length === 0) return;

    const existing = await api.getMyPreferences();
    if (existing && (existing.diet || existing.spice_level)) {
      // They already told us, properly. Drop the guess.
      clearGuestPreferences();
      return;
    }

    await api.putMyPreferences({
      diet: stored.diet ?? null,
      spice_level: stored.spice_level ?? null,
    });
    clearGuestPreferences();
  } catch {
    // Keep the local copy and try again next login.
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // Deliberately NOT a lazy initializer reading localStorage.
  //
  // The server has no localStorage, so it always rendered the signed-out
  // header; the client's initializer read the token and rendered the signed-in
  // one. React saw an href of /login against /orders on the very first node of
  // the shared header and did what it does with a mismatch: threw the entire
  // tree away and rebuilt it on the client. That happened on EVERY route, and
  // it is what discarded anything typed into a form before hydration finished.
  //
  // Starting empty makes the first client render agree with the server; the
  // effect below restores the real session in the same frame.
  const [state, setState] = useState<AuthState>({ user: null, token: null });
  const [ready, setReady] = useState(false);

  useIsomorphicLayoutEffect(() => {
    const user = getStoredUser();
    const token = getToken();
    if (user && token) setState({ user, token });
    setReady(true);
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const response = await api.login(email, password);
    if (response.role !== "CUSTOMER") {
      throw new ApiError(ROLE_REJECTION_MESSAGE, 403);
    }
    setSession(response.access_token, response.user);
    setState({ user: response.user, token: response.access_token });
    await promoteGuestPreferences();
  }, []);

  const register = useCallback(
    async (payload: {
      full_name: string;
      email: string;
      password: string;
      phone_number?: string | null;
    }) => {
      const response = await api.register(payload);
      if (response.role !== "CUSTOMER") {
        throw new ApiError(ROLE_REJECTION_MESSAGE, 403);
      }
      setSession(response.access_token, response.user);
      setState({ user: response.user, token: response.access_token });
      // Registration too: a brand new account is precisely the one with nothing
      // of its own, so it is the case promotion was written for.
      await promoteGuestPreferences();
    },
    [],
  );

  const logout = useCallback(() => {
    clearSession();
    setState({ user: null, token: null });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      ...state,
      isAuthenticated: Boolean(state.token && state.user),
      ready,
      login,
      register,
      logout,
    }),
    [state, ready, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}

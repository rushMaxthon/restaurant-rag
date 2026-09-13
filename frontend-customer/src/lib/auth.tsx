import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { api, ApiError, clearSession, getStoredUser, getToken, setSession, type AuthUser } from "@/lib/api";

type AuthState = {
  user: AuthUser | null;
  token: string | null;
};

type AuthContextValue = AuthState & {
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (payload: { full_name: string; email: string; password: string; phone_number?: string | null }) => Promise<void>;
  logout: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

const ROLE_REJECTION_MESSAGE = "This app is for customers only. Staff and admin accounts can't sign in here.";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>(() => ({ user: getStoredUser(), token: getToken() }));

  const login = useCallback(async (email: string, password: string) => {
    const response = await api.login(email, password);
    if (response.role !== "CUSTOMER") {
      throw new ApiError(ROLE_REJECTION_MESSAGE, 403);
    }
    setSession(response.access_token, response.user);
    setState({ user: response.user, token: response.access_token });
  }, []);

  const register = useCallback(
    async (payload: { full_name: string; email: string; password: string; phone_number?: string | null }) => {
      const response = await api.register(payload);
      if (response.role !== "CUSTOMER") {
        throw new ApiError(ROLE_REJECTION_MESSAGE, 403);
      }
      setSession(response.access_token, response.user);
      setState({ user: response.user, token: response.access_token });
    },
    [],
  );

  const logout = useCallback(() => {
    clearSession();
    setState({ user: null, token: null });
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, isAuthenticated: Boolean(state.token && state.user), login, register, logout }),
    [state, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}

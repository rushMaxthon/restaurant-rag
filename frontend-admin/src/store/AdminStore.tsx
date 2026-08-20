import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react';
import { ApiError, AUTH_INVALID_EVENT } from '../services/api';
import { storage } from '../services/storage';
import type { AuthSession, ToastMessage, User, UserRole } from '../types/app';
import { AdminStoreContext, type AdminStoreValue } from './AdminStoreContext';

function isAdminPanelRole(role: UserRole): boolean {
  return role === 'ADMIN' || role === 'OWNER';
}

/** Browser state tied to whoever was logged in, cleared on the way out. */
export function clearRestaurantScopedState(): void {
  const scoped = Object.keys(window.localStorage).filter((key) =>
    key.startsWith("ai-manager:"),
  );
  for (const key of scoped) {
    window.localStorage.removeItem(key);
  }
}


export function AdminStoreProvider({ children }: PropsWithChildren) {
  const storedAuth = typeof window !== 'undefined' ? storage.readAuth() : null;
  const [token, setToken] = useState<string | null>(storedAuth?.token ?? null);
  const [role, setRole] = useState<UserRole | null>(storedAuth?.role ?? null);
  const [restaurantId, setRestaurantId] = useState<string | null>(storedAuth?.restaurantId ?? null);
  const [user, setUser] = useState<User | null>(storedAuth?.user ?? null);
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const nextToastId = useRef(1);

  useEffect(() => {
    storage.writeAuth(token && role && user ? { token, role, restaurantId, user } : null);
  }, [restaurantId, role, token, user]);


  const pushToast = useCallback((title: string, description: string, tone: ToastMessage['tone'] = 'info') => {
    const id = nextToastId.current;
    nextToastId.current += 1;
    setToasts((current) => [...current, { id, title, description, tone }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 3200);
  }, []);

  const dismissToast = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  useEffect(() => {
    if (!token) {
      return;
    }
    const handleAuthInvalid = () => {
      setToken(null);
      setRole(null);
      setRestaurantId(null);
      setUser(null);
      pushToast(
        'Session expired',
        'Your session is no longer valid. Please sign in again.',
        'info',
      );
    };
    window.addEventListener(AUTH_INVALID_EVENT, handleAuthInvalid);
    return () => window.removeEventListener(AUTH_INVALID_EVENT, handleAuthInvalid);
  }, [pushToast, token]);

  const value = useMemo<AdminStoreValue>(
    () => ({
      token,
      role,
      restaurantId,
      user,
      isAuthenticated: Boolean(token && role && user),
      toasts,
      setSession: (session: AuthSession) => {
        if (
          !isAdminPanelRole(session.role) ||
          session.user.role !== session.role
        ) {
          throw new ApiError(
            'Customer accounts cannot access the admin panel.',
            403,
          );
        }
        setToken(session.token);
        setRole(session.role);
        setRestaurantId(session.restaurantId);
        setUser(session.user);
      },
      logout: () => {
        setToken(null);
        setRole(null);
        setRestaurantId(null);
        setUser(null);
        // Anything remembered about which restaurant was being looked at goes
        // with the session. Left behind, the next person to log in on this
        // machine opens the AI Manager pointed at the previous owner's
        // restaurant — it would 403 rather than leak, but it is the wrong
        // starting state and it looks like a leak.
        clearRestaurantScopedState();
      },
      pushToast,
      dismissToast,
    }),
    [restaurantId, role, token, toasts, user],
  );

  return <AdminStoreContext.Provider value={value}>{children}</AdminStoreContext.Provider>;
}

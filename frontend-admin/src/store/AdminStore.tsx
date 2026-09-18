import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react';
import { ApiError, AUTH_INVALID_EVENT, api } from '../services/api';
import { clearPageSnapshots } from '../services/pageCache';
import { storage } from '../services/storage';
import type {
  AuthSession,
  TenantSummary,
  ToastMessage,
  User,
  UserRole,
} from '../types/app';
import { AdminStoreContext, type AdminStoreValue } from './AdminStoreContext';

function isAdminPanelRole(role: UserRole): boolean {
  return role === 'ADMIN' || role === 'OWNER';
}

/**
 * Where the operator's working scope is remembered between visits.
 *
 * An admin picking a restaurant and finding the panel back on "all of them"
 * after a refresh is the behaviour the AI Manager already worked around with
 * its own key; this is that, for the whole panel.
 */
const ACTIVE_RESTAURANT_KEY = "restaurant-rag-admin-active-restaurant";

/** The AI Manager's own key, read once so nobody loses their selection. */
const LEGACY_AI_MANAGER_KEY = "ai-manager:restaurant";

function readActiveRestaurantId(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  try {
    return (
      window.localStorage.getItem(ACTIVE_RESTAURANT_KEY) ||
      window.localStorage.getItem(LEGACY_AI_MANAGER_KEY) ||
      null
    );
  } catch {
    // Private windows and blocked site data both throw here. A panel that
    // opens on "all restaurants" is a worse first impression than a
    // remembered one, not a broken one.
    return null;
  }
}

/** Browser state tied to whoever was logged in, cleared on the way out. */
export function clearRestaurantScopedState(): void {
  const scoped = Object.keys(window.localStorage).filter(
    (key) => key.startsWith("ai-manager:") || key === ACTIVE_RESTAURANT_KEY,
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
  // An owner never has one: they are already scoped to their restaurant, and
  // a switcher offering them a choice of one would be furniture.
  const [activeRestaurantId, setActiveRestaurantIdState] = useState<string | null>(() =>
    storedAuth?.role === "ADMIN" ? readActiveRestaurantId() : null,
  );
  // The whole tenant list, so the switcher can render names and the money
  // formatter can read currencies from the same load.
  const [tenants, setTenants] = useState<TenantSummary[]>([]);
  // An owner sees no tenant list at all — only their own restaurant's
  // currency, which comes from a different endpoint.
  const [ownerCurrencies, setOwnerCurrencies] = useState<Record<string, string>>({});
  const tenantCurrencies = useMemo(
    () =>
      role === "ADMIN"
        ? Object.fromEntries(
            tenants
              .filter((tenant) => tenant.restaurant_id && tenant.currency)
              .map((tenant) => [tenant.restaurant_id as string, tenant.currency]),
          )
        : ownerCurrencies,
    [ownerCurrencies, role, tenants],
  );
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const nextToastId = useRef(1);

  useEffect(() => {
    storage.writeAuth(token && role && user ? { token, role, restaurantId, user } : null);
  }, [restaurantId, role, token, user]);


  const setActiveRestaurantId = useCallback((next: string | null) => {
    setActiveRestaurantIdState(next);
    try {
      if (next) {
        window.localStorage.setItem(ACTIVE_RESTAURANT_KEY, next);
      } else {
        window.localStorage.removeItem(ACTIVE_RESTAURANT_KEY);
      }
    } catch {
      // The choice still applies for this session; it just will not survive
      // a reload. Not worth interrupting anyone over.
    }
  }, []);

  // What each restaurant charges in, so every figure on every screen can be
  // labelled with the right symbol. An admin reads it off the tenants list;
  // an owner has exactly one restaurant and reads it off that.
  //
  // **Fetched here and nowhere else.** The tenant switcher used to load the
  // same list for itself, so every admin page made two identical requests for
  // it — found by reading the network panel, not by anything going wrong.
  // One owner, and the switcher reads what is already here.
  const loadTenants = useCallback(async () => {
    if (!token || !role) {
      return;
    }
    try {
      if (role === "ADMIN") {
        setTenants(await api.listTenants(token));
      } else {
        const own = await api.getOwnerRestaurants(token);
        setOwnerCurrencies(
          Object.fromEntries(own.filter((row) => row.currency).map((row) => [row.id, row.currency])),
        );
      }
    } catch {
      // Labels and navigation, not data. A failure leaves every figure in the
      // platform default rather than blocking the screen that needed it.
    }
  }, [role, token]);

  useEffect(() => {
    // The lint rule reads `loadTenants` as a synchronous setState because it
    // cannot see that every write in it sits after an `await`. The cascading
    // render it warns about cannot happen here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadTenants();
  }, [loadTenants]);

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
      activeRestaurantId: role === "ADMIN" ? activeRestaurantId : null,
      setActiveRestaurantId,
      tenantCurrencies,
      tenants: role === "ADMIN" ? tenants : [],
      refreshTenants: loadTenants,
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
        // A fresh sign-in starts at the platform view rather than inheriting
        // whatever the last person on this machine was looking at.
        setActiveRestaurantId(null);
      },
      logout: () => {
        setToken(null);
        setRole(null);
        setRestaurantId(null);
        setUser(null);
        setActiveRestaurantIdState(null);
        setTenants([]);
        setOwnerCurrencies({});
        // Anything remembered about which restaurant was being looked at goes
        // with the session. Left behind, the next person to log in on this
        // machine opens the AI Manager pointed at the previous owner's
        // restaurant — it would 403 rather than leak, but it is the wrong
        // starting state and it looks like a leak.
        clearRestaurantScopedState();
        // Same reasoning for the in-memory page cache (services/pageCache.ts):
        // without this, the next person to sign in on this tab would see the
        // previous session's cached admin data flash on screen for the instant
        // before their own fetch lands.
        clearPageSnapshots();
      },
      pushToast,
      dismissToast,
    }),
    [
      activeRestaurantId,
      restaurantId,
      role,
      setActiveRestaurantId,
      loadTenants,
      tenantCurrencies,
      tenants,
      token,
      toasts,
      user,
    ],
  );

  return <AdminStoreContext.Provider value={value}>{children}</AdminStoreContext.Provider>;
}

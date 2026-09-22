import { createContext } from 'react';
import type { TenantSummary, ToastMessage, User, UserRole } from '../types/app';

export interface AdminStoreValue {
  token: string | null;
  role: UserRole | null;
  /**
   * The restaurant this *session* belongs to. Always set for an owner, always
   * null for platform staff. It comes from the login response and nobody can
   * change it — it is who you are, not what you are looking at.
   */
  restaurantId: string | null;
  /**
   * The restaurant the operator is currently working on, or null for "all of
   * them". Distinct from `restaurantId` above: an admin belongs to no
   * restaurant and works on one at a time.
   *
   * It lives here rather than on a page because four screens were each
   * keeping their own answer — the AI Manager in its own localStorage key,
   * Reports, Offers and Generated Combos each in a `<select>` that reset on
   * navigation. Switching restaurant meant switching it four times.
   *
   * Always null for an owner: they have exactly one restaurant and the
   * backend scopes them to it regardless of what any client asks for.
   */
  activeRestaurantId: string | null;
  setActiveRestaurantId: (restaurantId: string | null) => void;
  /**
   * Each restaurant's currency, by restaurant id.
   *
   * Held here rather than resolved per screen because one panel shows several
   * restaurants' money and every figure has to be labelled with the right
   * symbol. `useMoney()` is what reads it; nothing else should need to.
   *
   * Empty until the first load, which is why `useMoney` falls back rather
   * than waiting — a figure arriving a moment before its symbol is better
   * than a blank screen.
   */
  tenantCurrencies: Record<string, string>;
  /**
   * Every tenant on the platform, loaded once per session.
   *
   * Here rather than in the switcher that renders it, because the money
   * formatter needs the same rows for their currencies — two components
   * fetching the same list meant two identical requests on every admin page.
   *
   * Empty for an owner, who has one restaurant and no list to switch between.
   */
  tenants: TenantSummary[];
  /**
   * Whether that load has finished. An empty `tenants` means "not known yet"
   * until this is true, so nothing renders a count or an empty state over a
   * list that is merely still in flight.
   */
  tenantsLoaded: boolean;
  /** Reload it — after a lifecycle change on the Tenants page, say. */
  refreshTenants: () => Promise<void>;
  user: User | null;
  isAuthenticated: boolean;
  toasts: ToastMessage[];
  setSession: (session: {
    token: string;
    role: UserRole;
    restaurantId: string | null;
    user: User;
  }) => void;
  logout: () => void;
  pushToast: (title: string, description: string, tone?: ToastMessage['tone']) => void;
  dismissToast: (id: number) => void;
}

export const AdminStoreContext = createContext<AdminStoreValue | null>(null);

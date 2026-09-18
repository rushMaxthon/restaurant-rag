import { useMemo } from 'react';

import { useAdminStore } from './useAdminStore';
import { DEFAULT_CURRENCY, formatCompactCurrency, formatCurrency } from '../services/api';

/**
 * Money, written in whatever the restaurant being looked at charges in.
 *
 * The panel used to write every figure in one currency, which was right while
 * the platform ran one restaurant. It stopped being right the moment a Surat
 * kitchen was onboarded beside a Bangkok one: its ₹35 dhokla was shown as
 * "$35.00" — the right number under the wrong symbol, which is worse than
 * either being wrong alone because it reads as a real price.
 *
 * The currency comes from the shell's tenant switcher, so every screen below
 * it agrees without each one resolving a restaurant for itself.
 *
 * **`mixed` is the honest part.** With "All restaurants" selected and tenants
 * charging in different money, no symbol is correct and a total is not a
 * number at all — ₹40,000 plus $500 is not 40,500 of anything. Screens that
 * aggregate read this and say so rather than printing a figure that looks
 * authoritative and is meaningless.
 */
export interface Money {
  /**
   * A single figure, e.g. "₹1,23,456" or "$1,234.56".
   *
   * `restaurantId` is how a table that lists several restaurants' rows labels
   * each one correctly. Without it the Menu items page — which is explicitly
   * "all restaurants" — showed a Surat kitchen's ₹35 dhokla as "$35.00",
   * which is the same bug one level down: the page was scoped, the row was
   * not. A row that names a restaurant knows its own currency; only a figure
   * that belongs to no single restaurant falls back to the view's.
   */
  format: (value: number | string, restaurantId?: string | null) => string;
  /** The same, shortened for a stat tile: "₹1.2L", "$1.2K". */
  compact: (value: number | string, restaurantId?: string | null) => string;
  /** The ISO code being written. */
  code: string;
  /** True when the view spans restaurants that do not share a currency. */
  mixed: boolean;
}

export function useMoney(): Money {
  const { activeRestaurantId, tenantCurrencies } = useAdminStore();

  return useMemo(() => {
    const currencies = Object.values(tenantCurrencies ?? {});
    const scoped = activeRestaurantId ? tenantCurrencies?.[activeRestaurantId] : undefined;

    // One tenant selected: its currency, unambiguously. Otherwise, the
    // platform's — which is right when every tenant shares one and merely the
    // least-wrong label when they do not, which `mixed` is there to say.
    const distinct = new Set(currencies);
    const code = scoped ?? (distinct.size === 1 ? currencies[0] : DEFAULT_CURRENCY);

    // A row's own restaurant wins over the view's scope; the view's scope is
    // only the answer for a figure that belongs to no single restaurant.
    const codeFor = (restaurantId?: string | null) =>
      (restaurantId ? tenantCurrencies?.[restaurantId] : undefined) ?? code;

    return {
      format: (value, restaurantId) => formatCurrency(value, codeFor(restaurantId)),
      compact: (value, restaurantId) => formatCompactCurrency(value, codeFor(restaurantId)),
      code,
      mixed: !scoped && distinct.size > 1,
    };
  }, [activeRestaurantId, tenantCurrencies]);
}

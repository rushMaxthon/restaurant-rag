import { useMemo } from 'react';

import { useMoney } from './useMoney';
import { getRestaurantScope } from '../services/marketing/marketingApi';

/**
 * Money on the marketing screens, in the restaurant's own currency.
 *
 * Every figure here used to go through `formatCurrency(value)` with no
 * currency, which falls back to the platform default — so a Surat bakery's
 * campaign reported "$31" of revenue and "$0.00" of discount, and its Hub
 * opened on "Total Revenue $0". The right number under the wrong symbol,
 * which `useMoney` exists to stop and these screens had never been given.
 *
 * The restaurant is the one marketing is scoped to, not only the sidebar's:
 * an admin on "All restaurants" still reads ONE restaurant's marketing, and
 * its money is that restaurant's. An owner has no scope and gets their own.
 */
export function useMarketingMoney() {
  const money = useMoney();
  return useMemo(
    () => ({
      format: (value: number | string) => money.format(value, getRestaurantScope()),
      compact: (value: number | string) => money.compact(value, getRestaurantScope()),
    }),
    [money],
  );
}

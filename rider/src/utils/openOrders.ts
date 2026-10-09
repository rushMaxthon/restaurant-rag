/**
 * Words for the open-orders list. The `detail` strings are a contract with
 * `offers.claim` in the backend: `order_taken`, `rider_offline`, `rider_busy`,
 * `order_not_near` (the order is still with the riders nearest the restaurant).
 */

import type { Key } from '@/i18n/strings';
import { translate } from '@/i18n/translate';

const CLAIM_ERRORS: Record<string, Key> = {
  order_taken: 'system.claimTaken',
  rider_offline: 'system.claimOffline',
  rider_busy: 'system.claimBusy',
  order_not_near: 'system.claimNotNear',
};

export function claimErrorMessage(detail: string | undefined): string {
  const key =
    detail && Object.prototype.hasOwnProperty.call(CLAIM_ERRORS, detail)
      ? CLAIM_ERRORS[detail]
      : undefined;
  return translate(key ?? 'system.claimFailed');
}

/** How long before the order goes to a courier instead. */
export function minutesLeftLabel(minutes: number): string {
  return minutes <= 1
    ? translate('system.lastMinute')
    : translate('system.minutesLeft', { n: minutes });
}

/**
 * Why Take is disabled for this rider, or null when they can take an order.
 * The board is for everyone to look at; taking needs them online and free.
 */
export function takeBlockedReason(
  status: string | undefined,
  onTrip: boolean,
): string | null {
  if (onTrip || status === 'ON_TRIP')
    return translate('system.blockedBusy');
  if (status !== 'ONLINE') return translate('system.blockedOffline');
  return null;
}

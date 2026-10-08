/**
 * Words for the open-orders list. The `detail` strings are a contract with
 * `offers.claim` in the backend: `order_taken`, `rider_offline`, `rider_busy`.
 */

const CLAIM_ERRORS: Record<string, string> = {
  order_taken: 'Another rider took this one first.',
  rider_offline: 'Go online to take orders.',
  rider_busy: 'Finish your current delivery first.',
};

export function claimErrorMessage(detail: string | undefined): string {
  return (
    (detail && CLAIM_ERRORS[detail]) || 'Could not take this order. Try again.'
  );
}

/** How long before the order goes to a courier instead. */
export function minutesLeftLabel(minutes: number): string {
  return minutes <= 1 ? 'Last minute' : `${minutes} min left`;
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
    return 'Finish your current delivery first';
  if (status !== 'ONLINE') return 'Go online to take orders';
  return null;
}

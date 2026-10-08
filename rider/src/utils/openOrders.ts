/**
 * Words for the open-orders list. The `detail` strings are a contract with
 * `offers.claim` in the backend: `order_taken`, `rider_offline`.
 */

const CLAIM_ERRORS: Record<string, string> = {
  order_taken: 'Another rider took this one first.',
  rider_offline: 'Go online to take orders.',
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

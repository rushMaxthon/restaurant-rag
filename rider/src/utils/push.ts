/**
 * What a push from the backend means, and where tapping it goes.
 *
 * The backend sends DATA-only messages (`app/services/fleet/notify.py`), so
 * the app draws every notification itself - which is what lets an offer ring
 * full-screen and vanish when it expires. These keys are a contract with that
 * file: `type`, `offer_id`, `expires_at`, `trip_id`, `status`.
 */

export type RiderPush =
  | { kind: 'offer'; offerId: string; expiresAt: string }
  | { kind: 'trip_cancelled'; tripId: string }
  /** The phone stopped answering past push_minutes and the server ended the shift (`shift_ended`). */
  | { kind: 'shift_ended' }
  /** An admin approved, sent back or rejected a self-signed-up rider (`application_decided`). */
  | { kind: 'application'; status: string };

export function parsePush(
  data: Record<string, unknown> | undefined,
): RiderPush | null {
  if (!data) return null;
  const str = (k: string) =>
    typeof data[k] === 'string' ? (data[k] as string) : '';
  if (data.type === 'rider_offer' && str('offer_id')) {
    return {
      kind: 'offer',
      offerId: str('offer_id'),
      expiresAt: str('expires_at'),
    };
  }
  if (data.type === 'rider_trip_cancelled' && str('trip_id')) {
    return { kind: 'trip_cancelled', tripId: str('trip_id') };
  }
  if (data.type === 'rider_shift_ended') return { kind: 'shift_ended' };
  if (data.type === 'rider_application' && str('status')) {
    return { kind: 'application', status: str('status') };
  }
  return null;
}

/** The screen a tap opens: the offer to answer it; Home once a trip is cancelled, since it is gone. */
export function screenFor(push: RiderPush): 'Offer' | 'Home' {
  return push.kind === 'offer' ? 'Offer' : 'Home';
}

/**
 * How long an offer alert should stay up: until the offer expires, and not a
 * moment after - a rider who taps a dead offer gets an error, which is worse
 * than no alert. Null means do not show it at all.
 */
export function offerAlertMs(
  expiresAt: string,
  now: Date = new Date(),
): number | null {
  const left = Date.parse(expiresAt) - now.getTime();
  return Number.isFinite(left) && left > 0 ? left : null;
}

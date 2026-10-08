import type { LocationFix } from '@/types/api';

/**
 * What the next location send carries.
 *
 * The GPS watch only reports when the rider moves 15 m (`distanceFilter`), so
 * a rider standing still - waiting at a restaurant, at a red light - used to
 * send NOTHING, and the server's sweep took them offline after
 * `silent_minutes` (or raised a silent-rider alert mid-trip). Found
 * 2026-10-08. A still rider's last fix is still where they are, so it is
 * resent stamped now; but only while the GPS is healthy - a phone that has
 * lost its fix must read as silent, not as standing still.
 */
export function batchToSend(
  queued: LocationFix[],
  lastFix: LocationFix | null,
  gpsError: string | null,
  now: Date = new Date(),
): LocationFix[] {
  if (queued.length > 0) return queued;
  if (!lastFix || gpsError) return [];
  return [{ ...lastFix, at: now.toISOString() }];
}

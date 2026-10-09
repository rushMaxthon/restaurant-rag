import type { TripAction } from '@/types/api';

/**
 * A trip step the rider took while the phone had no signal.
 *
 * It is written to storage BEFORE the first attempt, so a step taken in a
 * basement survives the app being killed and is replayed on the next open
 * with the SAME action id - the server applies an id once, so a replay that
 * crosses a request which did land is harmless.
 */
export type PendingAction = {
  tripId: string;
  action: TripAction;
  id: string;
  otp?: string;
  savedAt: string;
};

/** Past this, the trip has long moved on; replaying would only confuse it. */
export const PENDING_MAX_AGE_MS = 6 * 60 * 60 * 1000;

const ACTIONS: readonly TripAction[] = [
  'arrived-pickup',
  'picked-up',
  'arrived-drop',
  'delivered',
  'unavailable',
  'call-logged',
];

export function encodePending(p: PendingAction): string {
  return JSON.stringify(p);
}

/** The saved step, if it belongs to this trip and is still worth sending. */
export function decodePending(
  raw: string | null,
  tripId: string,
  now: Date = new Date(),
): PendingAction | null {
  if (!raw) return null;
  let p: Partial<PendingAction>;
  try {
    p = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!p || p.tripId !== tripId || typeof p.id !== 'string') return null;
  if (!p.action || !ACTIONS.includes(p.action)) return null;
  const at = Date.parse(String(p.savedAt));
  if (!Number.isFinite(at) || now.getTime() - at > PENDING_MAX_AGE_MS) return null;
  return {
    tripId: p.tripId,
    action: p.action,
    id: p.id,
    ...(p.otp ? { otp: p.otp } : {}),
    savedAt: String(p.savedAt),
  };
}

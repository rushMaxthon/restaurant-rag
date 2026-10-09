/**
 * What a rider must allow before going online, and in which order.
 *
 * `battery` is Android's battery optimisation: left on, phones from Xiaomi,
 * Realme and friends kill the app minutes after the screen goes off, and the
 * rider silently stops getting orders - the failure the spec names first.
 */
export type PermissionKey = 'location' | 'notifications' | 'battery';
export type PermissionState = Record<PermissionKey, boolean>;

export const PERMISSION_ORDER: readonly PermissionKey[] = ['location', 'notifications', 'battery'];

const REASON: Record<PermissionKey, string> = {
  location: 'Allow location to start getting orders',
  notifications: 'Allow notifications to start getting orders',
  battery: 'Let the app run in the background to start getting orders',
};

export function firstMissing(state: PermissionState | null): PermissionKey | null {
  for (const key of PERMISSION_ORDER) {
    if (!state?.[key]) return key;
  }
  return null;
}

/** The sentence beside a disabled Continue (house rule: say why). */
export function gateReason(state: PermissionState | null): string | null {
  const missing = firstMissing(state);
  return missing ? REASON[missing] : null;
}

/**
 * What a rider must allow before going online, and in which order.
 *
 * `battery` is Android's battery optimisation: left on, phones from Xiaomi,
 * Realme and friends kill the app minutes after the screen goes off, and the
 * rider silently stops getting orders - the failure the spec names first.
 *
 * `fullScreen` is Android 14's "full-screen notifications": without it an
 * offer cannot light up a phone whose screen is off - it arrives as a quiet
 * line in the shade while the phone sits in a pocket (found on the emulator,
 * 2026-10-10). Older Android grants it with the app.
 */
import type { Key } from '@/i18n/strings';
import { translate } from '@/i18n/translate';

export type PermissionKey = 'location' | 'notifications' | 'fullScreen' | 'battery';
export type PermissionState = Record<PermissionKey, boolean>;

export const PERMISSION_ORDER: readonly PermissionKey[] = [
  'location',
  'notifications',
  'fullScreen',
  'battery',
];

const REASON: Record<PermissionKey, Key> = {
  location: 'account.perm.reasonLocation',
  notifications: 'account.perm.reasonNotifications',
  fullScreen: 'account.perm.reasonFullScreen',
  battery: 'account.perm.reasonBattery',
};

export function firstMissing(
  state: PermissionState | null,
): PermissionKey | null {
  for (const key of PERMISSION_ORDER) {
    if (!state?.[key]) return key;
  }
  return null;
}

/** The sentence beside a disabled Continue (house rule: say why). */
export function gateReason(state: PermissionState | null): string | null {
  const missing = firstMissing(state);
  return missing ? translate(REASON[missing]) : null;
}

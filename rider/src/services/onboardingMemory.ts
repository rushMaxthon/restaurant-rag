import AsyncStorage from '@react-native-async-storage/async-storage';

import type { RiderOnboarding } from '@/types/api';

/**
 * The last `onboarding` /rider/me answered on this phone, so the app can
 * pick tabs or the application before the network does (`gateFor`). Not a
 * secret and not the rule - the server refuses a pending rider whatever this
 * says - only a way not to show the wrong screen for a second.
 */
const KEY = 'rider.onboarding.v1';
const VALUES: readonly RiderOnboarding[] = ['PENDING', 'APPROVED', 'REJECTED'];

export async function loadOnboarding(): Promise<RiderOnboarding | null> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    return VALUES.includes(raw as RiderOnboarding)
      ? (raw as RiderOnboarding)
      : null;
  } catch {
    return null;
  }
}

export async function rememberOnboarding(
  value: RiderOnboarding | null,
): Promise<void> {
  try {
    if (value) await AsyncStorage.setItem(KEY, value);
    else await AsyncStorage.removeItem(KEY);
  } catch {
    // only a hint; /rider/me answers again in a moment
  }
}

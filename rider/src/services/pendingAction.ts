import AsyncStorage from '@react-native-async-storage/async-storage';

import { decodePending, encodePending, type PendingAction } from '@utils/pendingAction';

const KEY = 'rider.pendingTripAction';

/**
 * AsyncStorage, not the keychain: a step id and at most a 4-digit code that
 * is useless once the trip ends - unlike the session token. Storage errors
 * are swallowed: losing the saved copy only means the in-memory retry is the
 * one that lands, which is how it worked before this existed.
 */
export async function savePending(p: PendingAction): Promise<void> {
  try {
    await AsyncStorage.setItem(KEY, encodePending(p));
  } catch {}
}

export async function loadPending(tripId: string): Promise<PendingAction | null> {
  try {
    return decodePending(await AsyncStorage.getItem(KEY), tripId);
  } catch {
    return null;
  }
}

export async function clearPending(): Promise<void> {
  try {
    await AsyncStorage.removeItem(KEY);
  } catch {}
}

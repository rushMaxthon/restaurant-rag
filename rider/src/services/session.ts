import * as Keychain from 'react-native-keychain';

import type { SessionUser } from '@/types/api';

/**
 * The signed-in session, kept in the Android Keystore.
 *
 * Not AsyncStorage: that is a plain file any rooted phone or backup tool can
 * read, and this token opens customers' addresses and phone numbers while a
 * trip is live. One record holds the token and the user together, so they
 * can never disagree after a crash between two writes.
 */
const SERVICE = 'com.foodie.rider.session';

export type StoredSession = { token: string; user: SessionUser };

export async function loadSession(): Promise<StoredSession | null> {
  try {
    const found = await Keychain.getGenericPassword({ service: SERVICE });
    if (!found) return null;
    const parsed = JSON.parse(found.password) as StoredSession;
    return parsed?.token && parsed?.user ? parsed : null;
  } catch {
    return null;
  }
}

export async function saveSession(session: StoredSession): Promise<void> {
  await Keychain.setGenericPassword('rider', JSON.stringify(session), { service: SERVICE });
}

export async function clearSession(): Promise<void> {
  try {
    await Keychain.resetGenericPassword({ service: SERVICE });
  } catch {
    // nothing stored, or the keystore is unavailable: either way, signed out
  }
}

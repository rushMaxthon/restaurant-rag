import { useCallback, useEffect, useState } from 'react';
import { AppState, Linking, PermissionsAndroid, Platform } from 'react-native';

export type PermissionKey = 'location' | 'notifications';
export type PermissionState = Record<PermissionKey, boolean>;

const ANDROID_13 = 33;

async function check(): Promise<PermissionState> {
  if (Platform.OS !== 'android') return { location: true, notifications: true };
  const location = await PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION);
  const notifications =
    Number(Platform.Version) < ANDROID_13
      ? true
      : await PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS);
  return { location, notifications };
}

/**
 * What the app is allowed to do, re-read whenever the rider comes back from
 * Settings - a permission granted there must not need an app restart.
 */
export function usePermissions() {
  const [state, setState] = useState<PermissionState | null>(null);

  const refresh = useCallback(async () => setState(await check()), []);

  useEffect(() => {
    void refresh();
    const sub = AppState.addEventListener('change', next => next === 'active' && void refresh());
    return () => sub.remove();
  }, [refresh]);

  const request = useCallback(
    async (key: PermissionKey) => {
      if (Platform.OS !== 'android') return true;
      const permission =
        key === 'location'
          ? PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION
          : PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS;
      if (key === 'notifications' && Number(Platform.Version) < ANDROID_13) return true;
      const result = await PermissionsAndroid.request(permission);
      if (result === PermissionsAndroid.RESULTS.NEVER_ASK_AGAIN) {
        await Linking.openSettings();
      }
      await refresh();
      return result === PermissionsAndroid.RESULTS.GRANTED;
    },
    [refresh],
  );

  const ready = state !== null && state.location && state.notifications;
  return { state, ready, request, refresh };
}

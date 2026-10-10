import { useCallback, useEffect, useState } from 'react';
import {
  AppState,
  Linking,
  NativeModules,
  PermissionsAndroid,
  Platform,
} from 'react-native';
import notifee from '@notifee/react-native';

import {
  firstMissing,
  type PermissionKey,
  type PermissionState,
} from '@utils/permissions';

export type { PermissionKey, PermissionState } from '@utils/permissions';

const ANDROID_13 = 33;

/** Native (BatteryModule.kt); absent on an older install, so Notifee is the fallback. */
const battery:
  | {
      isUnrestricted(): Promise<boolean>;
      requestUnrestricted(): Promise<boolean>;
      canUseFullScreen?(): Promise<boolean>;
      openFullScreenSettings?(): Promise<boolean>;
    }
  | undefined = NativeModules.RiderBattery;

async function fullScreenAllowed(): Promise<boolean> {
  try {
    if (battery?.canUseFullScreen) return await battery.canUseFullScreen();
  } catch {}
  // Unknown is not a reason to lock a rider out of work.
  return true;
}

async function batteryUnrestricted(): Promise<boolean> {
  try {
    if (battery) return await battery.isUnrestricted();
    return !(await notifee.isBatteryOptimizationEnabled());
  } catch {
    // Unknown is not a reason to lock a rider out of work.
    return true;
  }
}

async function check(): Promise<PermissionState> {
  if (Platform.OS !== 'android')
    return {
      location: true,
      notifications: true,
      fullScreen: true,
      battery: true,
    };
  const location = await PermissionsAndroid.check(
    PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
  );
  const notifications =
    Number(Platform.Version) < ANDROID_13
      ? true
      : await PermissionsAndroid.check(
          PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS,
        );
  return {
    location,
    notifications,
    fullScreen: await fullScreenAllowed(),
    battery: await batteryUnrestricted(),
  };
}

/**
 * What the app is allowed to do, re-read whenever the rider comes back from
 * Settings - a permission granted there must not need an app restart.
 */
export function usePermissions() {
  const [state, setState] = useState<PermissionState | null>(null);

  // Returns what it read, so a caller can act on the phone's answer NOW
  // rather than on this copy's state, which another screen may have outdated.
  const refresh = useCallback(async () => {
    const next = await check();
    setState(next);
    return next;
  }, []);

  useEffect(() => {
    // A native check that throws must not become an unhandled rejection.
    const quietly = () => void refresh().catch(() => undefined);
    quietly();
    const sub = AppState.addEventListener(
      'change',
      next => next === 'active' && quietly(),
    );
    return () => sub.remove();
  }, [refresh]);

  const request = useCallback(
    async (key: PermissionKey) => {
      if (Platform.OS !== 'android') return true;
      if (key === 'fullScreen') {
        // Android 14's own settings page for this one app; read again on return.
        const opened = battery?.openFullScreenSettings
          ? await battery.openFullScreenSettings().catch(() => false)
          : false;
        if (!opened) await Linking.openSettings();
        return false;
      }
      if (key === 'battery') {
        // A system dialog; the answer is read when the app comes back.
        const asked = battery
          ? await battery.requestUnrestricted().catch(() => false)
          : false;
        if (!asked) await notifee.openBatteryOptimizationSettings();
        return false;
      }
      const permission =
        key === 'location'
          ? PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION
          : PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS;
      if (key === 'notifications' && Number(Platform.Version) < ANDROID_13)
        return true;
      const result = await PermissionsAndroid.request(permission);
      if (result === PermissionsAndroid.RESULTS.NEVER_ASK_AGAIN) {
        await Linking.openSettings();
      }
      await refresh();
      return result === PermissionsAndroid.RESULTS.GRANTED;
    },
    [refresh],
  );

  /** Phone makers' own "auto-start" screen, where the brand has one (Xiaomi, Oppo...). */
  const openAutoStart = useCallback(async () => {
    try {
      const info = await notifee.getPowerManagerInfo();
      if (info.activity) {
        await notifee.openPowerManagerSettings();
        return true;
      }
    } catch {}
    return false;
  }, []);

  const ready = state !== null && firstMissing(state) === null;
  return { state, ready, request, refresh, openAutoStart };
}

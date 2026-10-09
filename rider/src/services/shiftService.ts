import notifee, {
  AndroidForegroundServiceType,
  AndroidImportance,
} from '@notifee/react-native';
import { Platform } from 'react-native';

import type { Key } from '@/i18n/strings';
import { translate } from '@/i18n/translate';

/**
 * The ongoing "You're online" notification that keeps the rider's location
 * flowing while the app is in the background or the screen is off.
 *
 * Android stops a backgrounded app's GPS within a minute; a foreground
 * service of type LOCATION (declared in AndroidManifest.xml) is the only
 * sanctioned way to keep it, and Android requires the visible notification
 * that comes with it. Without this, the customer's map froze the moment the
 * rider switched to Google Maps to navigate - which is exactly when they ride.
 */

const CHANNEL_ID = 'rider-shift';
const NOTIFICATION_ID = 'rider-shift';

let registered = false;
let running = false;

/** Called once from index.js, before the app renders: the service's long-lived task. */
export function registerShiftService(): void {
  if (registered || Platform.OS !== 'android') return;
  registered = true;
  // The task never resolves on its own: the service lives until stopShift().
  notifee.registerForegroundService(() => new Promise<void>(() => undefined));
}

async function channel(): Promise<string> {
  return notifee.createChannel({
    id: CHANNEL_ID,
    name: translate('system.channelShift'),
    description: translate('system.channelShiftDesc'),
    // Quiet: it is a status, not an alert. Orders use their own loud channel.
    importance: AndroidImportance.LOW,
  });
}

export type ShiftMode = 'online' | 'trip';

// Keys, not sentences: read at display time, in the rider's language.
const COPY: Record<ShiftMode, { title: Key; body: Key }> = {
  online: { title: 'system.shiftOnlineTitle', body: 'system.shiftOnlineBody' },
  trip: { title: 'system.shiftTripTitle', body: 'system.shiftTripBody' },
};

/** Start the service, or update its text if it is already running. */
export async function startShift(mode: ShiftMode): Promise<void> {
  if (Platform.OS !== 'android') return;
  try {
    // Called from ShiftKeeper inside the React tree, so the rider's language
    // is already in force; reading storage here could race a fresh switch.
    const channelId = await channel();
    await notifee.displayNotification({
      id: NOTIFICATION_ID,
      title: translate(COPY[mode].title),
      body: translate(COPY[mode].body),
      android: {
        channelId,
        asForegroundService: true,
        foregroundServiceTypes: [
          AndroidForegroundServiceType.FOREGROUND_SERVICE_TYPE_LOCATION,
        ],
        ongoing: true,
        onlyAlertOnce: true,
        smallIcon: 'ic_notification',
        color: '#FF5200',
        pressAction: { id: 'default', launchActivity: 'default' },
      },
    });
    running = true;
  } catch (error) {
    // A missing notification permission must not stop the rider going
    // online; the app still reports location while it is open.
    console.warn('Could not start the shift service', error);
  }
}

export async function stopShift(): Promise<void> {
  if (Platform.OS !== 'android' || !running) return;
  running = false;
  try {
    await notifee.stopForegroundService();
    await notifee.cancelNotification(NOTIFICATION_ID);
  } catch {
    // already gone
  }
}

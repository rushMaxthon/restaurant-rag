import { Linking, PermissionsAndroid, Platform } from 'react-native';
import notifee, { AndroidImportance, EventType, type Event } from '@notifee/react-native';
import { getApps } from '@react-native-firebase/app';
import {
  AuthorizationStatus,
  deleteToken,
  getInitialNotification,
  getMessaging,
  getToken,
  hasPermission,
  onMessage,
  onNotificationOpenedApp,
  onTokenRefresh,
  registerDeviceForRemoteMessages,
  requestPermission,
  setBackgroundMessageHandler,
  type FirebaseMessagingTypes,
} from '@react-native-firebase/messaging';
import { registerDevice, unregisterDevice } from '@services/devices';
import { ordersChanged } from '@services/orderEvents';
import { storage } from '@services/storage';
import { navigateFromOutside } from '@/navigation/navigationService';

// Push for the kitchen app, after mobile/src/services/pushNotifications.ts:
// FCM delivers, Notifee draws what the OS will not, and a tap opens the order.
// What differs is what a kitchen needs:
//
// * In the FOREGROUND a new-order push draws nothing. The board is open (or
//   mounted under whatever screen is), and it already chimes and highlights
//   a new ticket; a banner too would ring twice for one order. The push is
//   used as a nudge instead — the board refetches at once rather than at its
//   next poll, which also makes a phone with realtime off feel instant.
// * In the BACKGROUND or when the app is CLOSED the OS shows the push on the
//   "New orders" channel, which carries the kitchen chime and a vibration.
// * Signing out unregisters the device AND deletes the local FCM token, so a
//   tablet handed to someone else stops ringing even if the server could not
//   be told.
//
// Every function is a no-op when Firebase is not configured on this build
// (no GoogleService-Info.plist / google-services.json), so a build without it
// still runs the board.

// Must match backend/app/services/kitchen_push.py.
export const KITCHEN_NEW_ORDER = 'kitchen_new_order';
export const ANDROID_CHANNEL_ID = 'kitchen-new-orders';
const ANDROID_SOUND = 'new_order'; // android/app/src/main/res/raw/new_order.wav
const IOS_SOUND = 'new_order.wav'; // ios/kitchen/new_order.wav
// Long-short-long: distinct from a phone call or a message on a pocket buzz.
const VIBRATION_PATTERN = [300, 500, 300, 500];

type PushData = { [key: string]: string | object | number | undefined };

export type PushStatus = 'on' | 'off' | 'unavailable';

let sessionToken: string | null = null;

const firebaseReady = (): boolean => getApps().length > 0;

const messaging = () => getMessaging();

// The channel is what a background push plays on Android — its sound and
// vibration are fixed when it is created, so it is made at startup, before
// any push can arrive.
export const ensureChannel = async (): Promise<void> => {
  if (Platform.OS !== 'android') {
    return;
  }
  await notifee.createChannel({
    id: ANDROID_CHANNEL_ID,
    name: 'New orders',
    description: 'Rings when a new order lands on the kitchen board.',
    importance: AndroidImportance.HIGH,
    sound: ANDROID_SOUND,
    vibration: true,
    vibrationPattern: VIBRATION_PATTERN,
  });
};

const orderIdOf = (data: PushData | undefined): string | null =>
  typeof data?.order_id === 'string' && data.order_id ? data.order_id : null;

// A tapped notification, from any state: open the order. Held by the
// navigation service until the app is ready and someone is signed in.
export const openFromNotification = (data: PushData | undefined): void => {
  const orderId = orderIdOf(data);
  if (orderId) {
    navigateFromOutside({ name: 'OrderDetailScreen', params: { orderId } });
  }
};

// Draws a push the OS did not: a data-only message, or anything other than a
// new-order page while the app is open.
const display = async (message: FirebaseMessagingTypes.RemoteMessage): Promise<void> => {
  await ensureChannel();
  await notifee.displayNotification({
    title: message.notification?.title ?? String(message.data?.title ?? 'Kitchen'),
    body: message.notification?.body ?? String(message.data?.body ?? 'New activity on the board.'),
    data: message.data,
    android: {
      channelId: ANDROID_CHANNEL_ID,
      sound: ANDROID_SOUND,
      pressAction: { id: 'default' },
    },
    ios: {
      sound: IOS_SOUND,
      foregroundPresentationOptions: { banner: true, list: true, sound: true },
    },
  });
};

export const handleForegroundMessage = async (
  message: FirebaseMessagingTypes.RemoteMessage,
): Promise<void> => {
  if (message.data?.notification_type === KITCHEN_NEW_ORDER) {
    ordersChanged();
    return;
  }
  await display(message);
};

export const handleNotifeeEvent = async ({ type, detail }: Event): Promise<void> => {
  if (type === EventType.PRESS || type === EventType.ACTION_PRESS) {
    openFromNotification(detail.notification?.data);
  }
};

// For index.js, before AppRegistry: runs with the app in the background or
// closed. A push with a `notification` block is drawn by the OS itself (the
// backend always sends one); only a data-only message needs drawing here.
export const registerBackgroundHandlers = (): void => {
  if (!firebaseReady()) {
    return;
  }
  setBackgroundMessageHandler(messaging(), async message => {
    if (!message.notification) {
      await display(message);
    }
  });
  notifee.onBackgroundEvent(handleNotifeeEvent);
};

// Listeners for as long as the app is open. Returns the cleanup.
export const initializePushNotifications = async (): Promise<() => void> => {
  if (!firebaseReady()) {
    return () => undefined;
  }
  try {
    await ensureChannel();
    const subscriptions = [
      onMessage(messaging(), handleForegroundMessage),
      onNotificationOpenedApp(messaging(), message => openFromNotification(message.data)),
      notifee.onForegroundEvent(handleNotifeeEvent),
      // FCM rotates tokens; re-register so the next page reaches this device.
      onTokenRefresh(messaging(), () => {
        if (sessionToken) {
          registerForPush(sessionToken);
        }
      }),
    ];

    // Launched by tapping a notification while the app was closed.
    const launchedBy = await getInitialNotification(messaging());
    if (launchedBy) {
      openFromNotification(launchedBy.data);
    }
    const launchedByLocal = await notifee.getInitialNotification();
    if (launchedByLocal) {
      openFromNotification(launchedByLocal.notification.data);
    }

    return () => subscriptions.forEach(unsubscribe => unsubscribe());
  } catch (error) {
    if (__DEV__) {
      console.warn('[Push] Could not start push notifications:', error);
    }
    return () => undefined;
  }
};

const askPermission = async (): Promise<boolean> => {
  if (Platform.OS === 'android') {
    if (Number(Platform.Version) < 33) {
      return true;
    }
    const result = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS);
    return result === PermissionsAndroid.RESULTS.GRANTED;
  }
  await registerDeviceForRemoteMessages(messaging());
  const status = await requestPermission(messaging());
  return status === AuthorizationStatus.AUTHORIZED || status === AuthorizationStatus.PROVISIONAL;
};

// After sign-in: ask once, then tell the backend where to reach this device.
// Resolves to what happened; never throws — a board without push still works.
export const registerForPush = async (
  token: string,
): Promise<'registered' | 'denied' | 'unavailable' | 'failed'> => {
  sessionToken = token;
  if (!firebaseReady()) {
    return 'unavailable';
  }
  try {
    if (!(await askPermission())) {
      return 'denied';
    }
    const fcmToken = await getToken(messaging());
    // Dev builds only: the token is a device credential, so never in release logs.
    if (__DEV__) {
      console.log('[Push] FCM token:', fcmToken);
    }
    const installationId = await storage.loadOrCreatePushInstallationId(`kitchen-${Platform.OS}`);
    await registerDevice(token, {
      installation_id: installationId,
      fcm_token: fcmToken,
      platform: Platform.OS === 'ios' ? 'IOS' : 'ANDROID',
    });
    return 'registered';
  } catch (error) {
    if (__DEV__) {
      console.warn('[Push] Could not register this device:', error);
    }
    return 'failed';
  }
};

// On sign-out, with the token that was signed in. The backend is told first
// (best effort — a forced sign-out's token is already refused), then the
// device's own FCM token is deleted, which stops delivery regardless.
export const unregisterForPush = async (token: string | null): Promise<void> => {
  sessionToken = null;
  if (!firebaseReady()) {
    return;
  }
  try {
    const installationId = await storage.loadPushInstallationId();
    if (token && installationId) {
      await unregisterDevice(token, installationId);
    }
  } catch {
    // Expired or offline: the local delete below still silences the device.
  }
  try {
    await deleteToken(messaging());
  } catch {
    // Nothing more this device can do.
  }
};

// For Settings: whether pushes can reach this device right now.
export const getPushStatus = async (): Promise<PushStatus> => {
  if (!firebaseReady()) {
    return 'unavailable';
  }
  try {
    if (Platform.OS === 'android') {
      if (Number(Platform.Version) < 33) {
        return 'on';
      }
      const granted = await PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS);
      return granted ? 'on' : 'off';
    }
    const status = await hasPermission(messaging());
    return status === AuthorizationStatus.AUTHORIZED || status === AuthorizationStatus.PROVISIONAL
      ? 'on'
      : 'off';
  } catch {
    return 'unavailable';
  }
};

export const openNotificationSettings = (): void => {
  Linking.openSettings().catch(() => undefined);
};

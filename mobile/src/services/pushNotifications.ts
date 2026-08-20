import { Platform, PermissionsAndroid } from 'react-native';
import notifee, {
  AndroidImportance,
  EventType,
  type Event,
} from '@notifee/react-native';
import firebase from '@react-native-firebase/app';
import type { FirebaseMessagingTypes } from '@react-native-firebase/messaging';
import messaging, {
  AuthorizationStatus,
} from '@react-native-firebase/messaging';
import { api } from '@services/api';
import { storage } from '@services/storage';
import { queueNotificationNavigation } from '@/navigation/navigationService';

const ANDROID_CHANNEL_ID = 'default';
const ANDROID_CHANNEL_NAME = 'General Notifications';
let currentFcmToken: string | null = null;
let currentBackendAuthToken: string | null = null;

type NotificationDataPayload = {
  notification_type?: string;
  order_id?: string;
};

function buildInstallationId() {
  return `push-${Platform.OS}-${Date.now()}-${Math.random()
    .toString(36)
    .slice(2, 10)}`;
}

async function getOrCreateInstallationId() {
  const existing = await storage.readPushInstallationId();
  if (existing) {
    return existing;
  }
  const nextValue = buildInstallationId();
  await storage.writePushInstallationId(nextValue);
  return nextValue;
}

function getRemoteMessageTitle(
  remoteMessage: FirebaseMessagingTypes.RemoteMessage,
): string {
  return (
    remoteMessage.notification?.title ??
    remoteMessage.data?.title?.toString() ??
    'QuickBite'
  );
}

function getRemoteMessageBody(
  remoteMessage: FirebaseMessagingTypes.RemoteMessage,
): string {
  return (
    remoteMessage.notification?.body ??
    remoteMessage.data?.body?.toString() ??
    'You have a new notification.'
  );
}

async function requestAndroidNotificationPermission(): Promise<boolean> {
  if (Platform.OS !== 'android' || Platform.Version < 33) {
    return true;
  }

  const status = await PermissionsAndroid.request(
    PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS,
  );
  if (__DEV__) {
    console.log('[Push] Android notification permission status:', status);
  }
  return status === PermissionsAndroid.RESULTS.GRANTED;
}

async function ensureForegroundChannel(): Promise<string | undefined> {
  if (Platform.OS !== 'android') {
    return undefined;
  }

  return notifee.createChannel({
    id: ANDROID_CHANNEL_ID,
    name: ANDROID_CHANNEL_NAME,
    importance: AndroidImportance.HIGH,
  });
}

async function displayForegroundNotification(
  remoteMessage: FirebaseMessagingTypes.RemoteMessage,
): Promise<void> {
  const channelId = await ensureForegroundChannel();

  await notifee.displayNotification({
    title: getRemoteMessageTitle(remoteMessage),
    body: getRemoteMessageBody(remoteMessage),
    data: remoteMessage.data,
    android: channelId
      ? {
          channelId,
          pressAction: {
            id: 'default',
          },
        }
      : undefined,
    ios: {
      foregroundPresentationOptions: {
        alert: true,
        badge: true,
        sound: true,
      },
    },
  });
}

function handleNotificationDataPayload(
  payload: NotificationDataPayload | undefined,
): void {
  if (!payload) {
    return;
  }

  if (payload.notification_type === 'order_placed' && payload.order_id) {
    queueNotificationNavigation({
      screen: 'OrderDetail',
      params: {
        orderId: payload.order_id,
      },
    });
  }
}

function handleRemoteMessageOpen(
  remoteMessage: FirebaseMessagingTypes.RemoteMessage | null,
): void {
  if (!remoteMessage) {
    return;
  }

  if (__DEV__) {
    console.log(
      '[Push] Handling remote notification open:',
      remoteMessage.data,
    );
  }
  handleNotificationDataPayload(
    remoteMessage.data as NotificationDataPayload | undefined,
  );
}

export async function handleNotifeeEvent(event: Event): Promise<void> {
  if (event.type !== EventType.PRESS && event.type !== EventType.ACTION_PRESS) {
    return;
  }

  if (__DEV__) {
    console.log(
      '[Push] Handling local notification press:',
      event.detail.notification?.data,
    );
  }
  handleNotificationDataPayload(
    event.detail.notification?.data as NotificationDataPayload | undefined,
  );
}

async function requestPushPermissions(): Promise<boolean> {
  const androidGranted = await requestAndroidNotificationPermission();

  if (firebase.apps.length === 0) {
    console.warn('[Push] Firebase app is not initialized yet.');
    return false;
  }

  if (Platform.OS === 'ios') {
    await messaging().registerDeviceForRemoteMessages();
    const authStatus = await messaging().requestPermission();
    if (__DEV__) {
      console.log('[Push] iOS messaging permission status:', authStatus);
    }
    await notifee.requestPermission();
    return (
      authStatus === AuthorizationStatus.AUTHORIZED ||
      authStatus === AuthorizationStatus.PROVISIONAL
    );
  }

  return androidGranted;
}

async function getCurrentMessagingToken() {
  if (currentFcmToken) {
    return currentFcmToken;
  }
  const token = await messaging().getToken();
  currentFcmToken = token;
  return token;
}

export async function initializePushNotifications(): Promise<() => void> {
  try {
    if (firebase.apps.length === 0) {
      console.warn('[Push] Firebase app is not initialized yet.');
      return () => undefined;
    }

    const permissionGranted = await requestPushPermissions();
    if (__DEV__) {
      console.log('[Push] Permission granted:', permissionGranted);
    }

    if (!permissionGranted) {
      return () => undefined;
    }

    const fcmToken = await getCurrentMessagingToken();
    if (__DEV__) {
      console.log('[Push] FCM token:', fcmToken);
    }

    const unsubscribeTokenRefresh = messaging().onTokenRefresh(
      refreshedToken => {
        currentFcmToken = refreshedToken;
        if (__DEV__) {
          console.log('[Push] FCM token refreshed:', refreshedToken);
        }
        if (currentBackendAuthToken) {
          void syncPushTokenRegistration(currentBackendAuthToken);
        }
      },
    );

    const unsubscribeForeground = messaging().onMessage(async remoteMessage => {
      if (__DEV__) {
        console.log('[Push] Foreground message received:', remoteMessage);
      }
      await displayForegroundNotification(remoteMessage);
    });

    const unsubscribeNotifeeForeground = notifee.onForegroundEvent(
      async event => {
        await handleNotifeeEvent(event);
      },
    );

    const unsubscribeOpened = messaging().onNotificationOpenedApp(
      remoteMessage => {
        if (__DEV__) {
          console.log(
            '[Push] Notification opened from background:',
            remoteMessage,
          );
        }
        handleRemoteMessageOpen(remoteMessage);
      },
    );

    const initialNotification = await messaging().getInitialNotification();
    if (initialNotification) {
      if (__DEV__) {
        console.log(
          '[Push] Notification opened from quit state:',
          initialNotification,
        );
      }
      handleRemoteMessageOpen(initialNotification);
    }

    const initialLocalNotification = await notifee.getInitialNotification();
    if (initialLocalNotification) {
      if (__DEV__) {
        console.log(
          '[Push] Local notification opened from quit/background state:',
          initialLocalNotification.notification?.data,
        );
      }
      handleNotificationDataPayload(
        initialLocalNotification.notification?.data as
          | NotificationDataPayload
          | undefined,
      );
    }

    return () => {
      unsubscribeTokenRefresh();
      unsubscribeForeground();
      unsubscribeNotifeeForeground();
      unsubscribeOpened();
    };
  } catch (error) {
    console.warn('[Push] Failed to initialize notifications:', error);
    return () => undefined;
  }
}

export async function syncPushTokenRegistration(
  authToken: string,
): Promise<void> {
  if (firebase.apps.length === 0) {
    return;
  }

  try {
    const permissionGranted = await requestPushPermissions();
    if (!permissionGranted) {
      return;
    }

    const fcmToken = await getCurrentMessagingToken();
    const installationId = await getOrCreateInstallationId();
    await api.registerDeviceToken(authToken, {
      installation_id: installationId,
      fcm_token: fcmToken,
      platform: Platform.OS === 'ios' ? 'IOS' : 'ANDROID',
    });
    if (__DEV__) {
      console.log('[Push] Registered FCM token with backend:', {
        installationId,
        platform: Platform.OS,
      });
    }
  } catch (error) {
    console.warn('[Push] Failed to sync FCM token with backend:', error);
  }
}

export function setPushRegistrationAuthToken(token: string | null): void {
  currentBackendAuthToken = token;
}

export function registerBackgroundRemoteMessageHandler(): void {
  if (firebase.apps.length === 0) {
    console.warn(
      '[Push] Skipping background handler because Firebase is not initialized.',
    );
    return;
  }

  messaging().setBackgroundMessageHandler(async remoteMessage => {
    if (__DEV__) {
      console.log('[Push] Background message received:', remoteMessage);
    }

    if (!remoteMessage.notification) {
      await displayForegroundNotification(remoteMessage);
    }
  });
}

import { Platform } from 'react-native';
import notifee from '@notifee/react-native';
import { getApps } from '@react-native-firebase/app';
import {
  deleteToken,
  getInitialNotification,
  requestPermission,
  setBackgroundMessageHandler,
} from '@react-native-firebase/messaging';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { registerDevice, unregisterDevice } from '@services/devices';
import { onOrdersChanged } from '@services/orderEvents';
import { navigateFromOutside } from '@/navigation/navigationService';
import {
  ANDROID_CHANNEL_ID,
  handleForegroundMessage,
  handleNotifeeEvent,
  initializePushNotifications,
  registerBackgroundHandlers,
  registerForPush,
  unregisterForPush,
} from './pushNotifications';

jest.mock('@services/devices', () => ({
  registerDevice: jest.fn(async () => undefined),
  unregisterDevice: jest.fn(async () => undefined),
}));
jest.mock('@/navigation/navigationService', () => ({ navigateFromOutside: jest.fn() }));

const newOrderData = { notification_type: 'kitchen_new_order', order_id: 'order-1' };
const newOrder = { data: newOrderData } as never;

beforeEach(async () => {
  jest.clearAllMocks();
  await AsyncStorage.clear();
});

describe('registering this device', () => {
  it('sends the FCM token with a stable installation id after permission', async () => {
    expect(await registerForPush('session-1')).toBe('registered');
    const [token, device] = (registerDevice as jest.Mock).mock.calls[0];
    expect(token).toBe('session-1');
    expect(device).toEqual({
      installation_id: expect.stringMatching(/^kitchen-ios-/),
      fcm_token: 'fcm-token-1',
      platform: Platform.OS === 'ios' ? 'IOS' : 'ANDROID',
    });

    await registerForPush('session-2');
    expect((registerDevice as jest.Mock).mock.calls[1][1].installation_id).toBe(device.installation_id);
  });

  it('registers nothing when notifications are refused', async () => {
    (requestPermission as jest.Mock).mockResolvedValueOnce(0);
    expect(await registerForPush('session-1')).toBe('denied');
    expect(registerDevice).not.toHaveBeenCalled();
  });

  it('does nothing at all on a build without Firebase', async () => {
    (getApps as jest.Mock).mockReturnValueOnce([]);
    expect(await registerForPush('session-1')).toBe('unavailable');
    expect(requestPermission).not.toHaveBeenCalled();
  });

  it('never throws, so a board without push still works', async () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
    (registerDevice as jest.Mock).mockRejectedValueOnce(new Error('offline'));
    expect(await registerForPush('session-1')).toBe('failed');
    warn.mockRestore();
  });
});

describe('signing out', () => {
  it('tells the server, then deletes the device token', async () => {
    await registerForPush('session-1');
    const installationId = (registerDevice as jest.Mock).mock.calls[0][1].installation_id;

    await unregisterForPush('session-1');

    expect(unregisterDevice).toHaveBeenCalledWith('session-1', installationId);
    expect(deleteToken).toHaveBeenCalled();
  });

  it('still silences the device when the server cannot be told', async () => {
    await registerForPush('expired');
    (unregisterDevice as jest.Mock).mockRejectedValueOnce(new Error('401'));
    await unregisterForPush('expired');
    expect(deleteToken).toHaveBeenCalled();
  });
});

describe('a push while the app is open', () => {
  it('nudges the board to refetch instead of drawing a second alert', async () => {
    const changed = jest.fn();
    const stop = onOrdersChanged(changed);
    await handleForegroundMessage(newOrder);
    stop();
    expect(changed).toHaveBeenCalledTimes(1);
    expect(notifee.displayNotification).not.toHaveBeenCalled();
  });

  it('draws anything that is not a new-order page, on the kitchen channel', async () => {
    await handleForegroundMessage({ notification: { title: 'Hello', body: 'World' }, data: {} } as never);
    const shown = (notifee.displayNotification as jest.Mock).mock.calls[0][0];
    expect(shown.title).toBe('Hello');
    expect(shown.android.channelId).toBe(ANDROID_CHANNEL_ID);
  });
});

describe('the app in the background or closed', () => {
  it('draws only data-only messages; the OS draws the rest', async () => {
    registerBackgroundHandlers();
    const handler = (setBackgroundMessageHandler as jest.Mock).mock.calls[0][1];

    await handler({ notification: { title: 'New order' }, data: newOrderData });
    expect(notifee.displayNotification).not.toHaveBeenCalled();

    await handler({ data: { title: 'Ping', body: 'Data only' } });
    expect(notifee.displayNotification).toHaveBeenCalledTimes(1);
    expect(notifee.onBackgroundEvent).toHaveBeenCalledWith(handleNotifeeEvent);
  });
});

describe('tapping a notification', () => {
  it('opens the order it is about', async () => {
    await handleNotifeeEvent({ type: 1, detail: { notification: { data: { order_id: 'order-9' } } } } as never);
    expect(navigateFromOutside).toHaveBeenCalledWith({
      name: 'OrderDetailScreen',
      params: { orderId: 'order-9' },
    });
  });

  it('ignores a dismissal', async () => {
    await handleNotifeeEvent({ type: 0, detail: { notification: { data: { order_id: 'order-9' } } } } as never);
    expect(navigateFromOutside).not.toHaveBeenCalled();
  });

  it('opens the order that launched a closed app', async () => {
    (getInitialNotification as jest.Mock).mockResolvedValueOnce(newOrder);
    const stop = await initializePushNotifications();
    stop();
    expect(navigateFromOutside).toHaveBeenCalledWith({
      name: 'OrderDetailScreen',
      params: { orderId: 'order-1' },
    });
  });
});

describe('on Android', () => {
  it('creates the chime channel at startup, before any push can arrive', async () => {
    const os = jest.replaceProperty(Platform, 'OS', 'android');
    const stop = await initializePushNotifications();
    stop();
    os.restore();
    expect(notifee.createChannel).toHaveBeenCalledWith(
      expect.objectContaining({
        id: ANDROID_CHANNEL_ID,
        sound: 'new_order',
        vibration: true,
        importance: 4,
      }),
    );
  });
});

/* eslint-env jest */
// Native modules have no implementation under Jest. Each is replaced with the
// smallest stand-in that lets screens render with the real store and hooks;
// tests fake the network themselves by mocking src/services.

jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock'),
);

jest.mock('react-native-sound', () => {
  class Sound {
    static MAIN_BUNDLE = '';
    static setCategory = jest.fn();
    constructor(_file, _base, onLoad) {
      if (onLoad) {
        onLoad(null);
      }
    }
    play = jest.fn();
    stop = jest.fn(callback => callback && callback());
  }
  return Sound;
});

// An inert socket: never connects, so the board runs on polling as it does
// with realtime switched off on the server.
jest.mock('socket.io-client', () => ({
  io: jest.fn(() => ({
    on: jest.fn(),
    emit: jest.fn(),
    connect: jest.fn(),
    disconnect: jest.fn(function () {
      return this;
    }),
    removeAllListeners: jest.fn(),
    close: jest.fn(),
    connected: false,
    active: true,
  })),
}));

// Firebase is configured in these tests (one app), with every messaging call
// a spy; a test that needs "not configured" overrides getApps.
jest.mock('@react-native-firebase/app', () => ({
  getApps: jest.fn(() => [{ name: '[DEFAULT]' }]),
}));

jest.mock('@react-native-firebase/messaging', () => {
  const unsubscribe = () => undefined;
  return {
    AuthorizationStatus: { NOT_DETERMINED: -1, DENIED: 0, AUTHORIZED: 1, PROVISIONAL: 2, EPHEMERAL: 3 },
    getMessaging: jest.fn(() => ({})),
    getToken: jest.fn(async () => 'fcm-token-1'),
    deleteToken: jest.fn(async () => undefined),
    getInitialNotification: jest.fn(async () => null),
    hasPermission: jest.fn(async () => 1),
    requestPermission: jest.fn(async () => 1),
    registerDeviceForRemoteMessages: jest.fn(async () => undefined),
    onMessage: jest.fn(() => unsubscribe),
    onNotificationOpenedApp: jest.fn(() => unsubscribe),
    onTokenRefresh: jest.fn(() => unsubscribe),
    setBackgroundMessageHandler: jest.fn(),
  };
});

jest.mock('@notifee/react-native', () => ({
  __esModule: true,
  default: {
    createChannel: jest.fn(async () => 'kitchen-new-orders'),
    displayNotification: jest.fn(async () => 'id'),
    onForegroundEvent: jest.fn(() => () => undefined),
    onBackgroundEvent: jest.fn(),
    getInitialNotification: jest.fn(async () => null),
    requestPermission: jest.fn(async () => ({ authorizationStatus: 1 })),
  },
  AndroidImportance: { HIGH: 4 },
  EventType: { PRESS: 1, ACTION_PRESS: 2, DISMISSED: 0 },
}));

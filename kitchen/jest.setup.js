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

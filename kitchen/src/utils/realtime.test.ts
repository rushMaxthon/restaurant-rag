import {
  LIVE_POLL_INTERVAL_MS,
  POLL_INTERVAL_MS,
  coalesce,
  pollIntervalFor,
  refusalAction,
  socketEndpoint,
} from './realtime';

describe('socketEndpoint', () => {
  it('moves the API prefix into the socket path', () => {
    expect(socketEndpoint('http://10.0.2.2:8000/api')).toEqual({
      url: 'http://10.0.2.2:8000',
      path: '/api/socket.io',
    });
    expect(socketEndpoint('https://example.com/api/')).toEqual({
      url: 'https://example.com',
      path: '/api/socket.io',
    });
    expect(socketEndpoint('https://example.com')).toEqual({
      url: 'https://example.com',
      path: '/socket.io',
    });
  });
});

describe('refusalAction', () => {
  it('signs out on auth, gives up on refusals that will not change, retries the rest', () => {
    expect(refusalAction('auth')).toBe('sign-out');
    expect(refusalAction('realtime_disabled')).toBe('give-up');
    expect(refusalAction('forbidden')).toBe('give-up');
    expect(refusalAction('invalid_restaurant_id')).toBe('give-up');
    expect(refusalAction('timeout')).toBe('retry');
  });
});

describe('pollIntervalFor', () => {
  it('slows polling only while a push can actually arrive', () => {
    expect(pollIntervalFor('live')).toBe(LIVE_POLL_INTERVAL_MS);
    expect(pollIntervalFor('disabled')).toBe(POLL_INTERVAL_MS);
    expect(pollIntervalFor(null)).toBe(POLL_INTERVAL_MS);
  });
});

describe('coalesce', () => {
  it('turns a burst into one call', () => {
    jest.useFakeTimers();
    const fn = jest.fn();
    const burst = coalesce(fn, 300);
    burst.call();
    burst.call();
    burst.call();
    jest.advanceTimersByTime(300);
    expect(fn).toHaveBeenCalledTimes(1);
    burst.call();
    burst.cancel();
    jest.advanceTimersByTime(300);
    expect(fn).toHaveBeenCalledTimes(1);
    jest.useRealTimers();
  });
});

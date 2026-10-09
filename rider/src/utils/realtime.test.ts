import { offerPollMs, refusalAction, socketEndpoint } from './realtime';

describe('socketEndpoint', () => {
  it('puts the API prefix in the path, not the URL', () => {
    expect(socketEndpoint('http://localhost:8000/api')).toEqual({
      url: 'http://localhost:8000',
      path: '/api/socket.io',
    });
    expect(socketEndpoint('https://api.example.com/api/')).toEqual({
      url: 'https://api.example.com',
      path: '/api/socket.io',
    });
  });
});

describe('refusalAction', () => {
  it('signs out on auth, gives up when realtime is off, retries otherwise', () => {
    expect(refusalAction('auth')).toBe('sign-out');
    expect(refusalAction('realtime_disabled')).toBe('give-up');
    expect(refusalAction('invalid_scope')).toBe('give-up');
    expect(refusalAction('timeout')).toBe('retry');
  });
});

describe('offerPollMs', () => {
  it('polls fast only without a live socket', () => {
    expect(offerPollMs(false)).toBe(3_000);
    expect(offerPollMs(true)).toBe(20_000);
  });
});

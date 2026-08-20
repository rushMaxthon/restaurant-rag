import {
  cachedRequest,
  invalidateRequestCache,
  tokenScope,
} from './requestCache';

describe('requestCache', () => {
  beforeEach(() => {
    invalidateRequestCache();
  });

  it('shares one in-flight request between concurrent callers', async () => {
    let calls = 0;
    let resolveFetch: (value: string) => void = () => {};
    const fetcher = () => {
      calls += 1;
      return new Promise<string>(resolve => {
        resolveFetch = resolve;
      });
    };

    const first = cachedRequest('key', 0, fetcher);
    const second = cachedRequest('key', 0, fetcher);

    resolveFetch('value');

    await expect(first).resolves.toBe('value');
    await expect(second).resolves.toBe('value');
    expect(calls).toBe(1);
  });

  it('reuses a settled value while it is within the TTL', async () => {
    let calls = 0;
    const fetcher = async () => {
      calls += 1;
      return calls;
    };

    await expect(cachedRequest('key', 10_000, fetcher)).resolves.toBe(1);
    await expect(cachedRequest('key', 10_000, fetcher)).resolves.toBe(1);
    expect(calls).toBe(1);
  });

  it('refetches once the TTL has elapsed', async () => {
    let calls = 0;
    const fetcher = async () => {
      calls += 1;
      return calls;
    };
    const nowSpy = jest.spyOn(Date, 'now');

    nowSpy.mockReturnValue(1_000);
    await expect(cachedRequest('key', 10_000, fetcher)).resolves.toBe(1);

    nowSpy.mockReturnValue(20_000);
    await expect(cachedRequest('key', 10_000, fetcher)).resolves.toBe(2);

    expect(calls).toBe(2);
    nowSpy.mockRestore();
  });

  it('does not reuse a settled value when the TTL is zero', async () => {
    let calls = 0;
    const fetcher = async () => {
      calls += 1;
      return calls;
    };

    await expect(cachedRequest('key', 0, fetcher)).resolves.toBe(1);
    await expect(cachedRequest('key', 0, fetcher)).resolves.toBe(2);
    expect(calls).toBe(2);
  });

  it('never caches a rejection', async () => {
    let calls = 0;
    const fetcher = async () => {
      calls += 1;
      if (calls === 1) {
        throw new Error('boom');
      }
      return 'recovered';
    };

    await expect(cachedRequest('key', 10_000, fetcher)).rejects.toThrow('boom');
    await expect(cachedRequest('key', 10_000, fetcher)).resolves.toBe(
      'recovered',
    );
    expect(calls).toBe(2);
  });

  it('keeps different keys independent', async () => {
    const fetcher = (value: string) => async () => value;

    await expect(cachedRequest('a', 10_000, fetcher('a'))).resolves.toBe('a');
    await expect(cachedRequest('b', 10_000, fetcher('b'))).resolves.toBe('b');
  });

  it('invalidates only the matching prefix', async () => {
    let favoriteCalls = 0;
    let orderCalls = 0;

    const favorites = async () => {
      favoriteCalls += 1;
      return favoriteCalls;
    };
    const orders = async () => {
      orderCalls += 1;
      return orderCalls;
    };

    await cachedRequest('favorites:ids', 10_000, favorites);
    await cachedRequest('orders:list', 10_000, orders);

    invalidateRequestCache('favorites:');

    await cachedRequest('favorites:ids', 10_000, favorites);
    await cachedRequest('orders:list', 10_000, orders);

    expect(favoriteCalls).toBe(2);
    expect(orderCalls).toBe(1);
  });

  it('scopes keys per session without exposing the token', () => {
    expect(tokenScope(null)).toBe('anon');
    expect(tokenScope('short')).toBe('short');
    expect(tokenScope('aaaaaaaaaaaaaaaaaaaaaaaaaaaabbbbbbbbbbbb')).toBe(
      'bbbbbbbbbbbb',
    );
  });
});

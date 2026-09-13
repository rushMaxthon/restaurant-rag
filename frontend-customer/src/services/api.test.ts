/**
 * `request()` sets an abort deadline before `fetch()` and used to clear it in
 * a `finally` that ran right after `fetch()` resolved — before the body was
 * ever read. A server that sends headers and then stalls the body (a
 * buffering proxy, a half-closed upstream, a chunked response missing its
 * final chunk) hit `response.json()` with the deadline already cancelled and
 * hung past it forever.
 *
 * This reproduces exactly that shape without mocking more than the stall
 * itself: `fetch` resolves immediately with headers, and `response.json()`
 * only ever settles if the request's own AbortSignal fires. On the old code
 * the timer backing that signal was already cleared by the time this promise
 * is awaited, so it never fires and this test hangs; on the fixed code the
 * timer is still live, fires at the deadline, and turns the stall into the
 * same `ApiError` a caller's `.catch()` already knows how to handle.
 */

import { afterEach, describe, expect, it, vi } from 'vitest';

import { api } from './api';

describe('request() body-read deadline', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('aborts a body that stalls after headers, not just a stalled connect', async () => {
    vi.useFakeTimers();

    const fetchMock = vi.fn((_input: unknown, init?: RequestInit) => {
      const signal = init?.signal;
      return Promise.resolve({
        status: 200,
        ok: true,
        json: () =>
          new Promise((_resolve, reject) => {
            signal?.addEventListener('abort', () => {
              reject(new DOMException('The operation was aborted', 'AbortError'));
            });
          }),
      } as unknown as Response);
    });
    vi.stubGlobal('fetch', fetchMock);

    // `getRestaurant` carries its own 10s `timeoutMs` — see services/api.ts.
    const pending = api.getRestaurant('some-restaurant-id');
    const assertion = expect(pending).rejects.toMatchObject({
      name: 'ApiError',
      status: 408,
    });

    await vi.advanceTimersByTimeAsync(10_000);
    await assertion;
  });
});

/**
 * The home and restaurant pages load their sections with `Promise.all`, and
 * every call in them carries a `.catch()`. That looked like full coverage and
 * was not: `.catch()` handles a REJECTION, and a request that never settles
 * never rejects. When `/recommendations/query` hung, `Promise.all` never
 * resolved, the `finally` that clears the loading flag never ran, and a page
 * whose other four responses had arrived in milliseconds sat in skeletons
 * indefinitely.
 *
 * `withTimeout` closes that hole by making "too slow" indistinguishable from
 * "failed", which the existing `.catch()` chains already know how to handle.
 */

import { describe, expect, it, vi } from 'vitest';

import { TimeoutError, withTimeout } from './withTimeout';

describe('withTimeout', () => {
  it('passes a value through when the promise settles in time', async () => {
    await expect(withTimeout(Promise.resolve('menu'), 50)).resolves.toBe('menu');
  });

  it('passes a rejection through unchanged', async () => {
    const failure = new Error('network down');

    await expect(withTimeout(Promise.reject(failure), 50)).rejects.toBe(failure);
  });

  it('rejects with a TimeoutError when the promise never settles', async () => {
    vi.useFakeTimers();
    try {
      const pending = withTimeout(new Promise(() => {}), 1000);
      const assertion = expect(pending).rejects.toBeInstanceOf(TimeoutError);

      await vi.advanceTimersByTimeAsync(1000);
      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });

  /**
   * The whole point is that callers need not special-case it: an existing
   * `.catch(() => [])` has to absorb a timeout exactly as it absorbs a 500.
   */
  it('is catchable by an ordinary catch handler', async () => {
    vi.useFakeTimers();
    try {
      const fallback = withTimeout<string[]>(new Promise(() => {}), 1000).catch(() => []);
      await vi.advanceTimersByTimeAsync(1000);

      await expect(fallback).resolves.toEqual([]);
    } finally {
      vi.useRealTimers();
    }
  });

  /**
   * A timer left running holds the event loop open and, in a component, fires
   * after unmount. It has to be cleared on the settled path too.
   */
  it('clears its timer once the promise settles', async () => {
    vi.useFakeTimers();
    const clearSpy = vi.spyOn(globalThis, 'clearTimeout');
    try {
      await withTimeout(Promise.resolve('menu'), 1000);

      expect(clearSpy).toHaveBeenCalled();
    } finally {
      clearSpy.mockRestore();
      vi.useRealTimers();
    }
  });

  it('names the elapsed budget so a slow endpoint can be identified from logs', async () => {
    vi.useFakeTimers();
    try {
      const pending = withTimeout(new Promise(() => {}), 1500, 'recommendations');
      const assertion = expect(pending).rejects.toThrow(/recommendations.*1500/);

      await vi.advanceTimersByTimeAsync(1500);
      await assertion;
    } finally {
      vi.useRealTimers();
    }
  });
});

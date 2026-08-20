/**
 * In-flight deduplication and short-TTL caching for read-only API calls.
 *
 * Several screens legitimately need the same data at the same time - Home,
 * Search and Restaurants all list restaurants; Home, Restaurant and Cart all
 * read personalized offers. Without this layer each screen issues its own
 * request, and effects that re-run on object identity issue the same request
 * twice within milliseconds.
 *
 * Two guarantees:
 *
 * - **Dedupe**: while a request for a key is in flight, every caller shares
 *   that one promise. This is unconditional, independent of any TTL.
 * - **TTL**: after it settles, the value is reused for `ttlMs`. `ttlMs: 0`
 *   means dedupe only - the next call after settle goes to the network.
 *
 * Failures are never cached: a rejected request is dropped immediately so the
 * next caller retries.
 */

interface CacheEntry {
  promise: Promise<unknown>;
  /** Epoch ms when the request settled; null while still in flight. */
  settledAt: number | null;
  ttlMs: number;
}

const entries = new Map<string, CacheEntry>();

function isFresh(entry: CacheEntry, now: number): boolean {
  if (entry.settledAt === null) {
    // Still in flight - always share, whatever the TTL.
    return true;
  }
  if (entry.ttlMs <= 0) {
    return false;
  }
  return now - entry.settledAt < entry.ttlMs;
}

/**
 * Runs `fetcher` unless an identical request is in flight or its result is
 * still within `ttlMs`.
 *
 * `key` must include every input that changes the response - the auth token
 * included, since most responses are user-scoped.
 */
export function cachedRequest<T>(
  key: string,
  ttlMs: number,
  fetcher: () => Promise<T>,
): Promise<T> {
  const now = Date.now();
  const existing = entries.get(key);

  if (existing && isFresh(existing, now)) {
    return existing.promise as Promise<T>;
  }

  const entry: CacheEntry = {
    promise: Promise.resolve(),
    settledAt: null,
    ttlMs,
  };

  const promise = fetcher().then(
    value => {
      if (entries.get(key) === entry) {
        entry.settledAt = Date.now();
        if (ttlMs <= 0) {
          entries.delete(key);
        }
      }
      return value;
    },
    error => {
      // Never cache a failure - the next caller must be able to retry.
      if (entries.get(key) === entry) {
        entries.delete(key);
      }
      throw error;
    },
  );

  entry.promise = promise;
  entries.set(key, entry);
  return promise;
}

/**
 * Drops cached entries.
 *
 * Pass a prefix to invalidate one family after a write (`'favorites'` after a
 * favorite toggle); pass nothing to clear everything, which the store does on
 * login and logout so one account never reads another's cached responses.
 */
export function invalidateRequestCache(prefix?: string): void {
  if (!prefix) {
    entries.clear();
    return;
  }
  for (const key of Array.from(entries.keys())) {
    if (key.startsWith(prefix)) {
      entries.delete(key);
    }
  }
}

/** Stable cache-key fragment for a token: user scope without logging secrets. */
export function tokenScope(token?: string | null): string {
  if (!token) {
    return 'anon';
  }
  return token.slice(-12);
}

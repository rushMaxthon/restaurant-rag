/**
 * Synchronous, module-scope cache for page-level data snapshots.
 *
 * This app renders routes with a plain conditional in App.tsx, not a router
 * that keeps matched screens mounted (see `usePathname`/`content` there) — so
 * every navigation, including navigating back to a page you were just on,
 * unmounts the previous page component and mounts a brand-new instance. Local
 * `useState` resets to its initial value on that remount, which is why a page
 * you had fully loaded a second ago flashes its skeleton and re-fetches
 * everything the moment you return to it.
 *
 * A page seeds its state from `getPageSnapshot` inside a `useState` lazy
 * initializer — synchronously, before the first paint — so the very first
 * render already shows the data and never shows a skeleton for a screen it
 * has already loaded. It writes back with `setPageSnapshot` once a fetch
 * resolves, and invalidates with `invalidatePageSnapshot` after a mutation
 * that changes what a future visit should fetch.
 *
 * There is no TTL. A snapshot is valid until the page explicitly invalidates
 * it (after a mutation) or an explicit refresh bypasses it — matching "only
 * fetch again on a genuine data change, a refresh, or a scope/filter change"
 * rather than silently re-fetching in the background on a timer.
 *
 * `key` must include every input that changes the result: the page identity,
 * any filters/sort/pagination that reach the API, and the signed-in scope
 * (`tokenScope`) — without that last part, one admin's cached data would seed
 * the next admin's screen for the instant before their own fetch lands.
 */

interface Snapshot<T> {
  data: T;
}

const snapshots = new Map<string, Snapshot<unknown>>();

/** Reads a cached snapshot for `key`, or `undefined` if none exists. */
export function getPageSnapshot<T>(key: string): T | undefined {
  return (snapshots.get(key) as Snapshot<T> | undefined)?.data;
}

/** Whether a snapshot exists for `key` — use to seed the initial loading flag. */
export function hasPageSnapshot(key: string): boolean {
  return snapshots.has(key);
}

export function setPageSnapshot<T>(key: string, data: T): void {
  snapshots.set(key, { data });
}

/** Drops one exact key — the common case after a mutation on that same page. */
export function invalidatePageSnapshot(key: string): void {
  snapshots.delete(key);
}

/** Drops every key starting with `prefix` — for a page-family, e.g. `orders:`. */
export function invalidatePageSnapshotsByPrefix(prefix: string): void {
  for (const key of Array.from(snapshots.keys())) {
    if (key.startsWith(prefix)) {
      snapshots.delete(key);
    }
  }
}

/** Drops everything. Called on logout so the next session never seeds from it. */
export function clearPageSnapshots(): void {
  snapshots.clear();
}

/** Stable cache-key fragment for a token: session scope without logging secrets. */
export function tokenScope(token?: string | null): string {
  if (!token) {
    return 'anon';
  }
  return token.slice(-12);
}

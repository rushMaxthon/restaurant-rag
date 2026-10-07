/**
 * The storefront's half of the restaurant's Traffic page (2026-10-07).
 *
 * The browser keeps one anonymous random id and, while a page is ON SCREEN,
 * tells the server it is here: once when it is first looked at, then every
 * minute. The server turns those beats into one visitor per restaurant per
 * day and "online now" as anyone heard from in the last two minutes
 * (`backend/app/services/traffic.py`).
 *
 * Why only while visible: a tab left open in the background all afternoon is
 * not somebody looking at the menu, and a page pre-rendered behind another
 * tab is not a visit at all. Why the id lives in localStorage: every tab and
 * every reload shares it, so none of them is a second visitor.
 *
 * Nothing here identifies a person. The id is random, made in this browser,
 * and means nothing outside this restaurant's counts.
 */

export const VISITOR_KEY = "visitor-id";
export const BEAT_EVERY_MS = 60_000;
/** Coming back to a tab beats at once, but not twice in quick succession. */
const MIN_GAP_MS = 20_000;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type KeyValue = { getItem(key: string): string | null; setItem(key: string, value: string): void };

/** For a browser that refuses storage: one id for the life of the page. */
let pageLifetimeId: string | null = null;

export function visitorId(storage: KeyValue | null, makeId: () => string): string {
  try {
    const stored = storage?.getItem(VISITOR_KEY);
    if (stored && UUID.test(stored)) return stored;
    const made = makeId();
    storage?.setItem(VISITOR_KEY, made);
    return made;
  } catch {
    pageLifetimeId ??= makeId();
    return pageLifetimeId;
  }
}

export type HeartbeatEnv = {
  isVisible: () => boolean;
  now: () => number;
  /** Calls `cb` every `ms`; returns a function that stops it. */
  every: (ms: number, cb: () => void) => () => void;
  /** Calls `cb` whenever the page becomes visible; returns a remover. */
  onVisible: (cb: () => void) => () => void;
};

export function startHeartbeat(send: () => void, env: HeartbeatEnv): () => void {
  let last = Number.NEGATIVE_INFINITY;
  const beat = () => {
    if (!env.isVisible()) return;
    if (env.now() - last < MIN_GAP_MS) return;
    last = env.now();
    send();
  };
  beat();
  const stopInterval = env.every(BEAT_EVERY_MS, beat);
  const stopVisible = env.onVisible(beat);
  return () => {
    stopInterval();
    stopVisible();
  };
}

/** The real browser, for `startHeartbeat`. Only call it in the browser. */
export function browserHeartbeatEnv(): HeartbeatEnv {
  return {
    isVisible: () => document.visibilityState === "visible",
    now: () => Date.now(),
    every: (ms, cb) => {
      const id = window.setInterval(cb, ms);
      return () => window.clearInterval(id);
    },
    onVisible: (cb) => {
      const listener = () => {
        if (document.visibilityState === "visible") cb();
      };
      document.addEventListener("visibilitychange", listener);
      return () => document.removeEventListener("visibilitychange", listener);
    },
  };
}

/** A random id, from the browser's own generator where it has one. */
export function makeVisitorId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Older browsers: RFC 4122 version 4 from Math.random. Good enough for an
  // anonymous counter; it is not a secret.
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const random = (Math.random() * 16) | 0;
    return (char === "x" ? random : (random & 0x3) | 0x8).toString(16);
  });
}

function safeLocalStorage(): KeyValue | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

/** Starts the heartbeat for this page. Returns the function that stops it. */
export function startVisitorHeartbeat(post: (visitorId: string) => Promise<unknown>): () => void {
  if (typeof window === "undefined" || typeof document === "undefined") return () => {};
  const id = visitorId(safeLocalStorage(), makeVisitorId);
  return startHeartbeat(() => {
    // A failed beat is a minute of one visitor missing from a chart; it must
    // never surface to the customer.
    post(id).catch(() => {});
  }, browserHeartbeatEnv());
}

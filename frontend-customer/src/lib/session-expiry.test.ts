/**
 * One reaction to a token the server has stopped accepting.
 *
 * Nothing in this app reacted to a 401. The dead token stayed in
 * localStorage, so every later request failed the same way, and each page
 * turned its own failure into whatever message it had nearest to hand — the
 * checkout's was "Check your connection and try again", which sends somebody
 * to look at their wifi because their sign-in lapsed.
 *
 * Two rules decide whether a 401 is an expiry at all, and both matter:
 *
 * - only when a token was actually PRESENTED. A 401 from a sign-in attempt is
 *   a wrong password, and clearing the session and redirecting on it would
 *   turn a typo into a bounce back to the page they were already on;
 * - only ONCE. A page fires four authenticated queries at once and gets four
 *   401s; without a latch that is four session clears and four navigations.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  api,
  announceSessionExpired,
  clearSession,
  getToken,
  setSession,
  setSessionExpiredHandler,
} from "./api";

const A_USER = { id: "u1", email: "customer@example.com", role: "CUSTOMER" } as never;

/**
 * The suite runs in node (see vitest.config.ts) and these helpers reach for
 * `window.localStorage`, so it is stood up here rather than pulling in a DOM
 * for five tests. Small enough to be obviously correct, which is the bar for
 * a fake standing in for something this simple.
 */
function installStorage() {
  const store = new Map<string, string>();
  (globalThis as { window?: unknown }).window = {
    // `request` reads the host to send X-Forwarded-Host.
    location: { host: "radhe-dhokla.localhost:5173", pathname: "/orders", search: "" },
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
      clear: () => store.clear(),
    },
  };
}

describe("session expiry", () => {
  beforeEach(() => {
    installStorage();
    setSessionExpiredHandler(null);
    // A sign-in re-arms the latch, which is also how each test starts clean.
    setSession("a-token", A_USER);
  });

  it("tells the app once, however many requests fail together", () => {
    const handler = vi.fn();
    setSessionExpiredHandler(handler);

    announceSessionExpired();
    announceSessionExpired();
    announceSessionExpired();

    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("throws the dead token away rather than leaving it to fail again", () => {
    setSessionExpiredHandler(() => {});
    expect(getToken()).toBe("a-token");

    announceSessionExpired();

    expect(getToken()).toBeNull();
  });

  it("arms again when somebody signs back in", () => {
    const handler = vi.fn();
    setSessionExpiredHandler(handler);

    announceSessionExpired();
    expect(handler).toHaveBeenCalledTimes(1);

    // The next session is a new one, and its own expiry is worth announcing.
    setSession("a-fresh-token", A_USER);
    announceSessionExpired();
    expect(handler).toHaveBeenCalledTimes(2);
  });

  it("does not need a handler to be registered", () => {
    // Server rendering, or a failure before the provider has mounted. The
    // token still has to go.
    setSessionExpiredHandler(null);
    expect(() => announceSessionExpired()).not.toThrow();
    expect(getToken()).toBeNull();
  });

  it("does not treat a wrong password as an expired session", async () => {
    // The rule that keeps a typo from becoming a logout. `login` presents no
    // token, so its 401 says "those credentials are wrong", not "the token
    // you are holding is dead" — and clearing the session and redirecting on
    // it would bounce somebody off the sign-in page they are already on.
    clearSession();
    const handler = vi.fn();
    setSessionExpiredHandler(handler);

    const originalFetch = globalThis.fetch;
    globalThis.fetch = (async () =>
      new Response(JSON.stringify({ detail: "Incorrect email or password" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      })) as typeof fetch;

    try {
      await expect(api.login("someone@example.com", "wrong")).rejects.toBeTruthy();
    } finally {
      globalThis.fetch = originalFetch;
    }

    expect(handler).not.toHaveBeenCalled();
  });

  it("leaves a signed-out visitor alone", () => {
    // Nothing to clear and nobody to tell: `request` only announces when it
    // actually sent a token, and this is the state that follows.
    clearSession();
    const handler = vi.fn();
    setSessionExpiredHandler(handler);
    setSession("t", A_USER);
    clearSession();

    announceSessionExpired();

    expect(getToken()).toBeNull();
    expect(handler).toHaveBeenCalledTimes(1);
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Withdrawing consent, as a contract rather than as a screen.
 *
 * Consent is the one preference in this app with legal weight, and the rules
 * that matter are not about rendering:
 *
 * * **It is its own endpoint, not part of `PUT /preferences/me`.** That payload
 *   replaces every column it is given, so folding consent in would let a screen
 *   that never showed the toggle silently rewrite it.
 * * **Opting out sends `false` immediately**, on the toggle, never behind a
 *   Save button — withdrawal has to be at least as easy as giving it.
 * * **A null `marketing_opt_in_changed_at` is not a date.** Existing customers
 *   were backfilled opted-in with no timestamp, which means nobody ever asked
 *   them; showing that as a decision they made would be false.
 */

/**
 * `request()` is private to `api.ts`, so the seam is `fetch` itself — which is
 * the better seam anyway: it pins the method, the path and the body that
 * actually go on the wire, not an internal call signature.
 */
const fetchMock = vi.fn<typeof fetch>();

/** What the last call sent: path, method, and the parsed JSON body. */
function lastCall() {
  const call = fetchMock.mock.calls.at(-1);
  const url = String(call?.[0] ?? "");
  const init = (call?.[1] ?? {}) as RequestInit;
  return {
    path: url.replace(/^.*\/api/, ""),
    method: init.method ?? "GET",
    body: init.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null,
    headers: new Headers(init.headers),
  };
}

/**
 * A fresh Response per call — a body can only be read once, so returning one
 * shared object makes the second request in a test fail with "Body is
 * unusable" rather than with whatever it was actually checking.
 */
function respondWith(payload: unknown) {
  fetchMock.mockImplementation(() =>
    Promise.resolve(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ),
  );
}

async function loadApi() {
  vi.resetModules();
  return import("./api");
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  // A signed-in customer: `auth: true` reads the token from storage.
  vi.stubGlobal("localStorage", {
    getItem: () => JSON.stringify({ token: "test-token" }),
    setItem: () => undefined,
    removeItem: () => undefined,
  });
  respondWith({ marketing_opt_in: true, marketing_opt_in_changed_at: null });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("marketing consent endpoint", () => {
  it("reads from its own route, authenticated", async () => {
    const api = await loadApi();
    await api.getMarketingConsent();

    expect(lastCall().path).toBe("/profile/marketing-preferences");
    expect(lastCall().method).toBe("GET");
  });

  it("opts out by sending false, not by omitting the field", async () => {
    const api = await loadApi();
    await api.putMarketingConsent(false);

    const sent = lastCall();
    expect(sent.path).toBe("/profile/marketing-preferences");
    expect(sent.method).toBe("PUT");
    expect(sent.body).toEqual({ marketing_opt_in: false });
  });

  it("opts back in the same way", async () => {
    const api = await loadApi();
    await api.putMarketingConsent(true);

    expect(lastCall().body).toEqual({ marketing_opt_in: true });
  });

  it("never touches the preferences payload, which replaces every column", async () => {
    const api = await loadApi();
    await api.putMarketingConsent(false);
    await api.putMyPreferences({ diet: "VEG" });

    const paths = fetchMock.mock.calls.map((call) => String(call[0]).replace(/^.*\/api/, ""));
    expect(paths).toEqual(["/profile/marketing-preferences", "/preferences/me"]);
    // The preferences write carries no consent field: if it ever did, saving a
    // diet would rewrite a legal record.
    expect(Object.keys(lastCall().body ?? {})).not.toContain("marketing_opt_in");
  });

  it("returns the server's answer rather than the value that was sent", async () => {
    // The server is the record. If it refuses the change and returns the old
    // value, the screen must show the old value.
    respondWith({
      marketing_opt_in: true,
      marketing_opt_in_changed_at: "2026-09-19T10:00:00Z",
    });
    const api = await loadApi();

    const result = await api.putMarketingConsent(false);

    expect(result.marketing_opt_in).toBe(true);
    expect(result.marketing_opt_in_changed_at).toBe("2026-09-19T10:00:00Z");
  });

  it("carries a null timestamp through, so 'never asked' stays distinguishable", async () => {
    const api = await loadApi();

    const result = await api.getMarketingConsent();

    expect(result.marketing_opt_in).toBe(true);
    expect(result.marketing_opt_in_changed_at).toBeNull();
  });
});

/**
 * Whose marketing the Hub is reading.
 *
 * `resolve_insights_scope` requires an ADMIN to name a restaurant and refuses
 * one from an OWNER, so the scope is the whole difference between the two
 * roles on the wire. Every `/marketing/*` call an admin made without it came
 * back `400 "restaurant_id is required for admin insights requests"`, which
 * the Hub rendered as "The Marketing Hub didn't load".
 *
 * These tests pin the query parameter onto the request, not just the setter:
 * a scope that is stored but never sent looks identical from the UI and fails
 * exactly the same way.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * A localStorage of our own.
 *
 * These tests run in node — this app has no jsdom and takes no new
 * dependencies — but the scope is deliberately persisted so a deep link to a
 * campaign editor is scoped before its first fetch. Without a `window` here
 * the production code's try/catch would swallow every write and the
 * persistence test would pass while persisting nothing.
 */
function installWindow(): void {
  const store = new Map<string, string>();
  (globalThis as { window?: unknown }).window = {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
      clear: () => store.clear(),
    },
    dispatchEvent: () => true,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  };
}

const requestMock =
  vi.fn<(path: string, options?: unknown) => Promise<unknown>>();

vi.mock("../api", () => ({
  request: (path: string, options: unknown) => requestMock(path, options),
  API_BASE_URL: "http://localhost:8000/api",
}));

vi.mock("../storage", () => ({
  storage: { readAuth: () => ({ token: "test-token" }) },
}));

const RESTAURANT = "262713a5-22e6-4dcc-a4f7-534a5375dd0f";

async function loadModules() {
  vi.resetModules();
  const api = await import("./marketingApi");
  const client = await import("./marketingClient");
  return { api, client };
}

beforeEach(() => {
  requestMock.mockReset();
  // A list, not `{}`: the client now normalises campaign responses, and the
  // list endpoint's normaliser maps over what it is given. The shape is not
  // what these tests assert — the path is — but a stub has to be answerable.
  requestMock.mockResolvedValue([]);
  installWindow();
});

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
});

describe("restaurant scope on the wire", () => {
  it("sends nothing for an owner, who the backend pins to their own restaurant", async () => {
    const { api, client } = await loadModules();
    api.setRestaurantScope(null);
    await client.fetchReference();
    expect(requestMock.mock.calls[0]?.[0]).toBe("/marketing/reference");
  });

  it("names the restaurant for an admin", async () => {
    const { api, client } = await loadModules();
    api.setRestaurantScope(RESTAURANT);
    await client.fetchReference();
    expect(requestMock.mock.calls[0]?.[0]).toBe(
      `/marketing/reference?restaurant_id=${RESTAURANT}`,
    );
  });

  it("scopes every call the Hub makes, not just the first one it loads", async () => {
    const { api, client } = await loadModules();
    api.setRestaurantScope(RESTAURANT);

    await client.fetchCampaigns();
    await client.fetchCampaign("abc");
    await client.saveDraft({ id: "cmp-local", name: "x" } as never);
    await client.scheduleCampaign("abc", "2026-10-01T10:00:00Z");
    await client.cancelCampaign("abc");
    await client.duplicateCampaign("abc");
    await client.deleteDraft("abc");
    await client.fetchReachEstimate({ goal: "WIN_BACK" } as never);

    const paths = requestMock.mock.calls.map((call) => call[0]);
    expect(paths).toHaveLength(8);
    for (const path of paths) {
      expect(path).toContain(`restaurant_id=${RESTAURANT}`);
    }
  });

  it("remembers the choice, so a deep link to a campaign is scoped before its first fetch", async () => {
    const first = await loadModules();
    first.api.setRestaurantScope(RESTAURANT);

    // A fresh page load: new modules, the same storage carried over, which is
    // exactly what a browser reload leaves behind.
    const second = await loadModules();
    expect(second.api.getRestaurantScope()).toBe(RESTAURANT);
    await second.client.fetchCampaign("abc");
    expect(requestMock.mock.calls.at(-1)?.[0] ?? "").toContain(
      `restaurant_id=${RESTAURANT}`,
    );
  });

  it("reports whether the scope actually changed, so an unchanged pick costs no reload", async () => {
    const { api } = await loadModules();
    expect(api.setRestaurantScope(RESTAURANT)).toBe(true);
    expect(api.setRestaurantScope(RESTAURANT)).toBe(false);
    expect(api.setRestaurantScope(null)).toBe(true);
  });

  it("forgets a cleared scope rather than leaving the old restaurant behind", async () => {
    const { api } = await loadModules();
    api.setRestaurantScope(RESTAURANT);
    api.setRestaurantScope(null);

    const reloaded = await loadModules();
    expect(reloaded.api.getRestaurantScope()).toBeNull();
  });
});

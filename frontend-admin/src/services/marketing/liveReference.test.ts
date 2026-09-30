/**
 * Mock data must never reach the wire in live mode.
 *
 * `marketingReference` used to be initialised from the mock constants, so for
 * the window between mount and the first `/reference` response every reader
 * got the demo dataset. `emptyDraft()` reads branches during exactly that
 * window, so a new campaign was seeded with `branch-indiranagar` and the
 * backend refused to save it: *"branch_ids: Input should be a valid UUID"*.
 * A brand new campaign could not be saved at all.
 *
 * These pin the invariant rather than the symptom: before real data lands,
 * live mode offers nothing rather than something fake.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

async function loadApi() {
  vi.resetModules();
  return import("./marketingApi");
}

/** Anything the backend types as a UUID has to look like one. */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

beforeEach(() => {
  requestMock.mockReset();
  installWindow();
});

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
});

describe("reference data before the first response", () => {
  it("offers no branches at all, rather than the mock ones", async () => {
    const api = await loadApi();
    expect(api.getDataSource()).toBe("live");
    expect(api.hasReference()).toBe(false);
    expect(api.marketingReference.branches).toEqual([]);
    expect(api.marketingReference.goals).toEqual([]);
    expect(api.marketingReference.offers).toEqual([]);
  });

  it("does not resolve a mock branch id", async () => {
    const api = await loadApi();
    expect(api.getBranch("branch-indiranagar")).toBeNull();
  });

  it("serves real branches once they arrive, and every id is a UUID", async () => {
    const api = await loadApi();
    requestMock.mockResolvedValue({
      goals: [],
      segments: [],
      branches: [
        {
          id: "67d703ac-f2bd-4e2d-b694-fe49e0aebcb2",
          branch_name: "Bangkok Bowl Bodakdev",
          city: "Ahmedabad",
          state: "Gujarat",
          is_active: true,
          opens_at: "11:00",
          closes_at: "23:00",
        },
      ],
      offers: [],
      templates: [],
      minimum_segment_size: 10,
      frequency_cap_per_week: 2,
      timezone: "Asia/Kolkata",
    });

    await api.ensureReference();

    expect(api.hasReference()).toBe(true);
    const ids = api.marketingReference.branches.map((branch) => branch.id);
    expect(ids).toHaveLength(1);
    for (const id of ids) {
      expect(id).toMatch(UUID);
    }
  });

  it("still serves the demo dataset when the source is mock", async () => {
    const api = await loadApi();
    api.setDataSource("mock");
    await api.ensureReference();
    expect(api.marketingReference.branches.length).toBeGreaterThan(0);
  });
});

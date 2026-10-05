/**
 * Whether the sidebar is a full column or an icon rail, remembered.
 *
 * It is a preference about the whole panel — more room for a wide table — so
 * it has to survive a reload, and it must never be the reason the panel fails
 * to render: `localStorage` throws in a private window.
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { storedSidebarCollapsed, storeSidebarCollapsed } from "./sidebarState";

function installStorage(throws = false): Map<string, string> {
  const store = new Map<string, string>();
  (globalThis as { localStorage?: unknown }).localStorage = {
    getItem: (key: string) => {
      if (throws) throw new Error("blocked");
      return store.get(key) ?? null;
    },
    setItem: (key: string, value: string) => {
      if (throws) throw new Error("blocked");
      store.set(key, value);
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
  };
  return store;
}

describe("the sidebar's remembered state", () => {
  beforeEach(() => {
    installStorage();
  });

  afterEach(() => {
    delete (globalThis as { localStorage?: unknown }).localStorage;
  });

  it("is expanded for somebody who never chose", () => {
    expect(storedSidebarCollapsed()).toBe(false);
  });

  it("remembers a collapse, and an expand after it", () => {
    storeSidebarCollapsed(true);
    expect(storedSidebarCollapsed()).toBe(true);
    storeSidebarCollapsed(false);
    expect(storedSidebarCollapsed()).toBe(false);
  });

  it("reads anything it did not write as expanded", () => {
    const store = installStorage();
    store.set("admin.sidebar", "sideways");
    expect(storedSidebarCollapsed()).toBe(false);
  });

  it("stays expanded, and does not throw, when storage is blocked", () => {
    installStorage(true);
    expect(storedSidebarCollapsed()).toBe(false);
    expect(() => storeSidebarCollapsed(true)).not.toThrow();
  });
});

import { beforeEach, describe, expect, it } from "vitest";

import {
  clearPageSnapshots,
  getPageSnapshot,
  hasPageSnapshot,
  invalidatePageSnapshot,
  invalidatePageSnapshotsByPrefix,
  setPageSnapshot,
  tokenScope,
} from "./pageCache";

describe("pageCache", () => {
  beforeEach(() => {
    clearPageSnapshots();
  });

  it("has nothing for a key that was never set", () => {
    expect(hasPageSnapshot("orders:abc")).toBe(false);
    expect(getPageSnapshot("orders:abc")).toBeUndefined();
  });

  it("returns exactly what was stored", () => {
    setPageSnapshot("orders:abc", { orders: [1, 2, 3], total: 3 });

    expect(hasPageSnapshot("orders:abc")).toBe(true);
    expect(getPageSnapshot("orders:abc")).toEqual({ orders: [1, 2, 3], total: 3 });
  });

  it("has no TTL - a snapshot stays valid until something invalidates it", () => {
    setPageSnapshot("dashboard:abc", { stats: 42 });

    // Nothing decays this on its own: it is only ever removed by an explicit
    // invalidation call (after a mutation) or clearPageSnapshots (on logout).
    expect(getPageSnapshot("dashboard:abc")).toEqual({ stats: 42 });
    expect(getPageSnapshot("dashboard:abc")).toEqual({ stats: 42 });
  });

  it("overwrites a snapshot for the same key rather than merging it", () => {
    setPageSnapshot("orders:abc", { total: 1 });
    setPageSnapshot("orders:abc", { total: 2 });

    expect(getPageSnapshot("orders:abc")).toEqual({ total: 2 });
  });

  it("keeps different keys independent", () => {
    setPageSnapshot("orders:abc", { total: 1 });
    setPageSnapshot("menu-items:abc", { total: 2 });

    expect(getPageSnapshot("orders:abc")).toEqual({ total: 1 });
    expect(getPageSnapshot("menu-items:abc")).toEqual({ total: 2 });
  });

  it("invalidatePageSnapshot drops only the exact key", () => {
    setPageSnapshot("orders:abc:list:1", { total: 1 });
    setPageSnapshot("orders:abc:list:2", { total: 2 });

    invalidatePageSnapshot("orders:abc:list:1");

    expect(hasPageSnapshot("orders:abc:list:1")).toBe(false);
    expect(hasPageSnapshot("orders:abc:list:2")).toBe(true);
  });

  it("invalidatePageSnapshotsByPrefix drops every matching key and nothing else", () => {
    setPageSnapshot("orders:abc:list:1", { total: 1 });
    setPageSnapshot("orders:abc:tiles", { total: 2 });
    setPageSnapshot("menu-items:abc", { total: 3 });

    invalidatePageSnapshotsByPrefix("orders:abc:");

    expect(hasPageSnapshot("orders:abc:list:1")).toBe(false);
    expect(hasPageSnapshot("orders:abc:tiles")).toBe(false);
    expect(hasPageSnapshot("menu-items:abc")).toBe(true);
  });

  it("clearPageSnapshots drops everything, for logout", () => {
    setPageSnapshot("orders:abc", { total: 1 });
    setPageSnapshot("menu-items:abc", { total: 2 });

    clearPageSnapshots();

    expect(hasPageSnapshot("orders:abc")).toBe(false);
    expect(hasPageSnapshot("menu-items:abc")).toBe(false);
  });

  it("scopes keys per session without exposing the token", () => {
    expect(tokenScope(null)).toBe("anon");
    expect(tokenScope(undefined)).toBe("anon");
    expect(tokenScope("short")).toBe("short");
    expect(tokenScope("aaaaaaaaaaaaaaaaaaaaaaaaaaaabbbbbbbbbbbb")).toBe(
      "bbbbbbbbbbbb",
    );
  });
});

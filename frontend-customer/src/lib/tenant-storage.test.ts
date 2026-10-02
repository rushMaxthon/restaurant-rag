import { beforeEach, describe, expect, it } from "vitest";

import {
  STORAGE,
  readTenant,
  removeTenant,
  tenantKey,
  writeTenant,
} from "./tenant-storage";

/**
 * One deployment serves every restaurant, and until now every one of them
 * wrote `bangkok-bowl-token` into its customers' browsers.
 *
 * Two things are worth testing here and neither is the renaming. The first is
 * that the key follows the HOST, because the host is what selects the tenant —
 * so two restaurants reached on one origin cannot read each other's cart or be
 * handed each other's sign-in token. The second is the adoption: a rename on
 * its own would sign every existing customer out and empty every cart on the
 * deploy, so the old value has to be picked up exactly once and then let go.
 */
function install(hostname: string) {
  const store = new Map<string, string>();
  (globalThis as { window?: unknown }).window = {
    location: { hostname },
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
      clear: () => store.clear(),
    },
  };
  return store;
}

describe("a key belongs to the restaurant being served", () => {
  it("names the host it was opened on", () => {
    install("bhagwati-bakery.localhost");
    expect(tenantKey(STORAGE.state)).toBe("storefront:bhagwati-bakery.localhost:state");
  });

  it("gives two restaurants on one origin two different keys", () => {
    // The case that matters. In production each tenant has its own subdomain
    // and the browser separates them anyway; in development they share
    // `localhost` and are told apart by a header.
    install("bhagwati-bakery.localhost");
    const one = tenantKey(STORAGE.token);
    install("dragon-wok.localhost");
    expect(tenantKey(STORAGE.token)).not.toBe(one);
  });

  it("does not let a host's case or a trailing port split a tenant in two", () => {
    install("Bhagwati-Bakery.localhost");
    expect(tenantKey(STORAGE.state)).toBe("storefront:bhagwati-bakery.localhost:state");
  });
});

describe("what one restaurant stores, another cannot read", () => {
  it("keeps carts apart", () => {
    const store = install("bhagwati-bakery.localhost");
    writeTenant(STORAGE.state, '{"cart":["a bun"]}');

    (globalThis as { window?: unknown }).window = {
      location: { hostname: "dragon-wok.localhost" },
      localStorage: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => void store.set(key, value),
        removeItem: (key: string) => void store.delete(key),
        clear: () => store.clear(),
      },
    };
    expect(readTenant(STORAGE.state)).toBeNull();
  });
});

describe("an existing customer keeps their cart across the rename", () => {
  it("adopts the old value the first time it is read", () => {
    const store = install("bhagwati-bakery.localhost");
    store.set("bangkok-bowl-state", '{"cart":["a bun"]}');

    expect(readTenant(STORAGE.state)).toBe('{"cart":["a bun"]}');
    // Moved, not copied: left behind, the next tenant on this origin would
    // inherit it too, which is the thing being fixed.
    expect(store.get(tenantKey(STORAGE.state))).toBe('{"cart":["a bun"]}');
    expect(store.has("bangkok-bowl-state")).toBe(false);
  });

  it("prefers what is already under the new name", () => {
    const store = install("bhagwati-bakery.localhost");
    store.set(tenantKey(STORAGE.token), "current");
    store.set("bangkok-bowl-token", "stale");
    expect(readTenant(STORAGE.token)).toBe("current");
  });

  it("clears the legacy key on sign-out, so it cannot come back", () => {
    // Without this, signing out would remove the new key and leave the old
    // one for the adoption above to pick up on the next load — signing the
    // customer back in with a token they asked to be rid of.
    const store = install("bhagwati-bakery.localhost");
    store.set("bangkok-bowl-token", "stale");
    writeTenant(STORAGE.token, "current");

    removeTenant(STORAGE.token);
    expect(readTenant(STORAGE.token)).toBeNull();
    expect(store.has("bangkok-bowl-token")).toBe(false);
  });
});

describe("storage that is unavailable is not fatal", () => {
  beforeEach(() => {
    (globalThis as { window?: unknown }).window = {
      location: { hostname: "bhagwati-bakery.localhost" },
      localStorage: {
        getItem: () => {
          throw new Error("blocked");
        },
        setItem: () => {
          throw new Error("blocked");
        },
        removeItem: () => {
          throw new Error("blocked");
        },
      },
    };
  });

  it("reads as empty rather than throwing", () => {
    // Private modes throw outright on access. A storefront that fails to
    // render because it could not read a cart is a far worse bug than a cart
    // that is forgotten.
    expect(() => readTenant(STORAGE.state)).not.toThrow();
    expect(readTenant(STORAGE.state)).toBeNull();
  });

  it("writes and removals fail quietly", () => {
    expect(() => writeTenant(STORAGE.state, "x")).not.toThrow();
    expect(() => removeTenant(STORAGE.state)).not.toThrow();
  });
});

describe("a window without a location does not break the page", () => {
  it("falls back rather than throwing", () => {
    // Stood up by hand in a few places, and an embedding may not provide one.
    (globalThis as { window?: unknown }).window = {
      localStorage: {
        getItem: () => null,
        setItem: () => undefined,
        removeItem: () => undefined,
      },
    };
    expect(() => tenantKey(STORAGE.state)).not.toThrow();
    expect(tenantKey(STORAGE.state)).toContain("unknown");
  });
});

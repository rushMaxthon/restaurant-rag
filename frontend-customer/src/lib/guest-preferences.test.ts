import { beforeEach, describe, expect, it } from "vitest";
import {
  clearGuestPreferences,
  guestPreferencesForRequest,
  mergeGuestPreferences,
  readGuestPreferences,
} from "./guest-preferences";

/**
 * What a browser is allowed to remember for a visitor with no account.
 *
 * This store is unusual in that its contents are sent to the server and used to
 * shape results, so the interesting cases are not "does it round-trip" but
 * "what happens when the value is wrong". A corrupt or oversized entry must
 * degrade to no memory, never to a broken chat and never to an unbounded string
 * on the wire.
 *
 * The narrowing matters for a second reason: the backend honours these only for
 * a guest and ignores them outright for a signed-in customer, so a wide field
 * here cannot become an injection into someone's account — but it can still
 * make this visitor's own results nonsense, and it costs nothing to prevent.
 */
/**
 * A localStorage stub rather than jsdom.
 *
 * `vitest.config.ts` runs these in `environment: "node"` and neither jsdom nor
 * happy-dom is installed. Pulling one in for eight assertions about a
 * twelve-line key-value store would be a dependency the repo does not otherwise
 * need — and the module only ever touches getItem/setItem/removeItem, so this
 * covers its whole surface.
 */
function installStorage(): void {
  const store = new Map<string, string>();
  const localStorage = {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key),
    clear: () => store.clear(),
  };
  (globalThis as { window?: unknown }).window = { localStorage };
}

describe("guest preferences", () => {
  beforeEach(() => {
    installStorage();
  });

  it("keeps what the server inferred", () => {
    mergeGuestPreferences({ diet: "VEG" });
    expect(readGuestPreferences()).toEqual({ diet: "VEG" });
  });

  it("lets a later statement win", () => {
    mergeGuestPreferences({ diet: "VEG", spice_level: "LOW" });
    mergeGuestPreferences({ diet: "NON_VEG" });
    // Spice survives: the new turn said nothing about it, which is not the same
    // as saying it no longer applies.
    expect(readGuestPreferences()).toEqual({ diet: "NON_VEG", spice_level: "LOW" });
  });

  it("stores only the two durable fields", () => {
    mergeGuestPreferences({ diet: "VEG", budget: "LOW", cuisines: ["thai"] });
    expect(readGuestPreferences()).toEqual({ diet: "VEG" });
  });

  it("drops an oversized value rather than sending it back to the server", () => {
    mergeGuestPreferences({ diet: "x".repeat(500) });
    expect(readGuestPreferences()).toEqual({});
  });

  it("recovers from a corrupt entry instead of throwing", () => {
    window.localStorage.setItem("bangkok-bowl-guest-prefs", "{not json");
    expect(readGuestPreferences()).toEqual({});
    // And clears it, so the next read is not the same recovery again.
    expect(window.localStorage.getItem("bangkok-bowl-guest-prefs")).toBeNull();
  });

  it("sends nothing when it knows nothing", () => {
    expect(guestPreferencesForRequest()).toBeUndefined();
    mergeGuestPreferences({ diet: "VEG" });
    expect(guestPreferencesForRequest()).toEqual({ diet: "VEG" });
  });

  it("clears on request — this is what login calls after promoting", () => {
    mergeGuestPreferences({ diet: "VEG" });
    clearGuestPreferences();
    expect(readGuestPreferences()).toEqual({});
  });

  it("survives a browser that refuses storage", () => {
    window.localStorage.setItem = () => {
      throw new Error("QuotaExceededError");
    };
    // Private mode costs the visitor a remembered preference. It must not cost
    // them the turn.
    expect(() => mergeGuestPreferences({ diet: "VEG" })).not.toThrow();
  });
});

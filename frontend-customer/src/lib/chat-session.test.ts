/**
 * Minting a session id where `crypto.randomUUID` does not exist.
 *
 * Browsers withhold `randomUUID` outside a secure context, and the storefront
 * opened by LAN address (http://192.168.x.x) is not one — the waiter prompt
 * threw on every page there. The fallback must still produce what
 * `/suggestions` validates: a UUID, version 4, RFC 4122 variant.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { mintChatSessionId } from "./chat-session";

const V4_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("mintChatSessionId", () => {
  it("uses randomUUID when the context provides it", () => {
    expect(mintChatSessionId()).toMatch(V4_UUID);
  });

  it("still returns a v4 UUID outside a secure context", () => {
    const real = globalThis.crypto;
    vi.stubGlobal("crypto", { getRandomValues: real.getRandomValues.bind(real) });

    const ids = new Set(Array.from({ length: 50 }, () => mintChatSessionId()));
    for (const id of ids) expect(id).toMatch(V4_UUID);
    expect(ids.size).toBe(50);
  });

  it("sets the version and variant bits even when every random byte is 0xff", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => bytes.fill(0xff),
    });
    expect(mintChatSessionId()).toBe("ffffffff-ffff-4fff-bfff-ffffffffffff");
  });
});

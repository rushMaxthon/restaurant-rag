/**
 * What the admin is told when a request fails validation.
 *
 * FastAPI answers a bad request with `detail` as a LIST of field errors, not a
 * string. `request()` read `detail` expecting a string, so every 422 in the
 * whole admin surfaced as the generic "Something went wrong" — the one error
 * class that knows exactly which field is wrong was the only one that told the
 * user nothing, and it made the failure undiagnosable from a screenshot.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, request } from "./api";

const originalFetch = globalThis.fetch;

function respondWith(status: number, body: unknown) {
  globalThis.fetch = vi.fn(async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  ) as unknown as typeof fetch;
}

async function messageFor(status: number, body: unknown): Promise<string> {
  respondWith(status, body);
  try {
    await request("/marketing/reference");
    throw new Error("expected the request to reject");
  } catch (caught) {
    expect(caught).toBeInstanceOf(ApiError);
    return (caught as ApiError).message;
  }
}

beforeEach(() => {
  // `request` dispatches a sign-out event on 401; nothing here is a 401, but a
  // window has to exist for the module to load in node.
  if (!("window" in globalThis)) {
    (globalThis as Record<string, unknown>).window = {
      dispatchEvent: () => true,
    };
  }
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("validation errors reaching the user", () => {
  it("names the field a query parameter failed on", async () => {
    const message = await messageFor(422, {
      detail: [
        {
          type: "uuid_parsing",
          loc: ["query", "restaurant_id"],
          msg: "Input should be a valid UUID",
        },
      ],
    });
    expect(message).toBe("restaurant_id: Input should be a valid UUID");
    expect(message).not.toBe("Something went wrong");
  });

  // `loc[0]` is the request part — "body", "query" — and is noise to a reader.
  it("drops the request part and keeps the field path", async () => {
    const message = await messageFor(422, {
      detail: [
        {
          loc: ["body", "content", "title"],
          msg: "String should have at most 120 characters",
        },
      ],
    });
    expect(message).toBe("content.title: String should have at most 120 characters");
  });

  it("summarises several failures rather than printing a wall", async () => {
    const message = await messageFor(422, {
      detail: [
        { loc: ["body", "name"], msg: "Field required" },
        { loc: ["body", "goal"], msg: "Input should be a valid enum" },
        { loc: ["body", "channels"], msg: "Input should be a valid list" },
        { loc: ["body", "last_step"], msg: "Input should be less than 5" },
      ],
    });
    expect(message).toContain("name: Field required");
    expect(message).toContain("(+2 more)");
  });

  // The ordinary case must keep working exactly as it did.
  it("still passes a plain string detail straight through", async () => {
    const message = await messageFor(409, {
      detail: "Nobody matches this audience yet",
    });
    expect(message).toBe("Nobody matches this audience yet");
  });

  it("falls back only when there is genuinely nothing to report", async () => {
    expect(await messageFor(500, {})).toBe("Something went wrong");
  });
});

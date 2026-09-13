import { describe, expect, it } from "vitest";
import { sanitizeRedirect } from "./require-auth";

/**
 * The redirect loop, locked down.
 *
 * Clicking "Ask the food concierge" while signed out produced a URL roughly
 * 4,000 characters long:
 *
 *   /login?redirect=%2Flogin%3Fredirect%3D%252Flogin%253Fredirect%253D…
 *
 * Six routes each carried their own copy of the auth guard, and every copy
 * listed the current href in its effect's dependency array — so the guard's own
 * navigate() changed the href, which re-fired the effect, which wrapped and
 * re-encoded the URL it had just produced. It never converged.
 *
 * The dependency-array half of that is fixed in the hook. This function is the
 * other half: even a single bad pass must not be able to start it, because a
 * redirect that points back at /login is the seed of the whole thing.
 */
describe("sanitizeRedirect", () => {
  it("keeps an ordinary in-app destination", () => {
    expect(sanitizeRedirect("/checkout")).toBe("/checkout");
    expect(sanitizeRedirect("/orders/abc-123")).toBe("/orders/abc-123");
  });

  it("keeps a query string on the destination", () => {
    expect(sanitizeRedirect("/concierge?q=something%20spicy")).toBe(
      "/concierge?q=something%20spicy",
    );
  });

  it("refuses to send someone back to an auth screen", () => {
    // This is the seed of the loop. Everything else here is secondary.
    expect(sanitizeRedirect("/login")).toBeUndefined();
    expect(sanitizeRedirect("/register")).toBeUndefined();
  });

  it("refuses an auth screen that already carries a redirect", () => {
    // What one pass of the old guard produced. If this survived, the next pass
    // would wrap it again.
    expect(sanitizeRedirect("/login?redirect=%2Fcheckout")).toBeUndefined();
  });

  it("refuses anything that would leave the site", () => {
    // The value arrives from the query string, so an absolute URL here is an
    // open redirect: a login link that lands on someone else's page.
    expect(sanitizeRedirect("https://evil.example/steal")).toBeUndefined();
    expect(sanitizeRedirect("//evil.example/steal")).toBeUndefined();
    expect(sanitizeRedirect("javascript:alert(1)")).toBeUndefined();
  });

  it("treats a missing or empty value as no destination", () => {
    expect(sanitizeRedirect(undefined)).toBeUndefined();
    expect(sanitizeRedirect("")).toBeUndefined();
  });

  it("is idempotent, so a second pass cannot grow the value", () => {
    const once = sanitizeRedirect("/checkout");
    expect(sanitizeRedirect(once)).toBe(once);
  });
});

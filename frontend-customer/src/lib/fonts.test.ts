/**
 * A restaurant's typeface has to arrive, and arrive in the right role.
 *
 * The backend has offered five faces since branding landed; the storefront
 * served one. Every tenant on the platform default — Manrope — rendered in the
 * system fallback, which differs by platform and is nobody's brand.
 *
 * Two rules worth a test each, because both fail silently:
 *
 * - A display serif must not become the body face. DM Serif Display at 13px in
 *   a form label is close to unreadable, and picking it used to set the family
 *   for the whole app including every input and table cell.
 * - The default here must match `DEFAULT_FONT_ID` in the backend allowlist. If
 *   they drift, a restaurant that changed nothing sees its storefront change.
 */

import { describe, expect, it } from "vitest";

import { DEFAULT_FONT, fontTokenCss, isFontId, resolveFonts } from "./fonts";

/** Every id in the backend's FONT_CHOICES, in its order. */
const BACKEND_IDS = ["manrope", "inter", "plus-jakarta", "dm-serif", "space-grotesk"] as const;

describe("the id list matches the backend allowlist", () => {
  it("accepts every id the backend can store", () => {
    for (const id of BACKEND_IDS) {
      expect(isFontId(id), id).toBe(true);
    }
  });

  it("defaults to the same face the backend defaults to", () => {
    // FONT_CHOICES[0] is manrope and DEFAULT_FONT_ID is derived from it.
    expect(DEFAULT_FONT).toBe(BACKEND_IDS[0]);
  });

  it("rejects anything else rather than passing it into CSS", () => {
    // The allowlist exists because a family name from a form going straight
    // into a declaration is an injection waiting to happen. That reasoning
    // only holds if this side refuses too.
    for (const bad of ["", "   ", "Comic Sans", "manrope; }", null, undefined]) {
      expect(isFontId(bad as string), String(bad)).toBe(false);
    }
  });
});

describe("resolving a tenant's choice", () => {
  it("gives every valid id a real stack and something to download", () => {
    for (const id of BACKEND_IDS) {
      const fonts = resolveFonts(id);
      expect(fonts.bodyStack, id).toBeTruthy();
      expect(fonts.displayStack, id).toBeTruthy();
      expect(fonts.hrefs.length, id).toBeGreaterThan(0);
    }
  });

  it("falls back to the default for an unknown id", () => {
    const unknown = resolveFonts("helvetica");
    const fallback = resolveFonts(DEFAULT_FONT);
    expect(unknown).toEqual(fallback);
    expect(resolveFonts(null)).toEqual(fallback);
    expect(resolveFonts(undefined)).toEqual(fallback);
  });

  it("downloads ONE face for a text family", () => {
    // The whole reason this module exists rather than importing five
    // stylesheets: bundling all of them to use one is ~400KB of waste on a
    // phone, which is most of this product's traffic.
    for (const id of ["manrope", "inter", "plus-jakarta", "space-grotesk"] as const) {
      expect(resolveFonts(id).hrefs, id).toHaveLength(1);
    }
  });

  it("uses one face for both roles when it can set body copy", () => {
    const fonts = resolveFonts("inter");
    expect(fonts.bodyStack).toBe(fonts.displayStack);
  });
});

describe("a display serif stays out of the body", () => {
  const serif = resolveFonts("dm-serif");

  it("sets the headings", () => {
    expect(serif.displayStack).toContain("DM Serif Display");
  });

  it("does NOT set the body", () => {
    // The bug this prevents: every input, label and table cell in a display
    // serif because the owner wanted serif headings.
    expect(serif.bodyStack).not.toContain("DM Serif Display");
    expect(serif.bodyStack).toBe(resolveFonts(DEFAULT_FONT).bodyStack);
  });

  it("downloads both, body first", () => {
    expect(serif.hrefs).toHaveLength(2);
    expect(serif.hrefs[0]).toBe(resolveFonts(DEFAULT_FONT).hrefs[0]);
  });

  it("is not asked for a weight it does not have", () => {
    // DM Serif Display ships one weight at 400. Asking for 700 makes the
    // browser synthesise a bold, which on a serif at display size smears the
    // stems and looks like a rendering fault rather than a heading.
    expect(serif.displayWeight).toBe(400);
  });

  it("is not tightened", () => {
    // It is already drawn wide at its single weight; negative tracking turns a
    // heading into a solid block.
    expect(serif.displayTracking).toBe("0");
  });
});

describe("a sans display face is given the treatment that makes it read", () => {
  it("gets weight and negative tracking", () => {
    // Most tenants pick a text face and get the same family in both roles, so
    // this is the ENTIRE difference between a heading and the paragraph under
    // it. Without it `.font-display` marks a hierarchy that is not on screen.
    for (const id of ["manrope", "inter", "plus-jakarta", "space-grotesk"] as const) {
      const fonts = resolveFonts(id);
      expect(fonts.displayWeight, id).toBeGreaterThanOrEqual(700);
      expect(fonts.displayTracking, id).toMatch(/^-/);
    }
  });
});

describe("every stack ends somewhere real", () => {
  it("names a system fallback for the load gap", () => {
    // Between the first paint and the font arriving, the page renders in
    // whatever this ends with. "sans-serif" or "serif" is the floor.
    for (const id of BACKEND_IDS) {
      const { bodyStack, displayStack } = resolveFonts(id);
      expect(bodyStack, `${id} body`).toMatch(/(sans-serif|serif)\s*$/);
      expect(displayStack, `${id} display`).toMatch(/(sans-serif|serif)\s*$/);
    }
  });
});

describe("the token stylesheet", () => {
  it("repoints both names and nothing else", () => {
    const css = fontTokenCss(resolveFonts("dm-serif"));
    expect(css).toContain("--font-stack:");
    // `-stack`, not `--font-display`: Tailwind v4 claims that name as a theme
    // key, and declaring both produces `--font-display: var(--font-display)` —
    // a circular reference that silently drops every heading to the browser
    // default.
    expect(css).toContain("--font-display-stack:");
    expect(css.startsWith(":root{")).toBe(true);
    // A stray brace here would end the rule early and leak the rest of the
    // declaration into the document as a selector.
    expect(css.match(/\{/g)).toHaveLength(1);
    expect(css.match(/\}/g)).toHaveLength(1);
  });
});

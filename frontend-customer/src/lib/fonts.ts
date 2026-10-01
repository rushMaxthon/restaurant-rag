/**
 * The five typefaces a restaurant can choose, and which one this page loads.
 *
 * The backend has offered a font picker since branding landed
 * (`app/services/app_branding.py` — an allowlist, not a free text field, so a
 * family name from a form can never reach a CSS declaration). The storefront
 * ignored it completely and served one face: Plus Jakarta Sans. A restaurant
 * on the PLATFORM DEFAULT, Manrope, rendered in whatever the device happened
 * to have — which differs by platform and is nobody's brand.
 *
 * Two things this gets right that are easy to get wrong.
 *
 * **A display serif is not a body face.** The allowlist calls DM Serif Display
 * "a serif for headings", and it is: set at 13px in a form label it is close
 * to unreadable. Picking it had made it the family for the entire app,
 * including every input and every table cell. So a face declares what it can
 * do, and a display-only face sets the headings while the body falls back to
 * the platform default. The owner gets the serif they asked for in the place
 * it belongs.
 *
 * **Only the chosen face is downloaded.** Bundling five families to use one is
 * roughly 400KB of waste on a phone on mobile data, which is most of this
 * product's traffic. Each face's stylesheet is a separate URL asset and the
 * root route emits a <link> for exactly one of them — resolved during SSR from
 * the request host, so there is no flash and no second guess after hydration.
 */

import dmSerifDisplayUrl from "@fontsource/dm-serif-display/400.css?url";
import interUrl from "@fontsource-variable/inter/index.css?url";
import manropeUrl from "@fontsource-variable/manrope/index.css?url";
import plusJakartaUrl from "@fontsource-variable/plus-jakarta-sans/index.css?url";
import spaceGroteskUrl from "@fontsource-variable/space-grotesk/index.css?url";

/** The ids the backend stores. Anything else resolves to the default. */
export type FontId = "manrope" | "inter" | "plus-jakarta" | "dm-serif" | "space-grotesk";

type Face = {
  /** The CSS family list. Always ends in a system fallback for the load gap. */
  stack: string;
  /** The stylesheet to fetch for this face. */
  href: string;
  /**
   * Whether this face can set body copy.
   *
   * False for a display serif, which then drives headings only. The
   * distinction is the backend's own: the allowlist describes DM Serif as
   * "a serif for headings. Reads as established."
   */
  body: boolean;
};

const SYSTEM = `"Segoe UI", system-ui, -apple-system, sans-serif`;

const FACES: Record<FontId, Face> = {
  manrope: {
    stack: `"Manrope Variable", "Manrope", ${SYSTEM}`,
    href: manropeUrl,
    body: true,
  },
  inter: {
    stack: `"Inter Variable", "Inter", ${SYSTEM}`,
    href: interUrl,
    body: true,
  },
  "plus-jakarta": {
    stack: `"Plus Jakarta Sans Variable", "Plus Jakarta Sans", ${SYSTEM}`,
    href: plusJakartaUrl,
    body: true,
  },
  "space-grotesk": {
    stack: `"Space Grotesk Variable", "Space Grotesk", ${SYSTEM}`,
    href: spaceGroteskUrl,
    body: true,
  },
  "dm-serif": {
    stack: `"DM Serif Display", Georgia, "Times New Roman", serif`,
    href: dmSerifDisplayUrl,
    body: false,
  },
};

/**
 * The platform default, and the body face whenever a tenant picked a
 * display-only one. Matches `DEFAULT_FONT_ID` in the backend's allowlist —
 * the two must agree or a restaurant that changed nothing would still see its
 * storefront change.
 */
export const DEFAULT_FONT: FontId = "manrope";

export function isFontId(value: string | null | undefined): value is FontId {
  return typeof value === "string" && value in FACES;
}

/** What one tenant's choice resolves to: the stacks, and what to download. */
export type ResolvedFonts = {
  bodyStack: string;
  displayStack: string;
  /** Stylesheet hrefs, deduplicated. One entry for most tenants, two for a serif. */
  hrefs: string[];
  /**
   * How `.font-display` should be set for this face.
   *
   * A variable sans wants weight and negative tracking — that is most of what
   * makes large type read as display. A display serif wants neither: DM Serif
   * Display ships one weight at 400, so asking for 700 makes the browser
   * synthesise a bold that smears, and it is already drawn wide enough that
   * tightening turns a heading into a solid block.
   */
  displayWeight: number;
  displayTracking: string;
};

export function resolveFonts(fontId: string | null | undefined): ResolvedFonts {
  const chosen: FontId = isFontId(fontId) ? fontId : DEFAULT_FONT;
  const face = FACES[chosen];

  if (face.body) {
    // One face, both roles. The display/body distinction is then carried by
    // weight, size and tracking rather than by a second download — which is
    // the right trade on a phone.
    return {
      bodyStack: face.stack,
      displayStack: face.stack,
      hrefs: [face.href],
      displayWeight: 700,
      displayTracking: "-0.02em",
    };
  }

  const fallback = FACES[DEFAULT_FONT];
  return {
    bodyStack: fallback.stack,
    displayStack: face.stack,
    // Order matters only for the reader: body first, because that is the one
    // that blocks the page feeling finished.
    hrefs: [fallback.href, face.href],
    displayWeight: 400,
    displayTracking: "0",
  };
}

/**
 * The `<style>` text that points the tokens at the resolved faces.
 *
 * Emitted server-side beside the <link>s so the first paint is already in the
 * right family. `--font-stack` and `--font-display` both live in
 * `frontend-shared/tokens.css`; this only repoints them.
 */
export function fontTokenCss(fonts: ResolvedFonts): string {
  return (
    `:root{--font-stack:${fonts.bodyStack};` +
    `--font-display-stack:${fonts.displayStack};` +
    `--display-weight:${fonts.displayWeight};` +
    `--display-tracking:${fonts.displayTracking};}`
  );
}

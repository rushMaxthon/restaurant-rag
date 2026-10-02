import { brandInitials } from "@/lib/brand-mark";

/** The platform's own accent, used only when a tenant has chosen none. */
const FALLBACK_COLOUR = "#ff5200";

/**
 * The icon in the browser tab, for whichever restaurant this site belongs to.
 *
 * It was a hardcoded `/favicon.ico` — the one the generator shipped with, so
 * every tenant on the platform wore Lovable's mark in the tab, in a bookmark
 * and on a phone's home screen. A shared favicon is the same class of mistake
 * as the shared hero photograph and the shared page title: the most visible
 * places a brand appears, carrying somebody else's.
 *
 * Three answers, in order of how much the restaurant meant them:
 *
 * 1. `favicon_url` — the operator chose an icon specifically.
 * 2. `logo_url` — they uploaded a logo and have not thought about tabs, which
 *    is nearly everybody. A logo is square-ish and reads at 32px far better
 *    than nothing does.
 * 3. A mark drawn from their own initials on their own brand colour.
 *
 * The third is a data URI rather than a file, which is what makes this work
 * for a tenant onboarded five minutes ago: there is no asset to upload, no
 * build step, and nothing shared between restaurants. It is also the only
 * option that cannot 404.
 */
export function faviconHref(config: {
  favicon_url?: string | null;
  logo_url?: string | null;
  primary_color?: string | null;
  name?: string | null;
}): string {
  const chosen = config.favicon_url?.trim();
  if (chosen) return chosen;

  const logo = config.logo_url?.trim();
  if (logo) return logo;

  return generatedMark(config.name, config.primary_color);
}

/**
 * A rounded square in the brand colour with the restaurant's initials on it.
 *
 * SVG rather than a canvas-drawn PNG because this has to be produced during
 * server rendering, where there is no canvas — and because an SVG favicon
 * stays sharp at every size a browser asks for.
 */
export function generatedMark(
  name: string | null | undefined,
  primaryColor: string | null | undefined,
): string {
  const initials = brandInitials(name) || "•";
  // Only a hex colour is trusted into the markup. Anything else — a CSS
  // function, a variable, something a tenant typed by hand — falls back,
  // because this string is interpolated into a document the browser parses.
  const colour = /^#[0-9a-f]{3,8}$/i.test((primaryColor ?? "").trim())
    ? (primaryColor as string).trim()
    : FALLBACK_COLOUR;
  // 0.5em per character keeps two letters inside the box and one letter from
  // looking lost in it.
  const size = initials.length > 1 ? 44 : 56;

  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">` +
    `<rect width="100" height="100" rx="22" fill="${colour}"/>` +
    `<text x="50" y="50" fill="#fff" font-family="system-ui,-apple-system,Segoe UI,Roboto,sans-serif"` +
    ` font-size="${size}" font-weight="700" text-anchor="middle" dominant-baseline="central">` +
    `${escapeText(initials)}</text></svg>`;

  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

/** The three characters that would end the attribute or the element early. */
function escapeText(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

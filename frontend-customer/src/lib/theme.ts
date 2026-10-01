/**
 * Puts a tenant's brand colour on the document.
 *
 * This is the single place the `/app-config` branding response becomes CSS.
 * Never hardcode a colour in a component.
 *
 * It writes a STYLESHEET rather than inline properties on `<html>`, and that
 * is the whole design rather than a detail. Inline styles beat every rule in
 * every stylesheet, including `.dark` — so setting `--primary` inline, which
 * is what this did before, meant a tenant's brand never lifted for dark mode.
 * `frontend-shared/tokens.css` carries `.dark { --primary: #ff6b26 }` for
 * exactly that reason and it was being silently overridden for every
 * restaurant, including the default one.
 *
 * A `<style>` element participates in the cascade like anything else, so the
 * light and dark halves can both be expressed and the `.dark` class still
 * decides which applies.
 */

import { brandPalette } from "@/lib/brand-palette";

/** One element, replaced in place, so repeated calls cannot stack up. */
const STYLE_ID = "brand-theme";

export function applyBrandColor(primaryColor: string | undefined | null) {
  if (typeof document === "undefined" || !primaryColor) return;

  const palette = brandPalette(primaryColor);
  // An unparseable colour leaves the platform defaults in place, which is the
  // only safe failure: a half-applied palette is a storefront with one brand
  // colour in the buttons and another in the prices.
  if (!palette) return;

  const css = `
:root {
  --primary: ${palette.primary};
  --primary-strong: ${palette.primaryStrong};
  --primary-text: ${palette.primaryText};
  --on-primary: ${palette.onPrimary};
  --primary-soft: color-mix(in srgb, ${palette.primary} 15%, var(--surface));
  --placeholder-a: color-mix(in srgb, ${palette.primary} 15%, var(--surface));
  --placeholder-b: color-mix(in srgb, ${palette.primary} 25%, var(--surface));
}
.dark {
  --primary: ${palette.darkPrimary};
  --primary-strong: ${palette.darkPrimary};
  --primary-text: ${palette.darkPrimary};
  --on-primary: ${palette.darkOnPrimary};
  --primary-soft: color-mix(in srgb, ${palette.darkPrimary} 18%, var(--surface));
  --placeholder-a: color-mix(in srgb, ${palette.darkPrimary} 15%, var(--surface));
  --placeholder-b: color-mix(in srgb, ${palette.darkPrimary} 25%, var(--surface));
}`.trim();

  let style = document.getElementById(STYLE_ID) as HTMLStyleElement | null;
  if (!style) {
    style = document.createElement("style");
    style.id = STYLE_ID;
    document.head.append(style);
  }
  if (style.textContent !== css) style.textContent = css;
}

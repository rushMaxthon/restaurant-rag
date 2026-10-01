/**
 * Stripe's Payment Element, wearing this storefront's theme.
 *
 * The Element renders inside an iframe Stripe serves, so none of our CSS
 * reaches it — not the tokens, not the `.dark` class, nothing. Left alone it
 * paints its own light theme: white inputs and, the part that actually broke,
 * LABELS in a dark grey chosen for a white page. On a dark card "Card number",
 * "Expiration date", "Security code" and "Country" were dark-on-dark and
 * effectively invisible, while the inputs below them stayed white — so the
 * block read as something bolted on from another site.
 *
 * The appearance API is the only way across that boundary. Everything below is
 * READ from the live tokens rather than written down here, for one reason that
 * matters: `--primary` is rewritten at runtime per tenant
 * (`frontend-customer/src/lib/theme.ts`), so a hard-coded orange would be
 * correct for exactly one restaurant and wrong for every other one.
 *
 * Safe to recompute on a theme toggle: `react-stripe-js` passes option changes
 * to `elements.update()` for everything except `clientSecret` and `fonts`, so
 * the Element restyles in place and a half-typed card number survives.
 */

import type { Appearance } from "@stripe/stripe-js";

/**
 * One custom property, as the browser has resolved it.
 *
 * The fallback is not decoration. This module can be evaluated during the
 * server render, where there is no `document` at all, and a token can resolve
 * to an empty string before the theme script has run — Stripe rejects an empty
 * colour and throws rather than ignoring it.
 */
function token(name: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function stripeAppearance(dark: boolean): Appearance {
  // The surface the Element sits on, which is also what its inputs should be:
  // this storefront's own fields are `bg-transparent` over a border, so a
  // filled white box inside a dark card is doubly out of place.
  const surface = token("--surface", dark ? "#191b20" : "#ffffff");
  const text = token("--text", dark ? "#f8fafc" : "#14171f");
  const muted = token("--muted", dark ? "#a7adb7" : "#6b7280");
  const border = token("--border", dark ? "#343740" : "#e5e7eb");
  const primary = token("--primary", "#ff5200");
  const danger = token("--danger", dark ? "#f87171" : "#dc2626");
  const radius = token("--radius", "0.5rem");

  return {
    // `night` rather than only overriding variables: it carries sensible
    // defaults for the parts not named here — the tab row, icons, the saved
    // card list — which would otherwise stay light while everything else
    // turned dark.
    theme: dark ? "night" : "stripe",
    variables: {
      colorPrimary: primary,
      colorBackground: surface,
      colorText: text,
      // The one that was actually wrong. Stripe uses it for labels and helper
      // text, and its default is picked for a white page.
      colorTextSecondary: muted,
      colorTextPlaceholder: muted,
      colorDanger: danger,
      borderRadius: radius,
    },
    rules: {
      // Stripe draws inputs with a shadow and no border by default, which
      // reads as a raised box; every field in this storefront is a hairline
      // over the card instead.
      ".Input": {
        border: `1px solid ${border}`,
        boxShadow: "none",
      },
      ".Input:focus": {
        border: `1px solid ${primary}`,
        boxShadow: `0 0 0 1px ${primary}`,
      },
      ".Input--invalid": {
        border: `1px solid ${danger}`,
        boxShadow: "none",
      },
      // Said explicitly as well as through `colorTextSecondary`, because this
      // is the rule the bug was in and a variable is easier to lose than a
      // rule when somebody edits this next.
      ".Label": {
        color: muted,
      },
      ".Tab": {
        border: `1px solid ${border}`,
        boxShadow: "none",
      },
      ".Tab--selected": {
        border: `1px solid ${primary}`,
        boxShadow: "none",
      },
    },
  };
}

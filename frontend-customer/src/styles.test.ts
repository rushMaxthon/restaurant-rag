/**
 * Every token a stylesheet names is a token something defines.
 *
 * The storefront had nothing asserting on its CSS at all, which is how
 * `--font-sans` came to name Manrope while no font file ever shipped, and how
 * `.font-display` came to resolve to the body family for the life of the app.
 * Both were invisible: a `var()` that resolves to nothing does not warn, it
 * just silently falls back to whatever the browser would have done.

 * The operator's panel has carried this guard for a while
 * (`frontend-admin/src/adminStyles.test.ts`) and it has caught real breakage.
 * This is the same idea for the three files the storefront actually loads.
 *
 * Read as TEXT with CRLF normalised, like the panel's version — this is a
 * Windows checkout, and a pattern that silently never matches is worse than no
 * test because it reports green.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));

function read(relative: string): string {
  return readFileSync(resolve(here, relative), "utf8").replace(/\r\n/g, "\n");
}

const SHARED_TOKENS = read("../../frontend-shared/tokens.css");
const SHARED_COMPONENTS = read("../../frontend-shared/components.css");
const STYLES = read("./styles.css");
const POLISH = read("./polish.css");

/** `--name:` anywhere, which is how a custom property is declared. */
function definitionsIn(css: string): Set<string> {
  const found = new Set<string>();
  for (const match of css.matchAll(/(--[a-z0-9-]+)\s*:/gi)) {
    found.add(match[1]!.toLowerCase());
  }
  return found;
}

/** `var(--name` — the reference, with or without a fallback. */
function referencesIn(css: string): Set<string> {
  const found = new Set<string>();
  for (const match of css.matchAll(/var\(\s*(--[a-z0-9-]+)/gi)) {
    found.add(match[1]!.toLowerCase());
  }
  return found;
}

/**
 * Names Tailwind v4 defines for us, which never appear in any of our files.
 *
 * `@import "tailwindcss"` brings a theme of its own — the colour, spacing and
 * type scales it generates utilities from. Our stylesheets legitimately read
 * some of them, and they are defined in `node_modules`, so matching on our
 * four files alone would report them as missing.
 */
const TAILWIND_PREFIXES = [
  "--color-",
  "--spacing",
  "--text-",
  "--font-weight-",
  "--tracking-",
  "--leading-",
  "--breakpoint-",
  "--container-",
  "--radius-",
  "--shadow-",
  "--blur-",
  "--ease-",
  "--animate-",
  "--default-",
  "--tw-",
];

/**
 * Names set from JavaScript at runtime rather than declared in a stylesheet.
 *
 * `--i` is the stagger index, set inline per row. The rest are written onto
 * the root element by `lib/theme.ts` from the tenant's branding, and by
 * `lib/fonts.ts` from the tenant's chosen typeface — real definitions that
 * simply do not live in a `.css` file.
 */
const SET_FROM_JS = new Set([
  "--i",
  "--display-weight",
  "--display-tracking",
  "--font-display-stack",
]);

describe("every token a stylesheet names is a token something defines", () => {
  const defined = new Set([
    ...definitionsIn(SHARED_TOKENS),
    ...definitionsIn(SHARED_COMPONENTS),
    ...definitionsIn(STYLES),
    ...definitionsIn(POLISH),
  ]);

  const undefinedNames = [...new Set([...referencesIn(STYLES), ...referencesIn(POLISH)])]
    .filter((name) => !defined.has(name))
    .filter((name) => !SET_FROM_JS.has(name))
    .filter((name) => !TAILWIND_PREFIXES.some((prefix) => name.startsWith(prefix)))
    .sort();

  it("leaves nothing dangling", () => {
    expect(undefinedNames).toEqual([]);
  });
});

describe("the shared files are actually loaded", () => {
  it("imports the tokens and the component vocabulary, in that order", () => {
    // Order is load-bearing: components.css is built FROM the tokens, so
    // importing it first would resolve every value against nothing.
    const tokensAt = STYLES.indexOf("frontend-shared/tokens.css");
    const componentsAt = STYLES.indexOf("frontend-shared/components.css");
    expect(tokensAt).toBeGreaterThan(-1);
    expect(componentsAt).toBeGreaterThan(-1);
    expect(tokensAt).toBeLessThan(componentsAt);
  });

  it("does not re-declare the motion tokens locally", () => {
    // They were declared in both tokens.css and polish.css, agreeing only by
    // luck. The next person to retune a curve would have retuned one of them.
    expect(POLISH).not.toMatch(/^\s*--ease-out\s*:/m);
    expect(POLISH).not.toMatch(/^\s*--dur\s*:/m);
  });
});

describe("the display class does not out-rank the call sites", () => {
  it("is declared in a layer, so utilities still win", () => {
    // Unlayered CSS beats EVERY Tailwind utility. Left unlayered, this rule's
    // font-weight and line-height silently override the `font-extrabold` and
    // `leading-[.98]` that seventeen files ask for — the hero's deliberate
    // .98 leading included — with nothing to show for it but headings that
    // look slightly wrong and no obvious cause.
    const at = STYLES.indexOf(".font-display {");
    expect(at).toBeGreaterThan(-1);
    const before = STYLES.slice(0, at);
    const lastLayerOpen = before.lastIndexOf("@layer components");
    expect(lastLayerOpen, "`.font-display` must sit inside @layer components").toBeGreaterThan(-1);
    // And the layer must not have closed again before the rule.
    const between = before.slice(lastLayerOpen);
    const opens = (between.match(/\{/g) ?? []).length;
    const closes = (between.match(/\}/g) ?? []).length;
    expect(opens).toBeGreaterThan(closes);
  });
});

describe("the brand's ink is only used on the brand's colour", () => {
  /**
   * `--on-primary` answers one question: what reads ON `--primary`. It is
   * derived from the TENANT's colour and it INVERTS between themes — white on
   * the light fill, near-black on the lifted dark one.
   *
   * So using it anywhere else is a bug that only shows up in one theme, for
   * some tenants. All four hero headlines carried it while sitting on a
   * photograph, and were rendering near-black on a black scrim for every
   * visitor in dark mode. Nobody had looked in dark mode.
   */
  const ROUTES = ["index", "concierge", "login", "register"] as const;

  it("is not used on hero copy, which sits on a photograph", () => {
    for (const route of ROUTES) {
      const source = read(`./routes/${route}.tsx`).replace(/\/\*[\s\S]*?\*\//g, "");
      const heroLines = source
        .split("\n")
        .filter((line) => line.includes("hero-copy"));
      for (const line of heroLines) {
        expect(line, `${route}.tsx hero`).not.toContain("text-primary-foreground");
      }
    }
  });

  it("is not what a destructive surface uses", () => {
    // A delete button is not a brand surface. Borrowing the brand's ink meant
    // a tenant with a pale brand got dark text on a red button.
    expect(STYLES).toContain("--color-destructive-foreground: var(--on-danger)");
  });

  it("has a danger counterpart defined in both themes", () => {
    // Split on the SELECTOR, not the string `.dark` — which also appears in
    // the file's header comment explaining why dark mode is a class.
    const at = SHARED_TOKENS.indexOf("\n.dark {");
    expect(at, "`.dark {` block not found").toBeGreaterThan(-1);
    const light = SHARED_TOKENS.slice(0, at);
    const dark = SHARED_TOKENS.slice(at);
    // Both halves, because a token defined in only one is how a dark mode
    // ends up with a light-mode value nobody notices until a screenshot.
    expect(light, "light").toContain("--on-danger:");
    expect(dark, "dark").toContain("--on-danger:");
  });
});

describe("the typeface is not bundled for every tenant", () => {
  it("imports no font package in the stylesheet", () => {
    // A restaurant picks one of five faces. An @import here ships that one to
    // everybody regardless, which is the bug the per-tenant <link> replaced.
    expect(STYLES).not.toMatch(/@import\s+["']@fontsource/);
  });
});

describe("the splash screen cannot outlast its welcome", () => {
  /**
   * The failure mode this guards is specific and nasty: a splash that waits on
   * data, shown to a customer whose backend is down. They stare at a logo.
   *
   * So the fade must be a CSS animation with `forwards` — nothing has to RUN
   * for the overlay to leave. If the bundle never loads, if hydration throws,
   * if every query hangs, it still goes away on time.
   */
  const block = POLISH.slice(POLISH.indexOf("@keyframes splash-out"));

  it("leaves on a CSS animation, not a timer", () => {
    expect(block).toMatch(/animation:\s*splash-out\s+[\d.]+s[^;]*forwards/);
  });

  it("is gone within about a second", () => {
    // Long enough to read a name, short enough that somebody who came to order
    // dinner does not notice they waited.
    const duration = /animation:\s*splash-out\s+([\d.]+)s/.exec(block)?.[1];
    expect(duration).toBeDefined();
    expect(Number(duration)).toBeLessThanOrEqual(1.5);
  });

  it("cannot swallow a tap while it fades", () => {
    expect(block).toContain("pointer-events: none");
  });

  it("is skipped entirely for a repeat view and for reduced motion", () => {
    // Not a shorter animation in either case — none at all.
    expect(block).toContain('html[data-splash="seen"] .splash');
    const reduced = block.slice(block.indexOf("prefers-reduced-motion"));
    expect(reduced).toContain(".splash");
    expect(reduced).toContain("display: none");
  });
});

describe("motion is answerable to prefers-reduced-motion", () => {
  it("states the END STATE, not just the absence of a journey", () => {
    // The trap: removing an animation from `.rise-in` without setting opacity
    // leaves the row at 0 and the list renders blank for the people who asked
    // for less motion — strictly worse than ignoring the preference.
    const reduced = SHARED_COMPONENTS.slice(
      SHARED_COMPONENTS.indexOf("prefers-reduced-motion"),
    );
    expect(reduced).toContain("opacity: 1");
    expect(reduced).toContain("transform: none");
  });

  it("covers every animated class the shared file introduces", () => {
    const reduced = SHARED_COMPONENTS.slice(
      SHARED_COMPONENTS.indexOf("prefers-reduced-motion"),
    );
    for (const name of [".rise-in", ".count-pop", ".lift", ".img-reveal"]) {
      expect(reduced, name).toContain(name);
    }
  });
});

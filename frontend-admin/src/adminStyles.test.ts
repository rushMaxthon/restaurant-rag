/**
 * Two rules in the panel's chrome that were wrong in a way nothing could
 * report: no error, no warning, no visibly broken page. Both were found by
 * measuring the rendered document rather than by reading the source, and both
 * would come back the same silent way.
 *
 * These assertions read the stylesheet and the HTML shell as text. That is
 * blunt, and it is the only level at which either mistake is visible: a unit
 * test of a component cannot see a specificity contest, and nothing in the
 * build resolves one either.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = fileURLToPath(new URL(".", import.meta.url));

/**
 * Line endings normalised, because these assertions match multi-line selector
 * groups as text and the working tree is on Windows — where git hands back
 * CRLF and a pattern written with `\n` silently matches nothing. A guard that
 * cannot fail is worse than no guard.
 */
const read = (path: string) => readFileSync(path, "utf8").replace(/\r\n/g, "\n");

const legacyCss = read(`${here}legacy.css`);
const indexHtml = read(`${here}../index.html`);

/**
 * Specificity as the cascade counts it, for the shapes that appear here:
 * ids, then classes, then elements. Enough to compare two selectors made of
 * class names and tag names, which is all either rule is.
 */
function specificity(selector: string): [number, number, number] {
  const cleaned = selector.trim();
  const ids = cleaned.match(/#[\w-]+/g)?.length ?? 0;
  const classes = cleaned.match(/\.[\w-]+|\[[^\]]+\]|:[\w-]+/g)?.length ?? 0;
  const elements =
    cleaned.replace(/[#.][\w-]+|\[[^\]]+\]|:[\w-]+/g, "").match(/\b[a-z]+\b/g)
      ?.length ?? 0;
  return [ids, classes, elements];
}

function outranks(a: string, b: string): boolean {
  const left = specificity(a);
  const right = specificity(b);
  for (let i = 0; i < 3; i += 1) {
    if (left[i] !== right[i]) return left[i] > right[i];
  }
  // A tie goes to whichever is written later, which this helper does not know
  // about — so a tie is not an answer and callers must not rely on one.
  return false;
}

/** The declaration block following a selector, as written. */
function blockFor(css: string, selectorEndsWith: string): string {
  const index = css.indexOf(selectorEndsWith);
  if (index === -1) return "";
  const open = css.indexOf("{", index);
  const close = css.indexOf("}", open);
  return css.slice(open + 1, close);
}

describe("a right-aligned table column is actually right-aligned", () => {
  /**
   * `ResponsiveTable` has taken `align: "right"` for a long time and 23
   * columns ask for it, including every money column in the panel. None of
   * them were right-aligned: `.admin-table th, .admin-table td` sets
   * `text-align: left` at (0,1,1), the modifier was a bare `.admin-table__cell--right`
   * at (0,1,0), and the modifier lost on every row regardless of file order.
   *
   * Nobody noticed because the one column anyone would check — Actions — looks
   * correct for an unrelated reason: `.table-actions` inside it sets
   * `margin-left: auto`.
   */
  it("outranks the rule that left-aligns every cell", () => {
    const base = ".admin-table th, .admin-table td";
    expect(legacyCss).toContain(base);

    const right = ".admin-table .admin-table__cell--right";
    expect(legacyCss).toContain(right);

    // Compared against the strongest half of the base rule, since either half
    // can match a given cell.
    expect(outranks(right, ".admin-table td")).toBe(true);
  });

  it("carries tabular figures, so decimal points line up down the column", () => {
    const block = blockFor(
      legacyCss,
      ".admin-table .admin-table__cell--right {",
    );
    expect(block).toContain("tabular-nums");
  });
});

describe("the chosen theme is applied before the first paint", () => {
  /**
   * `services/theme.ts` owns the preference and is the only thing that writes
   * it. Applying it from a React effect, which is where it lived, means the
   * first frame is always the default — a white flash on every navigation for
   * anyone who chose dark, and the reverse on a machine whose OS is dark,
   * because a document that has not declared `color-scheme` gets the
   * browser's own guess.
   *
   * The fix is an inline script in the shell, which duplicates exactly two
   * strings. These assertions are what keeps the copy honest: if the key or
   * the class changes in one place and not the other, the panel silently goes
   * back to repainting on every load.
   */
  it("reads the same storage key the panel writes", () => {
    const theme = read(`${here}services/theme.ts`);
    const key = theme.match(/const STORAGE_KEY = "([^"]+)"/)?.[1];
    expect(key).toBeTruthy();
    expect(indexHtml).toContain(`localStorage.getItem("${key}")`);
  });

  it("sets the class and color-scheme, in the head, before the app script", () => {
    expect(indexHtml).toContain('classList.add("dark")');
    expect(indexHtml).toContain("colorScheme");

    const bootstrap = indexHtml.indexOf("admin.theme");
    const app = indexHtml.indexOf("/src/main.tsx");
    expect(bootstrap).toBeGreaterThan(-1);
    expect(app).toBeGreaterThan(bootstrap);
  });

  it("falls back the same way the panel does when nothing was chosen", () => {
    expect(indexHtml).toContain("(prefers-color-scheme: dark)");
  });
});

describe("every token a stylesheet names is a token something defines", () => {
  /**
   * Two of these were live when this was written, and both were invisible for
   * the same reason: `var(--text-muted, #6b7280)` and
   * `var(--brand-strong, #ff5200)` name tokens that do not exist in this app,
   * so they silently resolved to their fallback — a LIGHT grey and a brand
   * orange, hard-coded, on every page including the dark ones. A fallback is
   * what made the typo survive; without one the declaration would simply have
   * had no effect and somebody would have noticed.
   *
   * The phone preview in `BrandingPanel` is the deliberate exception. It sets
   * `--p`, `--ink` and friends as inline styles from the tenant's palette, so
   * they are genuinely defined — just not in a stylesheet.
   */
  const SET_FROM_JS = new Set([
    // frontend-admin/src/components/BrandingPanel.tsx, the phone preview.
    "--p", "--on-p", "--ink", "--ink-2", "--w", "--soft", "--line", "--hero",
    "--raised", "--alt", "--divider", "--tab", "--white", "--bg", "--surface",
    "--text", "--muted", "--border", "--radius",
  ]);

  it("defines every custom property the admin stylesheets reference", () => {
    const sources = [
      legacyCss,
      read(`${here}index.css`),
      read(`${here}../../frontend-shared/tokens.css`),
      read(`${here}../../frontend-shared/components.css`),
    ];
    const defined = new Set<string>();
    for (const css of sources) {
      for (const m of css.matchAll(/(--[\w-]+)\s*:/g)) defined.add(m[1]);
    }

    const missing = new Set<string>();
    for (const m of legacyCss.matchAll(/var\(\s*(--[\w-]+)/g)) {
      if (!defined.has(m[1]) && !SET_FROM_JS.has(m[1])) missing.add(m[1]);
    }

    expect([...missing].sort()).toEqual([]);
  });
});

describe("a badge keeps its own colour inside a table", () => {
  /**
   * `.admin-table__cell-content span` sets `color: var(--hint)` at (0,1,1).
   * Every badge tone was a bare modifier at (0,1,0) and lost to it, so inside
   * a table — which is where most of them live — order statuses, roles, combo
   * visibility and offer states all rendered in the same grey at about 2.6:1
   * on their own tinted background. Outside a table they were correct, which
   * is why a tone looked right on a detail page and wrong in the list that
   * linked to it.
   *
   * The fix is to name the block class twice. The test is that they stay
   * named twice.
   */
  it("gives every tone enough specificity to beat the cell rule", () => {
    const badges =
      "status-pill|usr-role|st-role-pill|generated-combos-visibility-badge";
    const rule = new RegExp(
      String.raw`((?:^\.(?:${badges})[^{]*?))\{([^}]*)\}`,
      "gms",
    );
    const bare: string[] = [];
    for (const m of legacyCss.matchAll(rule)) {
      // Only the rules that paint a tone are in the contest; a modifier that
      // sets padding or a cursor has nothing to lose.
      if (!/(?<![a-z-])color:/.test(m[2])) continue;
      for (const sel of m[1].split(",")) {
        const cleaned = sel.trim();
        if (!cleaned.includes("--")) continue;
        // A modifier on its own is (0,1,0); the block plus modifier is (0,2,0).
        if (cleaned.split(".").length < 3) bare.push(cleaned);
      }
    }
    expect(bare).toEqual([]);
  });

  it("has a tone for every role the Users page can render", () => {
    // `ROLE_META` is exhaustive over `UserRole` or the page throws. The
    // stylesheet is not type-checked against anything, so KITCHEN arrived with
    // the kitchen board and had no tone at all for weeks.
    const page = read(`${here}pages/AdminUsersPage.tsx`);
    const block = page.slice(page.indexOf("const ROLE_META"));
    const roles = [...block.slice(0, block.indexOf("};")).matchAll(/^\s{2}([A-Z]+):/gm)].map(
      (m) => m[1].toLowerCase(),
    );
    expect(roles.length).toBeGreaterThan(3);
    for (const role of roles) {
      expect(legacyCss).toContain(`.usr-role.usr-role--${role}`);
    }
  });
});

describe("one page-title size", () => {
  /**
   * Five were measured across the panel: 24px on nineteen screens, 38.4px on
   * the order detail, 31.2px on the Marketing hub, 32px on the campaign
   * builder, and none at all on the AI Manager. A page is not more important
   * because its title is bigger; it just stops looking like the same product.
   */
  it("sizes every page title from the type scale", () => {
    const titles = [
      ".order-detail__title-row h1",
      ".mkt-h1",
      ".hub-banner__title",
      // Declared in a group with `.login-card h1`, and the group that sets
      // the SIZE is not the group that sets the margin — so this one is found
      // by the declaration rather than by the selector.
      ".page-intro h1,\n.login-card h1",
    ];
    for (const sel of titles) {
      const block = blockFor(legacyCss, `${sel} {`);
      expect(block, sel).toContain("var(--fs-display-sm)");
    }
  });
});

describe("no surface is painted a light literal", () => {
  /**
   * The defect this exists for: in dark mode the Location Editor opened with
   * a white header band and a white sticky footer around a dark form, and the
   * heading on it was invisible. The cause was not the modal. It was that
   * `background` had been written as `#ffffff` in fifteen places across the
   * panel — the modal's three bands, four table-row hovers, the card gradient
   * on four more surfaces, and the shimmer that ran through every skeleton.
   *
   * A literal cannot follow a theme, and nothing was checking. The `.dark`
   * block was thorough about the tokens it knew about, so the failure was
   * never in the palette — it was in the declarations that had never asked
   * the palette anything.
   *
   * Scoped to the properties that paint a surface. `color: #fff` is left
   * alone on purpose: white ink on a brand fill or on the permanently dark
   * sidebar is correct in both themes, and flagging it would bury this.
   */
  const SURFACE_PROPS =
    /^(background|background-color|background-image|border|border-top|border-bottom|border-left|border-right|border-color)$/;

  /** Relative luminance, 0 = black, 1 = white. */
  const luminance = (hex: string) => {
    let h = hex.slice(1);
    if (h.length === 3) h = [...h].map((c) => c + c).join("");
    if (h.length !== 6) return 0;
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  };

  it("uses a token, not a hex, for anything that paints a surface", () => {
    // Comments first: this file explains itself at length and names plenty of
    // colours it no longer uses.
    const css = legacyCss.replace(/\/\*[\s\S]*?\*\//g, "");

    const offenders: string[] = [];
    for (const [, prop, rawValue] of css.matchAll(/([-a-z]+)\s*:\s*([^;{}]*);/g)) {
      if (!SURFACE_PROPS.test(prop)) continue;
      // A `var(--x, #fff)` fallback never paints anything while the token
      // exists, and the test above already proves every one of them does.
      // A `color-mix()` lightens a token that flips, so it flips too.
      const value = rawValue
        .replace(/var\([^()]*\)/g, "")
        .replace(/color-mix\([^()]*\)/g, "");
      for (const [hex] of value.matchAll(/#[0-9a-fA-F]{3,8}\b/g)) {
        if (luminance(hex) > 0.75) offenders.push(`${prop}: ${hex}`);
      }
    }

    expect(offenders).toEqual([]);
  });

  it("paints the modal's three bands from tokens, which is where this started", () => {
    for (const band of [
      /\.modal-card__header\s*\{[^}]*\}/,
      /\.modal-card__body\s*\{[^}]*\}/,
      /\.modal-card \.modal-actions\s*\{[^}]*\}/,
    ]) {
      const rule = legacyCss.match(band)?.[0] ?? "";
      expect(rule).not.toBe("");
      expect(rule).toMatch(/background:[^;]*var\(--surface/);
    }
  });
});

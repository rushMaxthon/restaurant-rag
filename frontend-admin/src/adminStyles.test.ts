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
const legacyCss = readFileSync(`${here}legacy.css`, "utf8");
const indexHtml = readFileSync(`${here}../index.html`, "utf8");

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
    const theme = readFileSync(`${here}services/theme.ts`, "utf8");
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

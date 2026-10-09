/**
 * A ratchet. Each number is how many off-token declarations a family still
 * has; a number may be lowered and never raised. A screen pass starts by
 * setting its families to zero here and watching this fail.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { familyOf, measure, type Counts } from "./styleBudget";

const here = fileURLToPath(new URL(".", import.meta.url));
const css = readFileSync(`${here}legacy.css`, "utf8").replace(/\r\n/g, "\n");

const BUDGET: Record<string, Counts> = {
  "(element)": { spacing: 0, weight: 0, colour: 0 },
  "admin": { spacing: 0, weight: 0, colour: 0 },
  "ai": { spacing: 0, weight: 0, colour: 0 },
  // The tick on a brand swatch sits on the swatch's own colour, which is not
  // the theme's, so it is a literal white.
  "bp": { spacing: 0, weight: 0, colour: 1 },
  "branch": { spacing: 0, weight: 0, colour: 0 },
  "breadcrumbs": { spacing: 0, weight: 0, colour: 0 },
  "cancel": { spacing: 0, weight: 0, colour: 0 },
  "capability": { spacing: 0, weight: 0, colour: 0 },
  "chart": { spacing: 0, weight: 0, colour: 0 },
  "color": { spacing: 0, weight: 0, colour: 0 },
  "combo": { spacing: 0, weight: 0, colour: 0 },
  "confirm": { spacing: 0, weight: 0, colour: 0 },
  "dashboard": { spacing: 0, weight: 0, colour: 0 },
  "delivery": { spacing: 0, weight: 0, colour: 0 },
  "data": { spacing: 0, weight: 0, colour: 0 },
  "detail": { spacing: 0, weight: 0, colour: 0 },
  "empty": { spacing: 0, weight: 0, colour: 0 },
  "eyebrow": { spacing: 0, weight: 0, colour: 0 },
  "field": { spacing: 0, weight: 0, colour: 0 },
  "form": { spacing: 0, weight: 0, colour: 0 },
  "gateway": { spacing: 0, weight: 0, colour: 0 },
  "generated": { spacing: 0, weight: 0, colour: 0 },
  "gst": { spacing: 0, weight: 0, colour: 0 },
  // Not this product's colours to choose: WhatsApp's green on the channel
  // art, the white icons on it and on the purple badge, and the peach of the
  // promo illustration.
  "hub": { spacing: 0, weight: 0, colour: 4 },
  "insight": { spacing: 0, weight: 0, colour: 0 },
  "kds": { spacing: 0, weight: 0, colour: 0 },
  "lg": { spacing: 0, weight: 0, colour: 0 },
  "live": { spacing: 0, weight: 0, colour: 0 },
  "login": { spacing: 0, weight: 0, colour: 0 },
  "maintenance": { spacing: 0, weight: 0, colour: 0 },
  "menu": { spacing: 0, weight: 0, colour: 0 },
  "method": { spacing: 0, weight: 0, colour: 0 },
  "mixed": { spacing: 0, weight: 0, colour: 0 },
  // What is left is deliberate. `.mkt` and `.mkt-hub` define their own scoped
  // tokens (`--mkt-ink`, `--hub-banner-bg`…), each with a `.dark` twin, and a
  // token's definition is where a literal belongs. The rest is the phone and
  // message mock-ups, which draw another product's screen and do not theme.
  // 66, not the 59 first recorded: the first pass swapped seven of these
  // whites for `--on-primary`, which goes near-black in dark mode — on dark
  // hairlines, a lock-screen clock and a sender line. They are literals again.
  "mkt": { spacing: 0, weight: 0, colour: 66 },
  "mobile": { spacing: 0, weight: 0, colour: 0 },
  "modal": { spacing: 0, weight: 0, colour: 0 },
  "ntf": { spacing: 0, weight: 0, colour: 0 },
  "offer": { spacing: 0, weight: 0, colour: 0 },
  "order": { spacing: 0, weight: 0, colour: 0 },
  "page": { spacing: 0, weight: 0, colour: 0 },
  "pagination": { spacing: 0, weight: 0, colour: 0 },
  "panel": { spacing: 0, weight: 0, colour: 0 },
  // The branding phone preview: a scaled-down drawing of the customer app.
  // Its 5px and 7px are the miniature, and it is deliberately not on this
  // panel's scale. 57, not the 55 first recorded, because longhands count now.
  "ph": { spacing: 57, weight: 36, colour: 5 },
  "pref": { spacing: 0, weight: 0, colour: 0 },
  "primary": { spacing: 0, weight: 0, colour: 0 },
  "reports": { spacing: 0, weight: 0, colour: 0 },
  "restaurant": { spacing: 0, weight: 0, colour: 0 },
  "rmap": { spacing: 0, weight: 0, colour: 0 },
  "rider": { spacing: 0, weight: 0, colour: 0 },
  "rpt": { spacing: 0, weight: 0, colour: 0 },
  "secondary": { spacing: 0, weight: 0, colour: 0 },
  "segmented": { spacing: 0, weight: 0, colour: 0 },
  "set": { spacing: 0, weight: 0, colour: 0 },
  "settings": { spacing: 0, weight: 0, colour: 0 },
  "skip": { spacing: 0, weight: 0, colour: 0 },
  "slot": { spacing: 0, weight: 0, colour: 0 },
  "st": { spacing: 0, weight: 0, colour: 0 },
  "status": { spacing: 0, weight: 0, colour: 0 },
  "table": { spacing: 0, weight: 0, colour: 0 },
  "tenant": { spacing: 0, weight: 0, colour: 0 },
  "tip": { spacing: 0, weight: 0, colour: 0 },
  "pw": { spacing: 0, weight: 0, colour: 0 },
  "courier": { spacing: 0, weight: 0, colour: 0 },
  "period": { spacing: 0, weight: 0, colour: 0 },
  "print": { spacing: 0, weight: 0, colour: 0 },
  "printer": { spacing: 0, weight: 0, colour: 0 },
  "pairing": { spacing: 0, weight: 0, colour: 0 },
  "checkbox": { spacing: 0, weight: 0, colour: 0 },
  "toast": { spacing: 0, weight: 0, colour: 0 },
  "toggle": { spacing: 0, weight: 0, colour: 0 },
  "toolbar": { spacing: 0, weight: 0, colour: 0 },
  "traffic": { spacing: 0, weight: 0, colour: 0 },
  "ui": { spacing: 0, weight: 0, colour: 0 },
  "usr": { spacing: 0, weight: 0, colour: 0 },
  "visually": { spacing: 0, weight: 0, colour: 0 },
  "web": { spacing: 0, weight: 0, colour: 0 },
  "workspace": { spacing: 0, weight: 0, colour: 0 },
};

describe("familyOf", () => {
  it("names a rule by the first word of its class", () => {
    expect(familyOf(".rpt-card__title:hover")).toBe("rpt");
    expect(familyOf(".dark .mkt-shell")).toBe("mkt");
    expect(familyOf(".primary-button")).toBe("primary");
    expect(familyOf("button")).toBe("(element)");
  });
});

describe("measure", () => {
  it("counts off-scale spacing, bare weights and literal colours", () => {
    const sample = `
      .x-a { padding: 12px 14px; gap: var(--space-3); font-weight: 700; color: #fff; }
      .x-b { padding: 0; gap: 2px; font-weight: var(--fw-strong); border: 1px solid rgba(0,0,0,.1); }
    `;
    expect(measure(sample).x).toEqual({ spacing: 1, weight: 1, colour: 2 });
  });
});

describe("measure is not fooled", () => {
  /**
   * Three ways the first version reported zero while off-scale values were
   * still there. Each was found by a reviewer reading the stylesheet, not by
   * this test, which is the wrong way round for a ratchet.
   */
  it("counts a shorthand that is only partly on tokens", () => {
    const sample = ".x-a { padding: 0.95rem 0.9rem 0.95rem var(--space-4); }";
    expect(measure(sample).x.spacing).toBe(1);
  });

  it("counts padding longhands", () => {
    const sample = ".x-a { padding-top: 14px; padding-inline: var(--space-3); padding-left: 2px; }";
    expect(measure(sample).x.spacing).toBe(1);
  });

  it("counts a named colour hidden inside color-mix", () => {
    const sample = ".x-a { background: color-mix(in srgb, black 18%, transparent); color: color-mix(in srgb, var(--text) 50%, transparent); }";
    expect(measure(sample).x.colour).toBe(1);
  });
});

/** Every declaration block whose selector contains `needle`, joined. */
function blocksFor(needle: string): string {
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");
  return [...stripped.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .filter((m) => m[1].includes(needle))
    .map((m) => m[2])
    .join("\n");
}

describe("ink is chosen for the ground it sits on", () => {
  /**
   * `--on-primary` is the ink for a BRAND fill, and it inverts in dark mode
   * (#1a0f06). The refresh replaced literal whites with it wholesale, which
   * is right on a primary button and wrong everywhere the ground does not
   * flip with the theme: dark-mode hairlines went from white at 10% to
   * near-black at 10% and vanished, the clock on the phone mock-up went dark
   * on a dark screen, and the tick on a brand swatch went dark on Slate.
   */
  it.each([
    [".dark .mkt", "marketing's dark hairlines"],
    [".dark .mkt-hub", "the hub's dark hairlines"],
    [".mkt-preview__clock", "the mock-up lock screen"],
    [".mkt-preview__sender", "the mock-up sender line"],
    [".bp-swatch__chip", "the tick on a brand swatch"],
    [".mkt-skeleton", "the marketing skeleton's sheen"],
    [".mkt-hero", "the campaign banner, dark in both themes"],
  ])("%s does not use --on-primary (%s)", (selector) => {
    const block = blocksFor(selector);
    expect(block).not.toBe("");
    expect(block).not.toContain("--on-primary");
  });
});

describe("the campaign banner is one colour in both themes", () => {
  /**
   * Its ground was built from `--mkt-ink`, which is the marketing TEXT colour
   * and so goes near-white in dark mode: a pale banner on a dark page, with
   * white type on it. A banner is not text. It takes the tokens that are
   * dark in both themes, and the ink that goes with them.
   */
  it("is not painted with the text colour", () => {
    const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");
    const hero = stripped.match(/(?:^|\n)\.mkt-hero \{([^{}]*)\}/)?.[1] ?? "";
    expect(hero).not.toBe("");
    expect(hero).not.toContain("--mkt-ink");
    expect(hero).toContain("var(--sidebar)");
  });
});

describe("an offset that spans a gap is written from the gap", () => {
  /**
   * A literal equal to an old gap or padding is a coupling: move the gap to a
   * token and the connector stops short, or misses the centre of what it
   * connects. Both of these were found that way.
   */
  it("the order timeline connector follows the step's padding and gap", () => {
    const block = blocksFor(".order-timeline__step::after");
    expect(block).toMatch(/top:\s*calc\(var\(--space-4\)/);
    expect(block).toMatch(/width:\s*var\(--space-3\)/);
  });

  it("the preference facts dot is centred in its column gap", () => {
    const block = blocksFor(".pref-row__facts li + li::before");
    expect(block).toMatch(/left:\s*calc\(var\(--space-4\)/);
  });
});

describe("the stylesheet does not drift off its tokens", () => {
  const actual = measure(css);

  it("has a budget for every family", () => {
    const missing = Object.keys(actual).filter((family) => !(family in BUDGET));
    // Printed so the baseline can be pasted in once, in Task 1.
    if (missing.length) console.log(JSON.stringify(actual));
    expect(missing).toEqual([]);
  });

  it.each(Object.keys(actual))("%s stays within its budget", (family) => {
    const budget = BUDGET[family] ?? { spacing: 0, weight: 0, colour: 0 };
    expect(actual[family].spacing).toBeLessThanOrEqual(budget.spacing);
    expect(actual[family].weight).toBeLessThanOrEqual(budget.weight);
    expect(actual[family].colour).toBeLessThanOrEqual(budget.colour);
  });
});

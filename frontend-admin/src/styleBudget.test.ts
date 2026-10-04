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
  "ai": { spacing: 149, weight: 59, colour: 10 },
  "bp": { spacing: 19, weight: 9, colour: 3 },
  "branch": { spacing: 10, weight: 4, colour: 3 },
  "breadcrumbs": { spacing: 0, weight: 0, colour: 0 },
  "capability": { spacing: 8, weight: 4, colour: 0 },
  "chart": { spacing: 0, weight: 0, colour: 0 },
  "color": { spacing: 1, weight: 0, colour: 0 },
  "combo": { spacing: 9, weight: 1, colour: 1 },
  "confirm": { spacing: 0, weight: 0, colour: 0 },
  "dashboard": { spacing: 0, weight: 0, colour: 0 },
  "data": { spacing: 0, weight: 0, colour: 0 },
  "detail": { spacing: 0, weight: 0, colour: 0 },
  "empty": { spacing: 0, weight: 0, colour: 0 },
  "eyebrow": { spacing: 0, weight: 0, colour: 0 },
  "field": { spacing: 0, weight: 0, colour: 0 },
  "form": { spacing: 0, weight: 0, colour: 0 },
  "gateway": { spacing: 8, weight: 0, colour: 0 },
  "generated": { spacing: 3, weight: 2, colour: 0 },
  "gst": { spacing: 4, weight: 0, colour: 0 },
  "hub": { spacing: 44, weight: 24, colour: 9 },
  "insight": { spacing: 0, weight: 0, colour: 0 },
  "kds": { spacing: 2, weight: 1, colour: 0 },
  "lg": { spacing: 0, weight: 0, colour: 0 },
  "login": { spacing: 0, weight: 0, colour: 0 },
  "maintenance": { spacing: 0, weight: 0, colour: 0 },
  "menu": { spacing: 34, weight: 7, colour: 3 },
  "method": { spacing: 2, weight: 1, colour: 0 },
  "mixed": { spacing: 0, weight: 0, colour: 0 },
  "mkt": { spacing: 145, weight: 56, colour: 102 },
  "mobile": { spacing: 0, weight: 0, colour: 0 },
  "modal": { spacing: 0, weight: 0, colour: 0 },
  "ntf": { spacing: 20, weight: 6, colour: 2 },
  "offer": { spacing: 1, weight: 1, colour: 0 },
  "order": { spacing: 0, weight: 0, colour: 0 },
  "page": { spacing: 0, weight: 0, colour: 0 },
  "pagination": { spacing: 0, weight: 0, colour: 0 },
  "panel": { spacing: 0, weight: 0, colour: 0 },
  "ph": { spacing: 55, weight: 36, colour: 5 },
  "pref": { spacing: 24, weight: 8, colour: 0 },
  "primary": { spacing: 0, weight: 0, colour: 0 },
  "reports": { spacing: 0, weight: 0, colour: 0 },
  "restaurant": { spacing: 5, weight: 1, colour: 0 },
  "rpt": { spacing: 0, weight: 0, colour: 0 },
  "secondary": { spacing: 0, weight: 0, colour: 0 },
  "segmented": { spacing: 0, weight: 0, colour: 0 },
  "set": { spacing: 17, weight: 6, colour: 0 },
  "settings": { spacing: 0, weight: 0, colour: 0 },
  "skip": { spacing: 0, weight: 0, colour: 0 },
  "slot": { spacing: 9, weight: 1, colour: 0 },
  "st": { spacing: 0, weight: 1, colour: 3 },
  "status": { spacing: 0, weight: 0, colour: 0 },
  "table": { spacing: 0, weight: 0, colour: 0 },
  "tenant": { spacing: 3, weight: 0, colour: 0 },
  "toast": { spacing: 0, weight: 0, colour: 0 },
  "toggle": { spacing: 0, weight: 0, colour: 0 },
  "toolbar": { spacing: 0, weight: 0, colour: 0 },
  "ui": { spacing: 0, weight: 0, colour: 0 },
  "usr": { spacing: 0, weight: 0, colour: 0 },
  "visually": { spacing: 0, weight: 0, colour: 0 },
  "web": { spacing: 4, weight: 7, colour: 0 },
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

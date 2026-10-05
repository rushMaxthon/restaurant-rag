/**
 * How much of the stylesheet is still improvised, per class family.
 *
 * Type, radius, shadow and motion were put on tokens long ago and are used.
 * Spacing, weight and colour were not: 336 paddings in 153 distinct values,
 * every weight a bare number, 119 hex literals. That is what makes two screens
 * built from the same components sit on different rhythms.
 *
 * This counts what is left, grouped by the first word of the selector's class
 * (`rpt`, `mkt`, `admin`…), so a screen can be brought onto the scale one
 * family at a time and cannot drift back afterwards.
 */

export interface Counts {
  spacing: number;
  weight: number;
  colour: number;
}

/** `.rpt-card__title:hover` → `rpt`; `.dark .mkt-x` → `mkt`. */
export function familyOf(selector: string): string {
  const classes = selector.match(/\.([a-zA-Z][\w-]*)/g) ?? [];
  const first = classes.map((c) => c.slice(1)).find((c) => c !== "dark");
  if (!first) return "(element)";
  return first.split(/[-_]/)[0];
}

// Longhands too. `padding-top: 14px` beside a `padding-bottom` that had moved
// to a token went unseen by the first version, which matched the shorthand only.
const SPACING =
  /(?:^|;|\s)(?:padding(?:-[a-z-]+)?|gap|row-gap|column-gap)\s*:\s*([^;]+)/g;
const WEIGHT = /font-weight\s*:\s*([^;]+)/g;
// A literal is a hex, an `rgb()`, or a bare `black`/`white` — the last because
// `color-mix(in srgb, black 18%, transparent)` is a literal the first two
// cannot see. The lookarounds keep `white-space` out of it.
const COLOUR = /#[0-9a-fA-F]{3,8}\b|rgba?\(|(?<![-\w])(?:black|white)(?![-\w])/g;

// 0, 1px-3px (optical nudges and hairlines) and percentages are not rhythm.
const offScale = (value: string) =>
  value
    .split(/\s+/)
    .some((part) => /^\d*\.?\d+(px|rem|em)$/.test(part) && !/^[0-3]px$/.test(part));

export function measure(css: string): Record<string, Counts> {
  const out: Record<string, Counts> = {};
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const rule = /([^{}]+)\{([^{}]*)\}/g;
  let match: RegExpExecArray | null;
  while ((match = rule.exec(stripped))) {
    const selector = match[1].trim();
    if (selector.startsWith("@") || /^(from|to|\d+%)/.test(selector)) continue;
    const family = familyOf(selector.split(",")[0]);
    const body = match[2];
    const counts = (out[family] ??= { spacing: 0, weight: 0, colour: 0 });
    for (const m of body.matchAll(SPACING)) {
      // Each part is judged on its own. Skipping any value that mentions
      // `var(` let `0.95rem 0.9rem 0.95rem var(--space-4)` through as on-scale.
      // What is NOT seen: a literal inside `calc()`, `clamp()` or `max()`.
      const literalParts = m[1].replace(/var\([^()]*\)/g, " ").trim();
      if (offScale(literalParts)) counts.spacing += 1;
    }
    for (const m of body.matchAll(WEIGHT)) {
      if (!m[1].includes("var(")) counts.weight += 1;
    }
    counts.colour += body.match(COLOUR)?.length ?? 0;
  }
  return out;
}

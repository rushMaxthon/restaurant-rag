/**
 * One brand colour in, a readable palette out.
 *
 * A restaurant picks ONE colour — twelve presets or a custom hex, see
 * `backend/app/services/restaurant_theme.py`. Everything the storefront needs
 * beyond that has to be derived, and derived in a way that still reads for a
 * tenant who chose Slate or Forest rather than the platform's orange.
 *
 * Three values come out of it, and they are three because one colour cannot do
 * all three jobs:
 *
 * - **`--primary`** is a FILL nobody reads: a dot, a focus ring, an active bar,
 *   a chart stroke. WCAG asks 3:1 of those and most brand colours clear it.
 * - **`--primary-strong`** is a fill that CARRIES A LABEL — the primary button.
 *   White on the platform orange measures 3.25:1, which is under AA for a 13px
 *   label on the most-clicked control in the product. So the fill walks down
 *   until its ink reads.
 * - **`--primary-text`** is the brand used AS TEXT: an eyebrow, an active tab,
 *   a price. Set small on the page the fills come to roughly 3.1:1, under the
 *   4.5:1 a 12px label needs.
 *
 * Nothing here picks a colour. Every function walks the brand's own hue down
 * or up until a measured ratio is met, so the result is always recognisably
 * the restaurant's colour — just the shade of it that can be read.
 *
 * Pure and dependency-free on purpose: this is the half worth testing, and
 * `brand-palette.test.ts` checks every preset the backend ships.
 */

/** sRGB channels, 0-255. */
export type Rgb = { r: number; g: number; b: number };

/** `#abc`, `#aabbcc` or the same without the hash. Null when it is neither. */
export function parseHex(value: string | null | undefined): Rgb | null {
  if (!value) return null;
  const hex = value.trim().replace(/^#/, "");
  const full =
    hex.length === 3
      ? hex
          .split("")
          .map((c) => c + c)
          .join("")
      : hex;
  if (!/^[0-9a-f]{6}$/i.test(full)) return null;
  return {
    r: parseInt(full.slice(0, 2), 16),
    g: parseInt(full.slice(2, 4), 16),
    b: parseInt(full.slice(4, 6), 16),
  };
}

export function toHex({ r, g, b }: Rgb): string {
  const part = (n: number) =>
    Math.max(0, Math.min(255, Math.round(n)))
      .toString(16)
      .padStart(2, "0");
  return `#${part(r)}${part(g)}${part(b)}`;
}

/**
 * WCAG relative luminance.
 *
 * The linearisation step is the one people drop, and dropping it makes every
 * ratio wrong in the direction that flatters you — mid-tones look like they
 * pass when they do not.
 */
export function luminance({ r, g, b }: Rgb): number {
  const channel = (value: number) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

/** WCAG contrast ratio between two colours, 1 to 21. Order does not matter. */
export function contrast(a: Rgb, b: Rgb): number {
  const la = luminance(a);
  const lb = luminance(b);
  const [light, dark] = la >= lb ? [la, lb] : [lb, la];
  return (light + 0.05) / (dark + 0.05);
}

const WHITE: Rgb = { r: 255, g: 255, b: 255 };

/** HSL, with h in degrees and s/l in 0-1. */
export function toHsl({ r, g, b }: Rgb): { h: number; s: number; l: number } {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return { h: 0, s: 0, l };
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h: number;
  if (max === rn) h = ((gn - bn) / d + (gn < bn ? 6 : 0)) * 60;
  else if (max === gn) h = ((bn - rn) / d + 2) * 60;
  else h = ((rn - gn) / d + 4) * 60;
  return { h, s, l };
}

export function fromHsl({ h, s, l }: { h: number; s: number; l: number }): Rgb {
  if (s === 0) {
    const v = Math.round(l * 255);
    return { r: v, g: v, b: v };
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const channel = (t: number) => {
    let tt = t;
    if (tt < 0) tt += 1;
    if (tt > 1) tt -= 1;
    if (tt < 1 / 6) return p + (q - p) * 6 * tt;
    if (tt < 1 / 2) return q;
    if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6;
    return p;
  };
  const hn = (((h % 360) + 360) % 360) / 360;
  return {
    r: Math.round(channel(hn + 1 / 3) * 255),
    g: Math.round(channel(hn) * 255),
    b: Math.round(channel(hn - 1 / 3) * 255),
  };
}

/**
 * Walk a colour's lightness until it clears `ratio` against `against`.
 *
 * Hue and saturation are held, which is the whole point: the answer has to
 * still be the restaurant's colour. `direction` is -1 to darken and +1 to
 * lighten; the caller knows which way the backdrop is.
 *
 * Returns the original when it already passes, and the end of the ramp when no
 * shade of that hue can get there — black and white are the floor and ceiling,
 * and returning the best available beats returning something off-brand.
 */
export function walkToContrast(
  colour: Rgb,
  against: Rgb,
  ratio: number,
  direction: -1 | 1,
): Rgb {
  if (contrast(colour, against) >= ratio) return colour;
  const { h, s } = toHsl(colour);
  const start = toHsl(colour).l;
  // 1% steps. Finer than the eye resolves on a single swatch, coarse enough
  // that the loop is bounded at a hundred iterations.
  for (let step = 1; step <= 100; step += 1) {
    const l = start + direction * step * 0.01;
    if (l < 0 || l > 1) break;
    const candidate = fromHsl({ h, s, l });
    if (contrast(candidate, against) >= ratio) return candidate;
  }
  return direction < 0 ? { r: 0, g: 0, b: 0 } : WHITE;
}

/**
 * The ink that reads on a fill: white wherever white is legible, dark where it
 * is not.
 *
 * This was a luminance threshold, and the reasoning it carried was sound as
 * far as it went. White on a brand fill IS the design, and "whichever has more
 * contrast" would put near-black on nine brands that do not need it. That
 * argument is kept; only its conclusion moves.
 *
 * What it missed is that white on the platform's own orange measures
 * **3.25:1**, and AA wants 4.5 for text at the size these labels are actually
 * set — 12px on a dish's Add button, 16px on the rest. The comment above this
 * function quoted that 3.24 and treated it as acceptable. It is acceptable for
 * LARGE text only, and none of these buttons are large.
 *
 * So the rule is now: prefer white, and fall back to dark ink only when white
 * genuinely fails. Measured across all twelve presets a restaurant can pick,
 * that changes exactly two:
 *
 *     sunset  #FF5200   white 3.25  dark 5.51   -> dark
 *     ocean   #2D7FF9   white 3.81  dark 4.71   -> dark
 *     the other ten     white 4.99 to 10.35     -> white, unchanged
 *
 * Which is the point. It is not "maximise contrast", which would have flipped
 * all twelve; it is "keep the design until the design stops being readable".
 * And because it is derived rather than listed, a restaurant that types its
 * own hex into the branding panel gets a legible button too — including the
 * pale brands the luminance threshold was written to catch, which still land
 * on dark ink because white on them is nowhere near 4.5.
 *
 * The last clause is for a fill where NEITHER reaches 4.5, a mid-tone that is
 * equally awkward for both. Nothing can rescue that from here, so it takes the
 * better of the two and `everyPresetHasReadableInk` in the tests is what stops
 * such a colour reaching the preset list.
 */
export function readableInk(fill: Rgb): string {
  const DARK = "#14171f";
  const darkInk = parseHex(DARK) as Rgb;
  if (contrast(WHITE, fill) >= 4.5) return "#ffffff";
  if (contrast(darkInk, fill) >= 4.5) return DARK;
  return contrast(WHITE, fill) >= contrast(darkInk, fill) ? "#ffffff" : DARK;
}

/**
 * The ink for a fill that has been lifted for a dark page — and a different
 * rule, on purpose.
 *
 * In light mode the design is white-on-brand and `readableInk` exists to
 * protect that. In dark mode the fill is deliberately lifted to be the
 * brightest thing on the screen, which is what a primary action should be
 * there — so white on it goes the wrong way. The platform orange lifted comes
 * to 2.48:1 against white and 7.1:1 against near-black.
 *
 * The operator panel reached the same conclusion by hand and pinned
 * `--on-primary: #1a0f06` in its dark block. This is that decision, derived.
 */
export function inkForLiftedFill(fill: Rgb): string {
  const dark: Rgb = { r: 20, g: 23, b: 31 };
  return contrast(WHITE, fill) >= contrast(dark, fill) ? "#ffffff" : "#14171f";
}

/**
 * The brand, lifted for a dark page.
 *
 * A mid-tone brand that reads as a button on white disappears on near-black.
 * Lightness goes up by a little and is then clamped into a band that is bright
 * enough to carry dark ink and not so bright it glares — the same treatment
 * and the same band the mobile app uses (`themePalette.ts`), so one product
 * does not have two answers.
 */
export function liftForDark(colour: Rgb): Rgb {
  const { h, s, l } = toHsl(colour);
  const lifted = Math.min(0.72, Math.max(0.42, l + 0.135));
  return fromHsl({ h, s, l: lifted });
}

/** Every derived value for one brand colour, in one shape. */
export type BrandPalette = {
  primary: string;
  primaryStrong: string;
  primaryText: string;
  onPrimary: string;
  darkPrimary: string;
  darkOnPrimary: string;
};

/**
 * The DARKEST light-mode ground that orange text can land on — `--surface-alt`,
 * not `--bg`.
 *
 * It was `#fafafa`, the old page colour, and two things were wrong with that
 * even before the palette moved. The page became `#f2f5f0`, so every value
 * walked against the stale number came out a shade too light and the text tier
 * slipped to 4.39:1. And a tier derived against the PAGE is not safe on a
 * section tinted with `--surface-alt`, which is darker again — the "See all
 * dishes" link on the picks block landed at 4.24:1 for exactly that reason.
 *
 * Walking against the darkest of the three grounds makes the one value safe on
 * all of them, at the cost of being a shade darker than strictly needed on
 * white. That is the right trade: too much contrast is not a defect.
 *
 * Must track `--surface-alt` in `styles.css`. `e2e/contrast.spec.ts` is what
 * catches it if either moves, before anybody has to remember this comment.
 */
const LIGHT_PAGE: Rgb = { r: 232, g: 237, b: 228 };

/**
 * AA for small text. The fills only ever need 3:1 and already have it; it is
 * the two derived values that have to reach this.
 */
const AA_SMALL = 4.5;

export function brandPalette(input: string): BrandPalette | null {
  const primary = parseHex(input);
  if (!primary) return null;

  // The button fill: darkened until WHITE on it clears AA. White rather than
  // the eventual ink because a brand button is white-on-colour in every design
  // either app has, and solving for the ink we might pick instead would let a
  // pale brand stay pale and flip to dark ink, which reads as a different
  // button rather than the same one.
  const strong = walkToContrast(primary, WHITE, AA_SMALL, -1);

  // The text tier: darkened until it reads as 12px copy on the page.
  const text = walkToContrast(primary, LIGHT_PAGE, AA_SMALL, -1);

  const dark = liftForDark(primary);

  return {
    primary: toHex(primary),
    primaryStrong: toHex(strong),
    primaryText: toHex(text),
    onPrimary: readableInk(primary),
    darkPrimary: toHex(dark),
    darkOnPrimary: inkForLiftedFill(dark),
  };
}

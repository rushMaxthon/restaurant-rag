/**
 * Turning one brand colour into a full palette.
 *
 * A restaurant picks a single colour. Every accent-derived token in the app -
 * the primary itself, its soft wash, the warm tinted surfaces, the alpha tints
 * behind chips and badges - has to move with it, or a blue restaurant ends up
 * with peach cards and an orange chip border.
 *
 * The method is hue *rotation*, not recomputation and not replacement. Each
 * token in the base palette was hand-tuned against the default orange;
 * re-deriving them would throw that tuning away. Replacing their hue outright
 * would too: the palette's accent tokens do not all sit on exactly the primary's
 * hue - the dark-mode primary is 15.4 deg against the light one's 19.3 - and
 * flattening them onto one value quietly restyles them.
 *
 * So every token is rotated by the same delta between the brand hue and the
 * default. Saturation and lightness are untouched, the palette's internal
 * relationships survive, and a colour with no hue at all - white, a grey - is
 * left exactly as it was.
 *
 * That gives the property this change needs most: for the default orange the
 * delta is zero and the transformation is the identity, so an unbranded app
 * renders exactly what it rendered before.
 */

export const DEFAULT_BRAND_COLOR = '#FF5200';

/** Longest hex we accept; anything else falls back to the default. */
const HEX_PATTERN = /^#[0-9a-fA-F]{6}$/;

export interface Rgb {
  r: number;
  g: number;
  b: number;
}

export interface Hsl {
  h: number;
  s: number;
  l: number;
}

export function isValidHex(value: string | null | undefined): boolean {
  return typeof value === 'string' && HEX_PATTERN.test(value.trim());
}

export function normalizeHex(value: string | null | undefined): string {
  return isValidHex(value)
    ? (value as string).trim().toUpperCase()
    : DEFAULT_BRAND_COLOR;
}

export function hexToRgb(hex: string): Rgb {
  const value = normalizeHex(hex).slice(1);
  return {
    r: parseInt(value.slice(0, 2), 16),
    g: parseInt(value.slice(2, 4), 16),
    b: parseInt(value.slice(4, 6), 16),
  };
}

export function rgbToHex({ r, g, b }: Rgb): string {
  const channel = (value: number) =>
    Math.max(0, Math.min(255, Math.round(value)))
      .toString(16)
      .padStart(2, '0')
      .toUpperCase();
  return `#${channel(r)}${channel(g)}${channel(b)}`;
}

export function rgbToHsl({ r, g, b }: Rgb): Hsl {
  const red = r / 255;
  const green = g / 255;
  const blue = b / 255;
  const max = Math.max(red, green, blue);
  const min = Math.min(red, green, blue);
  const delta = max - min;
  const l = (max + min) / 2;

  if (delta === 0) {
    // A grey has no hue to speak of. Reporting 0 rather than NaN keeps it
    // stable through a round trip, and hue replacement leaves it alone.
    return { h: 0, s: 0, l };
  }

  const s = l > 0.5 ? delta / (2 - max - min) : delta / (max + min);
  let h: number;
  if (max === red) {
    h = ((green - blue) / delta + (green < blue ? 6 : 0)) / 6;
  } else if (max === green) {
    h = ((blue - red) / delta + 2) / 6;
  } else {
    h = ((red - green) / delta + 4) / 6;
  }
  return { h: h * 360, s, l };
}

export function hslToRgb({ h, s, l }: Hsl): Rgb {
  if (s === 0) {
    const value = l * 255;
    return { r: value, g: value, b: value };
  }
  const hue = ((h % 360) + 360) % 360 / 360;
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;

  const toChannel = (t: number) => {
    let value = t;
    if (value < 0) {
      value += 1;
    }
    if (value > 1) {
      value -= 1;
    }
    if (value < 1 / 6) {
      return p + (q - p) * 6 * value;
    }
    if (value < 1 / 2) {
      return q;
    }
    if (value < 2 / 3) {
      return p + (q - p) * (2 / 3 - value) * 6;
    }
    return p;
  };

  return {
    r: toChannel(hue + 1 / 3) * 255,
    g: toChannel(hue) * 255,
    b: toChannel(hue - 1 / 3) * 255,
  };
}

/**
 * How far a hue may sit from the default and still count as brand-derived.
 *
 * Wide enough to cover every warm token in the light palette - the warmest,
 * `surface` at 40 degrees, is 21 from the default orange - and nowhere near
 * wide enough to catch the cool blue-greys the dark palette is built from.
 */
export const BRAND_FAMILY_TOLERANCE = 45;

/** Circular distance between two hues, in degrees. */
function hueDistance(a: number, b: number): number {
  const raw = Math.abs(((a - b) % 360 + 360) % 360);
  return Math.min(raw, 360 - raw);
}

/**
 * Whether a colour was drawn from the brand, and so should follow it.
 *
 * This is the distinction that makes dark mode work. The light palette's
 * surfaces are warm - peach and cream washed out of the orange - so they must
 * move with the brand. The dark palette's surfaces are cool blue-greys at about
 * 216 degrees that were never orange at all; rotating those by a pink brand's
 * offset turned every card teal. A colour with no hue - a grey, pure white - is
 * unaffected either way and counts as in-family so the caller need not special
 * case it.
 */
export function isBrandFamily(color: string): boolean {
  const rgb = color.startsWith('rgba') ? rgbaToRgb(color) : hexToRgb(color);
  if (rgb === null) {
    return false;
  }
  const hsl = rgbToHsl(rgb);
  if (hsl.s === 0) {
    return true;
  }
  return (
    hueDistance(hsl.h, brandHue(DEFAULT_BRAND_COLOR)) <= BRAND_FAMILY_TOLERANCE
  );
}

function rgbaToRgb(value: string): Rgb | null {
  const match = value.match(
    /^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)$/,
  );
  if (!match) {
    return null;
  }
  return { r: Number(match[1]), g: Number(match[2]), b: Number(match[3]) };
}

/** How far the brand sits from the default, in degrees. Zero means unbranded. */
export function hueDelta(brandHex: string): number {
  return brandHue(brandHex) - brandHue(DEFAULT_BRAND_COLOR);
}

/**
 * Rotate a colour's hue by `delta`, keeping saturation and lightness.
 *
 * Greys and pure white have no hue and are returned untouched, which is why
 * backgrounds, text and borders survive rebranding unchanged.
 */
export function retint(hex: string, delta: number): string {
  // Exact, not merely close: an unbranded app must not drift by even one value
  // through a float round trip.
  if (delta === 0) {
    return normalizeHex(hex);
  }
  const hsl = rgbToHsl(hexToRgb(hex));
  if (hsl.s === 0) {
    return normalizeHex(hex);
  }
  return rgbToHex(hslToRgb({ ...hsl, h: hsl.h + delta }));
}

/** Same, for the `rgba(...)` strings the palette uses for dark-mode washes. */
export function retintRgba(value: string, delta: number): string {
  const match = value.match(
    /^rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([\d.]+)\s*\)$/,
  );
  if (delta === 0 || !match) {
    return value;
  }
  const [, r, g, b, alpha] = match;
  const hsl = rgbToHsl({ r: Number(r), g: Number(g), b: Number(b) });
  if (hsl.s === 0) {
    return value;
  }
  const next = hslToRgb({ ...hsl, h: hsl.h + delta });
  return `rgba(${Math.round(next.r)}, ${Math.round(next.g)}, ${Math.round(
    next.b,
  )}, ${alpha})`;
}

/** WCAG relative luminance. */
export function relativeLuminance({ r, g, b }: Rgb): number {
  const channel = (value: number) => {
    const c = value / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(a: string, b: string): number {
  const first = relativeLuminance(hexToRgb(a));
  const second = relativeLuminance(hexToRgb(b));
  const lighter = Math.max(first, second);
  const darker = Math.min(first, second);
  return (lighter + 0.05) / (darker + 0.05);
}

/** Ink on a brand colour must clear this to stay legible. */
export const MIN_INK_CONTRAST = 3;

/**
 * Ink that stays readable on the brand colour.
 *
 * Deliberately "white unless white fails", not "whichever contrasts most".
 * Dark ink actually scores higher than white on the default orange (4.6 vs
 * 3.2), so maximising contrast would flip every existing button to dark text
 * and change a design nobody asked to change. The threshold only intervenes
 * where white genuinely stops working - a yellow or a pale mint - which is the
 * case this exists for.
 *
 * 3.0 is the WCAG bar for large text and UI components. It is the bar the
 * shipped orange already sits on, so it is the bar that preserves it.
 */
export function readableInk(background: string, whiteInk = '#FFFFFF'): string {
  const darkInk = '#1F2430';
  if (contrastRatio(background, whiteInk) >= MIN_INK_CONTRAST) {
    return whiteInk;
  }
  return contrastRatio(background, darkInk) >= contrastRatio(background, whiteInk)
    ? darkInk
    : whiteInk;
}

/**
 * How far dark mode lifts the accent, and the band it must land in.
 *
 * The lift is the relationship the shipped palette already encodes: its dark
 * primary is the light one at the same saturation, 13.5 points lighter. The
 * band keeps a very dark brand visible against a near-black background and
 * stops a very light one washing out to near-white.
 */
export const DARK_LIGHTNESS_LIFT = 13.5;
export const DARK_LIGHTNESS_MIN = 42;
export const DARK_LIGHTNESS_MAX = 72;

/**
 * The brand as it should appear on a dark background.
 *
 * Derived from the brand itself, not by rotating the default's dark variant.
 * That variant is a fully saturated orange, so rotating it forced every brand
 * to 100% saturation - a deliberately muted forest green came out as neon lime.
 * Lifting the brand's own lightness keeps its character and only makes it
 * legible.
 */
export function darkModeAccent(hex: string): string {
  const hsl = rgbToHsl(hexToRgb(hex));
  const lifted = hsl.l * 100 + DARK_LIGHTNESS_LIFT;
  const clamped = Math.min(
    Math.max(lifted, DARK_LIGHTNESS_MIN),
    DARK_LIGHTNESS_MAX,
  );
  return rgbToHex(hslToRgb({ ...hsl, l: clamped / 100 }));
}

/** An alpha wash of the brand colour, for tints that used a literal rgba. */
export function tint(hex: string, alpha: number): string {
  const { r, g, b } = hexToRgb(hex);
  return `rgba(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)}, ${alpha})`;
}

export function brandHue(hex: string): number {
  return rgbToHsl(hexToRgb(hex)).h;
}

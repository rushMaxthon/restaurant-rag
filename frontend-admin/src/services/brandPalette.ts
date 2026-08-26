/**
 * The device's colour maths, mirrored for the preview.
 *
 * A preview that computes its colours differently from the app is worse than no
 * preview: it quietly promises something the phone will not deliver. This is a
 * direct port of `mobile/src/themePalette.ts` and the accent rules in
 * `mobile/src/themeBase.ts`, kept deliberately literal so the two can be
 * compared line by line. `brandPalette.test.ts` pins the outputs against values
 * taken from the mobile implementation.
 *
 * Only the tokens the preview actually paints are derived here. The full
 * palette lives on the device.
 */

export const DEFAULT_BRAND_COLOR = '#FF5200';

/** Ink on a brand colour must clear this to count as legible. */
export const MIN_INK_CONTRAST = 3;

/**
 * The dark accent the palette ships for the default brand.
 *
 * The device returns this verbatim rather than deriving it, so that an unbranded
 * app is byte-identical to what it rendered before theming existed. Deriving it
 * here instead would give #FF8145 and the preview would be subtly wrong for the
 * one colour most restaurants are on.
 */
const SHIPPED_DARK_PRIMARY = '#FF7A45';

/**
 * The ink the palette ships, per mode.
 *
 * The device recomputes ink only for a customised brand: the shipped palette is
 * ground truth for the default, and dark mode's near-white on #FF7A45 sits at
 * 2.5 - below the bar, but it is the current design and "fixing" it would
 * restyle every unbranded app.
 */
const SHIPPED_INK = { light: '#FFFFFF', dark: '#FFF8F4' } as const;

/** Dark mode lifts the accent by this much, into this band. */
const DARK_LIGHTNESS_LIFT = 13.5;
const DARK_LIGHTNESS_MIN = 42;
const DARK_LIGHTNESS_MAX = 72;

/** How far a hue may sit from the default and still count as brand-derived. */
const BRAND_FAMILY_TOLERANCE = 45;

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

/** The two grounds the mobile app paints on. */
export const LIGHT_SURFACES = {
  background: '#FFFFFF',
  card: '#FFFFFF',
  hero: '#FFF2EA',
  surfaceAlt: '#FFF5EE',
  surfaceRaised: '#FFFFFF',
  chip: '#FAF7F3',
  border: '#E9E9EB',
  muted: '#F8F8F8',
  hint: '#93959F',
  text: '#282C3F',
  secondaryText: '#686B78',
  tabBar: '#FFFDF9',
} as const;

export const DARK_SURFACES = {
  background: '#0E1116',
  card: '#151A22',
  hero: '#1A202B',
  surfaceAlt: '#1A202B',
  surfaceRaised: '#1C2430',
  chip: '#1A202B',
  border: '#252C38',
  muted: '#151A22',
  hint: '#8791A1',
  text: '#F3F5F8',
  secondaryText: '#B5BDC9',
  tabBar: '#12171F',
} as const;

export function isValidHex(value: string | null | undefined): boolean {
  return typeof value === 'string' && HEX_PATTERN.test(value.trim());
}

export function normalizeHex(value: string | null | undefined): string {
  return isValidHex(value) ? (value as string).trim().toUpperCase() : DEFAULT_BRAND_COLOR;
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
    Math.max(0, Math.min(255, Math.round(value))).toString(16).padStart(2, '0').toUpperCase();
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
  const hue = ((((h % 360) + 360) % 360) / 360);
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const toChannel = (t: number) => {
    let value = t;
    if (value < 0) value += 1;
    if (value > 1) value -= 1;
    if (value < 1 / 6) return p + (q - p) * 6 * value;
    if (value < 1 / 2) return q;
    if (value < 2 / 3) return p + (q - p) * (2 / 3 - value) * 6;
    return p;
  };
  return {
    r: toChannel(hue + 1 / 3) * 255,
    g: toChannel(hue) * 255,
    b: toChannel(hue - 1 / 3) * 255,
  };
}

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
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

/** White unless white fails, matching the device rule exactly. */
export function readableInk(background: string, whiteInk = '#FFFFFF'): string {
  const darkInk = '#1F2430';
  if (contrastRatio(background, whiteInk) >= MIN_INK_CONTRAST) {
    return whiteInk;
  }
  return contrastRatio(background, darkInk) >= contrastRatio(background, whiteInk)
    ? darkInk
    : whiteInk;
}

/** The brand as it appears on a dark background: its own hue and saturation, lifted. */
export function darkModeAccent(hex: string): string {
  const hsl = rgbToHsl(hexToRgb(hex));
  const lifted = hsl.l * 100 + DARK_LIGHTNESS_LIFT;
  const clamped = Math.min(Math.max(lifted, DARK_LIGHTNESS_MIN), DARK_LIGHTNESS_MAX);
  return rgbToHex(hslToRgb({ ...hsl, l: clamped / 100 }));
}

function hueDistance(a: number, b: number): number {
  const raw = Math.abs((((a - b) % 360) + 360) % 360);
  return Math.min(raw, 360 - raw);
}

function brandHue(hex: string): number {
  return rgbToHsl(hexToRgb(hex)).h;
}

export function isBrandFamily(hex: string): boolean {
  const hsl = rgbToHsl(hexToRgb(hex));
  if (hsl.s === 0) return true;
  return hueDistance(hsl.h, brandHue(DEFAULT_BRAND_COLOR)) <= BRAND_FAMILY_TOLERANCE;
}

/** Rotate a brand-derived colour onto this brand's hue. Identity for the default. */
export function retint(hex: string, brand: string): string {
  const delta = brandHue(normalizeHex(brand)) - brandHue(DEFAULT_BRAND_COLOR);
  if (delta === 0 || !isBrandFamily(hex)) {
    return normalizeHex(hex);
  }
  const hsl = rgbToHsl(hexToRgb(hex));
  if (hsl.s === 0) return normalizeHex(hex);
  return rgbToHex(hslToRgb({ ...hsl, h: hsl.h + delta }));
}

export function tint(hex: string, alpha: number): string {
  const { r, g, b } = hexToRgb(hex);
  return `rgba(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)}, ${alpha})`;
}

export interface PreviewPalette {
  mode: 'light' | 'dark';
  primary: string;
  onPrimary: string;
  primarySoft: string;
  hero: string;
  surfaceAlt: string;
  surfaceRaised: string;
  chip: string;
  background: string;
  card: string;
  border: string;
  muted: string;
  hint: string;
  text: string;
  secondaryText: string;
  tabBar: string;
  /** Contrast of the label on the button, for the readability note. */
  inkContrast: number;
  /** Contrast of the accent used as text on the page ground. */
  textContrast: number;
}

/** Everything the preview needs, derived the way the device derives it. */
export function previewPalette(brandColor: string, mode: 'light' | 'dark'): PreviewPalette {
  const brand = normalizeHex(brandColor);
  const surfaces = mode === 'dark' ? DARK_SURFACES : LIGHT_SURFACES;
  const primary =
    mode === 'dark'
      ? brand === DEFAULT_BRAND_COLOR
        ? SHIPPED_DARK_PRIMARY
        : darkModeAccent(brand)
      : brand;
  // Dark mode's washes follow the resolved accent; light mode's warm surfaces
  // are rotated onto the brand hue, exactly as on the device.
  const primarySoft = mode === 'dark' ? tint(primary, 0.14) : tint(primary, 0.1);
  const shippedInk = SHIPPED_INK[mode];
  const onPrimary =
    brand === DEFAULT_BRAND_COLOR ? shippedInk : readableInk(primary, shippedInk);

  return {
    mode,
    primary,
    onPrimary,
    primarySoft,
    hero: mode === 'dark' ? surfaces.hero : retint(LIGHT_SURFACES.hero, brand),
    surfaceAlt:
      mode === 'dark' ? surfaces.surfaceAlt : retint(LIGHT_SURFACES.surfaceAlt, brand),
    surfaceRaised: surfaces.surfaceRaised,
    chip: mode === 'dark' ? surfaces.chip : retint(LIGHT_SURFACES.chip, brand),
    background: surfaces.background,
    card: surfaces.card,
    border: surfaces.border,
    muted: surfaces.muted,
    hint: surfaces.hint,
    text: surfaces.text,
    secondaryText: surfaces.secondaryText,
    tabBar: mode === 'dark' ? surfaces.tabBar : retint(LIGHT_SURFACES.tabBar, brand),
    inkContrast: contrastRatio(primary, onPrimary),
    textContrast: contrastRatio(primary, surfaces.background),
  };
}

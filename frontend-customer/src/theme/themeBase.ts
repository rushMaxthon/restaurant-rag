/**
 * The base palettes and the brand-aware theme builder.
 *
 * Deliberately free of React and of the app store: this is data plus colour
 * maths, and keeping it importable on its own is what lets the palettes be
 * asserted directly in tests.
 */

import {
  darkModeAccent,
  hueDelta,
  isBrandFamily,
  normalizeHex,
  readableInk,
  retint,
  retintRgba,
  tint,
} from './palette';

export type ThemePreference = 'light' | 'dark' | 'system';
export type ThemeMode = 'light' | 'dark';

const spacing = {
  xs: 8,
  sm: 12,
  md: 16,
  lg: 20,
  xl: 24,
  screen: 16,
  stackTop: 10,
  card: 16,
  gap: 12,
  section: 24,
} as const;

const radius = {
  xs: 10,
  md: 16,
  lg: 20,
  card: 12,
  button: 8,
  pill: 20,
} as const;

const sharedColors = {
  primary: '#FF5200',
  deepRed: '#CB202D',
  success: '#48C479',
  warning: '#F8A000',
  info: '#1A73E8',
  offer: '#3D9B6D',
  white: '#FFFFFF',
} as const;

/**
 * Every colour the app can name. Both palettes implement it, so a themed value
 * can be built from either without the two drifting apart.
 */
export interface ThemeColors {
  primary: string;
  deepRed: string;
  success: string;
  warning: string;
  info: string;
  offer: string;
  white: string;
  background: string;
  card: string;
  surface: string;
  surfaceAlt: string;
  surfaceRaised: string;
  modalSurface: string;
  input: string;
  text: string;
  secondaryText: string;
  hint: string;
  disabledText: string;
  onPrimary: string;
  successSoft: string;
  warningSoft: string;
  infoSoft: string;
  dangerSoft: string;
  border: string;
  divider: string;
  sidebar: string;
  primarySoft: string;
  cream: string;
  chip: string;
  chipBorder: string;
  overlay: string;
  skeletonBase: string;
  skeletonHighlight: string;
  shadow: string;
  darkOverlay: string;
}

interface BasePalette {
  mode: ThemeMode;
  colors: ThemeColors;
  spacing: typeof spacing;
  radius: typeof radius;
}

export const lightTheme: BasePalette = {
  mode: 'light',
  colors: {
    ...sharedColors,
    background: '#FFFFFF',
    card: '#F8F8F8',
    surface: '#FFFDF9',
    surfaceAlt: '#FFF5EE',
    surfaceRaised: '#FFFFFF',
    modalSurface: '#FFFDF9',
    input: '#FFFFFF',
    text: '#282C3F',
    secondaryText: '#686B78',
    hint: '#93959F',
    disabledText: '#A8ABB5',
    onPrimary: '#FFFFFF',
    successSoft: '#E8F7EE',
    warningSoft: '#FFF4DA',
    infoSoft: '#E9F1FF',
    dangerSoft: '#FFF2F1',
    border: '#E9E9EB',
    divider: '#F2F2F2',
    sidebar: '#1A1A2E',
    primarySoft: '#FFF0E8',
    cream: '#FFF8F2',
    chip: '#FAF7F3',
    chipBorder: '#F0E7DF',
    overlay: 'rgba(16, 18, 28, 0.26)',
    skeletonBase: '#F0F0F0',
    skeletonHighlight: '#E0E0E0',
    shadow: 'rgba(20, 23, 34, 0.12)',
    darkOverlay: 'rgba(16, 18, 28, 0.26)',
  },
  spacing,
  radius,
};

export const darkTheme: BasePalette = {
  mode: 'dark',
  colors: {
    ...sharedColors,
    primary: '#FF7A45',
    background: '#0E1116',
    card: '#151A22',
    surface: '#12171F',
    surfaceAlt: '#1A202B',
    surfaceRaised: '#1C2430',
    modalSurface: '#151C26',
    input: '#1A202B',
    text: '#F3F5F8',
    secondaryText: '#B5BDC9',
    hint: '#8791A1',
    disabledText: '#6F7A8B',
    onPrimary: '#FFF8F4',
    successSoft: 'rgba(72, 196, 121, 0.14)',
    warningSoft: 'rgba(248, 160, 0, 0.14)',
    infoSoft: 'rgba(26, 115, 232, 0.16)',
    dangerSoft: 'rgba(203, 32, 45, 0.16)',
    border: '#252C38',
    divider: '#1D2430',
    sidebar: '#0B0E13',
    primarySoft: 'rgba(255, 122, 69, 0.12)',
    cream: '#181D26',
    chip: '#1A202B',
    chipBorder: '#2A3340',
    overlay: 'rgba(8, 10, 14, 0.52)',
    skeletonBase: '#1A202B',
    skeletonHighlight: '#232C38',
    shadow: 'rgba(0, 0, 0, 0.34)',
    darkOverlay: 'rgba(8, 10, 14, 0.42)',
  },
  spacing,
  radius,
};

export interface AppTheme extends BasePalette {
  /** The restaurant's colour as chosen, before any mode adjustment. */
  brandColor: string;
  /** An alpha wash of the brand colour, for tints screens used to hardcode. */
  primaryTint: (alpha: number) => string;
  /**
   * Move a hand-picked decorative colour onto the brand hue.
   *
   * The screens are full of one-off warm washes - a peach hero, a cream chip -
   * that are not the brand colour but are unmistakably drawn from it. Promoting
   * each to a palette token would bloat the palette; leaving them literal
   * strands them at orange. This rotates them the same way the palette is
   * rotated, so they follow the brand and stay exactly themselves by default.
   *
   * Only for brand-derived decoration. Semantic colours - the error red, the
   * rating amber, the veg-badge green - must not be passed through it.
   */
  tone: (color: string) => string;
}

/**
 * Build the palette for one brand colour.
 *
 * Only hue-bearing tokens move. Backgrounds, text, borders and the semantic
 * colours - success, warning, the cancelled-order red - are left exactly as
 * they are: a restaurant may own its accent, but a red "delivered" would be
 * actively harmful.
 *
 * `onPrimary` is the one token that is decided rather than rotated, because
 * readability on the brand colour is not a hue question.
 */
export function createTheme(
  brandColor: string,
  mode: ThemeMode = 'light',
): AppTheme {
  const base = mode === 'dark' ? darkTheme : lightTheme;
  const brand = normalizeHex(brandColor);
  const delta = hueDelta(brand);

  // Tokens that *may* be washes of the brand. Listing a key here only makes it
  // a candidate: each value is still checked, because the same key holds a warm
  // brand-derived wash in the light palette and a cool neutral in the dark one.
  const accentKeys: (keyof ThemeColors)[] = [
    'primary',
    'primarySoft',
    'surface',
    'surfaceAlt',
    'surfaceRaised',
    'modalSurface',
    'cream',
    'chip',
    'chipBorder',
  ];

  const colors: ThemeColors = { ...base.colors };
  for (const key of accentKeys) {
    const value = colors[key];
    // Only what was actually drawn from the brand follows it. Dark mode's
    // surfaces are cool blue-greys that were never orange; rotating those by a
    // pink brand's offset turned every card teal.
    if (!isBrandFamily(value)) {
      continue;
    }
    colors[key] = value.startsWith('rgba')
      ? retintRgba(value, delta)
      : retint(value, delta);
  }

  // The light mode primary IS the brand colour. Dark mode shows a lifted
  // version of it - derived from the brand, not by rotating the default's own
  // dark variant, which is a fully saturated orange and dragged every brand up
  // to 100% saturation with it.
  if (mode === 'dark') {
    colors.primary = delta === 0 ? darkTheme.colors.primary : darkModeAccent(brand);
    // Follows the resolved accent rather than the rotated base, so a muted
    // brand gets a muted wash. Identical to the shipped value by construction
    // when the accent is the shipped one.
    colors.primarySoft = tint(colors.primary, 0.12);
  } else {
    colors.primary = brand;
  }
  // Ink is only recomputed for a customised brand. The shipped palette is
  // ground truth for the default: dark mode runs near-white on #FF7A45 at a
  // ratio of 2.6, below the bar below, and "fixing" that would restyle a design
  // nobody asked to change. The rule exists to protect colours the designer
  // never saw - a yellow, a pale mint - not to second-guess the ones they did.
  if (delta !== 0) {
    colors.onPrimary = readableInk(colors.primary, base.colors.onPrimary);
  }

  return {
    ...base,
    colors,
    brandColor: brand,
    primaryTint: (alpha: number) => tint(colors.primary, alpha),
    tone: (color: string) => {
      if (!isBrandFamily(color)) {
        return color;
      }
      return color.startsWith('rgba')
        ? retintRgba(color, delta)
        : retint(color, delta);
    },
  };
}


import { createTheme, darkTheme, lightTheme } from './themeBase';
import {
  DARK_LIGHTNESS_MAX,
  DARK_LIGHTNESS_MIN,
  DEFAULT_BRAND_COLOR,
  contrastRatio,
  hexToRgb,
  rgbToHsl,
} from './themePalette';

describe('createTheme', () => {
  it('reproduces the shipped light palette exactly for the default brand', () => {
    // The regression that matters most: an unbranded app must be byte-identical
    // to what it rendered before per-restaurant theming existed.
    const built = createTheme(DEFAULT_BRAND_COLOR, 'light');
    expect(built.colors).toEqual(lightTheme.colors);
  });

  it('reproduces the shipped dark palette exactly for the default brand', () => {
    const built = createTheme(DEFAULT_BRAND_COLOR, 'dark');
    expect(built.colors).toEqual(darkTheme.colors);
  });

  it('falls back to the default when the stored colour is unusable', () => {
    expect(createTheme('nonsense', 'light').colors).toEqual(lightTheme.colors);
    expect(createTheme('', 'light').brandColor).toBe(DEFAULT_BRAND_COLOR);
  });

  it('uses the brand colour itself as the light primary', () => {
    expect(createTheme('#2D7FF9', 'light').colors.primary).toBe('#2D7FF9');
  });

  it('keeps the lightened relationship dark mode already had', () => {
    // Dark mode does not show the raw brand colour; it shows the lighter
    // variant the base palette encodes, moved onto the brand hue.
    const dark = createTheme('#2D7FF9', 'dark');
    expect(dark.colors.primary).not.toBe('#2D7FF9');
    expect(dark.colors.primary).not.toBe(darkTheme.colors.primary);
  });

  it('moves the warm surfaces onto the brand hue', () => {
    const blue = createTheme('#2D7FF9', 'light');
    for (const key of ['surfaceAlt', 'cream', 'chipBorder', 'primarySoft'] as const) {
      expect(blue.colors[key]).not.toBe(lightTheme.colors[key]);
    }
  });

  it('leaves dark mode surfaces neutral instead of tinting them', () => {
    // The regression: dark surfaces are cool blue-greys at ~216 degrees that
    // were never derived from the orange. Rotating them by a pink brand's
    // offset landed them near 173 and turned every card teal.
    const cherry = createTheme('#C2185B', 'dark');
    for (const key of [
      'surface',
      'surfaceAlt',
      'surfaceRaised',
      'modalSurface',
      'cream',
      'chip',
      'chipBorder',
    ] as const) {
      expect(cherry.colors[key]).toBe(darkTheme.colors[key]);
    }
  });

  it('keeps a muted brand muted in dark mode', () => {
    // The regression: dark mode used to rotate the default's own dark variant,
    // a fully saturated orange, so its 100% saturation was forced onto every
    // brand. Forest green, deliberately muted at 46%, came out as neon lime.
    const forest = '#2E7D32';
    const brandSaturation = rgbToHsl(hexToRgb(forest)).s;
    const dark = createTheme(forest, 'dark');
    const resultSaturation = rgbToHsl(hexToRgb(dark.colors.primary)).s;
    expect(resultSaturation).toBeCloseTo(brandSaturation, 2);
    expect(resultSaturation).toBeLessThan(0.6);
  });

  it('lifts the dark mode accent into a legible band', () => {
    for (const brand of ['#2E7D32', '#0B3D0B', '#FFD400', '#2D7FF9']) {
      const lightness = rgbToHsl(hexToRgb(createTheme(brand, 'dark').colors.primary)).l * 100;
      expect(lightness).toBeGreaterThanOrEqual(DARK_LIGHTNESS_MIN - 0.5);
      expect(lightness).toBeLessThanOrEqual(DARK_LIGHTNESS_MAX + 0.5);
    }
  });

  it('keeps the dark wash in step with the resolved accent', () => {
    // A muted accent must not sit on a fully saturated wash.
    const dark = createTheme('#2E7D32', 'dark');
    const { r, g, b } = hexToRgb(dark.colors.primary);
    expect(dark.colors.primarySoft).toBe(`rgba(${r}, ${g}, ${b}, 0.12)`);
  });

  it('still moves the dark mode accent onto the brand', () => {
    // The surfaces staying put must not cost us the accent.
    const cherry = createTheme('#C2185B', 'dark');
    expect(cherry.colors.primary).not.toBe(darkTheme.colors.primary);
    expect(cherry.colors.primarySoft).not.toBe(darkTheme.colors.primarySoft);
  });

  it('still moves the light mode warm surfaces, which are brand-derived', () => {
    // The light palette's surfaces really are washed out of the orange, so the
    // guard must not stop them following the brand.
    const cherry = createTheme('#C2185B', 'light');
    for (const key of ['surfaceAlt', 'cream', 'chip', 'chipBorder'] as const) {
      expect(cherry.colors[key]).not.toBe(lightTheme.colors[key]);
    }
  });

  it('tone leaves a colour that was never brand-derived alone', () => {
    const cherry = createTheme('#C2185B', 'dark');
    // A cool surface literal passed through tone must come back untouched.
    expect(cherry.tone('#1A202B')).toBe('#1A202B');
    // A warm wash still follows the brand.
    expect(cherry.tone('#FFF4EC')).not.toBe('#FFF4EC');
  });

  it('leaves backgrounds, text and semantic colours alone', () => {
    // A restaurant owns its accent. It does not own "delivered" or "cancelled".
    const blue = createTheme('#2D7FF9', 'light');
    for (const key of [
      'background',
      'text',
      'secondaryText',
      'border',
      'divider',
      'success',
      'warning',
      'info',
      'deepRed',
      'offer',
    ] as const) {
      expect(blue.colors[key]).toBe(lightTheme.colors[key]);
    }
  });

  it('leaves the shipped ink alone for the default brand', () => {
    // Dark mode ships near-white on the lightened orange at 2.6. That is the
    // design as drawn; the ink rule must not quietly restyle it.
    expect(createTheme(DEFAULT_BRAND_COLOR, 'dark').colors.onPrimary).toBe(
      darkTheme.colors.onPrimary,
    );
  });

  it('keeps label ink legible on every customised brand colour', () => {
    for (const brand of ['#2D7FF9', '#FFD400', '#A7F3D0', '#0F766E']) {
      const built = createTheme(brand, 'light');
      expect(
        contrastRatio(built.colors.primary, built.colors.onPrimary),
      ).toBeGreaterThanOrEqual(3);
    }
  });

  it('exposes a tint helper bound to the resolved primary', () => {
    expect(createTheme('#FF5200', 'light').primaryTint(0.12)).toBe(
      'rgba(255, 82, 0, 0.12)',
    );
    expect(createTheme('#2D7FF9', 'light').primaryTint(0.12)).toBe(
      'rgba(45, 127, 249, 0.12)',
    );
  });
});

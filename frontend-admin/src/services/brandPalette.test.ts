import { describe, expect, it } from 'vitest';
import {
  DEFAULT_BRAND_COLOR,
  MIN_INK_CONTRAST,
  contrastRatio,
  darkModeAccent,
  hexToRgb,
  normalizeHex,
  previewPalette,
  readableInk,
  retint,
  rgbToHsl,
} from './brandPalette';

/**
 * Values taken from the device implementation (`mobile/src/themeBase.ts`) by
 * running it over the shipped presets. If the two ever drift, the preview
 * starts promising something the phone will not render, and these fail.
 */
const DEVICE_VALUES: Array<[string, string, string, string, string]> = [
  // brand, light primary, light ink, dark primary, dark ink
  ['#FF5200', '#FF5200', '#FFFFFF', '#FF7A45', '#FFF8F4'],
  ['#B45309', '#B45309', '#FFFFFF', '#F3720F', '#1F2430'],
  ['#C0392B', '#C0392B', '#FFFFFF', '#D96357', '#FFF8F4'],
  ['#C2185B', '#C2185B', '#FFFFFF', '#E6387D', '#FFF8F4'],
  ['#7B3FA0', '#7B3FA0', '#FFFFFF', '#9D62C1', '#FFF8F4'],
  ['#4338CA', '#4338CA', '#FFFFFF', '#766ED8', '#FFF8F4'],
  ['#2D7FF9', '#2D7FF9', '#FFFFFF', '#70A8FB', '#1F2430'],
  ['#0F766E', '#0F766E', '#FFFFFF', '#18BEB1', '#1F2430'],
  ['#2E7D32', '#2E7D32', '#FFFFFF', '#41AF46', '#1F2430'],
  ['#4D7C0F', '#4D7C0F', '#FFFFFF', '#77BF17', '#1F2430'],
  ['#334155', '#334155', '#FFFFFF', '#506686', '#FFF8F4'],
  ['#78350F', '#78350F', '#FFFFFF', '#BE5418', '#FFF8F4'],
];

describe('parity with the device', () => {
  it.each(DEVICE_VALUES)(
    '%s resolves the same way the app does',
    (brand, lightPrimary, lightInk, darkPrimary, darkInk) => {
      const light = previewPalette(brand, 'light');
      const dark = previewPalette(brand, 'dark');
      expect(light.primary).toBe(lightPrimary);
      expect(light.onPrimary).toBe(lightInk);
      expect(dark.primary).toBe(darkPrimary);
      expect(dark.onPrimary).toBe(darkInk);
    },
  );
});

describe('darkModeAccent', () => {
  it('keeps the brand’s own saturation rather than forcing it up', () => {
    // The neon-green regression: dark mode must not inherit the default
    // orange's full saturation.
    const brandSaturation = rgbToHsl(hexToRgb('#2E7D32')).s;
    const accentSaturation = rgbToHsl(hexToRgb(darkModeAccent('#2E7D32'))).s;
    expect(accentSaturation).toBeCloseTo(brandSaturation, 2);
  });

  it('lifts a dark brand into a visible band', () => {
    expect(rgbToHsl(hexToRgb(darkModeAccent('#0B3D0B'))).l * 100).toBeGreaterThanOrEqual(41.5);
  });
});

describe('readableInk', () => {
  it('keeps white where white still works', () => {
    expect(readableInk('#2E7D32')).toBe('#FFFFFF');
  });

  it('flips to dark ink on a pale accent', () => {
    expect(readableInk('#70A8FB')).not.toBe('#FFFFFF');
  });
});

describe('retint', () => {
  it('is the identity for the default brand', () => {
    expect(retint('#FFF2EA', DEFAULT_BRAND_COLOR)).toBe('#FFF2EA');
  });

  it('leaves a colour that was never brand-derived alone', () => {
    // A cool dark surface must not be dragged onto the brand hue.
    expect(retint('#1A202B', '#C2185B')).toBe('#1A202B');
  });

  it('moves a warm wash onto the brand hue', () => {
    expect(retint('#FFF2EA', '#2D7FF9')).not.toBe('#FFF2EA');
  });
});

describe('preset readability', () => {
  const PRESETS = DEVICE_VALUES.map(([brand]) => brand);

  it('every preset except the platform default clears the bar in both modes', () => {
    for (const brand of PRESETS.filter((hex) => hex !== DEFAULT_BRAND_COLOR)) {
      for (const mode of ['light', 'dark'] as const) {
        const palette = previewPalette(brand, mode);
        expect(palette.inkContrast).toBeGreaterThanOrEqual(MIN_INK_CONTRAST);
        expect(palette.textContrast).toBeGreaterThanOrEqual(MIN_INK_CONTRAST);
      }
    }
  });

  it('records that the shipped default is the one marginal case', () => {
    // Documented rather than fixed: raising it would restyle the current app.
    expect(previewPalette(DEFAULT_BRAND_COLOR, 'dark').inkContrast).toBeLessThan(
      MIN_INK_CONTRAST,
    );
  });
});

describe('normalizeHex', () => {
  it('falls back rather than producing a broken colour', () => {
    expect(normalizeHex('nope')).toBe(DEFAULT_BRAND_COLOR);
    expect(normalizeHex('#2d7ff9')).toBe('#2D7FF9');
  });
});

describe('contrastRatio', () => {
  it('is symmetric and bounded', () => {
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 0);
    expect(contrastRatio('#FFFFFF', '#000000')).toBeCloseTo(21, 0);
  });
});

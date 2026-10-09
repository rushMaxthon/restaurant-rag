import { contrastRatio, highContrast } from './contrast';
import { dark, light } from './tokens';

describe('high contrast', () => {
  it('measures contrast the WCAG way', () => {
    expect(contrastRatio('#000000', '#FFFFFF')).toBeCloseTo(21, 0);
    expect(contrastRatio('#FFFFFF', '#FFFFFF')).toBeCloseTo(1, 5);
  });

  it.each([
    ['dark', dark],
    ['light', light],
  ] as const)('makes every line of %s text readable in sunlight (AAA, 7:1)', (_name, palette) => {
    const strong = highContrast(palette);
    for (const ink of [strong.text, strong.textMuted, strong.textFaint]) {
      expect(contrastRatio(ink, strong.bg)).toBeGreaterThanOrEqual(7);
      expect(contrastRatio(ink, strong.surface)).toBeGreaterThanOrEqual(7);
    }
  });

  it('draws borders a rider can see on a cheap screen (3:1)', () => {
    for (const palette of [dark, light]) {
      const strong = highContrast(palette);
      expect(contrastRatio(strong.border, strong.surface)).toBeGreaterThanOrEqual(3);
    }
  });

  it('leaves the brand and status colours alone', () => {
    const strong = highContrast(dark);
    expect([strong.primary, strong.success, strong.danger]).toEqual([dark.primary, dark.success, dark.danger]);
  });
});

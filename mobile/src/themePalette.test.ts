import {
  DEFAULT_BRAND_COLOR,
  brandHue,
  hueDelta,
  contrastRatio,
  hexToRgb,
  hslToRgb,
  isValidHex,
  normalizeHex,
  MIN_INK_CONTRAST,
  readableInk,
  retint,
  retintRgba,
  rgbToHex,
  rgbToHsl,
  tint,
} from './themePalette';

describe('hex handling', () => {
  it('accepts a six-digit hex and rejects everything else', () => {
    expect(isValidHex('#FF5200')).toBe(true);
    expect(isValidHex('#ff5200')).toBe(true);
    expect(isValidHex('#F52')).toBe(false);
    expect(isValidHex('FF5200')).toBe(false);
    expect(isValidHex(null)).toBe(false);
  });

  it('falls back to the default rather than producing a broken colour', () => {
    expect(normalizeHex('not-a-colour')).toBe(DEFAULT_BRAND_COLOR);
    expect(normalizeHex(undefined)).toBe(DEFAULT_BRAND_COLOR);
    expect(normalizeHex('#2d7ff9')).toBe('#2D7FF9');
  });

  it('round-trips rgb and hex', () => {
    expect(rgbToHex(hexToRgb('#2D7FF9'))).toBe('#2D7FF9');
    expect(rgbToHex(hexToRgb('#000000'))).toBe('#000000');
    expect(rgbToHex(hexToRgb('#FFFFFF'))).toBe('#FFFFFF');
  });

  it('round-trips rgb and hsl', () => {
    for (const hex of ['#FF5200', '#2D7FF9', '#48C479', '#7B3FA0', '#101418']) {
      expect(rgbToHex(hslToRgb(rgbToHsl(hexToRgb(hex))))).toBe(hex);
    }
  });
});

describe('retint', () => {
  it('is the identity when the brand is the default', () => {
    // The guarantee the whole design rests on: an unbranded app must render
    // exactly what it rendered before this change existed.
    const hue = hueDelta(DEFAULT_BRAND_COLOR);
    for (const token of [
      '#FF5200',
      '#FFF0E8',
      '#FFF5EE',
      '#FFF8F2',
      '#FAF7F3',
      '#F0E7DF',
      '#FFFDF9',
      '#FF7A45',
    ]) {
      expect(retint(token, hue)).toBe(token);
    }
  });

  it('leaves true neutrals alone, whatever the brand is', () => {
    const delta = hueDelta('#2D7FF9');
    for (const neutral of ['#FFFFFF', '#000000', '#7F7F7F']) {
      expect(retint(neutral, delta)).toBe(neutral);
    }
  });

  it('keeps a near-grey near-grey rather than colouring it in', () => {
    // Borders like #E9E9EB carry a trace of saturation. Rotating their hue must
    // not turn a hairline into a visible tint.
    const rotated = retint('#E9E9EB', hueDelta('#2D7FF9'));
    expect(rgbToHsl(hexToRgb(rotated)).s).toBeLessThan(0.1);
  });

  it('keeps lightness and saturation when swapping hue', () => {
    const source = rgbToHsl(hexToRgb('#FFF0E8'));
    const swapped = rgbToHsl(hexToRgb(retint('#FFF0E8', hueDelta('#2D7FF9'))));
    expect(swapped.l).toBeCloseTo(source.l, 2);
    expect(swapped.s).toBeCloseTo(source.s, 2);
  });

  it('moves a warm wash onto the brand hue', () => {
    const blue = retint('#FFF0E8', hueDelta('#2D7FF9'));
    const { r, b } = hexToRgb(blue);
    // A peach has more red than blue; its blue counterpart must be the reverse.
    expect(b).toBeGreaterThan(r);
  });
});

describe('retintRgba', () => {
  it('rewrites the colour and preserves the alpha', () => {
    expect(retintRgba('rgba(255, 122, 69, 0.12)', hueDelta('#2D7FF9'))).toMatch(
      /^rgba\(\d+, \d+, \d+, 0\.12\)$/,
    );
  });

  it('is the identity for the default brand', () => {
    expect(
      retintRgba('rgba(255, 122, 69, 0.12)', hueDelta(DEFAULT_BRAND_COLOR)),
    ).toBe('rgba(255, 122, 69, 0.12)');
  });

  it('leaves a non-rgba string untouched', () => {
    expect(retintRgba('transparent', 42)).toBe('transparent');
  });
});

describe('readableInk', () => {
  it('keeps white on the default orange', () => {
    expect(readableInk('#FF5200')).toBe('#FFFFFF');
  });

  it('switches to dark ink on a pale brand colour', () => {
    // The failure this exists to prevent: white label text on a yellow button.
    expect(readableInk('#FFD400')).not.toBe('#FFFFFF');
    expect(readableInk('#A7F3D0')).not.toBe('#FFFFFF');
  });

  it('keeps white wherever white still clears the bar', () => {
    // Dark ink scores higher on the default orange, but flipping to it would
    // restyle every existing button. White stays while it is legible.
    for (const brand of ['#FF5200', '#2D7FF9', '#2E7D32', '#C2185B']) {
      expect(readableInk(brand)).toBe('#FFFFFF');
    }
  });

  it('never leaves ink below the legibility bar', () => {
    for (const brand of ['#FF5200', '#2D7FF9', '#FFD400', '#0E1116', '#A7F3D0']) {
      expect(contrastRatio(brand, readableInk(brand))).toBeGreaterThanOrEqual(
        MIN_INK_CONTRAST,
      );
    }
  });

  it('clears the WCAG AA large-text bar for every preset we ship', () => {
    for (const brand of ['#FF5200', '#2D7FF9', '#2E7D32', '#7B3FA0', '#0F766E', '#C2185B']) {
      expect(contrastRatio(brand, readableInk(brand))).toBeGreaterThanOrEqual(3);
    }
  });
});

describe('tint', () => {
  it('reproduces the literal washes the screens used to hardcode', () => {
    expect(tint('#FF5200', 0.12)).toBe('rgba(255, 82, 0, 0.12)');
    expect(tint('#FF5200', 0.08)).toBe('rgba(255, 82, 0, 0.08)');
  });
});

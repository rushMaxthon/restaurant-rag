import { MIN_TEXT_CONTRAST, STATUS_COLORS, contrast, inkOn } from './themePalette';

describe('status chips', () => {
  it.each(Object.entries(STATUS_COLORS))(
    '%s keeps its label readable',
    (_status, color) => {
      expect(contrast(color, inkOn(color))).toBeGreaterThanOrEqual(
        MIN_TEXT_CONTRAST,
      );
    },
  );

  it('gives every status its own colour except the two terminal greys', () => {
    const { PAYMENT_PENDING, CANCELLED, ...active } = STATUS_COLORS;
    expect(new Set(Object.values(active)).size).toBe(Object.keys(active).length);
    expect(PAYMENT_PENDING).not.toBe(CANCELLED);
  });
});

describe('contrast', () => {
  it('is symmetric and spans 1..21', () => {
    expect(contrast('#000000', '#FFFFFF')).toBeCloseTo(21);
    expect(contrast('#FFFFFF', '#000000')).toBeCloseTo(21);
    expect(contrast('#2563EB', '#2563EB')).toBeCloseTo(1);
  });
});

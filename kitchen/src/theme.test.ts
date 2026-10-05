import { createTheme, darkTheme, lightTheme } from './themeBase';
import { STATUS_COLORS, contrast } from './themePalette';

describe('createTheme', () => {
  it('picks the palette for the mode', () => {
    expect(createTheme('light').colors).toBe(lightTheme);
    expect(createTheme('dark').colors).toBe(darkTheme);
  });

  it('keeps status colours identical across modes', () => {
    expect(createTheme('dark').status).toEqual(createTheme('light').status);
    expect(createTheme('light').status).toBe(STATUS_COLORS);
  });

  it.each([lightTheme, darkTheme])('body text is readable on its background', palette => {
    expect(contrast(palette.text, palette.background)).toBeGreaterThanOrEqual(7);
    expect(contrast(palette.textMuted, palette.surface)).toBeGreaterThanOrEqual(4.5);
  });

  it.each([lightTheme, darkTheme])('button and error text meet AA', palette => {
    expect(contrast(palette.onAccent, palette.accent)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(palette.danger, palette.dangerSoft)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(palette.text, palette.inputBackground)).toBeGreaterThanOrEqual(7);
  });

  it.each([lightTheme, darkTheme])('tinted callouts keep their text readable', palette => {
    expect(contrast(palette.warning, palette.warningSoft)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(palette.text, palette.warningSoft)).toBeGreaterThanOrEqual(7);
    expect(contrast(palette.accent, palette.accentSoft)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(palette.text, palette.surfaceMuted)).toBeGreaterThanOrEqual(7);
    expect(contrast(palette.danger, palette.surface)).toBeGreaterThanOrEqual(4.5);
  });
});

import type { Palette } from './tokens';

/**
 * High contrast, for a rider reading the screen in midday sun on a cheap
 * phone at low brightness. Only the neutrals change: the inks go to AAA
 * (7:1) and hairlines become lines. The brand orange and the status colours
 * keep their meaning, so a rider who switches it on does not have to relearn
 * the screen.
 */

function channel(hex: string, i: number): number {
  const v = parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255;
  return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  return 0.2126 * channel(hex, 0) + 0.7152 * channel(hex, 1) + 0.0722 * channel(hex, 2);
}

/** WCAG 2 contrast ratio between two #RRGGBB colours. */
export function contrastRatio(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

export function highContrast(palette: Palette): Palette {
  const isDark = luminance(palette.bg) < 0.2;
  return isDark
    ? {
        ...palette,
        bg: '#000000',
        surface: '#0B0D12',
        surfaceAlt: '#14171F',
        elevated: '#1B1F29',
        border: '#7A8296',
        text: '#FFFFFF',
        textMuted: '#DDE2EC',
        textFaint: '#C3CAD8',
      }
    : {
        ...palette,
        bg: '#FFFFFF',
        surface: '#FFFFFF',
        surfaceAlt: '#EEF0F4',
        elevated: '#FFFFFF',
        border: '#7A8296',
        text: '#000000',
        textMuted: '#262B36',
        textFaint: '#363C49',
      };
}

import type { OrderStatus } from '@/types/app';
import { STATUS_COLORS } from './themePalette';

export type ThemePreference = 'light' | 'dark' | 'system';
export type ThemeMode = 'light' | 'dark';

export interface ThemeColors {
  background: string;
  surface: string;
  border: string;
  text: string;
  textMuted: string;
  accent: string;
  // Text and spinners drawn on an accent-filled button.
  onAccent: string;
  inputBackground: string;
  danger: string;
  // Banner background behind danger-coloured text.
  dangerSoft: string;
  // "Due soon" tickets and special instructions — attention, not alarm.
  warning: string;
  warningSoft: string;
  // A selected row, a positive state.
  accentSoft: string;
  // Chips, tracks and other quiet fills on a surface.
  surfaceMuted: string;
}

export interface AppTheme {
  mode: ThemeMode;
  colors: ThemeColors;
  status: Record<OrderStatus, string>;
  spacing: (step: number) => number;
}

export const lightTheme: ThemeColors = {
  background: '#F4F4F5',
  surface: '#FFFFFF',
  border: '#E4E4E7',
  text: '#18181B',
  textMuted: '#71717A',
  // #15803D rather than the brighter #16A34A: white button text on the
  // brighter green measures about 3.3:1, short of AA.
  accent: '#15803D',
  onAccent: '#FFFFFF',
  inputBackground: '#FAFAFA',
  danger: '#B91C1C',
  dangerSoft: '#FEF2F2',
  warning: '#B45309',
  warningSoft: '#FFFBEB',
  accentSoft: '#F0FDF4',
  surfaceMuted: '#F4F4F5',
};

export const darkTheme: ThemeColors = {
  background: '#09090B',
  surface: '#18181B',
  border: '#27272A',
  text: '#FAFAFA',
  textMuted: '#A1A1AA',
  accent: '#22C55E',
  onAccent: '#052E16',
  inputBackground: '#09090B',
  danger: '#FCA5A5',
  dangerSoft: '#2A1215',
  warning: '#FCD34D',
  warningSoft: '#2A2110',
  accentSoft: '#0F2A1A',
  surfaceMuted: '#27272A',
};

// One spacing scale, one radius scale and one type scale for every screen,
// so cards, gaps and headings line up across the app instead of each screen
// picking its own numbers.
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 20, xxl: 24, xxxl: 32 } as const;

export const radius = { sm: 8, md: 12, lg: 16, xl: 20, pill: 999 } as const;

export const type = {
  // Order codes and the big numbers a cook reads from across the kitchen.
  display: { fontSize: 30, fontWeight: '900', letterSpacing: -0.3 },
  title: { fontSize: 22, fontWeight: '800', letterSpacing: -0.2 },
  heading: { fontSize: 17, fontWeight: '800' },
  body: { fontSize: 16, fontWeight: '500', lineHeight: 22 },
  bodyStrong: { fontSize: 16, fontWeight: '700', lineHeight: 22 },
  label: { fontSize: 14, fontWeight: '700' },
  caption: { fontSize: 13, fontWeight: '600', lineHeight: 18 },
  // Section labels above grouped lists.
  overline: { fontSize: 12, fontWeight: '800', letterSpacing: 0.8, textTransform: 'uppercase' },
} as const;

export function createTheme(mode: ThemeMode): AppTheme {
  return {
    mode,
    colors: mode === 'dark' ? darkTheme : lightTheme,
    status: STATUS_COLORS,
    spacing: step => step * 4,
  };
}

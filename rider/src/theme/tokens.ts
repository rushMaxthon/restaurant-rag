/**
 * The rider app's design tokens.
 *
 * Map-first and dark by default: a rider looks at this in sun, at night and
 * through a scratched screen, one-handed on a bike stand, so contrast and
 * target size come before decoration. Light follows the phone's setting.
 *
 * The accent is the platform's own orange (#ff5200, the same value the admin
 * panel uses) so the rider app reads as part of one product. Green means "you
 * are online / done", amber "needs you now", red only "something failed".
 */

export type Palette = {
  bg: string;
  surface: string;
  surfaceAlt: string;
  elevated: string;
  border: string;
  text: string;
  textMuted: string;
  textFaint: string;
  primary: string;
  primaryPressed: string;
  primarySoft: string;
  onPrimary: string;
  success: string;
  successSoft: string;
  onSuccess: string;
  warning: string;
  warningSoft: string;
  danger: string;
  dangerSoft: string;
  overlay: string;
  skeleton: string;
  skeletonSheen: string;
};

export const dark: Palette = {
  bg: '#0B0D12',
  surface: '#14171F',
  surfaceAlt: '#1B1F29',
  elevated: '#222734',
  border: '#2A3040',
  text: '#F4F6FA',
  textMuted: '#A3ABBD',
  textFaint: '#6B7385',
  primary: '#FF5200',
  primaryPressed: '#E04800',
  primarySoft: 'rgba(255, 82, 0, 0.16)',
  onPrimary: '#FFFFFF',
  success: '#22C55E',
  successSoft: 'rgba(34, 197, 94, 0.16)',
  onSuccess: '#05210F',
  warning: '#FBBF24',
  warningSoft: 'rgba(251, 191, 36, 0.16)',
  danger: '#F87171',
  dangerSoft: 'rgba(248, 113, 113, 0.16)',
  overlay: 'rgba(5, 7, 10, 0.72)',
  skeleton: '#1B1F29',
  skeletonSheen: '#262B38',
};

export const light: Palette = {
  bg: '#F6F7FA',
  surface: '#FFFFFF',
  surfaceAlt: '#F0F2F6',
  elevated: '#FFFFFF',
  border: '#E3E6EE',
  text: '#11141B',
  textMuted: '#5B6375',
  textFaint: '#8C93A3',
  primary: '#FF5200',
  primaryPressed: '#E04800',
  primarySoft: '#FFF0E8',
  onPrimary: '#FFFFFF',
  success: '#16A34A',
  successSoft: '#E8F7EE',
  onSuccess: '#FFFFFF',
  warning: '#B45309',
  warningSoft: '#FEF3C7',
  danger: '#DC2626',
  dangerSoft: '#FDECEC',
  overlay: 'rgba(17, 20, 27, 0.55)',
  skeleton: '#ECEEF3',
  skeletonSheen: '#F6F7FA',
};

/** 4-pt rhythm. Screens use these, never their own numbers. */
export const space = {
  xxs: 2,
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 24,
  xxxl: 32,
  huge: 48,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  xxl: 28,
  pill: 999,
} as const;

/**
 * Android names a bundled font by its FILE name, so these must match
 * android/app/src/main/assets/fonts exactly. Weight is chosen by face, not by
 * `fontWeight`, which Android ignores for a custom family.
 */
export const font = {
  regular: 'PlusJakartaSans-Regular',
  medium: 'PlusJakartaSans-Medium',
  semibold: 'PlusJakartaSans-SemiBold',
  bold: 'PlusJakartaSans-Bold',
  heavy: 'PlusJakartaSans-ExtraBold',
} as const;

export const type = {
  display: { fontFamily: font.heavy, fontSize: 34, lineHeight: 40, letterSpacing: -0.5 },
  title: { fontFamily: font.bold, fontSize: 24, lineHeight: 30, letterSpacing: -0.3 },
  heading: { fontFamily: font.bold, fontSize: 18, lineHeight: 24 },
  body: { fontFamily: font.medium, fontSize: 16, lineHeight: 22 },
  bodyStrong: { fontFamily: font.semibold, fontSize: 16, lineHeight: 22 },
  label: { fontFamily: font.semibold, fontSize: 14, lineHeight: 18 },
  caption: { fontFamily: font.medium, fontSize: 13, lineHeight: 17 },
  micro: { fontFamily: font.bold, fontSize: 11, lineHeight: 14, letterSpacing: 0.6 },
  money: { fontFamily: font.heavy, fontSize: 28, lineHeight: 34, letterSpacing: -0.4 },
} as const;

/** 48dp: the floor for anything a rider taps, often wearing gloves. */
export const touch = { min: 48, large: 56, hero: 64 } as const;

/**
 * Motion. Springs rather than durations for anything the finger moves, so a
 * release mid-gesture continues with the finger's velocity instead of jumping.
 */
export const motion = {
  fast: 160,
  base: 240,
  slow: 380,
  spring: { damping: 18, stiffness: 220, mass: 1 },
  springSoft: { damping: 22, stiffness: 140, mass: 1 },
  springSnappy: { damping: 14, stiffness: 320, mass: 0.8 },
} as const;

export type ThemeMode = 'dark' | 'light';

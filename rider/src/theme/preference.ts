import type { ThemeMode } from './tokens';

/** System follows the phone; the other two are the rider's own choice. */
export type ThemePreference = 'system' | ThemeMode;

export const THEME_KEY = 'rider.theme';

export const THEME_OPTIONS: readonly {
  key: ThemePreference;
  label: string;
  hint: string;
}[] = [
  {
    key: 'system',
    label: 'Follow the phone',
    hint: 'Dark at night if your phone is',
  },
  { key: 'light', label: 'Light', hint: 'Easier in bright sun' },
  { key: 'dark', label: 'Dark', hint: 'Easier on the eyes at night' },
];

export function resolveMode(
  preference: ThemePreference,
  scheme: 'light' | 'dark' | null | undefined,
): ThemeMode {
  if (preference !== 'system') return preference;
  return scheme === 'light' ? 'light' : 'dark';
}

export function decodePreference(raw: string | null): ThemePreference {
  return raw === 'light' || raw === 'dark' || raw === 'system' ? raw : 'system';
}
